import asyncio
import sqlite3
from dataclasses import replace
from decimal import Decimal

import pytest
from pydantic import ValidationError

from paper_engine.books import Market
from paper_engine.engine import Engine
from paper_engine.models import EngineError, OpenOrder
from paper_engine.store import Store
from tests.conftest import SYMBOL, make_book

D = Decimal


def order(**kwargs):
    return OpenOrder(symbol=SYMBOL, side=kwargs.pop("side", "long"), **kwargs)


async def test_default_sizing_margin_and_wallet(engine):
    position = await engine.open(order(), "open-default")
    assert D(position["allocation_budget"]) == 200
    assert D(position["quantity"]) == 20
    assert D(position["entry_notional"]) == 2000
    assert D(position["margin"]) == 200
    assert position["leverage"] == 10
    snapshot = await engine.snapshot()
    assert D(snapshot["account"]["wallet_balance"]) == 9998
    assert D(snapshot["account"]["available_balance"]) == 9798
    assert D(snapshot["positions"][0]["unrealized_pnl"]) == -20


@pytest.mark.parametrize(
    "side,bid,ask,expected_gross",
    [
        ("long", "110", "111", "200"),
        ("short", "89", "90", None),
    ],
)
async def test_close_pnl_fees_and_journal(engine, side, bid, ask, expected_gross):
    p = await engine.open(order(side=side), "entry-long-short")
    await engine.on_book(make_book(bid, ask))
    closed = await engine.close(p["id"], "close-long-short")
    quantity = D(p["quantity"])
    exit_price = D(bid if side == "long" else ask)
    gross = (exit_price - D(p["entry_price"])) * quantity * (1 if side == "long" else -1)
    if expected_gross:
        assert gross == D(expected_gross)
    assert D(closed["gross_pnl"]) == gross
    net = gross - D(p["entry_fee"]) - exit_price * quantity * D("0.001")
    assert D(closed["net_pnl"]) == net
    snapshot = await engine.snapshot()
    assert D(snapshot["account"]["wallet_balance"]) == D(10000) + net
    assert snapshot["account"]["reserved_margin"] == "0"
    journal = (await engine.journals(100, 0))[0]
    assert journal["trade_id"] == p["id"]
    assert journal["status"] == "pending" and journal["provider"] == "disabled"
    assert journal["ai_output"] is None
    assert journal["metrics"]["trade"]["net_pnl"] == closed["net_pnl"]


@pytest.mark.parametrize(
    "side,sl,tp,bid,ask,reason",
    [
        ("long", "95", "110", "94", "95", "stop_loss"),
        ("long", "95", "110", "112", "113", "take_profit"),
        ("short", "105", "90", "106", "107", "stop_loss"),
        ("short", "105", "90", "88", "89", "take_profit"),
    ],
)
async def test_automatic_exits_use_executable_price(engine, side, sl, tp, bid, ask, reason):
    p = await engine.open(order(side=side, stop_loss=sl, take_profit=tp), "entry-trigger")
    await engine.on_book(make_book(bid, ask))
    closed = engine.store.position(p["id"])
    assert closed.exit_reason == reason
    assert closed.exit_price == D(bid if side == "long" else ask)
    await engine.on_book(make_book(bid, ask))
    assert len(await engine.journals(100, 0)) == 1


@pytest.mark.parametrize("side,bid,ask", [("long", "50", "51"), ("short", "149", "150")])
async def test_gap_liquidation_caps_loss_to_isolated_collateral(engine, side, bid, ask):
    p = await engine.open(order(side=side), "entry-liquidation")
    await engine.on_book(make_book(bid, ask))
    closed = engine.store.position(p["id"])
    assert closed.exit_reason == "liquidation"
    assert closed.isolated_loss_adjustment > 0
    assert closed.net_pnl == -D(p["margin"]) - D(p["entry_fee"])
    assert engine.store.account()["wallet"] == D(10000) + closed.net_pnl
    assert engine._available() >= 0


async def test_liquidation_does_not_consume_other_position_margin(engine):
    first = await engine.open(order(), "isolated-one")
    second = await engine.open(order(side="short"), "isolated-two")
    await engine.on_book(make_book("50", "51"))
    assert engine.store.position(first["id"]).status == "closed"
    assert engine.store.position(second["id"]).status == "open"
    assert D((await engine.snapshot())["account"]["reserved_margin"]) == D(second["margin"])


