import json
import logging
from contextlib import asynccontextmanager
from decimal import Decimal

import httpx2
import pytest
from mcp import Client
from pydantic import SecretStr

from paper_engine import mcp_server
from paper_engine.api import create_app
from paper_engine.books import Market
from paper_engine.mcp_server import TOOL_NAMES, build_server, check_bind_host, check_engine_url
from tests.conftest import AGENT_TOKEN, SYMBOL, TOKEN, make_book

D = Decimal
OPEN = {
    "symbol": SYMBOL,
    "side": "long",
    "allocation_pct": "0.02",
    "leverage": 10,
    "stop_loss": "95.5",
    "reason": "Range breakout on the 15m close with rising volume.",
}


@asynccontextmanager
async def mcp_stack(settings):
    """Real FastAPI app (with lifespan) behind an in-process ASGI transport.

    Used as `async with` inside each test: the MCP client's anyio task group must be
    entered and exited in the same task, which async yield-fixtures do not guarantee.
    """
    settings.agent_token = SecretStr(AGENT_TOKEN)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        engine = app.state.engine
        await engine.register_markets({SYMBOL: Market(SYMBOL, D("0.001"))})
        await engine.on_book(make_book())
        requests: list[httpx2.Request] = []

        async def record(request):
            requests.append(request)

        http = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://127.0.0.1:8000",
            headers={"Authorization": f"Bearer {AGENT_TOKEN}"},
            event_hooks={"request": [record]},
        )
        async with http, Client(build_server(http)) as client:
            yield client, engine, requests


async def call(client, name, args=None):
    result = await client.call_tool(name, args or {})
    text = result.content[0].text
    return result.is_error, (json.loads(text) if not result.is_error else text)


async def test_exactly_the_documented_tools_and_no_operator_controls(settings):
    async with mcp_stack(settings) as stack:
        client, _, _ = stack
        tools = (await client.list_tools()).tools
        assert sorted(t.name for t in tools) == sorted(TOOL_NAMES) and len(tools) == 8
        names = " ".join(t.name for t in tools)
        assert "pause" not in names and "resume" not in names and "config" not in names
        schema = next(t for t in tools if t.name == "open_position").input_schema
        assert set(schema["required"]) == {
            "symbol", "side", "allocation_pct", "leverage", "stop_loss", "reason"
        }  # fmt: skip


async def test_open_cooldown_and_close_through_mcp(settings):
    async with mcp_stack(settings) as stack:
        client, engine, _ = stack
        error, body = await call(client, "get_guardrails")
        assert not error and body["paused"] is True and body["can_open_now"] is False
        error, body = await call(client, "open_position", OPEN)
        assert body == {
            "error": {"code": "agent_paused", "message": "Hermes is paused by the operator",
                      "status": 409}
        }  # fmt: skip
        await engine.set_agent_paused(False, "operator", None)
        error, body = await call(client, "open_position", {**OPEN, "strategy": "breakout-15m"})
        assert not error and body["opened"]["symbol"] == SYMBOL
        position_id = body["opened"]["id"]
        assert body["opened"]["strategy"] == "hermes:breakout-15m"
        error, body = await call(client, "open_position", OPEN)
        assert body["error"]["code"] == "agent_cooldown"
        error, overview = await call(client, "get_overview")
        assert overview["paper_only"] is True
        assert [p["id"] for p in overview["my_open_positions"]] == [position_id]
        assert overview["symbols"] == [SYMBOL]
        error, market = await call(client, "get_market", {"symbol": SYMBOL})
        assert market["bid"] == "99" and market["spread_bps"] == "100.50"
        error, closed = await call(
            client, "close_position", {"position_id": position_id, "reason": "Thesis played out"}
        )
        assert closed["closed"]["id"] == position_id
        error, history = await call(client, "get_history", {"limit": 5})
        assert history["trades"][0]["exit_notes"] == "Thesis played out"
        assert history["trades"][0]["entry_reason"] == OPEN["reason"]


