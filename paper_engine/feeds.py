import asyncio
import logging
import random
import time
from decimal import Decimal, InvalidOperation

import ccxt.pro as ccxt
from ccxt import DECIMAL_PLACES, TICK_SIZE

from paper_engine.books import Book, Market
from paper_engine.engine import Engine

logger = logging.getLogger(__name__)

BASE_QUANTITY_EXCHANGES = frozenset({"apex"})


def quantity_multiplier(raw: dict, exchange_id: str) -> Decimal:
    contract_size = Decimal(str(raw["contractSize"]))
    if not contract_size.is_finite() or contract_size <= 0:
        raise ValueError("Invalid contract size")
    # ApeX sizes are base quantities; CCXT 4.5.85 uses minOrderSize as contractSize.
    return Decimal(1) if exchange_id in BASE_QUANTITY_EXCHANGES else contract_size


def market_from_ccxt(raw: dict, precision_mode: int, exchange_id: str = "") -> Market:
    if not (raw.get("swap") and raw.get("linear") and raw.get("settle") == "USDT"):
        raise ValueError(f"{raw['symbol']} is not a USDT-settled linear perpetual")
    if raw.get("active") is False:
        raise ValueError(f"{raw['symbol']} is inactive")
    contract_size = quantity_multiplier(raw, exchange_id)
    precision = raw["precision"]["amount"]
    if precision_mode == TICK_SIZE:
        contract_step = Decimal(str(precision))
    elif precision_mode == DECIMAL_PLACES:
        contract_step = Decimal(10) ** -int(precision)
    else:
        raise ValueError("Significant-digit quantity precision is not supported")
    if not contract_step.is_finite() or contract_step <= 0:
        raise ValueError("Invalid quantity precision")
    limits = raw.get("limits") or {}
    amount, cost = limits.get("amount") or {}, limits.get("cost") or {}
    price_precision = raw["precision"].get("price")
    price_tick = (
        Decimal("0.01")
        if price_precision is None
        else Decimal(str(price_precision))
        if precision_mode == TICK_SIZE
        else Decimal(10) ** -int(price_precision)
    )
    if not price_tick.is_finite() or price_tick <= 0:
        raise ValueError("Invalid price precision")
    return Market(
        symbol=raw["symbol"],
        quantity_step=contract_step * contract_size,
        min_quantity=Decimal(str(amount.get("min") or 0)) * contract_size,
        min_notional=Decimal(str(cost.get("min") or 0)),
        max_quantity=(
            Decimal(str(amount["max"])) * contract_size if amount.get("max") is not None else None
        ),
        max_notional=Decimal(str(cost["max"])) if cost.get("max") is not None else None,
        price_tick=price_tick,
    )


def book_from_ccxt(symbol: str, raw: dict, contract_size: Decimal) -> Book:
    def levels(side: str) -> tuple:
        # The multiplier is 1 when the adapter already supplies base quantities.
        return tuple(
            (Decimal(str(level[0])), Decimal(str(level[1])) * contract_size)
            for level in raw[side]
            if Decimal(str(level[1])) != 0
        )

    return Book(
        symbol=symbol,
        bids=levels("bids"),
        asks=levels("asks"),
        received_mono=time.perf_counter(),
        received_at_ms=time.time_ns() // 1_000_000,
        exchange_timestamp_ms=int(raw["timestamp"]) if raw.get("timestamp") is not None else None,
    )


async def select_top_symbols(exchange, count: int, max_age: float) -> list[str]:
    tickers = await asyncio.wait_for(exchange.fetch_tickers(), timeout=30)
    ranked = []
    for symbol, raw in exchange.markets.items():
        if raw.get("active") is not True:
            continue
        try:
            market_from_ccxt(raw, exchange.precisionMode, "apex")
            volume = Decimal(str(tickers.get(symbol, {}).get("quoteVolume")))
            if volume.is_finite() and volume > 0:
                ranked.append((volume, symbol))
        except (ValueError, KeyError, TypeError, InvalidOperation):
            continue
    selected = []
    for _, symbol in sorted(ranked, key=lambda item: (-item[0], item[1])):
        await asyncio.sleep(0.2)
        try:
            raw = await asyncio.wait_for(exchange.fetch_order_book(symbol), timeout=15)
            book = book_from_ccxt(symbol, raw, Decimal(1))
            book.validate()
            if book.age_seconds() > max_age:
                continue
        except (ccxt.BaseError, TimeoutError, ValueError, KeyError, TypeError, InvalidOperation):
            continue
        selected.append(symbol)
        if len(selected) == count:
            return selected
    raise ValueError(
        f"Need {count} tradable ApeX markets; only {len(selected)} passed depth checks"
    )


