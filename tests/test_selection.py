import time
from unittest.mock import AsyncMock

import ccxt
import pytest
from fastapi.testclient import TestClient

from paper_engine import feeds
from paper_engine.api import create_app
from paper_engine.config import Settings
from paper_engine.models import EngineError, OpenOrder
from tests.conftest import TOKEN


def market(symbol, active=True):
    return {
        "symbol": symbol,
        "active": active,
        "swap": True,
        "linear": True,
        "settle": "USDT",
        "contractSize": 1,
        "precision": {"amount": 1, "price": 0.00001},
        "limits": {},
    }


class Universe:
    precisionMode = ccxt.TICK_SIZE

    def __init__(self):
        self.markets = {f"C{i}/USDT:USDT": market(f"C{i}/USDT:USDT") for i in range(40)}
        self.markets["C0/USDT:USDT"]["active"] = False
        self.checked = []

    async def fetch_tickers(self):
        return {s: {"quoteVolume": 1000 - i} for i, s in enumerate(self.markets)}

    def market(self, symbol):
        return self.markets[symbol]

    async def fetch_order_book(self, symbol):
        self.checked.append(symbol)
        return {
            "bids": [] if symbol == "C1/USDT:USDT" else [[0.001, 1000]],
            "asks": [[0.00101, 1000]],
            "timestamp": time.time_ns() // 1_000_000,
        }


async def test_selects_35_by_quote_volume_skipping_inactive_and_empty(monkeypatch):
    exchange = Universe()
    select = getattr(feeds, "select_top_symbols", None)
    assert callable(select), "Startup top-volume selector is missing"
    monkeypatch.setattr(feeds.asyncio, "sleep", AsyncMock())
    selected = await select(exchange, 35, 5)
    assert selected == [f"C{i}/USDT:USDT" for i in range(2, 37)]
    assert "C0/USDT:USDT" not in exchange.checked


async def test_selection_fails_closed_when_not_enough_valid_depth(monkeypatch):
    exchange = Universe()
    exchange.fetch_order_book = AsyncMock(return_value={"bids": [], "asks": []})
    select = getattr(feeds, "select_top_symbols", None)
    assert callable(select), "Startup top-volume selector is missing"
    monkeypatch.setattr(feeds.asyncio, "sleep", AsyncMock())
    with pytest.raises(ValueError, match="35"):
        await select(exchange, 35, 5)


def test_fixed_universe_accepts_35_and_preserves_safety():
    settings = Settings(
        _env_file=None, api_token=TOKEN, symbols=[f"C{i}/USDT:USDT" for i in range(35)]
    )
    assert len(settings.symbols) == 35
    assert settings.max_quote_age_seconds == 5


def test_apex_metadata_preserves_small_price_tick():
    result = feeds.market_from_ccxt(market("C2/USDT:USDT"), ccxt.TICK_SIZE, "apex")
    assert getattr(result, "price_tick", None) is not None
    assert str(result.price_tick) == "0.00001"


async def test_startup_selection_retains_open_position_as_close_only(engine, monkeypatch):
    opened = await engine.open(OpenOrder(symbol="BTC/USDT:USDT", side="long"), "retained-position")
    settings = engine.settings
    engine.store.close()
    settings.exchange = "okx"
    settings.symbol_selection = "top_volume"
    settings.feed_enabled = True
    selected = ["ETH/USDT:USDT"]
    monkeypatch.setattr(
        "paper_engine.api.discover_symbols", AsyncMock(return_value=selected), raising=False
    )
    monkeypatch.setattr(feeds.CCXTFeed, "run", AsyncMock())
    with TestClient(create_app(settings)) as client:
        config = client.get("/api/v1/config", headers={"Authorization": f"Bearer {TOKEN}"}).json()
        assert config["symbols"] == selected
        state = client.app.state.engine
        assert "BTC/USDT:USDT" in state.feed
        assert state.store.position(opened["id"]).status == "open"
        with pytest.raises(EngineError, match="not configured"):
            client.portal.call(
                state.open, OpenOrder(symbol="BTC/USDT:USDT", side="long"), "new-order"
            )


async def test_quiet_market_rest_refresh_preserves_five_second_protection(engine):
    refresh = getattr(feeds.CCXTFeed(engine), "refresh_book", None)
    assert callable(refresh), "Quiet-book recovery is missing"
    exchange = Universe()
    exchange.markets["BTC/USDT:USDT"] = market("BTC/USDT:USDT")
    exchange.fetch_order_book = AsyncMock(
        return_value={
            "bids": [[99, 100]],
            "asks": [[100, 100]],
            "timestamp": (time.time_ns() // 1_000_000) - 10000,
        }
    )
    previous = engine.books["BTC/USDT:USDT"]
    await refresh(exchange, "BTC/USDT:USDT")
    assert engine.books.get("BTC/USDT:USDT") is previous


async def test_repeated_depth_snapshot_does_not_replenish_consumed_liquidity(engine):
    exchange = Universe()
    exchange.markets["BTC/USDT:USDT"] = market("BTC/USDT:USDT")
    original = engine.books["BTC/USDT:USDT"]
    await engine.open(OpenOrder(symbol="BTC/USDT:USDT", side="long"), "consume-once")
    remaining = engine.liquidity["BTC/USDT:USDT"]
    exchange.fetch_order_book = AsyncMock(
        return_value={
            "bids": [[99, 10000]],
            "asks": [[100, 10000]],
            "timestamp": original.exchange_timestamp_ms,
        }
    )
    await feeds.CCXTFeed(engine).refresh_book(exchange, "BTC/USDT:USDT")
    assert engine.liquidity["BTC/USDT:USDT"] is remaining


async def test_invalid_volumes_and_stale_crossed_depth_are_skipped(monkeypatch):
    exchange = Universe()
    exchange.fetch_tickers = AsyncMock(
        return_value={
            s: {"quoteVolume": "NaN" if i == 2 else "Infinity" if i == 3 else 1000 - i}
            for i, s in enumerate(exchange.markets)
        }
    )
    fetch = exchange.fetch_order_book

    async def depth(symbol):
        book = await fetch(symbol)
        if symbol == "C4/USDT:USDT":
            book["timestamp"] -= 10000
        if symbol == "C5/USDT:USDT":
            book["bids"] = [[1, 1000]]
        return book

    exchange.fetch_order_book = depth
    monkeypatch.setattr(feeds.asyncio, "sleep", AsyncMock())
    assert await feeds.select_top_symbols(exchange, 2, 5) == ["C6/USDT:USDT", "C7/USDT:USDT"]
