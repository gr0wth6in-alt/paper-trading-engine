import json

from paper_engine import smoke
from tests.conftest import SYMBOL
from tests.test_feeds import FakeExchange


async def test_apex_smoke_reports_base_quantities(monkeypatch, capsys):
    class ApexExchange(FakeExchange):
        def market(self, symbol):
            return {**super().market(symbol), "contractSize": 0.001}

        async def watch_order_book(self, symbol):
            self.calls = 0
            return await super().watch_order_book(symbol)

    exchange = ApexExchange({})
    monkeypatch.setattr("paper_engine.smoke.ccxt.apex", lambda config: exchange)
    await smoke.check("apex", SYMBOL)
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(rows) == 3
    assert all(row["quantity_step"] == "0.001" for row in rows)
    assert all(row["bid_base_quantity"] == "100" for row in rows)
    assert exchange.closed


def test_smoke_cli_accepts_apex(monkeypatch):
    calls = []

    async def check(exchange_id, symbol):
        calls.append((exchange_id, symbol))

    monkeypatch.setattr("sys.argv", ["paper_engine.smoke", "--exchange", "apex"])
    monkeypatch.setattr(smoke, "check", check)
    smoke.main()
    assert calls == [("apex", SYMBOL)]
