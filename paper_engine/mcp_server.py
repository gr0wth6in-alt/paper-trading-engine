"""MCP tool server that lets Hermes (or any MCP host) paper-trade through the engine API.

Run by the MCP host as a stdio subprocess:

    PAPER_AGENT_TOKEN=... python -m paper_engine.mcp_server

Optional Streamable HTTP mode (for an MCP host running inside a container); it requires its
own bearer token and refuses wildcard bind addresses:

    PAPER_AGENT_TOKEN=... PAPER_MCP_TOKEN=... \\
        python -m paper_engine.mcp_server --transport streamable-http --host 172.17.0.1

Every guardrail (pause, cooldown, daily loss breaker, stop-loss, risk cap, ownership) is
enforced by the engine itself. This server only adds strict input validation, compact
outputs and idempotency keys. It exposes no pause/resume/config/operator tools.
"""

import argparse
import ipaddress
import logging
import os
import secrets
import sys
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4

import httpx2
from mcp.server import MCPServer
from pydantic import Field

logger = logging.getLogger("paper_engine.mcp")

TOOL_NAMES = (
    "get_overview",
    "get_market",
    "get_candles",
    "get_news",
    "get_history",
    "get_guardrails",
    "open_position",
    "close_position",
)
DEFAULT_ENGINE_URL = "http://127.0.0.1:8000"
LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})

Symbol = Annotated[
    str,
    Field(
        pattern=r"^[A-Z0-9]{1,20}/USDT:USDT$",
        description="Configured market, e.g. BTC/USDT:USDT (see get_overview.symbols)",
    ),
]
Price = Annotated[
    str,
    Field(
        pattern=r"^\d{1,12}(\.\d{1,12})?$",
        description="Positive decimal price as a string, e.g. '64250.5'",
    ),
]
Allocation = Annotated[
    str,
    Field(
        pattern=r"^0\.0\d{1,6}$",
        description="Isolated margin as a fraction of wallet, '0.02' to '0.05'",
    ),
]
Leverage = Annotated[int, Field(ge=1, le=20, strict=True, description="Integer leverage")]
EntryReason = Annotated[
    str,
    Field(
        min_length=20,
        max_length=2000,
        description="Concrete thesis and invalidation, stored in the trade journal",
    ),
]
ExitReason = Annotated[
    str, Field(min_length=10, max_length=2000, description="Why this position is closed now")
]
Strategy = Annotated[str | None, Field(max_length=100, pattern=r"^[A-Za-z0-9 ._:/+()-]+$")]
PositionId = Annotated[
    str,
    Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
]
Timeframe = Literal["1m", "5m", "15m", "1h", "4h", "1d"]
CandleLimit = Annotated[int, Field(ge=10, le=100, strict=True)]
NewsLimit = Annotated[int, Field(ge=1, le=10, strict=True)]
HistoryLimit = Annotated[int, Field(ge=1, le=20, strict=True)]
Query = Annotated[str | None, Field(max_length=100)]

INSTRUCTIONS = (
    "Paper trading only: virtual money, simulated fills, no real orders exist or are possible. "
    "Call get_guardrails first. The engine enforces pause, a minimum interval between entries, "
    "a daily loss breaker, a mandatory stop-loss and a per-trade risk cap; rejected requests "
    "return {'error': {'code', 'message'}}. Adjust and retry only when the message says how; "
    "otherwise do nothing this run."
)


def _error(code: str, message: str, status: int | None = None) -> dict:
    body: dict[str, Any] = {"code": code, "message": message}
    if status is not None:
        body["status"] = status
    return {"error": body}


def _decimal_between(value: str, low: str, high: str) -> bool:
    try:
        number = Decimal(value)
    except InvalidOperation:
        return False
    return Decimal(low) <= number <= Decimal(high)