async def test_stale_book_blocks_orders_close_and_valuation(engine):
    p = await engine.open(order(), "entry-before-stale")
    engine.books[SYMBOL] = replace(
        engine.books[SYMBOL], received_mono=engine.books[SYMBOL].received_mono - 10
    )
    for action in [engine.open(order(), "stale-entry"), engine.close(p["id"], "stale-close")]:
        with pytest.raises(EngineError, match="too old"):
            await action
    snapshot = await engine.snapshot()
    assert snapshot["account"]["equity"] is None
    assert snapshot["account"]["valuation_complete"] is False
    assert snapshot["markets"][SYMBOL]["status"] == "stale"


async def test_disconnected_feed_blocks_execution(engine):
    await engine.feed_status(SYMBOL, "disconnected")
    with pytest.raises(EngineError) as exc:
        await engine.open(order(), "disconnected-order")
    assert exc.value.code == "feed_unavailable"


async def test_idempotency_concurrent_open_and_close(engine):
    responses = await asyncio.gather(*(engine.open(order(), "same-request") for _ in range(15)))
    assert len({p["id"] for p in responses}) == 1
    assert len(engine.store.positions("open")) == 1
    with pytest.raises(EngineError) as exc:
        await engine.open(order(side="short"), "same-request")
    assert exc.value.code == "idempotency_conflict"
    closes = await asyncio.gather(
        *(engine.close(responses[0]["id"], "same-close") for _ in range(15))
    )
    assert all(p == closes[0] for p in closes)
    assert len(await engine.journals(100, 0)) == 1
    with pytest.raises(EngineError) as exc:
        await engine.close(responses[0]["id"], "different-close")
    assert exc.value.code == "position_closed"


async def test_concurrent_requests_cannot_overallocate(engine):
    results = await asyncio.gather(
        *(engine.open(order(allocation_pct="0.05"), f"allocation-{i:03}") for i in range(30)),
        return_exceptions=True,
    )
    assert sum(isinstance(r, dict) for r in results) == 19
    assert all(isinstance(r, dict) or r.code == "insufficient_funds" for r in results)
    assert engine._available() >= 0


async def test_close_and_journal_are_atomic(engine, monkeypatch):
    p = await engine.open(order(), "atomic-entry")
    wallet = engine.store.account()["wallet"]

    def fail(journal):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(engine.store, "save_journal", fail)
    with pytest.raises(sqlite3.OperationalError):
        await engine.close(p["id"], "atomic-close")
    assert engine.store.position(p["id"]).status == "open"
    assert engine.store.account()["wallet"] == wallet
    assert engine.store.connection.execute("SELECT count(*) FROM idempotency").fetchone()[0] == 1


async def test_trigger_stays_latched_after_insufficient_depth(engine):
    p = await engine.open(order(stop_loss="95"), "latched-entry")
    await engine.on_book(make_book("94", "95", size="1"))
    pending = engine.store.position(p["id"])
    assert pending.status == "open"
    assert pending.pending_exit_reason == "stop_loss"
    assert engine.blocked_exits[p["id"]] == "insufficient_liquidity"
    await engine.on_book(make_book("98", "99"))
    assert engine.store.position(p["id"]).exit_reason == "stop_loss"


async def test_same_snapshot_liquidity_is_not_reused(engine):
    await engine.on_book(make_book(size="30"))
    await engine.open(order(), "liquidity-one")
    with pytest.raises(EngineError) as exc:
        await engine.open(order(), "liquidity-two")
    assert exc.value.code == "insufficient_liquidity"


async def test_restart_restores_positions_wallet_jobs_and_idempotency(settings):
    store = Store(settings.db_path, settings.initial_balance, settings.exchange, settings.symbols)
    engine = Engine(settings, store)
    await engine.register_markets({SYMBOL: Market(SYMBOL, D("0.001"))})
    await engine.on_book(make_book())
    opened = await engine.open(order(stop_loss="95"), "restart-entry")
    await engine.on_book(make_book("94", "95", size="1"))
    wallet = store.account()["wallet"]
    store.close()
    store = Store(settings.db_path, D(999999), settings.exchange, settings.symbols)
    try:
        engine = Engine(settings, store)
        assert store.account()["wallet"] == wallet
        assert await engine.open(order(stop_loss="95"), "restart-entry") == opened
        with pytest.raises(EngineError):
            await engine.close(opened["id"], "restart-no-feed")
        assert (await engine.snapshot())["account"]["equity"] is None
        await engine.on_book(make_book("98", "99"))
        assert store.position(opened["id"]).exit_reason == "stop_loss"
        assert len(store.journals()) == 1
    finally:
        store.close()
    store = Store(settings.db_path, D(10000), settings.exchange, settings.symbols)
    try:
        assert len(store.journals()) == 1
        assert len(store.positions("closed")) == 1
    finally:
        store.close()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"allocation_pct": "0.051"},
        {"allocation_pct": "0.019"},
        {"allocation_pct": "NaN"},
        {"leverage": 0},
        {"leverage": 21},
        {"leverage": True},
        {"stop_loss": "Infinity"},
        {"margin_mode": "cross"},
        {"quantity": 123},
    ],
)
def test_input_constraints(kwargs):
    with pytest.raises(ValidationError):
        order(**kwargs)


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"stop_loss": "101"}, "invalid_stop_loss"),
        ({"stop_loss": "99.5"}, "invalid_stop_loss"),
        ({"take_profit": "99"}, "invalid_take_profit"),
        ({"side": "short", "stop_loss": "98"}, "invalid_stop_loss"),
        ({"side": "short", "take_profit": "101"}, "invalid_take_profit"),
    ],
)
async def test_directional_brackets(engine, kwargs, code):
    with pytest.raises(EngineError) as exc:
        await engine.open(order(**kwargs), "invalid-bracket")
    assert exc.value.code == code
    assert engine.store.positions("open") == []


