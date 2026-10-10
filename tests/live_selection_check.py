"""Opt-in, read-only ApeX check: python -m tests.live_selection_check."""

import asyncio
import json
import tempfile
import time
from contextlib import suppress
from pathlib import Path

from paper_engine.config import Settings
from paper_engine.engine import Engine
from paper_engine.feeds import CCXTFeed, discover_symbols
from paper_engine.store import Store


async def main():
    settings = Settings(_env_file=None, api_token="public-smoke-" + "x" * 40, exchange="apex")
    started = time.monotonic()
    async with asyncio.timeout(180):
        symbols = await discover_symbols(settings)
    print(
        json.dumps(
            {"selected": symbols, "selection_seconds": round(time.monotonic() - started, 2)}
        ),
        flush=True,
    )
    settings.symbols = symbols
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory) / "smoke.db", settings.initial_balance, "apex", symbols)
        engine = Engine(settings, store)
        task = asyncio.create_task(CCXTFeed(engine).run())
        try:
            for _ in range(6):
                await asyncio.sleep(5)
                snapshot = await engine.snapshot()
                fresh = [s for s, m in snapshot["markets"].items() if not m["stale"]]
                print(
                    json.dumps(
                        {
                            "elapsed": round(time.monotonic() - started, 2),
                            "fresh": len(fresh),
                            "selected_count": len(symbols),
                            "positions": len(snapshot["positions"]),
                        }
                    ),
                    flush=True,
                )
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            store.close()


if __name__ == "__main__":
    asyncio.run(main())
