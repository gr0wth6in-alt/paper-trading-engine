import os
import time
from decimal import Decimal

import pytest

from paper_engine.books import Book, Market
from paper_engine.config import Settings
from paper_engine.engine import Engine
from paper_engine.store import Store

D = Decimal
SYMBOL = "BTC/USDT:USDT"
TOKEN = "test-only-" + "x" * 40
AGENT_TOKEN = "agent-test-only-" + "y" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}"}
AGENT_AUTH = {"Authorization": f"Bearer {AGENT_TOKEN}"}


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    """Shell variables such as PAPER_AGENT_TOKEN must never change test settings."""
    for name in list(os.environ):
        if name.startswith("PAPER_"):
            monkeypatch.delenv(name)


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        api_token=TOKEN,
        db_path=tmp_path / "test.db",
        frontend_dist=tmp_path / "frontend",
        symbols=[SYMBOL],
        feed_enabled=False,
        news_enabled=False,
        slippage_bps=D(0),
        taker_fee_rate=D("0.001"),
    )


def make_book(bid="99", ask="100", size="10000", age=0, symbol=SYMBOL, timestamp=True):
    now = time.time_ns() // 1_000_000
    return Book(
        symbol=symbol,
        bids=((D(bid), D(size)),),
        asks=((D(ask), D(size)),),
        received_mono=time.perf_counter() - age,
        received_at_ms=now - int(age * 1000),
        exchange_timestamp_ms=now - int(age * 1000) if timestamp else None,
    )


@pytest.fixture
async def engine(settings):
    store = Store(settings.db_path, settings.initial_balance, settings.exchange, settings.symbols)
    engine = Engine(settings, store)
    await engine.register_markets({SYMBOL: Market(SYMBOL, D("0.001"), D("0.001"), D("1"))})
    await engine.on_book(make_book())
    yield engine
    store.close()
