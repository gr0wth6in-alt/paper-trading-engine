from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import SecretStr, ValidationError

from paper_engine.books import Market
from paper_engine.engine import Engine
from paper_engine.models import AgentOrder, EngineError, OpenOrder
from paper_engine.store import Store
from tests.conftest import AGENT_TOKEN, SYMBOL, make_book

D = Decimal
REASON = "Breakout above range high with rising volume; invalidated below 95.5."
START = datetime(2026, 10, 10, 10, 0, tzinfo=UTC)


class Clock:
    def __init__(self):
        self.now = START

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


def agent_order(**kwargs) -> AgentOrder:
    values = dict(
        symbol=SYMBOL, side="long", allocation_pct="0.02", leverage=10, stop_loss="95.5",
        reason=REASON,
    )  # fmt: skip
    values.update(kwargs)
    return AgentOrder(**values)


@pytest.fixture
def agent_settings(settings):
    settings.agent_token = SecretStr(AGENT_TOKEN)
    return settings


async def make_engine(settings, clock):
    store = Store(settings.db_path, settings.initial_balance, settings.exchange, settings.symbols)
    engine = Engine(settings, store)
    engine.clock = clock
    await engine.register_markets({SYMBOL: Market(SYMBOL, D("0.001"), D("0.001"), D("1"))})
    await engine.on_book(make_book())
    return engine


@pytest.fixture
async def agent(agent_settings):
    clock = Clock()
    engine = await make_engine(agent_settings, clock)
    await engine.set_agent_paused(False, "operator", "test resume")
    yield engine, clock
    engine.store.close()


async def expect_code(coro, code):
    with pytest.raises(EngineError) as exc:
        await coro
    assert exc.value.code == code, exc.value.message
    return exc.value


async def test_fresh_database_starts_paused_and_resume_allows(agent_settings):
    clock = Clock()
    engine = await make_engine(agent_settings, clock)
    try:
        assert (await engine.agent_state())["paused"] is True
        await expect_code(engine.agent_open(agent_order(), "k-paused"), "agent_paused")
        await engine.set_agent_paused(False, "operator", None)
        position = await engine.agent_open(agent_order(), "k-resumed")
        assert position["actor"] == "agent"
        assert position["notes"] == REASON and position["strategy"] == "hermes"
        events = engine.store.agent_events(10)
        assert [(e["action"], e["outcome"], e["code"]) for e in events[:3]] == [
            ("open", "accepted", None),
            ("operator_resume", "accepted", None),
            ("open", "rejected", "agent_paused"),
        ]
    finally:
        engine.store.close()


async def test_agent_disabled_without_token(engine):
    await expect_code(engine.agent_open(agent_order(), "k-disabled"), "agent_disabled")
    assert (await engine.agent_state()) == {"enabled": False}
    assert (await engine.snapshot())["agent"] == {"enabled": False}


async def test_cooldown_boundary_and_closes_are_never_rate_limited(agent):
    engine, clock = agent
    first = await engine.agent_open(agent_order(), "k1")
    clock.advance(seconds=899)
    error = await expect_code(engine.agent_open(agent_order(), "k2"), "agent_cooldown")
    assert "1 s" in error.message
    closed = await engine.agent_close(first["id"], "Thesis invalidated by news", "c1")
    assert closed["exit_notes"] == "Thesis invalidated by news"
    clock.advance(seconds=1)
    assert (await engine.agent_open(agent_order(), "k3"))["actor"] == "agent"


async def test_position_and_leverage_caps(agent):
    engine, clock = agent
    engine.settings.agent_max_open_positions = 2
    for n in range(2):
        await engine.agent_open(agent_order(), f"cap-{n}")
        clock.advance(seconds=900)
    await expect_code(engine.agent_open(agent_order(), "cap-3"), "agent_position_limit")
    engine.settings.agent_max_open_positions = 5
    await expect_code(engine.agent_open(agent_order(leverage=11), "lev"), "agent_leverage_limit")


