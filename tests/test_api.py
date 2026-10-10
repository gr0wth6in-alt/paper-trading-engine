from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from paper_engine.api import create_app
from paper_engine.books import Market
from tests.conftest import SYMBOL, TOKEN, make_book

AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        engine = app.state.engine
        client.portal.call(engine.register_markets, {SYMBOL: Market(SYMBOL, Decimal("0.001"))})
        client.portal.call(engine.on_book, make_book())
        yield client


def test_health_auth_and_docs(client):
    assert client.get("/health").json()["mode"] == "paper"
    assert client.get("/api/v1/account").status_code == 401
    assert (
        client.get("/api/v1/account", headers={"Authorization": "Bearer invalid"}).status_code
        == 401
    )
    assert client.get("/api/v1/account", headers=AUTH).status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_root_redirects_to_docs(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"
    docs = client.get("/")
    assert docs.status_code == 200
    assert "swagger-ui" in docs.text


def test_order_lifecycle_and_validation(client):
    body = {"symbol": SYMBOL, "side": "long"}
    assert client.post("/api/v1/orders", json=body, headers=AUTH).status_code == 422
    headers = {**AUTH, "Idempotency-Key": "api-open-123"}
    response = client.post("/api/v1/orders", json=body, headers=headers)
    assert response.status_code == 201, response.text
    assert client.post("/api/v1/orders", json=body, headers=headers).json() == response.json()
    conflict = client.post("/api/v1/orders", json={**body, "side": "short"}, headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"
    assert len(client.get("/api/v1/positions", headers=AUTH).json()) == 1
    url = f"/api/v1/positions/{response.json()['id']}/close"
    close = client.post(url, headers={**AUTH, "Idempotency-Key": "api-close-123"})
    assert close.status_code == 200
    assert close.json()["status"] == "closed"
    assert len(client.get("/api/v1/trades", headers=AUTH).json()) == 1
    assert len(client.get("/api/v1/journals", headers=AUTH).json()) == 1
    assert client.get("/api/v1/trades?limit=101", headers=AUTH).status_code == 422
    assert client.get("/api/v1/journals?offset=-1", headers=AUTH).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"symbol": SYMBOL, "side": "long", "allocation_pct": "0.06"},
        {"symbol": SYMBOL, "side": "long", "margin_mode": "cross"},
        {"symbol": SYMBOL, "side": "long", "leverage": 1.5},
        {"symbol": SYMBOL, "side": "long", "stop_loss": "NaN"},
        {"symbol": "DOGE/USDT:USDT", "side": "long"},
    ],
)
def test_order_validation(client, body):
    response = client.post(
        "/api/v1/orders", json=body, headers={**AUTH, "Idempotency-Key": "invalid-123"}
    )
    assert response.status_code == 422


def test_websocket_snapshot(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"token": TOKEN})
        snapshot = ws.receive_json()
        assert snapshot["mode"] == "paper"
        assert snapshot["account"]["wallet_balance"] == "10000"
        assert snapshot["journaling"]["provider"] == "disabled"


@pytest.mark.parametrize(
    "frame", [{"token": "wrong"}, {"token": 123}, [], {"token": TOKEN, "extra": 1}]
)
def test_websocket_requires_auth(client, frame):
    with client.websocket_connect("/ws") as ws:
        ws.send_json(frame)
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1008


def test_websocket_rejects_unknown_browser_origin(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"Origin": "https://untrusted.example"}):
            pass


def test_disabled_feed_never_manufactures_prices(settings):
    with TestClient(create_app(settings)) as client:
        status = client.get("/api/v1/status", headers=AUTH).json()
        assert status["markets"][SYMBOL]["bid"] is None
        response = client.post(
            "/api/v1/orders",
            json={"symbol": SYMBOL, "side": "long"},
            headers={**AUTH, "Idempotency-Key": "offline-entry"},
        )
        assert response.status_code == 503
