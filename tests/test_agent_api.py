from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from paper_engine.api import create_app
from paper_engine.books import Market
from tests.conftest import AGENT_AUTH, AGENT_TOKEN, AUTH, SYMBOL, TOKEN, make_book

ORDER = {
    "symbol": SYMBOL,
    "side": "long",
    "allocation_pct": "0.02",
    "leverage": 10,
    "stop_loss": "95.5",
    "reason": "Range breakout confirmed on 15m close with volume.",
}


def key(n):
    return {"Idempotency-Key": f"agent-key-{n:04d}"}


@pytest.fixture
def client(settings):
    settings.agent_token = SecretStr(AGENT_TOKEN)
    app = create_app(settings)
    with TestClient(app) as client:
        engine = app.state.engine
        client.portal.call(engine.register_markets, {SYMBOL: Market(SYMBOL, Decimal("0.001"))})
        client.portal.call(engine.on_book, make_book())
        yield client


def resume(client):
    response = client.post("/api/v1/agent/resume", headers=AUTH, json={"reason": "go live"})
    assert response.status_code == 200 and response.json()["paused"] is False


def test_health_and_config_report_hermes_status(client):
    assert client.get("/health").json()["hermes"] == "paused"
    config = client.get("/api/v1/config", headers=AUTH).json()
    assert config["hermes"] == "paused"
    assert config["agent"] == {
        "enabled": True,
        "min_open_interval_seconds": 900,
        "daily_loss_pct": "0.03",
        "max_open_positions": 3,
        "max_leverage": 10,
        "max_risk_per_trade_pct": "0.01",
    }
    resume(client)
    assert client.get("/health").json()["hermes"] == "active"


def test_agent_trade_flow_and_guardrail_codes(client):
    response = client.post("/api/v1/agent/orders", headers={**AGENT_AUTH, **key(1)}, json=ORDER)
    assert response.status_code == 409 and response.json()["error"]["code"] == "agent_paused"
    resume(client)
    opened = client.post("/api/v1/agent/orders", headers={**AGENT_AUTH, **key(2)}, json=ORDER)
    assert opened.status_code == 201 and opened.json()["actor"] == "agent"
    again = client.post("/api/v1/agent/orders", headers={**AGENT_AUTH, **key(3)}, json=ORDER)
    assert again.status_code == 409 and again.json()["error"]["code"] == "agent_cooldown"
    position_id = opened.json()["id"]
    closed = client.post(
        f"/api/v1/agent/positions/{position_id}/close",
        headers={**AGENT_AUTH, **key(4)},
        json={"reason": "Target zone reached early"},
    )
    assert closed.status_code == 200 and closed.json()["exit_notes"] == "Target zone reached early"
    journal = client.get("/api/v1/journals", headers=AGENT_AUTH).json()[0]
    assert journal["metrics"]["exit_rationale"] == "Target zone reached early"
    snapshot = client.get("/api/v1/status", headers=AUTH).json()
    assert snapshot["agent"]["cooldown_remaining_seconds"] > 800
    events = client.get("/api/v1/agent/events", headers=AUTH).json()
    assert [e["code"] for e in events[:4]] == [None, "agent_cooldown", None, None]


def test_validation_and_risk_errors(client):
    resume(client)
    for body, status in [
        ({**ORDER, "stop_loss": None}, 422),
        ({**ORDER, "reason": "short"}, 422),
        ({**ORDER, "leverage": 11}, 422),
        ({**ORDER, "unknown": True}, 422),
    ]:
        response = client.post(
            "/api/v1/agent/orders", headers={**AGENT_AUTH, **key(status)}, json=body
        )
        assert response.status_code == status, response.text
    for n, (stop, code) in enumerate(
        [("95", "agent_risk_limit"), ("90", "agent_stop_beyond_liquidation")]
    ):
        response = client.post(
            "/api/v1/agent/orders",
            headers={**AGENT_AUTH, **key(20 + n)},
            json={**ORDER, "stop_loss": stop},
        )
        assert response.status_code == 422 and response.json()["error"]["code"] == code
    missing_key = client.post("/api/v1/agent/orders", headers=AGENT_AUTH, json=ORDER)
    assert missing_key.status_code == 422


@pytest.mark.parametrize(
    ("method", "path", "operator", "agent"),
    [
        ("post", "/api/v1/agent/orders", 403, None),
        ("post", "/api/v1/agent/pause", 200, 403),
        ("post", "/api/v1/agent/resume", 200, 403),
        ("post", "/api/v1/agent/close-all", 200, 403),
        ("get", "/api/v1/agent/events", 200, 403),
        ("get", "/api/v1/agent/state", 200, 200),
    ],
)
def test_agent_route_access_matrix(client, method, path, operator, agent):
    kwargs = {"json": ORDER} if path.endswith("orders") else {}
    call = getattr(client, method)
    response = call(path, headers={**AUTH, **key(1)}, **kwargs)
    assert response.status_code == operator
    if operator == 403:
        assert response.json()["error"]["code"] == "agent_token_required"
    if agent is not None:
        response = call(path, headers={**AGENT_AUTH, **key(2)}, **kwargs)
        assert response.status_code == agent
    assert call(path, **kwargs).status_code == 401


def test_agent_cannot_close_manual_position(client):
    manual = client.post(
        "/api/v1/orders", headers={**AUTH, **key(1)}, json={"symbol": SYMBOL, "side": "long"}
    ).json()
    response = client.post(
        f"/api/v1/agent/positions/{manual['id']}/close",
        headers={**AGENT_AUTH, **key(2)},
        json={"reason": "Trying to close a manual trade"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_agent_position"


def test_pause_close_all_and_websocket_snapshot(client):
    resume(client)
    client.post("/api/v1/agent/orders", headers={**AGENT_AUTH, **key(1)}, json=ORDER)
    paused = client.post("/api/v1/agent/pause", headers=AUTH)
    assert paused.status_code == 200 and paused.json()["paused"] is True
    result = client.post("/api/v1/agent/close-all", headers=AUTH).json()
    assert len(result["closed"]) == 1 and result["failed"] == []
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"token": TOKEN})
        agent = ws.receive_json()["agent"]
        assert agent["paused"] is True and agent["open_positions"] == 0


def test_agent_routes_when_agent_disabled(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").json()["hermes"] == "disabled"
        assert client.get("/api/v1/agent/state", headers=AUTH).json() == {"enabled": False}
        response = client.post("/api/v1/agent/pause", headers=AUTH)
        assert response.status_code == 503 and response.json()["error"]["code"] == "agent_disabled"
        assert client.get("/api/v1/config", headers=AUTH).json()["agent"]["enabled"] is False
