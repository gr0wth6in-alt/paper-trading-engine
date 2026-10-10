from datetime import UTC, datetime
from pathlib import Path

import pytest

from paper_engine.news import CoinTagger, FeedError, clean_text, parse_feed, safe_url

FIXTURES = Path(__file__).parent / "fixtures" / "news"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
SYMBOLS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "LINK/USDT:USDT"]


def parse(name, symbols=SYMBOLS, base_url=None):
    body = (FIXTURES / name).read_bytes()
    return parse_feed(body, "Test", CoinTagger(symbols), base_url, NOW)


def test_html_is_stripped_and_unsafe_links_dropped():
    items = parse("hostile.rss")
    by_url = {item.url: item for item in items}
    first = by_url["https://hostile.example.test/a?id=7"]
    assert first.title == "Bitcoin surges & $ETH follows"
    assert first.summary == "Price jumps again."
    for item in items:
        for text in (item.title, item.summary):
            assert "<" not in text and ">" not in text
            assert "script" not in text.lower() and "onerror" not in text
        assert item.url.startswith("https://")
    assert not any("javascript" in i.url or i.url.startswith("data:") for i in items)
    assert not any(i.title == "" for i in items)


def test_tracking_parameters_collapse_duplicates():
    items = parse("hostile.rss")
    assert [i.url for i in items].count("https://hostile.example.test/a?id=7") == 1
    assert all("utm_" not in i.url for i in items)


def test_missing_and_future_dates_clamp_to_now():
    items = {i.url.rsplit("/", 1)[1]: i for i in parse("hostile.rss")}
    assert items["nodate"].published_at == NOW
    assert items["future"].published_at == NOW
    assert items["a?id=7"].published_at == datetime(2026, 10, 9, 20, 39, 17, tzinfo=UTC)


def test_symbol_tagging_by_ticker_and_name():
    items = {i.url.rsplit("/", 1)[1]: i for i in parse("hostile.rss")}
    assert items["a?id=7"].symbols == ("BTC", "ETH")
    # Chainlink matches; lowercase "link"/"ether"/"near" and "Bitcoin Cash" do not.
    assert items["words"].symbols == ("LINK",)


def test_atom_relative_links_resolve_and_tag():
    (item,) = parse("atom.xml", base_url="https://atom.example.test/feed")
    assert item.url == "https://atom.example.test/posts/upgrade"
    assert item.title == "Ethereum upgrade ships"
    assert item.summary == "Developers say ETH fees fall."
    assert item.symbols == ("ETH",)


def test_relative_link_without_base_is_dropped():
    assert parse("atom.xml") == []


@pytest.mark.parametrize(
    ("text", "symbols", "expected"),
    [
        ("BTC rallies", ["BTC/USDT:USDT"], ("BTC",)),
        ("btc rallies", ["BTC/USDT:USDT"], ()),
        ("BITCOIN RALLIES", ["BTC/USDT:USDT"], ("BTC",)),
        ("WBTC is not BTC-USD", ["BTC/USDT:USDT"], ("BTC",)),
        ("WBTC only", ["BTC/USDT:USDT"], ()),
        ("Ethereum's ETHBTC ratio", ["ETH/USDT:USDT"], ("ETH",)),
        ("OP Mainnet and $OP", ["OP/USDT:USDT"], ("OP",)),
        ("OP Mainnet", ["OP/USDT:USDT"], ()),
        ("Pepe and PEPE", ["1000PEPE/USDT:USDT"], ("1000PEPE",)),
        ("Bitcoin Cash forks", ["BTC/USDT:USDT", "BCH/USDT:USDT"], ("BCH",)),
        ("AI tokens", ["AI/USDT:USDT"], ()),
    ],
)
def test_coin_tagger(text, symbols, expected):
    assert CoinTagger(symbols).tag(text) == expected


def test_external_entities_are_not_resolved(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-MARKER")
    body = (
        '<?xml version="1.0"?>\n'
        f'<!DOCTYPE rss [<!ENTITY xxe SYSTEM "{secret.as_uri()}">]>\n'
        '<rss version="2.0"><channel><title>x</title><item>'
        "<title>Leak &xxe; test</title><link>https://x.example.test/1</link>"
        "<description>&xxe;</description></item></channel></rss>"
    ).encode()
    items = parse_feed(body, "Test", CoinTagger(SYMBOLS), None, NOW)
    assert len(items) == 1  # the document parsed; the entity was simply not expanded
    assert "TOP-SECRET-MARKER" not in items[0].title + items[0].summary


@pytest.mark.parametrize("body", [b"", b"not xml at all", b"<html><body>Blocked</body></html>"])
def test_unreadable_documents_raise_feed_error(body):
    with pytest.raises(FeedError):
        parse_feed(body, "Test", CoinTagger(SYMBOLS), None, NOW)


def test_parse_refuses_non_bytes_so_feedparser_never_fetches():
    with pytest.raises(TypeError):
        parse_feed("https://example.test/rss", "Test", CoinTagger(SYMBOLS))  # type: ignore[arg-type]


def test_clean_text_handles_double_encoding_and_limits():
    assert clean_text("&amp;lt;b&amp;gt;Bold&amp;lt;/b&amp;gt; &amp;#039;quote&amp;#039;") == (
        "Bold 'quote'"
    )
    assert clean_text("a\u202eb\x00c   d") == "abc d"
    assert clean_text("x < 5 and y > 3") == "x < 5 and y > 3"
    long = clean_text("word " * 200, 50)
    assert len(long) <= 50 and long.endswith("…")
    assert clean_text(None) == ""


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://Example.TEST/a?utm_source=x&b=1#frag", "https://example.test/a?b=1"),
        ("http://example.test", "http://example.test/"),
        ("javascript:alert(1)", None),
        ("data:text/html,hi", None),
        ("/relative", None),
        ("https://user:pw@example.test/", None),
        ("https://example.test:99999/", None),
        ("https://exa mple.test/", None),
        ("https://[::1", None),
        (None, None),
    ],
)
def test_safe_url(url, expected):
    assert safe_url(url) == expected
