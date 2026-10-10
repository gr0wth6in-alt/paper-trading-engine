import pytest

from paper_engine.store import Store


def test_second_engine_cannot_open_same_database(settings):
    first = Store(settings.db_path, settings.initial_balance, settings.exchange, settings.symbols)
    try:
        with pytest.raises(RuntimeError, match="one engine"):
            Store(settings.db_path, settings.initial_balance, settings.exchange, settings.symbols)
    finally:
        first.close()


@pytest.mark.parametrize("exchange_id", ["binance", "apex"])
def test_exchange_change_is_rejected(settings, exchange_id):
    store = Store(settings.db_path, settings.initial_balance, settings.exchange, settings.symbols)
    store.close()
    with pytest.raises(RuntimeError, match="another exchange"):
        Store(settings.db_path, settings.initial_balance, exchange_id, settings.symbols)


def test_invalid_schema_is_rejected_and_lock_released(settings):
    store = Store(settings.db_path, settings.initial_balance, settings.exchange, settings.symbols)
    store.connection.execute("PRAGMA user_version=99")
    store.close()
    for _ in range(2):
        with pytest.raises(RuntimeError, match="schema"):
            Store(settings.db_path, settings.initial_balance, settings.exchange, settings.symbols)
