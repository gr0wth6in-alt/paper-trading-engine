import asyncio
import os
import threading
import time

import httpx2
import pytest

from paper_engine import news
from paper_engine.config import NewsSource
from paper_engine.models import EngineError
from paper_engine.news import NewsService

SYMBOLS = ["BTC/USDT:USDT", "ETH/USDT:USDT"]
A = NewsSource(name="Alpha", url="https://alpha.example.test/rss")
B = NewsSource(name="Beta", url="https://beta.example.test/feed")


def rss(*items: tuple[str, str, str]) -> bytes:
    body = "".join(
        f"<item><title>{title}</title><link>{link}</link><pubDate>{date}</pubDate></item>"
        for title, link, date in items
    )
    head = '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
    return f"{head}{body}</channel></rss>".encode()


ALPHA = rss(
    ("Bitcoin hits a high", "https://alpha.example.test/1", "Fri, 09 Oct 2026 10:00:00 +0000"),
    ("Markets drift", "https://alpha.example.test/2", "Fri, 09 Oct 2026 08:00:00 +0000"),
)
BETA = rss(
    ("ETH gas falls", "https://beta.example.test/1", "Fri, 09 Oct 2026 09:00:00 +0000"),
    (
        "Shared story",
        "https://alpha.example.test/2?utm_source=beta",
        "Fri, 09 Oct 2026 08:00:00 +0000",
    ),
)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_service(settings, handler, sources=(A, B), clock=None, parser="thread"):
    settings.symbols = SYMBOLS
    settings.news_feeds = list(sources)
    return NewsService(
        settings, transport=httpx2.MockTransport(handler), clock=clock or Clock(), parser=parser
    )


def routes(mapping, calls=None):
    async def handler(request: httpx2.Request):
        if calls is not None:
            calls.append(request)
        result = mapping[str(request.url)]
        return result(request) if callable(result) else httpx2.Response(200, content=result)

    return handler


async def test_merges_sources_newest_first_and_dedupes(settings):
    service = make_service(settings, routes({A.url: ALPHA, B.url: BETA}))
    await service.poll_once()
    result = service.query()
    assert [i["title"] for i in result["items"]] == [
        "Bitcoin hits a high",
        "ETH gas falls",
        "Markets drift",
    ]
    assert result["total"] == 3
    assert result["items"][0]["symbols"] == ["BTC"]
    assert result["items"][1]["symbols"] == ["ETH"]
    assert {s["name"]: s["status"] for s in result["sources"]} == {"Alpha": "ok", "Beta": "ok"}
    assert result["updated_at"] is not None
    await service.close()


async def test_failing_source_is_isolated_and_backs_off(settings):
    calls = []
    clock = Clock()
    handler = routes({A.url: ALPHA, B.url: lambda r: httpx2.Response(403)}, calls)
    service = make_service(settings, handler, clock=clock)
    await service.poll_once()
    sources = {s["name"]: s for s in service.query()["sources"]}
    assert sources["Alpha"]["status"] == "ok"
    assert sources["Beta"] == {
        "name": "Beta",
        "status": "error",
        "error": "HTTP 403",
        "last_success": None,
        "item_count": 0,
    }
    assert service.query()["total"] == 2

    calls.clear()
    await service.poll_once()
    assert [str(c.url) for c in calls] == [A.url]  # Beta is backing off
    clock.now += news.BACKOFF_BASE_SECONDS
    calls.clear()
    await service.poll_once()
    assert sorted(str(c.url) for c in calls) == sorted([A.url, B.url])
    assert service.sources[1].failures == 2
    assert service.sources[1].retry_at == clock.now + news.BACKOFF_BASE_SECONDS * 2
    await service.close()


async def test_backoff_is_capped_and_resets_after_success(settings):
    clock = Clock()
    state = {"ok": False}

    def beta(request):
        return httpx2.Response(200, content=BETA) if state["ok"] else httpx2.Response(500)

    service = make_service(settings, routes({A.url: ALPHA, B.url: beta}), clock=clock)
    for _ in range(8):
        await service.poll_once()
        clock.now = service.sources[1].retry_at
    assert service.sources[1].retry_at - clock.now <= news.BACKOFF_MAX_SECONDS
    state["ok"] = True
    await service.poll_once()
    assert service.sources[1].status == "ok"
    assert service.sources[1].failures == 0 and service.sources[1].error is None
    await service.close()