async def test_changed_fee_configuration_does_not_reprice_open_positions(engine):
    p = await engine.open(order(), "immutable-entry")
    engine.settings.taker_fee_rate = D("0.009")
    closed = await engine.close(p["id"], "immutable-close")
    assert D(closed["exit_fee"]) == D(closed["exit_price"]) * D(p["quantity"]) * D("0.001")


async def test_exchange_out_of_order_book_cannot_trigger_a_stop(engine):
    p = await engine.open(order(stop_loss="95"), "out-of-order-entry")
    previous = engine.books[SYMBOL]
    old = replace(
        make_book("94", "95"), exchange_timestamp_ms=previous.exchange_timestamp_ms - 1000
    )
    await engine.on_book(old)
    assert engine.books[SYMBOL] is previous
    assert engine.store.position(p["id"]).status == "open"


async def test_old_exchange_timestamp_on_new_receipt_is_not_fresh(engine):
    p = await engine.open(order(stop_loss="95"), "old-exchange-entry")
    await engine.feed_status(SYMBOL, "disconnected")
    book = make_book("94", "95")
    book = replace(book, exchange_timestamp_ms=book.received_at_ms - 10000)
    await engine.on_book(book)
    assert engine.feed[SYMBOL]["status"] == "stale"
    assert engine.store.position(p["id"]).status == "open"
    with pytest.raises(EngineError):
        await engine.close(p["id"], "old-exchange-close")


async def test_equal_resolution_receipt_times_do_not_drop_changed_books(engine):
    p = await engine.open(order(stop_loss="95"), "equal-time-entry")
    previous = engine.books[SYMBOL]
    book = replace(
        make_book("94", "95"),
        received_mono=previous.received_mono,
        exchange_timestamp_ms=previous.exchange_timestamp_ms,
    )
    await engine.on_book(book)
    assert engine.store.position(p["id"]).exit_reason == "stop_loss"


async def test_api_close_racing_auto_exit_settles_only_once(engine):
    p = await engine.open(order(stop_loss="95"), "racing-entry")
    results = await asyncio.gather(
        engine.on_book(make_book("94", "95")),
        engine.close(p["id"], "racing-close"),
        return_exceptions=True,
    )
    assert all(
        r is None
        or isinstance(r, dict)
        or (isinstance(r, EngineError) and r.code == "position_closed")
        for r in results
    )
    closed = engine.store.position(p["id"])
    assert closed.status == "closed"
    assert len(await engine.journals(100, 0)) == 1
    assert engine.store.account()["wallet"] == D(10000) + closed.net_pnl


async def test_restarting_without_open_position_symbol_is_rejected(settings):
    store = Store(settings.db_path, settings.initial_balance, settings.exchange, settings.symbols)
    engine = Engine(settings, store)
    try:
        await engine.register_markets({SYMBOL: Market(SYMBOL, D("0.001"))})
        await engine.on_book(make_book())
        await engine.open(order(), "preserve-symbol-entry")
    finally:
        store.close()
    with pytest.raises(RuntimeError, match="omit an open position"):
        Store(settings.db_path, settings.initial_balance, settings.exchange, ["ETH/USDT:USDT"])


async def test_open_transaction_rolls_back_if_idempotency_cannot_be_saved(engine, monkeypatch):
    before = engine.store.account()["wallet"]
    depth = engine.liquidity[SYMBOL]

    def fail(*args):
        raise sqlite3.OperationalError("simulated full disk")

    monkeypatch.setattr(engine.store, "remember", fail)
    with pytest.raises(sqlite3.OperationalError):
        await engine.open(order(), "atomic-open-error")
    assert engine.store.account()["wallet"] == before
    assert engine.store.positions("open") == []
    assert engine.liquidity[SYMBOL] is depth
