import time

import httpx2
import pytest
from fastapi.testclient import TestClient

from paper_engine import api as api_module
from paper_engine.api import create_app
from paper_engine.config import NewsSource
from paper_engine.news import NewsService
from paper_engine.store import Store
from tests.conftest import SYMBOL, TOKEN

AUTH = {"Authorization": f"Bearer {TOKEN}"}
SOURCE = NewsSource(name="Alpha", url="https://alpha.example.test/rss")
FEED = (
    b'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
    b"<item><title>Bitcoin &lt;b&gt;rallies&lt;/b&gt;</title>"
    b"<link>https://alpha.example.test/1?utm_source=rss</link>"
    b"<description>&lt;script&gt;alert(1)&lt;/script&gt;Buyers return.</description>"
    b"<pubDate>Fri, 09 Oct 2026 10:00:00 +0000</pubDate></item>"
    b"<item><title>Macro wrap</title><link>https://alpha.example.test/2</link>"
    b"<pubDate>Fri, 09 Oct 2026 09:00:00 +0000</pubDate></item>"
    b"</channel></rss>"
)


@pytest.fixture
def news_app(settings, monkeypatch):
    settings.news_enabled = True
    settings.news_feeds = [SOURCE]
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx2.Response(200, content=FEED)

    real = NewsService
    monkeypatch.setattr(
        api_module,
        "NewsService",
        lambda s: real(s, transport=httpx2.MockTransport(handler)),
    )
    with TestClient(create_app(settings)) as client:
        deadline = time.monotonic() + 5
        while not client.app.state.news.items and time.monotonic() < deadline:
            time.sleep(0.02)
        yield client, calls


def test_news_requires_auth(news_app):
    client, _ = news_app
    assert client.get("/api/v1/news").status_code == 401
    assert client.get("/api/v1/news", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_news_is_served_from_the_background_poller(news_app):
    client, calls = news_app
    assert calls == [SOURCE.url]
    response = client.get("/api/v1/news", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True and body["total"] == 2
    first = body["items"][0]
    assert first["title"] == "Bitcoin rallies"
    assert first["summary"] == "Buyers return."
    assert first["url"] == "https://alpha.example.test/1"
    assert first["symbols"] == ["BTC"]
    for item in body["items"]:
        assert "<" not in item["title"] + item["summary"]
        assert "script" not in item["summary"]
    assert body["sources"] == [
        {
            "name": "Alpha",
            "status": "ok",
            "error": None,
            "last_success": body["sources"][0]["last_success"],
            "item_count": 2,
        }
    ]
    assert set(first) == {"id", "source", "title", "summary", "url", "published_at", "symbols"}


def test_news_filters_and_validation(news_app):
    client, _ = news_app
    get = lambda **params: client.get("/api/v1/news", params=params, headers=AUTH)  # noqa: E731
    assert [i["title"] for i in get(symbol=SYMBOL).json()["items"]] == ["Bitcoin rallies"]
    assert get(source="Alpha").json()["total"] == 2
    assert get(q="macro").json()["total"] == 1
    page = get(limit=1, offset=1).json()
    assert page["total"] == 2 and [i["title"] for i in page["items"]] == ["Macro wrap"]
    for params, code in [
        ({"source": "Gamma"}, "unsupported_news_filter"),
        ({"symbol": "DOGE/USDT:USDT"}, "unsupported_news_filter"),
    ]:
        response = get(**params)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == code
    for params in [{"q": "x" * 101}, {"limit": 0}, {"limit": 51}, {"offset": 501}, {"source": ""}]:
        assert get(**params).status_code == 422


def test_news_disabled_fails_closed_without_network(settings):
    with TestClient(create_app(settings)) as client:
        assert client.app.state.news is None
        response = client.get("/api/v1/news", headers=AUTH)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "news_disabled"
        config = client.get("/api/v1/config", headers=AUTH).json()
        assert config["news_enabled"] is False
        assert TOKEN not in str(config)


def test_news_poller_shuts_down_with_the_app(settings, monkeypatch):
    settings.news_enabled = True
    settings.news_feeds = [SOURCE]
    created = []

    def factory(s):
        service = NewsService(
            s, transport=httpx2.MockTransport(lambda r: httpx2.Response(200, content=FEED))
        )
        created.append(service)
        return service

    monkeypatch.setattr(api_module, "NewsService", factory)
    with TestClient(create_app(settings)) as client:
        deadline = time.monotonic() + 5
        while not created[0].items and time.monotonic() < deadline:
            time.sleep(0.02)
        assert client.get("/api/v1/news", headers=AUTH).json()["total"] == 2
        http_client = created[0].client
    assert http_client is not None and http_client.is_closed
    assert created[0].client is None


def test_startup_failure_releases_store_lock(settings, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("engine failed")

    monkeypatch.setattr(api_module, "Engine", broken)
    with pytest.raises(RuntimeError, match="engine failed"):
        with TestClient(create_app(settings)):
            pass
    store = Store(settings.db_path, settings.initial_balance, settings.exchange, settings.symbols)
    store.close()