def test_order_shape_requires_stop_and_reason():
    for bad in [
        {"stop_loss": None},
        {"reason": "too short"},
        {"reason": "x" * 2001},
        {"reason": "contains a control\x00 character....."},
        {"allocation_pct": "0.06"},
        {"leverage": "10"},
        {"strategy": "<script>"},
        {"extra": 1},
    ]:
        with pytest.raises(ValidationError):
            agent_order(**bad)
    with pytest.raises(ValidationError):
        AgentOrder(symbol=SYMBOL, side="long", allocation_pct="0.02", leverage=10, reason=REASON)


async def test_stop_on_wrong_side_and_beyond_liquidation(agent):
    engine, _ = agent
    await expect_code(engine.agent_open(agent_order(stop_loss="101"), "w1"), "invalid_stop_loss")
    engine.settings.agent_max_risk_per_trade_pct = D("0.05")
    await expect_code(
        engine.agent_open(agent_order(stop_loss="85"), "w2"), "agent_stop_beyond_liquidation"
    )
    assert engine.store.positions("open") == []


async def test_risk_cap_boundary(agent):
    engine, _ = agent
    # qty 20 @ 100, stop 95.5: 4.5*20 + entry fee 2 + exit fee 95.5*20*0.001 = 93.91 USDT
    engine.settings.agent_max_risk_per_trade_pct = D("0.009390")
    error = await expect_code(engine.agent_open(agent_order(), "r1"), "agent_risk_limit")
    assert "93.91" in error.message and "93.90" in error.message
    assert engine.store.positions("open") == []
    assert engine.store.account()["wallet"] == D("10000")
    engine.settings.agent_max_risk_per_trade_pct = D("0.009391")
    assert (await engine.agent_open(agent_order(), "r2"))["actor"] == "agent"


async def test_default_risk_cap_rejects_wide_stop(agent):
    engine, _ = agent
    # stop 95: 100 + 2 + 1.9 = 103.9 > 1% of 10,000
    await expect_code(engine.agent_open(agent_order(stop_loss="95"), "wide"), "agent_risk_limit")


async def test_breaker_trips_on_realized_loss_and_resets_next_utc_day(agent):
    engine, clock = agent
    engine.settings.agent_daily_loss_pct = D("0.005")  # 50 USDT of 10,000
    position = await engine.agent_open(agent_order(stop_loss="96"), "b1")
    await engine.on_book(make_book("97", "98"))
    closed = await engine.agent_close(position["id"], "Momentum failed, cutting", "b-close")
    assert D(closed["net_pnl"]) < -50
    await engine.on_book(make_book())
    clock.advance(seconds=900)
    error = await expect_code(engine.agent_open(agent_order(), "b2"), "agent_daily_loss_limit")
    assert "2026-10-11T00:00:00+00:00" in error.message
    state = await engine.agent_state()
    assert state["breaker_tripped"] is True and D(state["daily_loss"]) >= 50
    clock.now = datetime(2026, 10, 11, 0, 0, 1, tzinfo=UTC)
    state = await engine.agent_state()
    assert state["breaker_tripped"] is False and state["day"] == "2026-10-11"
    assert D(state["day_start_wallet"]) == engine.store.account()["wallet"]
    assert (await engine.agent_open(agent_order(), "b3"))["actor"] == "agent"


async def test_breaker_trips_on_unrealized_loss_and_stays_tripped(agent):
    engine, clock = agent
    engine.settings.agent_daily_loss_pct = D("0.005")
    await engine.agent_open(agent_order(stop_loss="96"), "u1")
    await engine.on_book(make_book("97", "98"))
    clock.advance(seconds=900)
    await expect_code(
        engine.agent_open(agent_order(stop_loss="96"), "u2"), "agent_daily_loss_limit"
    )
    await engine.on_book(make_book())  # price recovers; breaker remains for the day
    clock.advance(seconds=900)
    await expect_code(engine.agent_open(agent_order(), "u3"), "agent_daily_loss_limit")


