import time
from dataclasses import dataclass, replace
from decimal import ROUND_DOWN, Decimal

from paper_engine.models import EngineError

ZERO = Decimal("0")


@dataclass(frozen=True)
class Market:
    symbol: str
    quantity_step: Decimal
    min_quantity: Decimal = ZERO
    min_notional: Decimal = ZERO
    max_quantity: Decimal | None = None
    max_notional: Decimal | None = None
    price_tick: Decimal = Decimal("0.01")

    def round_quantity(self, quantity: Decimal) -> Decimal:
        return (quantity / self.quantity_step).to_integral_value(
            rounding=ROUND_DOWN
        ) * self.quantity_step


@dataclass(frozen=True)
class Book:
    symbol: str
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]
    received_mono: float
    received_at_ms: int
    exchange_timestamp_ms: int | None = None

    def validate(self) -> None:
        if not self.bids or not self.asks:
            raise ValueError("Order book must have bids and asks")
        for levels in (self.bids, self.asks):
            if any(not v.is_finite() or v <= 0 for level in levels for v in level):
                raise ValueError("Order book prices and sizes must be finite and positive")
        if any(a[0] <= b[0] for a, b in zip(self.bids, self.bids[1:], strict=False)):
            raise ValueError("Bids must be strictly descending")
        if any(a[0] >= b[0] for a, b in zip(self.asks, self.asks[1:], strict=False)):
            raise ValueError("Asks must be strictly ascending")
        if self.bids[0][0] >= self.asks[0][0]:
            raise ValueError("Crossed or locked book")
        if self.exchange_timestamp_ms is not None:
            if self.exchange_timestamp_ms > self.received_at_ms + 2000:
                raise ValueError("Exchange timestamp is in the future; check the system clock")

    def age_seconds(self) -> float:
        transport_age = 0.0
        if self.exchange_timestamp_ms is not None:
            transport_age = max(0.0, (self.received_at_ms - self.exchange_timestamp_ms) / 1000)
        return max(0.0, time.perf_counter() - self.received_mono) + transport_age

    @property
    def spread_bps(self) -> Decimal:
        bid, ask = self.bids[0][0], self.asks[0][0]
        return (ask - bid) / ((ask + bid) / 2) * 10000

    def reference(self, buy: bool) -> Decimal:
        return self.asks[0][0] if buy else self.bids[0][0]


@dataclass(frozen=True)
class Fill:
    quantity: Decimal
    price: Decimal
    notional: Decimal


def fill_book(book: Book, buy: bool, quantity: Decimal, slippage_bps: Decimal) -> Fill:
    if quantity <= 0:
        raise EngineError("quantity_too_small", "Rounded position quantity is zero", 422)
    remaining, total = quantity, ZERO
    levels = book.asks if buy else book.bids
    for price, available in levels:
        amount = min(available, remaining)
        total += price * amount
        remaining -= amount
        if remaining == 0:
            break
    if remaining > 0:
        raise EngineError(
            "insufficient_liquidity", "Visible order-book depth cannot fill the position"
        )
    factor = 1 + (slippage_bps / 10000) * (1 if buy else -1)
    total *= factor
    return Fill(quantity, total / quantity, total)


def size_entry(book: Book, market: Market, buy: bool, budget: Decimal, slippage: Decimal) -> Fill:
    factor = 1 + (slippage / 10000) * (1 if buy else -1)
    quantity = market.round_quantity(budget / (book.reference(buy) * factor))
    fill = fill_book(book, buy, quantity, slippage)
    if fill.notional > budget:
        low, high = 0, int(quantity / market.quantity_step)
        while low < high:
            mid = (low + high + 1) // 2
            candidate = fill_book(book, buy, mid * market.quantity_step, slippage)
            if candidate.notional <= budget:
                low = mid
            else:
                high = mid - 1
        fill = fill_book(book, buy, low * market.quantity_step, slippage)
    if fill.quantity < market.min_quantity or fill.notional < market.min_notional:
        raise EngineError(
            "below_market_minimum", "Position is below market size or notional minimum", 422
        )
    if market.max_quantity is not None and fill.quantity > market.max_quantity:
        raise EngineError("above_market_maximum", "Position exceeds market quantity maximum", 422)
    if market.max_notional is not None and fill.notional > market.max_notional:
        raise EngineError("above_market_maximum", "Position exceeds market notional maximum", 422)
    return fill


def consume_book(book: Book, buy: bool, quantity: Decimal) -> Book:
    remaining = quantity
    levels = []
    for price, available in book.asks if buy else book.bids:
        taken = min(available, remaining)
        remaining -= taken
        if available > taken:
            levels.append((price, available - taken))
    return replace(book, **{"asks" if buy else "bids": tuple(levels)})
