import asyncio
import time
from dataclasses import replace
from decimal import Decimal

import ccxt
import pytest

from paper_engine import feeds
from paper_engine.engine import Engine
from paper_engine.feeds import CCXTFeed
from paper_engine.models import EngineError, OpenOrder
from paper_engine.store import Store
from tests.conftest import SYMBOL


class FakeExchange:
    has = {"watchOrderBook": True}
    precisionMode = ccxt.TICK_SIZE

    def __init__(self, config):
        assert "apiKey" not in config and "secret" not in config
        self.closed = False
        self.calls = 0
        self.invalid = False

    async def load_markets(self):
        pass

    def market(self, symbol):
        return {
            "symbol": symbol,
            "swap": not self.invalid,
            "linear": True,
            "settle": "USDT",
            "contractSize": 1,
            "precision": {"amount": 0.001},
            "limits": {},
        }

    async def watch_order_book(self, symbol):
        self.calls += 1
        if self.calls == 1:
            return {
                "bids": [[99, 100]],
                "asks": [[100, 100]],
                "timestamp": time.time_ns() // 1_000_000,
            }
        await asyncio.Event().wait()

    async def close(self):
        self.closed = True


async def wait_until(predicate):
    async with asyncio.timeout(5):
        for _ in range(500):
            if predicate():
                return
            await asyncio.sleep(0.01)
    raise AssertionError("Condition did not become true")


async def test_feed_normalizes_books_and_closes_on_cancel(engine, monkeypatch):
    created = []

    def factory(config):
        instance = FakeExchange(config)
        created.append(instance)
        return instance

    monkeypatch.setattr("paper_engine.feeds.ccxt.okx", factory)
    task = asyncio.create_task(CCXTFeed(engine).run())
    try:
        await wait_until(lambda: bool(created) and created[0].calls >= 2)
        assert engine.feed[SYMBOL]["status"] == "connected"
        assert engine.markets[SYMBOL].quantity_step == Decimal("0.001")
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert created[0].closed


async def test_feed_reconnects_without_preserving_stale_quotes(engine, monkeypatch):
    created = []

    class BrokenExchange(FakeExchange):
        async def watch_order_book(self, symbol):
            raise ConnectionError("simulated disconnect")

    def factory(config):
        instance = BrokenExchange(config) if not created else FakeExchange(config)
        created.append(instance)
        return instance

    monkeypatch.setattr("paper_engine.feeds.ccxt.okx", factory)
    monkeypatch.setattr("paper_engine.feeds.random.uniform", lambda a, b: 0)
    task = asyncio.create_task(CCXTFeed(engine).run())
    try:
        await wait_until(lambda: engine.feed[SYMBOL]["status"] == "disconnected")
        assert SYMBOL not in engine.books
        assert created[0].closed
        await wait_until(lambda: len(created) == 2 and created[1].calls >= 2)
        assert engine.feed[SYMBOL]["status"] == "connected"
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert all(exchange.closed for exchange in created)


async def test_invalid_market_fails_closed_without_retry_loop(engine, monkeypatch):
    created = []

    def factory(config):
        instance = FakeExchange(config)
        instance.invalid = True
        created.append(instance)
        return instance

    monkeypatch.setattr("paper_engine.feeds.ccxt.okx", factory)
    await CCXTFeed(engine).run()
    assert engine.feed[SYMBOL]["status"] == "error"
    assert SYMBOL not in engine.books
    assert len(created) == 1 and created[0].closed


@pytest.mark.parametrize(
    "symbol,step,minimum,maximum",
    [
        (SYMBOL, "0.001", "0.001", "50"),
        ("ETH/USDT:USDT", "0.01", "0.01", "1000"),
    ],
)
def test_apex_market_and_depth_use_base_quantities(symbol, step, minimum, maximum):
    raw = {
        **FakeExchange({}).market(symbol),
        "contractSize": float(minimum),
        "precision": {"amount": float(step)},
        "limits": {"amount": {"min": float(minimum), "max": float(maximum)}},
    }
    market = feeds.market_from_ccxt(raw, ccxt.TICK_SIZE, exchange_id="apex")
    assert market.quantity_step == Decimal(step)
    assert market.min_quantity == Decimal(minimum)
    assert market.max_quantity == Decimal(maximum)
    multiplier = feeds.quantity_multiplier(raw, "apex")
    assert multiplier == 1
    book = feeds.book_from_ccxt(symbol, {"bids": [[99, 3.143]], "asks": [[100, 4.334]]}, multiplier)
    book.validate()
    assert book.bids[0][1] == Decimal("3.143")
    assert book.asks[0][1] == Decimal("4.334")


@pytest.mark.parametrize("exchange_id", ["okx", "binance", "bybit"])
def test_contract_quantity_multiplier_is_preserved(exchange_id):
    assert feeds.quantity_multiplier({"contractSize": 0.01}, exchange_id) == Decimal("0.01")


@pytest.mark.parametrize("exchange_id", ["okx", "apex"])
@pytest.mark.parametrize("size", [0, -1, "NaN", "Infinity"])
def test_invalid_contract_size_is_rejected(exchange_id, size):
    with pytest.raises(ValueError, match="Invalid contract size"):
        feeds.quantity_multiplier({"contractSize": size}, exchange_id)


async def test_apex_feed_preserves_depth_and_blocks_stale_or_disconnected_orders(
    settings, monkeypatch
):
    settings.exchange = "apex"
    created = []

    class ApexExchange(FakeExchange):
        def market(self, symbol):
            return {
                **super().market(symbol),
                "contractSize": 0.001,
                "limits": {"amount": {"min": 0.001, "max": 50}},
            }

    def factory(config):
        instance = ApexExchange(config)
        created.append(instance)
        return instance

    monkeypatch.setattr("paper_engine.feeds.ccxt.apex", factory)
    store = Store(settings.db_path, settings.initial_balance, settings.exchange, settings.symbols)
    engine = Engine(settings, store)
    task = asyncio.create_task(CCXTFeed(engine).run())
    try:
        await wait_until(lambda: bool(created) and created[0].calls >= 2)
        assert engine.feed[SYMBOL]["status"] == "connected"
        assert engine.books[SYMBOL].bids[0][1] == Decimal(100)
        assert engine.markets[SYMBOL].quantity_step == Decimal("0.001")
        assert engine.markets[SYMBOL].max_quantity == Decimal(50)
        order = OpenOrder(symbol=SYMBOL, side="long")
        position = await engine.open(order, "apex-paper-entry")
        assert Decimal(position["quantity"]) > Decimal("0.1")
        engine.books[SYMBOL] = replace(
            engine.books[SYMBOL], received_mono=engine.books[SYMBOL].received_mono - 10
        )
        with pytest.raises(EngineError, match="too old"):
            await engine.open(order, "apex-stale-entry")
        with pytest.raises(EngineError, match="too old"):
            await engine.close(position["id"], "apex-stale-close")
        await engine.feed_status(SYMBOL, "disconnected")
        assert SYMBOL not in engine.books
        with pytest.raises(EngineError, match="No connected live order book"):
            await engine.open(order, "apex-disconnected-entry")
    finally:
        task.cancel()
        try:
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            store.close()
    assert created[0].closed