async def test_stale_quote_on_open_agent_position_blocks_entries(agent):
    engine, clock = agent
    await engine.agent_open(agent_order(), "s1")
    engine.books[SYMBOL] = replace(
        engine.books[SYMBOL], received_mono=engine.books[SYMBOL].received_mono - 10
    )
    clock.advance(seconds=900)
    await expect_code(engine.agent_open(agent_order(), "s2"), "agent_valuation_unavailable")


async def test_agent_cannot_close_operator_position_but_operator_flow_unchanged(agent):
    engine, _ = agent
    manual = await engine.open(OpenOrder(symbol=SYMBOL, side="long"), "manual-1")
    assert manual["actor"] == "operator"
    await expect_code(
        engine.agent_close(manual["id"], "I want to close this one", "x1"), "not_agent_position"
    )
    assert engine.store.position(manual["id"]).status == "open"
    await engine.set_agent_paused(True, "operator", "stop")
    assert (await engine.close(manual["id"], "manual-close"))["status"] == "closed"


async def test_close_allowed_while_paused_and_reasons_reach_journal(agent):
    engine, _ = agent
    position = await engine.agent_open(agent_order(), "j1")
    await engine.set_agent_paused(True, "operator", "lunch")
    await engine.agent_close(position["id"], "Closing before CPI release", "j-close")
    journal = engine.store.journals(1)[0]
    assert journal["metrics"]["actor"] == "agent"
    assert journal["metrics"]["entry_rationale"] == REASON
    assert journal["metrics"]["exit_rationale"] == "Closing before CPI release"
    assert "Hermes agent" in journal["local_summary"]


async def test_agent_idempotency_replays_without_second_execution(agent):
    engine, clock = agent
    first = await engine.agent_open(agent_order(), "idem")
    clock.advance(seconds=10)  # replay is answered even inside the cooldown
    assert await engine.agent_open(agent_order(), "idem") == first
    assert len(engine.store.positions("open")) == 1
    await expect_code(engine.agent_open(agent_order(side="short"), "idem"), "idempotency_conflict")


async def test_close_all_reports_failures_per_position(agent):
    engine, clock = agent
    engine.settings.agent_max_open_positions = 3
    for n in range(2):
        await engine.agent_open(agent_order(), f"all-{n}")
        clock.advance(seconds=900)
    manual = await engine.open(OpenOrder(symbol=SYMBOL, side="long"), "manual-all")
    result = await engine.agent_close_all("operator")
    assert len(result["closed"]) == 2 and result["failed"] == []
    assert all(p["exit_notes"].startswith("Closed by operator") for p in result["closed"])
    assert engine.store.position(manual["id"]).status == "open"
    await engine.agent_open(agent_order(), "all-3")
    await engine.feed_status(SYMBOL, "disconnected")
    result = await engine.agent_close_all("operator")
    assert result["closed"] == [] and result["failed"][0]["code"] == "feed_unavailable"


async def test_restart_keeps_pause_and_cooldown(agent_settings):
    clock = Clock()
    engine = await make_engine(agent_settings, clock)
    await engine.set_agent_paused(False, "operator", None)
    await engine.agent_open(agent_order(), "restart-1")
    engine.store.close()
    clock.advance(seconds=60)
    engine = await make_engine(agent_settings, clock)
    try:
        state = await engine.agent_state()
        assert state["paused"] is False and state["cooldown_remaining_seconds"] == 840
        await expect_code(engine.agent_open(agent_order(), "restart-2"), "agent_cooldown")
        await engine.set_agent_paused(True, "operator", None)
    finally:
        engine.store.close()
    engine = await make_engine(agent_settings, clock)
    try:
        assert (await engine.agent_state())["paused"] is True
    finally:
        engine.store.close()


async def test_snapshot_contains_agent_block(agent):
    engine, _ = agent
    state = (await engine.snapshot())["agent"]
    assert state["enabled"] is True and state["paused"] is False
    assert state["max_risk_per_trade_pct"] == "0.01"
    assert state["daily_loss_limit"] == "300.00"
