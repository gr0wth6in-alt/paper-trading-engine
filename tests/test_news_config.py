import json

import pytest
from pydantic import ValidationError

from paper_engine.config import DEFAULT_NEWS_SOURCES, Settings
from tests.conftest import TOKEN


def test_news_defaults_are_https_and_enabled():
    settings = Settings(_env_file=None, api_token=TOKEN)
    assert settings.news_enabled is True
    assert settings.news_poll_seconds == 300
    assert [s.name for s in settings.news_feeds] == [s.name for s in DEFAULT_NEWS_SOURCES]
    assert all(s.url.startswith("https://") for s in settings.news_feeds)


def test_news_feeds_override_from_environment(monkeypatch):
    feeds = [{"name": "Example", "url": "https://news.example.test/rss"}]
    monkeypatch.setenv("PAPER_NEWS_FEEDS", json.dumps(feeds))
    monkeypatch.setenv("PAPER_NEWS_POLL_SECONDS", "120")
    settings = Settings(_env_file=None, api_token=TOKEN)
    assert [(s.name, s.url) for s in settings.news_feeds] == [
        ("Example", "https://news.example.test/rss")
    ]
    assert settings.news_poll_seconds == 120


@pytest.mark.parametrize(
    "kwargs",
    [
        {"news_feeds": []},
        {"news_feeds": [{"name": "Plain", "url": "http://example.test/rss"}]},
        {"news_feeds": [{"name": "Js", "url": "javascript:alert(1)"}]},
        {"news_feeds": [{"name": "Creds", "url": "https://user:pw@example.test/rss"}]},
        {"news_feeds": [{"name": "Port", "url": "https://example.test:99999/rss"}]},
        {"news_feeds": [{"name": "<b>x</b>", "url": "https://example.test/rss"}]},
        {"news_feeds": [{"name": "Extra", "url": "https://example.test/rss", "x": 1}]},
        {
            "news_feeds": [
                {"name": "Same", "url": "https://a.example.test/rss"},
                {"name": "same", "url": "https://b.example.test/rss"},
            ]
        },
        {
            "news_feeds": [
                {"name": "A", "url": "https://a.example.test/rss"},
                {"name": "B", "url": "https://a.example.test/rss"},
            ]
        },
        {"news_feeds": [{"name": f"S{i}", "url": f"https://{i}.example.test/"} for i in range(21)]},
        {"news_poll_seconds": 59},
        {"news_poll_seconds": 3601},
    ],
)
def test_unsafe_news_configuration_rejected(kwargs):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, api_token=TOKEN, **kwargs)
