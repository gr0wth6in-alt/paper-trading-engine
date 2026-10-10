import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from starlette.websockets import WebSocketDisconnect

from paper_engine import configure
from paper_engine.api import create_app
from paper_engine.config import Settings
from tests.conftest import AGENT_AUTH, AGENT_TOKEN, AUTH, SYMBOL, TOKEN

POSITION = "00000000-0000-4000-8000-000000000000"
KEY = {"Idempotency-Key": "test-key-123"}


@pytest.fixture
def agent_settings(settings):
    settings.agent_token = SecretStr(AGENT_TOKEN)
    return settings


def test_agent_settings_validation():
    base = {"_env_file": None, "api_token": TOKEN}
    assert Settings(**base).agent_enabled is False
    assert Settings(**base, agent_token="").agent_enabled is False
    assert Settings(**base, agent_token=AGENT_TOKEN).agent_enabled is True
    for kwargs in [
        {"agent_token": "short"},
        {"agent_token": TOKEN},
        {"agent_token": "replace-with-a-random-token-at-least-32-characters"},
        {"agent_max_leverage": 21},
        {"agent_max_leverage": 15, "max_leverage": 10},
        {"agent_min_open_interval_seconds": 299},
        {"agent_daily_loss_pct": "0.001"},
        {"agent_daily_loss_pct": "0.5"},
        {"agent_max_risk_per_trade_pct": "0.06"},
        {"agent_max_open_positions": 0},
    ]:
        with pytest.raises(ValidationError):
            Settings(**base, **kwargs)


@pytest.mark.parametrize(
    ("method", "path", "operator", "agent"),
    [
        ("get", "/api/v1/config", 200, 200),
        ("get", "/api/v1/status", 200, 200),
        ("get", "/api/v1/account", 200, 200),
        ("get", "/api/v1/markets", 200, 200),
        ("get", "/api/v1/positions", 200, 200),
        ("get", "/api/v1/trades", 200, 200),
        ("get", "/api/v1/journals", 200, 200),
        ("post", "/api/v1/orders", 422, 403),
        ("post", f"/api/v1/positions/{POSITION}/close", 404, 403),
        ("get", "/api/v1/memes", 200, 403),
    ],
)
def test_route_access_matrix(agent_settings, method, path, operator, agent):
    with TestClient(create_app(agent_settings)) as client:
        call = getattr(client, method)
        kwargs = {"json": {}} if method == "post" else {}
        assert call(path, headers={**AUTH, **KEY}, **kwargs).status_code == operator
        response = call(path, headers={**AGENT_AUTH, **KEY}, **kwargs)
        assert response.status_code == agent
        if agent == 403:
            assert response.json()["error"]["code"] == "forbidden_for_agent"
        assert call(path, headers={"Authorization": "Bearer nope" + "x" * 40}).status_code == 401


def test_agent_token_rejected_when_agent_disabled(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/status", headers=AGENT_AUTH).status_code == 401


def test_tokens_never_exposed(agent_settings):
    with TestClient(create_app(agent_settings)) as client:
        for headers in (AUTH, AGENT_AUTH):
            text = client.get("/api/v1/config", headers=headers).text
            assert TOKEN not in text and AGENT_TOKEN not in text and "agent_token" not in text


def test_agent_token_cannot_open_websocket(agent_settings):
    with TestClient(create_app(agent_settings)) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"token": AGENT_TOKEN})
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"token": TOKEN})
            assert ws.receive_json()["type"] == "snapshot"


def test_configure_adds_agent_token_once(tmp_path, capsys):
    env = tmp_path / ".env"
    (tmp_path / ".env.example").write_text(
        "PAPER_API_TOKEN=replace-with-a-random-token-at-least-32-characters\n# PAPER_AGENT_TOKEN=\n"
    )
    configure.main(["--env", str(env)])
    assert "replace-with-" not in env.read_text()
    configure.main(["--env", str(env), "--agent-token"])
    first = env.read_text()
    line = [x for x in first.splitlines() if x.startswith("PAPER_AGENT_TOKEN=")]
    assert len(line) == 1 and len(line[0].split("=", 1)[1]) >= 32
    out = capsys.readouterr().out
    assert line[0].split("=", 1)[1] not in out  # not printed without --print
    configure.main(["--env", str(env), "--agent-token", "--print"])
    assert env.read_text() == first  # never overwritten
    assert line[0].split("=", 1)[1] in capsys.readouterr().out
    settings = Settings(_env_file=env)
    assert settings.agent_enabled and settings.agent_token.get_secret_value() != (
        settings.api_token.get_secret_value()
    )


def test_configure_fills_blank_agent_token(tmp_path):
    env = tmp_path / ".env"
    env.write_text(f'PAPER_API_TOKEN={TOKEN}\nPAPER_AGENT_TOKEN=\nPAPER_SYMBOLS=["{SYMBOL}"]\n')
    added, token = configure.add_agent_token(env)
    assert added and f"PAPER_AGENT_TOKEN={token}" in env.read_text()
    assert env.read_text().count("PAPER_AGENT_TOKEN") == 1
