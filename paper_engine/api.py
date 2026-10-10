import asyncio
import secrets
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketDisconnect

from paper_engine.candles import TIMEFRAMES, CandleService
from paper_engine.config import Settings
from paper_engine.engine import Engine
from paper_engine.feeds import CCXTFeed, discover_symbols
from paper_engine.memes import list_memes, read_meme
from paper_engine.models import AgentClose, AgentControlRequest, AgentOrder, EngineError, OpenOrder
from paper_engine.news import NewsService
from paper_engine.store import Store

bearer = HTTPBearer(auto_error=False)
Principal = Literal["operator", "agent"]
IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
]
PageLimit = Annotated[int, Query(ge=1, le=100)]
PageOffset = Annotated[int, Query(ge=0, le=1_000_000)]
NewsLimit = Annotated[int, Query(ge=1, le=50)]
NewsOffset = Annotated[int, Query(ge=0, le=500)]
NewsSourceFilter = Annotated[str | None, Query(min_length=1, max_length=40)]
NewsSearch = Annotated[str | None, Query(max_length=100)]
NewsSymbol = Annotated[str | None, Query(min_length=1, max_length=40)]


async def cancel_task(task: asyncio.Task) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Resources unwind in reverse order even if a later startup step raises,
        # so the SQLite file lock is always released.
        async with AsyncExitStack() as stack:
            store = Store(
                settings.db_path,
                settings.initial_balance,
                settings.exchange,
                settings.symbols,
                retain_open_symbols=settings.symbol_selection == "top_volume",
            )
            stack.callback(store.close)
            if settings.symbol_selection == "top_volume" and settings.feed_enabled:
                settings.symbols = await discover_symbols(settings)
            engine = Engine(settings, store)
            app.state.engine = engine
            app.state.candles = CandleService(settings)
            stack.push_async_callback(app.state.candles.close)
            # Created after discovery so coin tags follow the active symbol list.
            app.state.news = NewsService(settings) if settings.news_enabled else None
            if app.state.news is not None:
                stack.push_async_callback(app.state.news.close)
            app.state.websocket_clients = 0
            if settings.feed_enabled:
                stack.push_async_callback(cancel_task, asyncio.create_task(CCXTFeed(engine).run()))
            if app.state.news is not None:
                stack.push_async_callback(cancel_task, asyncio.create_task(app.state.news.run()))
            yield

    app = FastAPI(
        title="Paper Trading Engine",
        version="0.1.0",
        lifespan=lifespan,
        description=(
            "Virtual isolated-margin execution only. No exchange order placement. Hermes disabled."
        ),
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        )

    def token_matches(value: str) -> bool:
        """Operator token only. Used by REST operator routes and the WebSocket."""
        return secrets.compare_digest(
            value.encode(), settings.api_token.get_secret_value().encode()
        )

    def agent_token_matches(value: str) -> bool:
        if settings.agent_token is None:
            return False
        return secrets.compare_digest(
            value.encode(), settings.agent_token.get_secret_value().encode()
        )

    def authenticate(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> Principal:
        if credentials is not None:
            # Evaluate both comparisons so timing does not reveal which token matched.
            operator = token_matches(credentials.credentials)
            agent = agent_token_matches(credentials.credentials)
            if operator:
                return "operator"
            if agent:
                return "agent"
        raise HTTPException(
            401, "Invalid or missing API token", headers={"WWW-Authenticate": "Bearer"}
        )

    PrincipalDependency = Annotated[Principal, Depends(authenticate)]

    def require_operator(principal: PrincipalDependency) -> None:
        if principal != "operator":
            raise EngineError("forbidden_for_agent", "This action requires the operator token", 403)

    def require_agent(principal: PrincipalDependency) -> None:
        if principal != "agent":
            raise EngineError("agent_token_required", "Agent routes require PAPER_AGENT_TOKEN", 403)

    OperatorOnly = [Depends(require_operator)]
    AgentOnly = [Depends(require_agent)]

    def get_engine(request: Request) -> Engine:
        return request.app.state.engine

    EngineDependency = Annotated[Engine, Depends(get_engine)]
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(authenticate)])

    @app.exception_handler(EngineError)
    async def handle_engine_error(request: Request, exc: EngineError):
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": {"code": exc.code, "message": exc.message},
            },
        )

    @app.get("/", include_in_schema=False)
    async def index():
        index_file = settings.frontend_dist / "index.html"
        if index_file.is_file():
            return FileResponse(index_file, headers={"Cache-Control": "no-store"})
        return RedirectResponse(url="/docs", status_code=307)

    assets = settings.frontend_dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

    def hermes_status(engine: Engine) -> str:
        if not settings.agent_enabled:
            return "disabled"
        return "paused" if engine.store.agent_control()["paused"] else "active"

    @app.get("/health")
    async def health(request: Request):
        return {"status": "ok", "mode": "paper", "hermes": hermes_status(request.app.state.engine)}

    @router.get("/config")
    async def client_config(engine: EngineDependency):
        return {
            "exchange": settings.exchange,
            "symbols": settings.symbols,
            "mode": "paper",
            "margin_mode": "isolated",
            "hermes": hermes_status(engine),
            "agent": {
                "enabled": settings.agent_enabled,
                "min_open_interval_seconds": settings.agent_min_open_interval_seconds,
                "daily_loss_pct": str(settings.agent_daily_loss_pct),
                "max_open_positions": settings.agent_max_open_positions,
                "max_leverage": settings.agent_max_leverage,
                "max_risk_per_trade_pct": str(settings.agent_max_risk_per_trade_pct),
            },
            "feed_enabled": settings.feed_enabled,
            "default_leverage": settings.default_leverage,
            "max_leverage": settings.max_leverage,
            "default_allocation_pct": str(settings.default_allocation_pct),
            "min_allocation_pct": "0.02",
            "max_allocation_pct": "0.05",
            "taker_fee_rate": str(settings.taker_fee_rate),
            "slippage_bps": str(settings.slippage_bps),
            "max_quote_age_seconds": settings.max_quote_age_seconds,
            "timeframes": list(TIMEFRAMES),
            "news_enabled": settings.news_enabled,
        }

    @router.get("/news")
    async def news(
        request: Request,
        source: NewsSourceFilter = None,
        q: NewsSearch = None,
        symbol: NewsSymbol = None,
        limit: NewsLimit = 20,
        offset: NewsOffset = 0,
    ):
        service: NewsService | None = request.app.state.news
        if service is None:
            raise EngineError("news_disabled", "News feed is disabled", 503)
        # In-memory filtering over at most 500 items; cheap enough for the event loop.
        return service.query(source=source, q=q, symbol=symbol, limit=limit, offset=offset)

    @router.get("/candles")
    async def candles(request: Request, symbol: str, timeframe: str = "5m"):
        try:
            async with asyncio.timeout(15):
                return await request.app.state.candles.get(symbol, timeframe)
        except TimeoutError as exc:
            raise EngineError("chart_busy", "Chart request timed out. Retry shortly.", 503) from exc

    @router.get("/status")
    async def status(engine: EngineDependency):
        return await engine.snapshot()

    @router.get("/account")
    async def account(engine: EngineDependency):
        return (await engine.snapshot())["account"]

    @router.get("/markets")
    async def markets(engine: EngineDependency):
        return (await engine.snapshot())["markets"]

    @router.get("/positions")
    async def positions(engine: EngineDependency):
        return (await engine.snapshot())["positions"]

    @router.post("/orders", status_code=201, dependencies=OperatorOnly)
    async def open_order(
        order: OpenOrder, idempotency_key: IdempotencyKey, engine: EngineDependency
    ):
        return await engine.open(order, idempotency_key)

    @router.post("/positions/{position_id}/close", dependencies=OperatorOnly)
    async def close_position(
        position_id: UUID, idempotency_key: IdempotencyKey, engine: EngineDependency
    ):
        return await engine.close(str(position_id), idempotency_key)

    # --- Hermes agent: trading (agent token) and control (operator token) ---------------

    @router.post("/agent/orders", status_code=201, dependencies=AgentOnly)
    async def agent_open(
        order: AgentOrder, idempotency_key: IdempotencyKey, engine: EngineDependency
    ):
        return await engine.agent_open(order, idempotency_key)

    @router.post("/agent/positions/{position_id}/close", dependencies=AgentOnly)
    async def agent_close(
        position_id: UUID,
        body: AgentClose,
        idempotency_key: IdempotencyKey,
        engine: EngineDependency,
    ):
        return await engine.agent_close(str(position_id), body.reason, idempotency_key)

    @router.get("/agent/state")
    async def agent_state(engine: EngineDependency):
        return await engine.agent_state()

    @router.post("/agent/pause", dependencies=OperatorOnly)
    async def agent_pause(engine: EngineDependency, body: AgentControlRequest | None = None):
        return await engine.set_agent_paused(True, "operator", body.reason if body else None)

    @router.post("/agent/resume", dependencies=OperatorOnly)
    async def agent_resume(engine: EngineDependency, body: AgentControlRequest | None = None):
        return await engine.set_agent_paused(False, "operator", body.reason if body else None)

    @router.post("/agent/close-all", dependencies=OperatorOnly)
    async def agent_close_all(engine: EngineDependency):
        return await engine.agent_close_all("operator")

    @router.get("/agent/events", dependencies=OperatorOnly)
    async def agent_events(engine: EngineDependency, limit: PageLimit = 50, offset: PageOffset = 0):
        return await engine.agent_events(limit, offset)

    @router.get("/trades")
    async def trades(engine: EngineDependency, limit: PageLimit = 50, offset: PageOffset = 0):
        return await engine.history(limit, offset)

    @router.get("/journals")
    async def journals(engine: EngineDependency, limit: PageLimit = 50, offset: PageOffset = 0):
        return await engine.journals(limit, offset)

    @router.get("/memes", dependencies=OperatorOnly)
    def memes():
        return list_memes(settings.memes_dir)

    @router.get("/memes/{category}/{name}", dependencies=OperatorOnly)
    def meme(category: str, name: str):
        data, content_type = read_meme(settings.memes_dir, category, name)
        return Response(
            data,
            media_type=content_type,
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'; sandbox",
            },
        )

    app.include_router(router)

    @app.websocket("/ws")
    async def websocket(websocket: WebSocket):
        origin = websocket.headers.get("origin")
        try:
            parsed_origin = urlsplit(origin or "")
        except ValueError:
            await websocket.close(code=1008)
            return
        same_origin = (
            parsed_origin.scheme == ("https" if websocket.url.scheme == "wss" else "http")
            and parsed_origin.netloc == websocket.headers.get("host")
            and parsed_origin.hostname in ("localhost", "127.0.0.1", "::1")
            and parsed_origin.username is None
            and parsed_origin.password is None
            and not parsed_origin.path
            and not parsed_origin.query
            and not parsed_origin.fragment
        )
        if origin is not None and not same_origin and origin not in settings.cors_origins:
            await websocket.close(code=1008)
            return
        if websocket.app.state.websocket_clients >= 20:
            await websocket.close(code=1013)
            return
        websocket.app.state.websocket_clients += 1
        try:
            await websocket.accept()
            try:
                auth = await asyncio.wait_for(websocket.receive_json(), timeout=5)
                if not isinstance(auth, dict) or set(auth) != {"token"}:
                    raise ValueError("Invalid authentication frame")
                if not isinstance(auth["token"], str) or not token_matches(auth["token"]):
                    raise ValueError("Invalid token")
            except (TimeoutError, ValueError, KeyError, TypeError):
                await websocket.close(code=1008, reason="Authentication required")
                return
            while True:
                snapshot = await websocket.app.state.engine.snapshot()
                await asyncio.wait_for(websocket.send_json(snapshot), timeout=5)
                await asyncio.sleep(1)
        except (WebSocketDisconnect, OSError):
            pass
        except TimeoutError:
            await websocket.close(code=1013, reason="Slow client")
        finally:
            websocket.app.state.websocket_clients -= 1

    return app