async def test_conditional_requests_keep_items_on_304(settings):
    calls = []

    def alpha(request):
        if request.headers.get("if-none-match") == '"v1"':
            return httpx2.Response(304)
        return httpx2.Response(200, content=ALPHA, headers={"ETag": '"v1"'})

    service = make_service(settings, routes({A.url: alpha}, calls), sources=(A,))
    await service.poll_once()
    await service.poll_once()
    assert calls[1].headers["if-none-match"] == '"v1"'
    assert service.query()["total"] == 2
    assert service.sources[0].status == "ok"
    await service.close()


async def test_oversized_bodies_are_aborted(settings, monkeypatch):
    monkeypatch.setattr(news, "MAX_BODY_BYTES", 1000)

    async def endless():
        while True:
            yield b"x" * 400

    handler = routes(
        {
            A.url: lambda r: httpx2.Response(200, content=b"x" * 2000),  # declared length
            B.url: lambda r: httpx2.Response(200, content=endless()),  # chunked, no length
        }
    )
    service = make_service(settings, handler)
    await service.poll_once()
    assert [s.error for s in service.sources] == ["Response too large", "Response too large"]
    await service.close()


async def test_redirect_to_http_is_refused_before_sending(settings):
    calls = []
    handler = routes(
        {
            A.url: lambda r: httpx2.Response(
                302, headers={"Location": "http://alpha.example.test/x"}
            )
        },
        calls,
    )
    service = make_service(settings, handler, sources=(A,))
    await service.poll_once()
    assert service.sources[0].error == "Insecure redirect refused"
    assert [str(c.url) for c in calls] == [A.url]
    await service.close()


async def test_https_redirect_is_followed(settings):
    target = "https://cdn.alpha.example.test/rss"
    handler = routes(
        {A.url: lambda r: httpx2.Response(301, headers={"Location": target}), target: ALPHA}
    )
    service = make_service(settings, handler, sources=(A,))
    await service.poll_once()
    assert service.query()["total"] == 2
    await service.close()


async def test_slow_source_times_out_without_blocking_others(settings, monkeypatch):
    monkeypatch.setattr(news, "SOURCE_TIMEOUT_SECONDS", 0.2)

    async def handler(request):
        if str(request.url) == B.url:
            await asyncio.sleep(5)
        return httpx2.Response(200, content=ALPHA)

    service = make_service(settings, handler)
    started = time.perf_counter()
    await service.poll_once()
    assert time.perf_counter() - started < 2
    assert [s.status for s in service.sources] == ["ok", "error"]
    assert service.sources[1].error == "Timed out"
    await service.close()


async def test_unreadable_feed_is_a_source_error(settings):
    service = make_service(settings, routes({A.url: b"<html>blocked</html>"}), sources=(A,))
    await service.poll_once()
    assert service.sources[0].error == "Feed unreadable"
    await service.close()


async def test_item_cap(settings, monkeypatch):
    monkeypatch.setattr(news, "MAX_ITEMS", 2)
    service = make_service(settings, routes({A.url: ALPHA, B.url: BETA}))
    await service.poll_once()
    assert [i["title"] for i in service.query()["items"]] == [
        "Bitcoin hits a high",
        "ETH gas falls",
    ]
    await service.close()


