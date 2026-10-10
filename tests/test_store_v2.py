import json
import sqlite3
from decimal import Decimal

import pytest

from paper_engine import store as store_module
from paper_engine.models import Position, utc_now
from paper_engine.store import Store
from tests.conftest import SYMBOL

D = Decimal
V1_SCHEMA = """
CREATE TABLE account (id INTEGER PRIMARY KEY CHECK(id = 1), wallet TEXT NOT NULL,
    initial_balance TEXT NOT NULL, exchange TEXT NOT NULL);
CREATE TABLE positions (id TEXT PRIMARY KEY, status TEXT NOT NULL
    CHECK(status IN ('open', 'closed')), opened_at TEXT NOT NULL, closed_at TEXT,
    payload TEXT NOT NULL);
CREATE TABLE journal_jobs (trade_id TEXT PRIMARY KEY REFERENCES positions(id),
    payload TEXT NOT NULL);
CREATE TABLE idempotency (key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
    response TEXT NOT NULL);
PRAGMA user_version=1;
"""


def make_position(**overrides) -> Position:
    values = dict(
        id="p1", exchange="okx", symbol=SYMBOL, side="long", leverage=10,
        allocation_pct=D("0.02"), allocation_budget=D("200"), quantity=D("0.03"),
        entry_price=D("65000"), entry_notional=D("1950"), margin=D("195"),
        entry_fee=D("1.17"), fee_rate=D("0.0006"), slippage_bps=D("2"),
        maintenance_margin_rate=D("0.005"), entry_reference_price=D("64990"),
        entry_quote_age_ms=D("10"), entry_spread_bps=D("1"), opened_at=utc_now(),
        notes="legacy note",
    )  # fmt: skip
    values.update(overrides)
    return Position(**values)


def open_store(path, symbols=(SYMBOL,)):
    return Store(path, D("10000"), "okx", list(symbols))


def test_v1_database_migrates_without_data_loss(tmp_path):
    path = tmp_path / "v1.db"
    legacy = json.loads(make_position().model_dump_json())
    legacy.pop("actor"), legacy.pop("exit_notes")  # exactly what v1 code wrote
    connection = sqlite3.connect(path)
    connection.executescript(V1_SCHEMA)
    connection.execute("INSERT INTO account VALUES (1, '9876.5', '10000', 'okx')")
    connection.execute(
        "INSERT INTO positions VALUES ('p1', 'open', ?, NULL, ?)",
        (legacy["opened_at"], json.dumps(legacy)),
    )
    connection.execute("INSERT INTO idempotency VALUES ('k1', 'fp', '{\"ok\": 1}')")
    connection.commit()
    connection.close()

    store = open_store(path)
    try:
        assert store.connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert store.account()["wallet"] == D("9876.5")
        position = store.position("p1")
        assert position.actor == "operator" and position.exit_notes is None
        assert position.notes == "legacy note"
        assert store.replay("k1", "fp") == {"ok": 1}
        control = store.agent_control()
        assert control["paused"] is True and control["changed_by"] == "system"
        assert store.agent_positions("open") == []
    finally:
        store.close()


def test_unknown_schema_version_rejected(tmp_path):
    path = tmp_path / "v3.db"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version=3")
    connection.close()
    with pytest.raises(RuntimeError, match="schema version: 3"):
        open_store(path)
    open_store(tmp_path / "fresh.db").close()  # the failed open released its lock


def test_agent_queries_and_control_persist_across_restart(tmp_path):
    path = tmp_path / "agent.db"
    store = open_store(path)
    try:
        early = make_position(id="a1", actor="agent")
        late = make_position(id="a2", actor="agent")
        closed = make_position(
            id="a3", actor="agent", status="closed", closed_at=utc_now(), net_pnl=D("-12.5")
        )
        old = make_position(
            id="a4", actor="agent", status="closed",
            closed_at=utc_now().replace(year=2020), net_pnl=D("-99"),
        )  # fmt: skip
        manual = make_position(id="m1", status="closed", closed_at=utc_now(), net_pnl=D("-50"))
        with store.transaction():
            for position in (early, late, closed, old, manual):
                store.save_position(position)
            store.update_agent_control(paused=False, changed_by="operator", reason="go")
        assert {p.id for p in store.agent_positions("open")} == {"a1", "a2"}
        assert store.last_agent_open_at() == max(
            p.opened_at.isoformat() for p in (early, late, closed, old)
        )
        today = utc_now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        assert store.agent_realized_pnl_since(today) == D("-12.5")
    finally:
        store.close()
    store = open_store(path)
    try:
        control = store.agent_control()
        assert control["paused"] is False and control["reason"] == "go"
        with pytest.raises(ValueError):
            store.update_agent_control(unknown=1)
    finally:
        store.close()


def test_agent_events_are_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "MAX_AGENT_EVENTS", 5)
    store = open_store(tmp_path / "events.db")
    try:
        with store.transaction():
            for n in range(12):
                store.add_agent_event(f"t{n:02d}", "agent", "open", "rejected", "c", "x" * 3000)
        events = store.agent_events(limit=50)
        assert [e["at"] for e in events] == [f"t{n:02d}" for n in range(11, 6, -1)]
        assert len(events[0]["detail"]) == 2000
    finally:
        store.close()
