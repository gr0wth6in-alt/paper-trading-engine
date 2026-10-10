import asyncio
import math
import time

import ccxt.async_support as ccxt

from paper_engine.config import Settings
from paper_engine.models import EngineError, utc_now

TIMEFRAMES = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


def normalize_candles(rows: list, timeframe: str) -> list[dict]:
    result = {}
    now = time.time()
    for row in rows:
        if len(row) < 6 or any(v is None for v in row[:6]):
            raise ValueError("Incomplete candle")
        timestamp, opening, high, low, close, volume = [float(v) for v in row[:6]]
        if not all(math.isfinite(v) for v in (timestamp, opening, high, low, close, volume)):
            raise ValueError("Invalid candle number")
        stamp = int(timestamp / 1000)
        if stamp < 0 or stamp > now + 2 or min(opening, high, low, close) <= 0 or volume < 0:
            raise ValueError("Invalid candle bounds")
        if high < max(opening, close, low) or low > min(opening, close, high):
            raise ValueError("Inconsistent OHLC prices")
        result[stamp] = {
            "time": stamp,
            "open": opening,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "closed": stamp + TIMEFRAMES[timeframe] <= now,
        }
    return [result[t] for t in sorted(result)]


class CandleService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.exchange = None
        self.lock = asyncio.Lock()
        self.cache: dict[tuple[str, str], tuple[float, dict]] = {}
        self.retry_after = 0.0

    async def get(self, symbol: str, timeframe: str) -> dict:
        if symbol not in self.settings.symbols or timeframe not in TIMEFRAMES:
            raise EngineError("unsupported_chart", "Unsupported chart symbol or timeframe", 422)
        if not self.settings.feed_enabled:
            raise EngineError("feed_disabled", "Public market subscriptions are disabled", 503)
        key = (symbol, timeframe)
        async with self.lock:
            cached = self.cache.get(key)
            if cached and time.monotonic() - cached[0] < 15:
                return cached[1]
            if time.monotonic() < self.retry_after:
                raise EngineError(
                    "candles_unavailable", "Chart feed unavailable. Retry shortly.", 503
                )
            try:
                if self.exchange is None:
                    self.exchange = getattr(ccxt, self.settings.exchange)(
                        {
                            "enableRateLimit": True,
                            **({"rateLimit": 200} if self.settings.exchange == "apex" else {}),
                            "timeout": 10000,
                            "options": {"defaultType": "swap", "defaultSubType": "linear"},
                        }
                    )
                async with asyncio.timeout(12):
                    rows = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=200)
                candles = normalize_candles(rows[-200:], timeframe)
                payload = {
                    "symbol": symbol,
                    "exchange": self.settings.exchange,
                    "timeframe": timeframe,
                    "source": "exchange_ohlcv",
                    "fetched_at": utc_now().isoformat(),
                    "candles": candles,
                }
                self.cache[key] = (time.monotonic(), payload)
                return payload
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.retry_after = time.monotonic() + 15
                raise EngineError(
                    "candles_unavailable",
                    "Public candle request failed. Check exchange connectivity; "
                    "execution feed is separate.",
                    503,
                ) from exc

    async def close(self):
        if self.exchange is not None:
            await asyncio.wait_for(self.exchange.close(), timeout=5)