async def test_risk_cap_message_reaches_the_model(settings):
    async with mcp_stack(settings) as stack:
        client, engine, _ = stack
        await engine.set_agent_paused(False, "operator", None)
        error, body = await call(client, "open_position", {**OPEN, "stop_loss": "95"})
        assert body["error"]["code"] == "agent_risk_limit"
        assert "maximum is 100.00 USDT" in body["error"]["message"]


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("open_position", {**OPEN, "symbol": "btc/usdt"}),
        ("open_position", {**OPEN, "symbol": "BTC/USDT:USDT; DROP"}),
        ("open_position", {**OPEN, "stop_loss": "-1"}),
        ("open_position", {**OPEN, "stop_loss": "1e9"}),
        ("open_position", {**OPEN, "allocation_pct": "0.5"}),
        ("open_position", {**OPEN, "leverage": "10"}),
        ("open_position", {**OPEN, "side": "buy"}),
        ("open_position", {**OPEN, "reason": "too short"}),
        ("open_position", {**OPEN, "reason": "x" * 2001}),
        ("open_position", {**OPEN, "strategy": "<b>x</b>"}),
        ("open_position", {k: v for k, v in OPEN.items() if k != "stop_loss"}),
        ("close_position", {"position_id": "../../orders", "reason": "long enough reason"}),
        ("get_candles", {"symbol": SYMBOL, "timeframe": "2m"}),
        ("get_candles", {"symbol": SYMBOL, "limit": 1000}),
        ("get_news", {"limit": 50}),
        ("get_history", {"limit": 500}),
    ],
)
async def test_invalid_inputs_are_rejected_before_any_http_call(settings, tool, args):
    async with mcp_stack(settings) as stack:
        client, _, requests = stack
        error, _ = await call(client, tool, args)
        assert error is True
        assert requests == []


async def test_allocation_below_minimum_is_rejected_locally(settings):
    async with mcp_stack(settings) as stack:
        client, _, requests = stack
        error, body = await call(client, "open_position", {**OPEN, "allocation_pct": "0.01"})
        assert body["error"]["code"] == "invalid_allocation" and requests == []


async def test_engine_failures_are_structured_and_token_never_leaks(settings, caplog):
    async with mcp_stack(settings) as stack:
        client, _, _ = stack
        caplog.set_level(logging.DEBUG)
        error, body = await call(client, "get_news")
        assert body["error"]["code"] == "news_disabled"
        error, body = await call(client, "get_candles", {"symbol": SYMBOL})
        assert body["error"]["code"] == "feed_disabled"
        assert AGENT_TOKEN not in caplog.text and TOKEN not in caplog.text


async def test_unreachable_engine_is_reported_not_raised():
    async def refuse(request):
        raise httpx2.ConnectError("refused", request=request)

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(refuse), base_url="http://127.0.0.1")
    async with http, Client(build_server(http)) as client:
        error, body = await call(client, "get_overview")
        assert body == {
            "error": {"code": "engine_unreachable", "message": "The paper engine is not reachable"}
        }


def test_engine_url_must_be_loopback():
    assert check_engine_url("http://127.0.0.1:8000/") == "http://127.0.0.1:8000"
    for url in ["http://10.0.0.5:8000", "https://example.com", "ftp://127.0.0.1",
                "http://user:pw@127.0.0.1:8000", "http://127.0.0.1.evil.test"]:  # fmt: skip
        with pytest.raises(ValueError):
            check_engine_url(url)


def test_http_mode_refuses_wildcard_and_requires_token():
    assert check_bind_host("172.17.0.1") == "172.17.0.1"
    for host in ["0.0.0.0", "::", "my-host"]:
        with pytest.raises(ValueError):
            check_bind_host(host)
    with pytest.raises(ValueError):
        mcp_server.build_http_app(build_server(httpx2.AsyncClient()), "127.0.0.1", 8765, "short")


async def test_http_mode_requires_bearer_token():
    token = "mcp-test-token-" + "z" * 30
    app = mcp_server.build_http_app(build_server(httpx2.AsyncClient()), "127.0.0.1", 8765, token)
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:8765"
    ) as http:
        response = await http.post("/mcp", json={})
        assert response.status_code == 401
        wrong = await http.post("/mcp", json={}, headers={"Authorization": "Bearer nope"})
        assert wrong.status_code == 401


def test_main_refuses_missing_token(monkeypatch):
    monkeypatch.delenv("PAPER_AGENT_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="PAPER_AGENT_TOKEN"):
        mcp_server.main([])
    monkeypatch.setenv("PAPER_AGENT_TOKEN", AGENT_TOKEN)
    monkeypatch.setenv("PAPER_ENGINE_URL", "http://203.0.113.9:8000")
    with pytest.raises(SystemExit, match="loopback|127.0.0.1"):
        mcp_server.main([])