async def test_query_filters_and_paging(settings):
    service = make_service(settings, routes({A.url: ALPHA, B.url: BETA}))
    await service.poll_once()
    assert [i["title"] for i in service.query(source="Beta")["items"]] == ["ETH gas falls"]
    assert [i["title"] for i in service.query(symbol="BTC/USDT:USDT")["items"]] == [
        "Bitcoin hits a high"
    ]
    assert [i["title"] for i in service.query(q="  GAS   eth ")["items"]] == ["ETH gas falls"]
    assert service.query(q="<b>gas</b>")["total"] == 1
    page = service.query(limit=1, offset=1)
    assert page["total"] == 3 and [i["title"] for i in page["items"]] == ["ETH gas falls"]
    for kwargs in ({"source": "Gamma"}, {"symbol": "DOGE/USDT:USDT"}):
        with pytest.raises(EngineError) as exc:
            service.query(**kwargs)
        assert exc.value.status == 422
    await service.close()


async def test_parsing_runs_off_the_event_loop_thread(settings, monkeypatch):
    threads = []
    original = news.parse_feed

    def recording(*args, **kwargs):
        threads.append(threading.get_ident())
        return original(*args, **kwargs)

    monkeypatch.setattr(news, "parse_feed", recording)
    service = make_service(settings, routes({A.url: ALPHA}), sources=(A,))
    await service.poll_once()
    assert threads and threading.get_ident() not in threads
    await service.close()


async def test_default_parser_runs_in_a_separate_process(settings):
    settings.symbols = SYMBOLS
    settings.news_feeds = [A]
    service = NewsService(settings, transport=httpx2.MockTransport(routes({A.url: ALPHA})))
    assert service.parser == "process"
    await service.poll_once()
    assert service.query()["items"][0]["symbols"] == ["BTC"]
    pids = [p.pid for p in service.executor._processes.values()]
    assert pids and os.getpid() not in pids
    await service.close()
    assert service.executor is None


async def test_hung_parser_is_replaced_and_later_polls_recover(settings, monkeypatch):
    service = make_service(settings, routes({A.url: ALPHA}), sources=(A,), parser="process")
    await service.poll_once()  # warm the worker
    first = service.executor
    first_processes = list(first._processes.values())
    monkeypatch.setattr(news, "PARSE_TIMEOUT_SECONDS", 0)
    await service.poll_once()
    assert service.sources[0].error == "Parser restarted"
    assert service.executor is None
    assert first_processes and not any(p.is_alive() for p in first_processes)
    monkeypatch.setattr(news, "PARSE_TIMEOUT_SECONDS", 15)
    service.sources[0].retry_at = 0
    await service.poll_once()
    assert service.sources[0].status == "ok" and service.executor is not first
    await service.close()


async def test_large_feed_parse_does_not_stall_event_loop(settings):
    parser = "process"
    entries = [
        (
            f"Bitcoin story {n} " + "word " * 40,
            f"https://alpha.example.test/{n}",
            "Fri, 09 Oct 2026 10:00:00 +0000",
        )
        for n in range(2500)
    ]
    body = rss(*entries)
    assert 0.5 * 1024 * 1024 < len(body) < news.MAX_BODY_BYTES
    service = make_service(settings, routes({A.url: body}), sources=(A,), parser=parser)
    if parser == "process":
        service.executor = await asyncio.to_thread(service._start_executor)  # exclude spawn
    lags = []
    done = asyncio.Event()

    async def ticker():
        while not done.is_set():
            started = time.perf_counter()
            await asyncio.sleep(0.01)
            lags.append(time.perf_counter() - started - 0.01)

    tick = asyncio.create_task(ticker())
    started = time.perf_counter()
    await service.poll_once()
    elapsed = time.perf_counter() - started
    done.set()
    await tick
    assert service.query()["total"] == news.MAX_ENTRIES_PER_FEED
    assert len(lags) >= 5, f"parse finished too fast to measure ({elapsed:.3f}s)"
    assert max(lags) < 0.1, f"event loop stalled for {max(lags):.3f}s"
    await service.close()


async def test_run_loop_cancels_cleanly_and_close_releases_client(settings, monkeypatch):
    service = make_service(settings, routes({A.url: ALPHA}), sources=(A,))
    task = asyncio.create_task(service.run())
    for _ in range(100):
        if service.items:
            break
        await asyncio.sleep(0.01)
    assert service.items
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    client = service.client
    await service.close()
    assert client is not None and client.is_closed and service.client is None
    await service.close()  # idempotent