def check_engine_url(url: str) -> str:
    """The engine must be reached over loopback; the agent token never leaves the host."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or parts.hostname not in LOOPBACK_NAMES:
        raise ValueError("PAPER_ENGINE_URL must be http(s)://127.0.0.1, localhost or [::1]")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("PAPER_ENGINE_URL must not contain credentials, query or fragment")
    return url.rstrip("/")


class EngineClient:
    """Thin API wrapper. Converts every failure into a compact {'error': ...} dict."""

    def __init__(self, client: httpx2.AsyncClient):
        self.client = client

    async def request(self, method: str, path: str, **kwargs) -> Any:
        try:
            response = await self.client.request(method, f"/api/v1{path}", **kwargs)
        except httpx2.TimeoutException:
            return _error("engine_timeout", "The paper engine did not respond in time")
        except httpx2.HTTPError:
            return _error("engine_unreachable", "The paper engine is not reachable")
        try:
            data = response.json()
        except ValueError:
            data = None
        if response.is_success:
            return data
        if isinstance(data, dict) and isinstance(data.get("error"), dict):
            error = data["error"]
            return _error(
                str(error.get("code", "error")), str(error.get("message", "")), response.status_code
            )
        if response.status_code == 422 and isinstance(data, dict):
            details = data.get("detail")
            text = "; ".join(
                f"{'.'.join(str(p) for p in d.get('loc', [])[1:])}: {d.get('msg')}"
                for d in (details if isinstance(details, list) else [])[:5]
            )
            return _error("validation_error", text or "Invalid request", 422)
        if response.status_code == 401:
            return _error("unauthorized", "PAPER_AGENT_TOKEN was rejected by the engine", 401)
        return _error("engine_error", f"HTTP {response.status_code}", response.status_code)


def _compact_position(p: dict) -> dict:
    keys = (
        "id", "symbol", "side", "leverage", "quantity", "entry_price", "margin", "stop_loss",
        "take_profit", "mark_price", "unrealized_pnl", "estimated_settlement_pnl", "opened_at",
        "quote_stale", "strategy",
    )  # fmt: skip
    return {k: p.get(k) for k in keys if p.get(k) is not None}


def _guardrails(state: dict) -> dict:
    keys = (
        "enabled", "paused", "pause_reason", "breaker_tripped", "breaker_resets_at",
        "daily_pnl", "daily_loss", "daily_loss_limit", "valuation_complete",
        "cooldown_remaining_seconds", "min_open_interval_seconds", "open_positions",
        "max_open_positions", "max_leverage", "max_risk_per_trade_pct",
        "max_risk_per_trade_usdt",
    )  # fmt: skip
    result = {k: state.get(k) for k in keys if k in state}
    if state.get("enabled"):
        result["can_open_now"] = bool(
            not state["paused"]
            and not state["breaker_tripped"]
            and state["valuation_complete"]
            and state["cooldown_remaining_seconds"] <= 0
            and state["open_positions"] < state["max_open_positions"]
        )
    return result


def build_server(client: httpx2.AsyncClient) -> MCPServer:
    engine = EngineClient(client)
    server = MCPServer("paper-trading-engine", instructions=INSTRUCTIONS, log_level="WARNING")

    @server.tool()
    async def get_guardrails() -> dict:
        """Current agent limits and status. Call this first; respect can_open_now."""
        state = await engine.request("GET", "/agent/state")
        return state if "error" in state else _guardrails(state)

    @server.tool()
    async def get_overview() -> dict:
        """Wallet, guardrails, your open (Hermes) positions and the tradable symbol list."""
        snapshot = await engine.request("GET", "/status")
        if "error" in snapshot:
            return snapshot
        account = snapshot["account"]
        markets = snapshot["markets"]
        return {
            "paper_only": True,
            "wallet": account["wallet_balance"],
            "available": account["available_balance"],
            "equity": account["equity"],
            "guardrails": _guardrails(snapshot.get("agent", {})),
            "my_open_positions": [
                _compact_position(p) for p in snapshot["positions"] if p.get("actor") == "agent"
            ],
            "other_open_positions": sum(
                1 for p in snapshot["positions"] if p.get("actor") != "agent"
            ),
            "symbols": [s for s, m in markets.items() if not m.get("close_only")],
            "live_symbols": [
                s for s, m in markets.items() if not m.get("stale") and not m.get("close_only")
            ],
        }

    @server.tool()
    async def get_market(symbol: Symbol) -> dict:
        """Best bid/ask, spread, quote age and feed status for one symbol."""
        snapshot = await engine.request("GET", "/status")
        if "error" in snapshot:
            return snapshot
        market = snapshot["markets"].get(symbol)
        if market is None:
            return _error("unsupported_symbol", "Symbol is not configured; see get_overview")
        bid, ask = market.get("bid"), market.get("ask")
        spread = None
        if bid and ask:
            mid = (Decimal(bid) + Decimal(ask)) / 2
            spread = str(((Decimal(ask) - Decimal(bid)) / mid * 10000).quantize(Decimal("0.01")))
        return {
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "spread_bps": spread,
            "age_ms": market.get("age_ms"),
            "status": market.get("status"),
            "stale": market.get("stale"),
            "close_only": market.get("close_only"),
            "price_tick": market.get("price_tick"),
        }

    @server.tool()
    async def get_candles(
        symbol: Symbol, timeframe: Timeframe = "15m", limit: CandleLimit = 60
    ) -> dict:
        """Recent OHLCV candles as [unix_time, open, high, low, close, volume], oldest first."""
        data = await engine.request(
            "GET", "/candles", params={"symbol": symbol, "timeframe": timeframe}
        )
        if "error" in data:
            return data
        rows = data["candles"][-limit:]
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "last_closed": bool(rows and rows[-1]["closed"]),
            "candles": [
                [c["time"], c["open"], c["high"], c["low"], c["close"], c["volume"]] for c in rows
            ],
        }

    @server.tool()
    async def get_news(symbol: Symbol | None = None, q: Query = None, limit: NewsLimit = 5) -> dict:
        """Latest crypto RSS headlines (plain text), optionally for one symbol or keyword."""
        params: dict[str, Any] = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        if q:
            params["q"] = q
        data = await engine.request("GET", "/news", params=params)
        if "error" in data:
            return data
        return {
            "updated_at": data.get("updated_at"),
            "items": [
                {
                    "title": i["title"],
                    "summary": i["summary"][:200],
                    "source": i["source"],
                    "published_at": i["published_at"],
                    "symbols": i["symbols"],
                }
                for i in data["items"]
            ],
        }

    @server.tool()
    async def get_history(limit: HistoryLimit = 10) -> dict:
        """Your recent closed paper trades with net PnL and recorded reasons."""
        rows = await engine.request("GET", "/trades", params={"limit": 100})
        if isinstance(rows, dict) and "error" in rows:
            return rows
        mine = [r for r in rows if r.get("actor") == "agent"][:limit]
        return {
            "trades": [
                {
                    "id": r["id"],
                    "symbol": r["symbol"],
                    "side": r["side"],
                    "leverage": r["leverage"],
                    "entry_price": r["entry_price"],
                    "exit_price": r["exit_price"],
                    "net_pnl": r["net_pnl"],
                    "exit_reason": r["exit_reason"],
                    "opened_at": r["opened_at"],
                    "closed_at": r["closed_at"],
                    "entry_reason": (r.get("notes") or "")[:300],
                    "exit_notes": (r.get("exit_notes") or "")[:300],
                }
                for r in mine
            ]
        }

    @server.tool()
    async def open_position(
        symbol: Symbol,
        side: Literal["long", "short"],
        allocation_pct: Allocation,
        leverage: Leverage,
        stop_loss: Price,
        reason: EntryReason,
        take_profit: Price | None = None,
        strategy: Strategy = None,
    ) -> dict:
        """Open an isolated paper position. stop_loss is mandatory; the engine rejects any
        trade whose estimated loss at the stop exceeds the per-trade risk cap."""
        if not _decimal_between(allocation_pct, "0.02", "0.05"):
            return _error("invalid_allocation", "allocation_pct must be between 0.02 and 0.05")
        body: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "allocation_pct": allocation_pct,
            "leverage": leverage,
            "stop_loss": stop_loss,
            "reason": reason,
        }
        if take_profit is not None:
            body["take_profit"] = take_profit
        if strategy:
            body["strategy"] = strategy
        result = await engine.request(
            "POST", "/agent/orders", json=body, headers={"Idempotency-Key": f"mcp-{uuid4()}"}
        )
        return result if "error" in result else {"opened": _compact_position(result)}

    @server.tool()
    async def close_position(position_id: PositionId, reason: ExitReason) -> dict:
        """Close one of your own open paper positions at market."""
        result = await engine.request(
            "POST",
            f"/agent/positions/{position_id}/close",
            json={"reason": reason},
            headers={"Idempotency-Key": f"mcp-{uuid4()}"},
        )
        if "error" in result:
            return result
        keys = ("id", "symbol", "side", "exit_price", "net_pnl", "exit_reason", "closed_at")
        return {"closed": {k: result.get(k) for k in keys}}

    return server


def make_http_client(engine_url: str, agent_token: str) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        base_url=check_engine_url(engine_url),
        headers={"Authorization": f"Bearer {agent_token}", "User-Agent": "paper-engine-mcp/1"},
        timeout=httpx2.Timeout(20, connect=5),
        follow_redirects=False,
    )


class BearerAuth:
    """Pure ASGI middleware: every HTTP request must carry the MCP bearer token."""

    def __init__(self, app, token: str):
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            supplied = dict(scope.get("headers") or []).get(b"authorization", b"")
            if not secrets.compare_digest(supplied, self.expected):
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"www-authenticate", b"Bearer"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
                return
        await self.app(scope, receive, send)


def check_bind_host(host: str) -> str:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("--host must be an explicit IP address") from exc
    if address.is_unspecified:
        raise ValueError("Refusing to bind every interface; pass a specific IP (e.g. 172.17.0.1)")
    return host


def build_http_app(server: MCPServer, host: str, port: int, token: str):
    from mcp.server.transport_security import TransportSecuritySettings

    if len(token) < 32:
        raise ValueError("PAPER_MCP_TOKEN must contain at least 32 characters")
    authority = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=[authority, host]
    )
    app = server.streamable_http_app(host=host, transport_security=security)
    return BearerAuth(app, token)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Paper trading MCP tool server")
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    # stdout carries the MCP protocol in stdio mode; diagnostics go to stderr only.
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    token = os.environ.get("PAPER_AGENT_TOKEN", "").strip()
    if len(token) < 32:
        sys.exit("PAPER_AGENT_TOKEN is missing or too short (see DEPLOYMENT.md)")
    try:
        client = make_http_client(os.environ.get("PAPER_ENGINE_URL", DEFAULT_ENGINE_URL), token)
    except ValueError as exc:
        sys.exit(str(exc))
    server = build_server(client)
    if args.transport == "stdio":
        server.run("stdio")
        return
    import anyio
    import uvicorn

    try:
        host = check_bind_host(args.host)
        app = build_http_app(server, host, args.port, os.environ.get("PAPER_MCP_TOKEN", ""))
    except ValueError as exc:
        sys.exit(str(exc))
    config = uvicorn.Config(app, host=host, port=args.port, log_level="warning", workers=1)
    anyio.run(uvicorn.Server(config).serve)


if __name__ == "__main__":
    main()
