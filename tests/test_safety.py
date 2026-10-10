import ast
import tomllib
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from paper_engine.config import Settings
from tests.conftest import TOKEN


def test_exchange_adapter_uses_only_public_market_methods():
    path = Path(__file__).parents[1] / "paper_engine" / "feeds.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "exchange"
    }
    assert called == {
        "market",
        "load_markets",
        "watch_order_book",
        "fetch_tickers",
        "fetch_order_book",
        "close",
    }


def test_apex_public_feed_configuration_is_supported():
    settings = Settings(_env_file=None, api_token=TOKEN, exchange="apex")
    assert settings.exchange == "apex"
    assert settings.max_quote_age_seconds == 5
    assert settings.taker_fee_rate == Decimal("0.0006")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"api_token": "short"},
        {"api_token": "replace-with-a-random-token-at-least-32-characters"},
        {"exchange": "unsupported"},
        {"default_leverage": 21},
        {"max_leverage": 2},
        {"default_allocation_pct": "0.06"},
        {"initial_balance": "NaN"},
        {"symbols": []},
        {"symbols": ["BTC/USDT"]},
        {"cors_origins": ["*"]},
        {"api_key": "not-allowed"},
    ],
)
def test_unsafe_configuration_rejected(kwargs):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{"api_token": TOKEN, **kwargs})


def test_network_dependencies_are_exactly_pinned():
    root = Path(__file__).parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    runtime = project["dependencies"]
    dev = project["optional-dependencies"]["dev"]
    assert "httpx2==2.13.1" in runtime
    assert "feedparser==6.0.14" in runtime
    # Legacy httpx is stalled and deprecated for Starlette's TestClient; keep it out.
    assert not any(dep.split("=")[0].split(">")[0].strip() == "httpx" for dep in runtime + dev)
    assert not any(dep.startswith("httpx2") for dep in dev)
    assert project["optional-dependencies"]["agent"] == ["mcp==2.3.0"]
    lock = (root / "requirements.lock").read_text(encoding="utf-8").splitlines()
    assert "httpx2==2.13.1" in lock and "feedparser==6.0.14" in lock
    assert "mcp==2.3.0" in lock
    assert not any(line.startswith("httpx==") for line in lock)
