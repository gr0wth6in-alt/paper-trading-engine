import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from paper_engine.api import create_app
from paper_engine.candles import CandleService, normalize_candles
from paper_engine.models import EngineError
from tests.conftest import SYMBOL, TOKEN

AUTH = {"Authorization": f"Bearer {TOKEN}"}


def test_config_requires_auth_and_never_exposes_secrets(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/config").status_code == 401
        response = client.get("/api/v1/config", headers=AUTH)
        assert response.status_code == 200
        assert TOKEN not in response.text
        assert "api_token" not in response.text
        assert "db_path" not in response.text
        assert response.json()["max_leverage"] == settings.max_leverage


def test_static_frontend_preserves_api_routes(settings):
    settings.frontend_dist.mkdir()
    (settings.frontend_dist / "index.html").write_text("<h1>Test terminal</h1>")
    (settings.frontend_dist / "assets").mkdir()
    (settings.frontend_dist / "assets" / "app.js").write_text("console.log('test')")
    with TestClient(create_app(settings)) as client:
        assert "Test terminal" in client.get("/").text
        assert client.get("/").headers["cache-control"] == "no-store"
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/assets/../.env").status_code == 404
        assert client.get("/.env").status_code == 404
        assert client.get("/health").status_code == 200
        assert client.get("/docs").status_code == 200
        assert client.get("/api/v1/account").status_code == 401


def test_same_origin_browser_websocket_is_allowed(settings):
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8000") as client:
        with client.websocket_connect(
            "ws://127.0.0.1:8000/ws", headers={"Origin": "http://127.0.0.1:8000"}
        ) as ws:
            ws.send_json({"token": TOKEN})
            assert ws.receive_json()["mode"] == "paper"


def test_candle_request_fails_closed_without_network_when_disabled(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/candles", params={"symbol": SYMBOL}).status_code == 401
        response = client.get("/api/v1/candles", params={"symbol": SYMBOL}, headers=AUTH)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "feed_disabled"
        response = client.get(
            "/api/v1/candles", params={"symbol": SYMBOL, "timeframe": "1s"}, headers=AUTH
        )
        assert response.status_code == 422


@pytest.mark.parametrize(
    "origin",
    ["http://127.0.0.1:8001", "https://127.0.0.1:8000", "null", "http://[", "http://evil.test"],
)
def test_browser_origin_must_match_scheme_host_and_port(settings, origin):
    with TestClient(create_app(settings)) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("ws://127.0.0.1:8000/ws", headers={"Origin": origin}):
                pass


def test_candle_normalization():
    start = (int(time.time()) // 300 - 2) * 300 * 1000
    rows = [[start + 300000, 100, 110, 99, 105, 12], [start, 95, 101, 94, 100, 10]]
    candles = normalize_candles(rows + rows, "5m")
    assert len(candles) == 2
    assert candles[0]["time"] < candles[1]["time"]
    assert candles[0]["closed"] is True
    for row in [
        [start, 100, 90, 110, 105, 10],
        [start, 100, 110, 90, float("nan"), 10],
        [start, 100, 110, 90, 105, -1],
    ]:
        with pytest.raises(ValueError):
            normalize_candles([row], "5m")


async def test_candle_cache_and_shutdown(settings):
    settings.feed_enabled = True
    service = CandleService(settings)

    class Exchange:
        calls = 0
        closed = False

        async def fetch_ohlcv(self, symbol, timeframe, limit):
            self.calls += 1
            return [[(int(time.time()) // 300 - 1) * 300000, 100, 110, 90, 105, 1]]

        async def close(self):
            self.closed = True

    service.exchange = Exchange()
    responses = await asyncio.gather(*(service.get(SYMBOL, "5m") for _ in range(5)))
    assert service.exchange.calls == 1
    assert all(r == responses[0] for r in responses)
    assert responses[0]["source"] == "exchange_ohlcv"
    await service.close()
    assert service.exchange.closed


async def test_candle_failure_has_bounded_retry(settings):
    settings.feed_enabled = True
    service = CandleService(settings)

    class Exchange:
        calls = 0

        async def fetch_ohlcv(self, *args, **kwargs):
            self.calls += 1
            raise ConnectionError("offline")

    service.exchange = Exchange()
    for _ in range(2):
        with pytest.raises(EngineError) as exc:
            await service.get(SYMBOL, "1m")
        assert exc.value.code == "candles_unavailable"
    assert service.exchange.calls == 1
