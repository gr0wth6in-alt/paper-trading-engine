import json
import sqlite3
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from filelock import FileLock, Timeout

from paper_engine.models import EngineError, Journal, Position

SCHEMA_VERSION = 2
MAX_AGENT_EVENTS = 5000
AGENT_CONTROL_FIELDS = frozenset(
    {"paused", "reason", "changed_at", "changed_by", "day", "day_start_wallet", "breaker_day"}
)
AGENT_FILTER = "json_extract(payload, '$.actor') = 'agent'"


class Store:
    def __init__(
        self,
        path: Path,
        initial_balance: Decimal,
        exchange: str,
        symbols: list[str],
        *,
        retain_open_symbols: bool = False,
    ):
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(path) + ".lock")
        try:
            self.lock.acquire(timeout=0)
        except Timeout as exc:
            raise RuntimeError("Database is in use. Run exactly one engine worker.") from exc
        self.connection = None
        try:
            self.connection = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
            self.connection.execute("PRAGMA foreign_keys=ON")
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, SCHEMA_VERSION):
                raise RuntimeError(f"Unsupported database schema version: {version}")
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS account (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    wallet TEXT NOT NULL,
                    initial_balance TEXT NOT NULL,
                    exchange TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS positions (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL CHECK(status IN ('open', 'closed')),
                    opened_at TEXT NOT NULL,
                    closed_at TEXT,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS positions_status ON positions(status);
                CREATE TABLE IF NOT EXISTS journal_jobs (
                    trade_id TEXT PRIMARY KEY REFERENCES positions(id),
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS idempotency (
                    key TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    response TEXT NOT NULL
                );
                -- v2: autonomous agent (Hermes) control state and audit trail.
                CREATE TABLE IF NOT EXISTS agent_control (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    paused INTEGER NOT NULL DEFAULT 1 CHECK(paused IN (0, 1)),
                    reason TEXT,
                    changed_at TEXT,
                    changed_by TEXT,
                    day TEXT,
                    day_start_wallet TEXT,
                    breaker_day TEXT
                );
                CREATE TABLE IF NOT EXISTS agent_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    code TEXT,
                    detail TEXT
                );
                CREATE INDEX IF NOT EXISTS agent_events_at ON agent_events(at);
                PRAGMA user_version=2;
            """)
            with self.transaction():
                self.connection.execute(
                    "INSERT OR IGNORE INTO account VALUES (1, ?, ?, ?)",
                    (str(initial_balance), str(initial_balance), exchange),
                )
                # New and migrated databases start with the agent paused.
                self.connection.execute(
                    "INSERT OR IGNORE INTO agent_control (id, paused, reason, changed_by) "
                    "VALUES (1, 1, 'Initial state: resume from the terminal', 'system')"
                )
            account = self.account()
            if account["exchange"] != exchange:
                raise RuntimeError("This database belongs to another exchange; use a new DB path")
            if not retain_open_symbols and any(
                p.symbol not in symbols for p in self.positions("open")
            ):
                raise RuntimeError(
                    "Configured symbols omit an open position; restore its subscription"
                )
        except BaseException:
            self.close()
            raise

    @contextmanager
    def transaction(self):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def account(self) -> dict:
        row = dict(self.connection.execute("SELECT * FROM account WHERE id = 1").fetchone())
        row["wallet"] = Decimal(row["wallet"])
        row["initial_balance"] = Decimal(row["initial_balance"])
        return row

    def set_wallet(self, wallet: Decimal) -> None:
        if not wallet.is_finite() or wallet < 0:
            raise RuntimeError("Wallet invariant violated")
        self.connection.execute("UPDATE account SET wallet = ? WHERE id = 1", (str(wallet),))

    def position(self, position_id: str) -> Position:
        row = self.connection.execute(
            "SELECT payload FROM positions WHERE id = ?", (position_id,)
        ).fetchone()
        if row is None:
            raise EngineError("position_not_found", "Position does not exist", 404)
        return Position.model_validate_json(row[0])

    def positions(self, status: str, limit: int = 1000, offset: int = 0) -> list[Position]:
        rows = self.connection.execute(
            "SELECT payload FROM positions WHERE status = ? "
            "ORDER BY opened_at DESC, id LIMIT ? OFFSET ?",
            (status, limit, offset),
        ).fetchall()
        return [Position.model_validate_json(row[0]) for row in rows]

    def save_position(self, position: Position) -> None:
        self.connection.execute(
            "INSERT INTO positions VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET status=excluded.status, "
            "closed_at=excluded.closed_at, payload=excluded.payload",
            (
                position.id,
                position.status,
                position.opened_at.isoformat(),
                position.closed_at.isoformat() if position.closed_at else None,
                position.model_dump_json(),
            ),
        )

    def save_journal(self, journal: Journal) -> None:
        self.connection.execute(
            "INSERT INTO journal_jobs VALUES (?, ?)",
            (journal.trade_id, journal.model_dump_json()),
        )

    def journals(self, limit: int = 100, offset: int = 0) -> list[dict]:
        rows = self.connection.execute(
            "SELECT payload FROM journal_jobs ORDER BY rowid DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def replay(self, key: str, fingerprint: str) -> dict | None:
        row = self.connection.execute(
            "SELECT fingerprint, response FROM idempotency WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        if row["fingerprint"] != fingerprint:
            raise EngineError(
                "idempotency_conflict", "This key was already used for a different request"
            )
        return json.loads(row["response"])

    def remember(self, key: str, fingerprint: str, response: dict) -> None:
        self.connection.execute(
            "INSERT INTO idempotency VALUES (?, ?, ?)",
            (key, fingerprint, json.dumps(response)),
        )

    # --- Agent (v2) -------------------------------------------------------------------

    def agent_control(self) -> dict:
        row = self.connection.execute("SELECT * FROM agent_control WHERE id = 1").fetchone()
        result = dict(row)
        result["paused"] = bool(result["paused"])
        if result["day_start_wallet"] is not None:
            result["day_start_wallet"] = Decimal(result["day_start_wallet"])
        return result

    def update_agent_control(self, **fields) -> None:
        unknown = set(fields) - AGENT_CONTROL_FIELDS
        if unknown or not fields:
            raise ValueError(f"Unknown agent control fields: {sorted(unknown)}")
        values = {
            k: (int(v) if k == "paused" else (str(v) if v is not None else None))
            for k, v in fields.items()
        }
        assignments = ", ".join(f"{name} = ?" for name in values)  # names are allow-listed
        self.connection.execute(
            f"UPDATE agent_control SET {assignments} WHERE id = 1", tuple(values.values())
        )

    def add_agent_event(
        self,
        at: str,
        actor: str,
        action: str,
        outcome: str,
        code: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.connection.execute(
            "INSERT INTO agent_events (at, actor, action, outcome, code, detail) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (at, actor, action, outcome, code, (detail or "")[:2000] or None),
        )
        self.connection.execute(
            "DELETE FROM agent_events WHERE id <= (SELECT MAX(id) FROM agent_events) - ?",
            (MAX_AGENT_EVENTS,),
        )

    def agent_events(self, limit: int = 50, offset: int = 0) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM agent_events ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
        return [dict(row) for row in rows]

    def agent_positions(self, status: str, limit: int = 1000, offset: int = 0) -> list[Position]:
        rows = self.connection.execute(
            f"SELECT payload FROM positions WHERE status = ? AND {AGENT_FILTER} "
            "ORDER BY opened_at DESC, id LIMIT ? OFFSET ?",
            (status, limit, offset),
        ).fetchall()
        return [Position.model_validate_json(row[0]) for row in rows]

    def last_agent_open_at(self) -> str | None:
        row = self.connection.execute(
            f"SELECT MAX(opened_at) FROM positions WHERE {AGENT_FILTER}"
        ).fetchone()
        return row[0]

    def agent_realized_pnl_since(self, since: str) -> Decimal:
        """Sum of net PnL of agent positions closed at or after `since` (ISO UTC)."""
        rows = self.connection.execute(
            "SELECT json_extract(payload, '$.net_pnl') FROM positions "
            f"WHERE status = 'closed' AND closed_at >= ? AND {AGENT_FILTER}",
            (since,),
        ).fetchall()
        return sum((Decimal(str(row[0])) for row in rows if row[0] is not None), Decimal(0))

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        self.lock.release()
