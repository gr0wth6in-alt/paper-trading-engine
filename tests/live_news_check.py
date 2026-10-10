"""Opt-in, read-only check of the real RSS sources: python -m tests.live_news_check.

Fetches every configured feed once (public GETs only, no credentials) while measuring
event-loop lag, then prints per-source status and a few tagged headlines.
"""

import asyncio
import json
import time

from paper_engine.config import Settings
from paper_engine.news import NewsService

SYMBOLS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT"]


async def main():
    settings = Settings(_env_file=None, api_token="public-smoke-" + "x" * 40, symbols=SYMBOLS)
    service = NewsService(settings)
    lags: list[float] = []
    done = asyncio.Event()

    async def ticker():
        while not done.is_set():
            started = time.perf_counter()
            await asyncio.sleep(0.01)
            lags.append(time.perf_counter() - started - 0.01)

    tick = asyncio.create_task(ticker())
    started = time.perf_counter()
    try:
        await service.poll_once()
    finally:
        done.set()
        await tick
        await service.close()
    result = service.query(limit=5)
    print(
        json.dumps(
            {
                "poll_seconds": round(time.perf_counter() - started, 2),
                "max_loop_lag_ms": round(max(lags, default=0) * 1000, 1),
                "total_items": result["total"],
                "sources": result["sources"],
                "latest": [
                    {k: item[k] for k in ("source", "title", "symbols", "url")}
                    for item in result["items"]
                ],
                "tagged": {s: service.query(symbol=s)["total"] for s in SYMBOLS},
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