async def discover_symbols(settings) -> list[str]:
    exchange = ccxt.apex({"enableRateLimit": True, "rateLimit": 200, "timeout": 30000})
    try:
        await asyncio.wait_for(exchange.load_markets(), timeout=30)
        return await select_top_symbols(
            exchange, settings.top_symbols_count, settings.max_quote_age_seconds
        )
    finally:
        await asyncio.wait_for(exchange.close(), timeout=10)


class CCXTFeed:
    def __init__(self, engine: Engine):
        self.engine = engine

    async def _watch(self, exchange, symbol: str) -> None:
        contract_size = quantity_multiplier(exchange.market(symbol), self.engine.settings.exchange)
        while True:
            try:
                raw = await asyncio.wait_for(
                    exchange.watch_order_book(symbol),
                    timeout=self.engine.settings.feed_idle_timeout_seconds,
                )
                await self.engine.on_book(book_from_ccxt(symbol, raw, contract_size))
            except Exception as exc:
                if self.engine.settings.exchange != "apex":
                    raise
                await self.engine.feed_status(symbol, "disconnected", type(exc).__name__)
                await asyncio.sleep(2)

    async def refresh_book(self, exchange, symbol: str) -> None:
        raw = await asyncio.wait_for(exchange.fetch_order_book(symbol), timeout=15)
        multiplier = quantity_multiplier(exchange.market(symbol), self.engine.settings.exchange)
        book = book_from_ccxt(symbol, raw, multiplier)
        book.validate()
        if book.age_seconds() <= self.engine.settings.max_quote_age_seconds:
            await self.engine.on_book(book)

    async def _refresh_quiet_books(self, exchange, symbols: list[str]) -> None:
        while True:
            for symbol in symbols:
                book = self.engine.books.get(symbol)
                if book is not None and book.age_seconds() < 3:
                    continue
                try:
                    await self.refresh_book(exchange, symbol)
                except Exception:
                    logger.debug("Depth refresh unavailable for %s", symbol)
                await asyncio.sleep(0.25)
            await asyncio.sleep(1)

    async def run(self) -> None:
        settings = self.engine.settings
        backoff = 1.0
        while True:
            exchange = getattr(ccxt, settings.exchange)(
                {
                    "enableRateLimit": True,
                    **({"rateLimit": 200} if settings.exchange == "apex" else {}),
                    "options": {"defaultType": "swap", "defaultSubType": "linear"},
                    "timeout": 15000,
                }
            )
            connected_at = time.monotonic()
            try:
                for symbol in self.engine.symbols:
                    await self.engine.feed_status(symbol, "connecting")
                await asyncio.wait_for(exchange.load_markets(), timeout=30)
                if not exchange.has.get("watchOrderBook"):
                    raise ValueError("Exchange does not support public order-book subscriptions")
                markets = {}
                for symbol in self.engine.symbols:
                    try:
                        markets[symbol] = market_from_ccxt(
                            exchange.market(symbol), exchange.precisionMode, settings.exchange
                        )
                    except (ValueError, ccxt.BadSymbol) as exc:
                        await self.engine.feed_status(symbol, "error", str(exc))
                        if symbol in settings.symbols:
                            logger.error("Invalid market configuration: %s", exc)
                            return
                await self.engine.register_markets(markets)
                async with asyncio.TaskGroup() as group:
                    for symbol in markets:
                        group.create_task(self._watch(exchange, symbol))
                    if settings.exchange == "apex":
                        group.create_task(self._refresh_quiet_books(exchange, list(markets)))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Public market feed interrupted: %s", type(exc).__name__)
                for symbol in self.engine.symbols:
                    await self.engine.feed_status(
                        symbol,
                        "disconnected",
                        f"Public feed interrupted ({type(exc).__name__})",
                    )
            finally:
                try:
                    await asyncio.wait_for(exchange.close(), timeout=10)
                except Exception:
                    logger.warning("Exchange connection cleanup failed")
            if time.monotonic() - connected_at > 60:
                backoff = 1.0
            await asyncio.sleep(backoff + random.uniform(0, 0.5))
            backoff = min(backoff * 2, 30)
