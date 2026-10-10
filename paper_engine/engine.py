import asyncio
import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from paper_engine.books import Book, Market, consume_book, fill_book, size_entry
from paper_engine.config import Settings
from paper_engine.journals import journal_for
from paper_engine.models import AgentOrder, EngineError, OpenOrder, Position, utc_now
from paper_engine.store import Store

D = Decimal


def fingerprint(operation: str, payload: dict) -> str:
    data = json.dumps([operation, payload], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


class Engine:
    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store
        self.lock = asyncio.Lock()
        self.books: dict[str, Book] = {}
        self.liquidity: dict[str, Book] = {}
        self.markets: dict[str, Market] = {}
        self.symbols = list(
            dict.fromkeys([*settings.symbols, *(p.symbol for p in store.positions("open"))])
        )
        self.feed: dict[str, dict] = {
            symbol: {"status": "starting" if settings.feed_enabled else "disabled", "error": None}
            for symbol in self.symbols
        }
        self.blocked_exits: dict[str, str] = {}
        self.revision = 0
        # Injectable for tests of cooldown and the UTC-day loss breaker.
        self.clock: Callable[[], datetime] = utc_now

    def _fresh_book(self, symbol: str) -> Book:
        book = self.books.get(symbol)
        if book is None or self.feed[symbol]["status"] != "connected":
            raise EngineError(
                "feed_unavailable", "No connected live order book for this symbol", 503
            )
        if book.age_seconds() > self.settings.max_quote_age_seconds:
            raise EngineError("stale_quote", "The live order book is too old for execution", 503)
        return book

    def _execution_book(self, symbol: str, buy: bool) -> Book:
        self._fresh_book(symbol)
        book = self.liquidity[symbol]
        if not (book.asks if buy else book.bids):
            raise EngineError(
                "insufficient_liquidity", "This snapshot's executable depth is exhausted"
            )
        return book

    async def register_markets(self, markets: dict[str, Market]) -> None:
        async with self.lock:
            if not set(self.settings.symbols).issubset(markets):
                raise ValueError("Market metadata must cover every configured symbol")
            self.markets = markets

    async def feed_status(self, symbol: str, status: str, error: str | None = None) -> None:
        async with self.lock:
            self.feed[symbol] = {"status": status, "error": error}
            if status != "connected":
                self.books.pop(symbol, None)
                self.liquidity.pop(symbol, None)
            self.revision += 1

    async def on_book(self, book: Book) -> None:
        book.validate()
        async with self.lock:
            if book.symbol not in self.symbols:
                raise ValueError("Unsubscribed symbol")
            previous = self.books.get(book.symbol)
            if previous is not None:
                if book.received_mono < previous.received_mono or book is previous:
                    return
                if (
                    book.exchange_timestamp_ms is not None
                    and previous.exchange_timestamp_ms is not None
                    and book.exchange_timestamp_ms < previous.exchange_timestamp_ms
                ):
                    return
                if (
                    book.exchange_timestamp_ms == previous.exchange_timestamp_ms
                    and book.bids == previous.bids
                    and book.asks == previous.asks
                ):
                    return
            if book.age_seconds() > self.settings.max_quote_age_seconds:
                self.feed[book.symbol] = {"status": "stale", "error": "Received an old order book"}
                self.books.pop(book.symbol, None)
                self.liquidity.pop(book.symbol, None)
                self.revision += 1
                return
            self.books[book.symbol] = book
            self.liquidity[book.symbol] = book
            self.feed[book.symbol] = {"status": "connected", "error": None}
            for position in self.store.positions("open"):
                if position.symbol == book.symbol:
                    reason = self._exit_trigger(position, book)
                    if reason:
                        if reason != position.pending_exit_reason:
                            position.pending_exit_reason = reason
                            position.triggered_at = position.triggered_at or utc_now()
                            with self.store.transaction():
                                self.store.save_position(position)
                        try:
                            self._close(position, reason)
                        except EngineError as exc:
                            self.blocked_exits[position.id] = exc.code
            self.revision += 1

    def _exit_trigger(self, position: Position, book: Book) -> str | None:
        price = book.reference(position.side == "short")
        sign = 1 if position.side == "long" else -1
        gross = (price - position.entry_price) * position.quantity * sign
        maintenance = (
            price * position.quantity * (position.maintenance_margin_rate + position.fee_rate)
        )
        if position.margin + gross <= maintenance:
            return "liquidation"
        if position.pending_exit_reason:
            return position.pending_exit_reason
        if position.stop_loss is not None and (price - position.stop_loss) * sign <= 0:
            return "stop_loss"
        if position.take_profit is not None and (price - position.take_profit) * sign >= 0:
            return "take_profit"
        return None

    def _available(self) -> Decimal:
        reserved = sum((p.margin for p in self.store.positions("open")), D(0))
        return self.store.account()["wallet"] - reserved

    async def open(self, request: OpenOrder, key: str) -> dict:
        digest = fingerprint("open", request.model_dump(mode="json"))
        async with self.lock:
            replay = self.store.replay(key, digest)
            if replay is not None:
                return replay
            return self._open_locked(request, key, digest)

    def _open_locked(
        self,
        request: OpenOrder,
        key: str,
        digest: str,
        *,
        actor: str = "operator",
        pre_commit: Callable[[Position], None] | None = None,
    ) -> dict:
        """Shared entry path. Caller holds self.lock and has already checked replay."""
        if request.symbol not in self.settings.symbols:
            raise EngineError("unsupported_symbol", "Symbol is not configured", 422)
        if request.symbol not in self.markets:
            raise EngineError("market_not_ready", "Market metadata has not loaded", 503)
        if len(self.store.positions("open")) >= self.settings.max_open_positions:
            raise EngineError("position_limit", "Maximum open position count reached")
        allocation = request.allocation_pct or self.settings.default_allocation_pct
        leverage = request.leverage or self.settings.default_leverage
        if leverage > self.settings.max_leverage:
            raise EngineError("leverage_limit", "Leverage exceeds the configured maximum", 422)
        wallet = self.store.account()["wallet"]
        budget = wallet * allocation
        if budget <= 0:
            raise EngineError("insufficient_funds", "Virtual wallet is empty")
        buy = request.side == "long"
        book = self._execution_book(request.symbol, buy)
        fill = size_entry(
            book,
            self.markets[request.symbol],
            buy,
            budget * leverage,
            self.settings.slippage_bps,
        )
        margin = fill.notional / leverage
        fee = fill.notional * self.settings.taker_fee_rate
        if margin > budget:
            raise EngineError("allocation_exceeded", "Rounded fill exceeds allocation budget")
        if margin + fee > self._available():
            raise EngineError(
                "insufficient_funds", "Available balance cannot cover margin and entry fee"
            )
        sign = 1 if buy else -1
        mark = self.books[request.symbol].reference(not buy)
        if request.stop_loss is not None and (
            (fill.price - request.stop_loss) * sign <= 0 or (mark - request.stop_loss) * sign <= 0
        ):
            raise EngineError(
                "invalid_stop_loss", "Stop must be beyond both entry and exit-side quote", 422
            )
        if request.take_profit is not None and (
            (request.take_profit - fill.price) * sign <= 0
            or (request.take_profit - mark) * sign <= 0
        ):
            raise EngineError(
                "invalid_take_profit",
                "Target must be beyond both entry and exit-side quote",
                422,
            )
        position = Position(
            id=str(uuid4()),
            exchange=self.settings.exchange,
            symbol=request.symbol,
            side=request.side,
            leverage=leverage,
            allocation_pct=allocation,
            allocation_budget=budget,
            quantity=fill.quantity,
            entry_price=fill.price,
            entry_notional=fill.notional,
            margin=margin,
            entry_fee=fee,
            fee_rate=self.settings.taker_fee_rate,
            slippage_bps=self.settings.slippage_bps,
            maintenance_margin_rate=self.settings.maintenance_margin_rate,
            entry_reference_price=book.reference(buy),
            entry_quote_age_ms=D(str(book.age_seconds() * 1000)),
            entry_spread_bps=self.books[request.symbol].spread_bps,
            opened_at=self.clock(),
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            strategy=request.strategy,
            notes=request.notes,
            actor=actor,
        )
        if self._exit_trigger(position, self.books[request.symbol]) == "liquidation":
            raise EngineError(
                "immediate_liquidation", "Spread and slippage consume the isolated margin"
            )
        if pre_commit is not None:
            pre_commit(position)  # may raise; nothing has been written yet
        self._fresh_book(request.symbol)
        response = position.model_dump(mode="json")
        with self.store.transaction():
            self.store.set_wallet(wallet - fee)
            self.store.save_position(position)
            self.store.remember(key, digest, response)
        self.liquidity[request.symbol] = consume_book(book, buy, fill.quantity)
        self.revision += 1
        return response

    def _close(
        self, position: Position, reason: str, key: str | None = None, digest: str | None = None
    ) -> dict:
        buy = position.side == "short"
        book = self._execution_book(position.symbol, buy)
        fill = fill_book(book, buy, position.quantity, position.slippage_bps)
        sign = 1 if position.side == "long" else -1
        gross = (fill.price - position.entry_price) * position.quantity * sign
        exit_fee = fill.notional * position.fee_rate
        settlement = gross - exit_fee
        # Synthetic insurance caps a gap loss at isolated collateral; it is not exchange-exact.
        adjustment = max(D(0), -position.margin - settlement)
        position.status = "closed"
        position.exit_price = fill.price
        position.exit_fee = exit_fee
        position.exit_reference_price = book.reference(buy)
        position.exit_quote_age_ms = D(str(book.age_seconds() * 1000))
        position.closed_at = self.clock()
        position.exit_reason = reason
        position.gross_pnl = gross
        position.net_pnl = settlement + adjustment - position.entry_fee
        position.isolated_loss_adjustment = adjustment
        position.pending_exit_reason = None
        response = position.model_dump(mode="json")
        self._fresh_book(position.symbol)
        with self.store.transaction():
            self.store.set_wallet(self.store.account()["wallet"] + settlement + adjustment)
            self.store.save_position(position)
            self.store.save_journal(journal_for(position))
            if key is not None:
                self.store.remember(key, digest, response)
        self.liquidity[position.symbol] = consume_book(book, buy, fill.quantity)
        self.blocked_exits.pop(position.id, None)
        self.revision += 1
        return response

    async def close(self, position_id: str, key: str) -> dict:
        digest = fingerprint("close", {"id": position_id})
        async with self.lock:
            replay = self.store.replay(key, digest)
            if replay is not None:
                return replay
            position = self.store.position(position_id)
            if position.status == "closed":
                raise EngineError("position_closed", "Position is already closed")
            book = self._fresh_book(position.symbol)
            return self._close(
                position, self._exit_trigger(position, book) or "manual", key, digest
            )

    # --- Autonomous agent (Hermes) ------------------------------------------------------
    # Every guardrail lives here, under self.lock, so no client (MCP, curl, a confused LLM)
    # can bypass it. Operator trading is unaffected.

    def _agent_event(self, action: str, outcome: str, code: str | None, detail: str) -> None:
        with self.store.transaction():
            self.store.add_agent_event(
                self.clock().isoformat(),
                "operator" if action.startswith("operator_") else "agent",
                action,
                outcome,
                code,
                detail,
            )

    def _agent_state(self) -> dict:
        """Compute agent status. Caller holds self.lock. Persists the UTC-day baseline."""
        s = self.settings
        if not s.agent_enabled:
            return {"enabled": False}
        now = self.clock()
        day = now.date().isoformat()
        day_start = datetime.combine(now.date(), datetime.min.time(), now.tzinfo)
        control = self.store.agent_control()
        if control["day"] != day:
            # First evaluation of a new UTC day: record the baseline once and reset breaker.
            baseline = self.store.account()["wallet"]
            with self.store.transaction():
                self.store.update_agent_control(day=day, day_start_wallet=baseline)
            control.update(day=day, day_start_wallet=baseline)
        open_positions = self.store.agent_positions("open")
        realized = self.store.agent_realized_pnl_since(day_start.isoformat())
        unrealized = D(0)
        valuation_complete = True
        for position in open_positions:
            view = self._position_view(position)
            if view["quote_stale"]:
                valuation_complete = False
                continue
            unrealized += D(view["estimated_settlement_pnl"]) - position.entry_fee
        daily_pnl = realized + unrealized
        loss = max(D(0), -daily_pnl)
        limit = control["day_start_wallet"] * s.agent_daily_loss_pct
        tripped = control["breaker_day"] == day
        if not tripped and loss >= limit:
            tripped = True
            with self.store.transaction():
                self.store.update_agent_control(breaker_day=day)
                self.store.add_agent_event(
                    now.isoformat(), "system", "breaker", "tripped", "agent_daily_loss_limit",
                    f"Daily loss {loss:.4f} reached limit {limit:.4f} USDT",
                )  # fmt: skip
        last_open = self.store.last_agent_open_at()
        cooldown = 0.0
        if last_open is not None:
            elapsed = (now - datetime.fromisoformat(last_open)).total_seconds()
            cooldown = max(0.0, s.agent_min_open_interval_seconds - elapsed)
        next_day = day_start + timedelta(days=1)
        return {
            "enabled": True,
            "paused": control["paused"],
            "pause_reason": control["reason"],
            "changed_at": control["changed_at"],
            "changed_by": control["changed_by"],
            "day": day,
            "day_start_wallet": str(control["day_start_wallet"]),
            "daily_pnl": str(daily_pnl) if valuation_complete else None,
            "daily_loss": str(loss) if valuation_complete else None,
            "daily_loss_limit": str(limit),
            "breaker_tripped": tripped,
            "breaker_resets_at": next_day.isoformat() if tripped else None,
            "valuation_complete": valuation_complete,
            "cooldown_remaining_seconds": round(cooldown, 1),
            "min_open_interval_seconds": s.agent_min_open_interval_seconds,
            "open_positions": len(open_positions),
            "max_open_positions": s.agent_max_open_positions,
            "max_leverage": s.agent_max_leverage,
            "max_risk_per_trade_pct": str(s.agent_max_risk_per_trade_pct),
            "max_risk_per_trade_usdt": str(
                self.store.account()["wallet"] * s.agent_max_risk_per_trade_pct
            ),
            "daily_loss_pct": str(s.agent_daily_loss_pct),
        }

    def _require_agent_enabled(self) -> None:
        if not self.settings.agent_enabled:
            raise EngineError("agent_disabled", "The agent API is not configured", 503)

    def _check_agent_entry(self, order: AgentOrder) -> None:
        state = self._agent_state()
        if state["paused"]:
            raise EngineError("agent_paused", "Hermes is paused by the operator")
        if state["breaker_tripped"]:
            raise EngineError(
                "agent_daily_loss_limit",
                f"Daily loss limit reached ({state['daily_loss_limit']} USDT). "
                f"New entries resume at {state['breaker_resets_at']}",
            )
        if not state["valuation_complete"]:
            raise EngineError(
                "agent_valuation_unavailable",
                "An open Hermes position has no fresh quote; daily loss cannot be verified",
                503,
            )
        if state["cooldown_remaining_seconds"] > 0:
            raise EngineError(
                "agent_cooldown",
                f"Next entry allowed in {int(state['cooldown_remaining_seconds'] + 0.999)} s "
                f"(minimum {state['min_open_interval_seconds']} s between entries)",
            )
        if state["open_positions"] >= state["max_open_positions"]:
            raise EngineError(
                "agent_position_limit",
                f"Hermes may hold at most {state['max_open_positions']} open positions",
            )
        if order.leverage > self.settings.agent_max_leverage:
            raise EngineError(
                "agent_leverage_limit",
                f"Hermes leverage is capped at {self.settings.agent_max_leverage}x",
                422,
            )

    def _agent_risk_check(self, order: AgentOrder) -> Callable[[Position], None]:
        def check(position: Position) -> None:
            sign = 1 if position.side == "long" else -1
            stop = order.stop_loss
            # The stop must trigger before isolated liquidation, or the risk estimate is wrong.
            gross_at_stop = (stop - position.entry_price) * position.quantity * sign
            maintenance = (
                stop * position.quantity * (position.maintenance_margin_rate + position.fee_rate)
            )
            if position.margin + gross_at_stop <= maintenance:
                raise EngineError(
                    "agent_stop_beyond_liquidation",
                    "Stop-loss lies beyond the liquidation price; tighten the stop",
                    422,
                )
            exit_notional = stop * position.quantity
            exit_costs = exit_notional * (position.fee_rate + position.slippage_bps / 10000)
            risk = abs(position.entry_price - stop) * position.quantity
            risk += position.entry_fee + exit_costs
            wallet = self.store.account()["wallet"]
            limit = wallet * self.settings.agent_max_risk_per_trade_pct
            if risk > limit:
                raise EngineError(
                    "agent_risk_limit",
                    f"Estimated loss at stop is {risk:.2f} USDT; maximum is {limit:.2f} USDT "
                    f"({self.settings.agent_max_risk_per_trade_pct * 100}% of wallet). "
                    "Lower allocation or leverage, or tighten the stop",
                    422,
                )

        return check

    async def agent_open(self, order: AgentOrder, key: str) -> dict:
        self._require_agent_enabled()
        digest = fingerprint("agent_open", order.model_dump(mode="json"))
        async with self.lock:
            replay = self.store.replay(key, digest)
            if replay is not None:
                return replay
            summary = f"{order.side} {order.symbol} {order.allocation_pct}x{order.leverage}"
            try:
                self._check_agent_entry(order)
                request = OpenOrder(
                    symbol=order.symbol,
                    side=order.side,
                    allocation_pct=order.allocation_pct,
                    leverage=order.leverage,
                    stop_loss=order.stop_loss,
                    take_profit=order.take_profit,
                    strategy=f"hermes:{order.strategy}" if order.strategy else "hermes",
                    notes=order.reason,
                )
                response = self._open_locked(
                    request,
                    key,
                    digest,
                    actor="agent",
                    pre_commit=self._agent_risk_check(order),
                )
            except EngineError as exc:
                self._agent_event("open", "rejected", exc.code, f"{summary}: {exc.message}")
                raise
            self._agent_event("open", "accepted", None, f"{summary} id={response['id']}")
            return response

    async def agent_close(self, position_id: str, reason: str, key: str) -> dict:
        self._require_agent_enabled()
        digest = fingerprint("agent_close", {"id": position_id, "reason": reason})
        async with self.lock:
            replay = self.store.replay(key, digest)
            if replay is not None:
                return replay
            try:
                position = self.store.position(position_id)
                if position.actor != "agent":
                    raise EngineError(
                        "not_agent_position", "Hermes may only close its own positions", 403
                    )
                if position.status == "closed":
                    raise EngineError("position_closed", "Position is already closed")
                book = self._fresh_book(position.symbol)
                position.exit_notes = reason
                trigger = self._exit_trigger(position, book) or "manual"
                response = self._close(position, trigger, key, digest)
            except EngineError as exc:
                self._agent_event("close", "rejected", exc.code, f"{position_id}: {exc.message}")
                raise
            self._agent_event(
                "close", "accepted", None, f"{position_id} net_pnl={response['net_pnl']}"
            )
            return response

    async def agent_state(self) -> dict:
        async with self.lock:
            return self._agent_state()

    async def set_agent_paused(self, paused: bool, by: str, reason: str | None) -> dict:
        self._require_agent_enabled()
        async with self.lock:
            text = reason or ("Paused from the terminal" if paused else "Resumed from the terminal")
            with self.store.transaction():
                self.store.update_agent_control(
                    paused=paused, reason=text, changed_at=self.clock().isoformat(), changed_by=by
                )
            self._agent_event(
                "operator_pause" if paused else "operator_resume", "accepted", None, text
            )
            return self._agent_state()

    async def agent_close_all(self, by: str) -> dict:
        self._require_agent_enabled()
        async with self.lock:
            closed, failed = [], []
            for position in self.store.agent_positions("open"):
                try:
                    book = self._fresh_book(position.symbol)
                    position.exit_notes = f"Closed by {by}: close all Hermes positions"
                    trigger = self._exit_trigger(position, book) or "manual"
                    closed.append(self._close(position, trigger))
                except EngineError as exc:
                    self.blocked_exits[position.id] = exc.code
                    failed.append(
                        {"id": position.id, "symbol": position.symbol, "code": exc.code,
                         "message": exc.message}
                    )  # fmt: skip
            self._agent_event(
                "operator_close_all",
                "partial" if failed else "accepted",
                failed[0]["code"] if failed else None,
                f"closed={len(closed)} failed={len(failed)}",
            )
            return {"closed": closed, "failed": failed}

    async def agent_events(self, limit: int, offset: int) -> list[dict]:
        async with self.lock:
            return self.store.agent_events(limit, offset)

    def _position_view(self, position: Position) -> dict:
        result = position.model_dump(mode="json")
        result.update(
            mark_price=None,
            unrealized_pnl=None,
            estimated_settlement_pnl=None,
            estimated_exit_fee=None,
            quote_stale=True,
            quote_age_ms=None,
            blocked_exit=self.blocked_exits.get(position.id),
        )
        book = self.books.get(position.symbol)
        if book is None:
            return result
        result["quote_age_ms"] = round(book.age_seconds() * 1000, 1)
        try:
            self._fresh_book(position.symbol)
        except EngineError:
            return result
        price = book.reference(position.side == "short")
        gross = (
            (price - position.entry_price)
            * position.quantity
            * (1 if position.side == "long" else -1)
        )
        fee = price * position.quantity * position.fee_rate
        result.update(
            mark_price=str(price),
            unrealized_pnl=str(gross),
            estimated_exit_fee=str(fee),
            estimated_settlement_pnl=str(max(-position.margin, gross - fee)),
            quote_stale=False,
        )
        return result

    async def snapshot(self) -> dict:
        async with self.lock:
            account = self.store.account()
            positions = self.store.positions("open")
            views = [self._position_view(p) for p in positions]
            reserved = sum((p.margin for p in positions), D(0))
            complete = all(not p["quote_stale"] for p in views)
            unrealized = sum((D(p["unrealized_pnl"]) for p in views), D(0)) if complete else None
            settlement = (
                sum((D(p["estimated_settlement_pnl"]) for p in views), D(0)) if complete else None
            )
            markets = {}
            for symbol, status in self.feed.items():
                book = self.books.get(symbol)
                age = book.age_seconds() if book else None
                stale = age is None or age > self.settings.max_quote_age_seconds
                markets[symbol] = {
                    **status,
                    "close_only": symbol not in self.settings.symbols,
                    "price_tick": str(self.markets[symbol].price_tick)
                    if symbol in self.markets
                    else None,
                    "status": "stale"
                    if status["status"] == "connected" and stale
                    else status["status"],
                    "stale": stale,
                    "age_ms": round(age * 1000, 1) if age is not None else None,
                    "bid": str(book.bids[0][0]) if book else None,
                    "ask": str(book.asks[0][0]) if book else None,
                    "exchange_timestamp_ms": book.exchange_timestamp_ms if book else None,
                    "received_at_ms": book.received_at_ms if book else None,
                    "freshness_basis": "exchange_and_receipt"
                    if book and book.exchange_timestamp_ms
                    else "receipt_only",
                }
            return {
                "type": "snapshot",
                "mode": "paper",
                "margin_mode": "isolated",
                "exchange": self.settings.exchange,
                "revision": self.revision,
                "timestamp": utc_now().isoformat(),
                "account": {
                    "currency": "USDT",
                    "initial_balance": str(account["initial_balance"]),
                    "wallet_balance": str(account["wallet"]),
                    "reserved_margin": str(reserved),
                    "available_balance": str(account["wallet"] - reserved),
                    "unrealized_pnl": str(unrealized) if unrealized is not None else None,
                    "equity": str(account["wallet"] + unrealized)
                    if unrealized is not None
                    else None,
                    "estimated_settlement_equity": str(account["wallet"] + settlement)
                    if settlement is not None
                    else None,
                    "valuation_complete": complete,
                },
                "positions": views,
                "markets": markets,
                "journaling": {"provider": "disabled", "recent": self.store.journals(10)},
                "agent": self._agent_state(),
            }

    async def history(self, limit: int, offset: int) -> list[dict]:
        async with self.lock:
            return [
                p.model_dump(mode="json") for p in self.store.positions("closed", limit, offset)
            ]

    async def journals(self, limit: int, offset: int) -> list[dict]:
        async with self.lock:
            return self.store.journals(limit, offset)
