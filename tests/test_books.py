import time
from dataclasses import replace
from decimal import Decimal

import ccxt
import pytest

from paper_engine.books import Market, fill_book, size_entry
from paper_engine.feeds import book_from_ccxt, market_from_ccxt
from paper_engine.models import EngineError
from tests.conftest import SYMBOL, make_book

D = Decimal


def test_vwap_and_adverse_slippage():
    book = replace(make_book(), asks=((D(100), D(1)), (D(102), D(2))))
    fill = fill_book(book, True, D(2), D(10))
    assert fill.price == D("101.101")
    assert fill.notional == D("202.202")
    sell = fill_book(book, False, D(2), D(10))
    assert sell.price == D("98.901")


def test_rounding_keeps_depth_fill_inside_notional_budget():
    book = replace(make_book(), asks=((D(100), D(1)), (D(110), D(100))))
    market = Market(SYMBOL, D("0.001"))
    fill = size_entry(book, market, True, D(2000), D(20))
    assert fill.notional <= 2000
    assert fill.quantity % market.quantity_step == 0
    assert fill_book(book, True, fill.quantity + market.quantity_step, D(20)).notional > 2000


@pytest.mark.parametrize(
    "market,budget,code",
    [
        (Market(SYMBOL, D(1)), D("0.01"), "quantity_too_small"),
        (Market(SYMBOL, D("0.001"), min_notional=D(500)), D(100), "below_market_minimum"),
        (Market(SYMBOL, D("0.001"), max_quantity=D(1)), D(200), "above_market_maximum"),
        (Market(SYMBOL, D("0.001"), max_notional=D(100)), D(200), "above_market_maximum"),
    ],
)
def test_market_limits(market, budget, code):
    with pytest.raises(EngineError) as exc:
        size_entry(make_book(), market, True, budget, D(0))
    assert exc.value.code == code


def test_depth_exhaustion_rejects_instead_of_partial_fill():
    with pytest.raises(EngineError) as exc:
        fill_book(make_book(size="1"), True, D(2), D(0))
    assert exc.value.code == "insufficient_liquidity"


@pytest.mark.parametrize(
    "bids,asks",
    [
        ((), ((D(100), D(1)),)),
        (((D(101), D(1)),), ((D(100), D(1)),)),
        (((D(99), D(-1)),), ((D(100), D(1)),)),
        (((D(99), D(1)),), ((D("NaN"), D(1)),)),
        (((D(98), D(1)), (D(99), D(1))), ((D(100), D(1)),)),
        (((D(99), D(1)),), ((D(101), D(1)), (D(100), D(1)))),
    ],
)
def test_invalid_books(bids, asks):
    with pytest.raises(ValueError):
        replace(make_book(), bids=bids, asks=asks).validate()


def test_exchange_timestamp_contributes_to_freshness():
    now = time.time_ns() // 1_000_000
    assert replace(make_book(), exchange_timestamp_ms=now - 10000).age_seconds() >= 10
    with pytest.raises(ValueError, match="future"):
        replace(make_book(), exchange_timestamp_ms=now + 5000).validate()


def test_contract_precision_and_depth_normalization():
    raw = {
        "symbol": SYMBOL,
        "swap": True,
        "linear": True,
        "settle": "USDT",
        "active": True,
        "contractSize": 0.01,
        "precision": {"amount": 0.01},
        "limits": {"amount": {"min": 0.01, "max": 1000}, "cost": {"min": 1}},
    }
    market = market_from_ccxt(raw, ccxt.TICK_SIZE)
    assert market.quantity_step == D("0.0001")
    assert market.min_quantity == D("0.0001")
    assert market.max_quantity == D(10)
    book = book_from_ccxt(SYMBOL, {"bids": [[99, 10]], "asks": [[100, 20]]}, D("0.01"))
    assert book.bids[0][1] == D("0.1")
    assert book.asks[0][1] == D("0.2")
    assert book.exchange_timestamp_ms is None


def test_inverse_and_spot_markets_rejected():
    for raw in [
        {"symbol": "BTC/USDT", "swap": False},
        {"symbol": "BTC/USD:BTC", "swap": True, "linear": False},
    ]:
        with pytest.raises(ValueError):
            market_from_ccxt(raw, ccxt.TICK_SIZE)
