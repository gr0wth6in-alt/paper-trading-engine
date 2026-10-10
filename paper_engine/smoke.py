import argparse
import asyncio
import json
import sys

import ccxt.pro as ccxt

from paper_engine.feeds import book_from_ccxt, market_from_ccxt, quantity_multiplier


async def check(exchange_id: str, symbol: str) -> None:
    exchange = getattr(ccxt, exchange_id)(
        {
            "enableRateLimit": True,
            "options": {"defaultType": "swap", "defaultSubType": "linear"},
            "timeout": 15000,
        }
    )
    try:
        await asyncio.wait_for(exchange.load_markets(), timeout=25)
        raw_market = exchange.market(symbol)
        market = market_from_ccxt(raw_market, exchange.precisionMode, exchange_id)
        multiplier = quantity_multiplier(raw_market, exchange_id)
        for _ in range(3):
            raw = await asyncio.wait_for(exchange.watch_order_book(symbol), timeout=20)
            book = book_from_ccxt(symbol, raw, multiplier)
            book.validate()
            age = book.age_seconds()
            if age > 5:
                raise RuntimeError(
                    f"Order book is stale ({age:.2f}s); check your clock or connection"
                )
            print(
                json.dumps(
                    {
                        "exchange": exchange_id,
                        "symbol": symbol,
                        "bid": str(book.bids[0][0]),
                        "ask": str(book.asks[0][0]),
                        "bid_base_quantity": str(book.bids[0][1]),
                        "quantity_step": str(market.quantity_step),
                        "age_ms": round(age * 1000, 1),
                        "exchange_timestamp_ms": book.exchange_timestamp_ms,
                    }
                ),
                flush=True,
            )
    finally:
        await asyncio.wait_for(exchange.close(), timeout=5)


def main():
    parser = argparse.ArgumentParser(
        description="Read three public order-book updates; no orders or DB"
    )
    parser.add_argument("--exchange", choices=["okx", "binance", "bybit", "apex"], default="okx")
    parser.add_argument("--symbol", default="BTC/USDT:USDT")
    args = parser.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(check(args.exchange, args.symbol))


if __name__ == "__main__":
    main()
