"""Crypto news aggregation from public RSS/Atom feeds.

Everything here is memory-only. Network I/O is async (httpx2) and feed parsing runs in a
worker thread, so the trading event loop and WebSocket snapshots are never blocked.
All markup is stripped to plain text before an item leaves this module.
"""

import asyncio
import calendar
import hashlib
import html
import io
import logging
import multiprocessing
import os
import re
import signal
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import httpx2

from paper_engine.config import NewsSource, Settings
from paper_engine.models import EngineError, utc_now

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_ENTRIES_PER_FEED = 50
MAX_ITEMS = 500
MAX_TITLE = 300
MAX_SUMMARY = 400
MAX_URL = 2048
FETCH_CONCURRENCY = 4
SOURCE_TIMEOUT_SECONDS = 20
PARSE_TIMEOUT_SECONDS = 15
BACKOFF_BASE_SECONDS = 300
BACKOFF_MAX_SECONDS = 3600
USER_AGENT = "paper-trading-engine-news/0.1 (+local RSS reader)"
ACCEPT = (
    "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.1"
)

# Names are proper nouns matched case-sensitively (exact or ALL CAPS). Words that are common
# in ordinary English (Near, Link, Optimism, Stellar, Jupiter...) are deliberately omitted.
COIN_ALIASES: dict[str, tuple[str, ...]] = {
    "BTC": ("Bitcoin",),
    "ETH": ("Ethereum", "Ether"),
    "SOL": ("Solana",),
    "XRP": ("Ripple",),
    "BNB": ("BNB Chain", "Binance Coin"),
    "DOGE": ("Dogecoin",),
    "ADA": ("Cardano",),
    "AVAX": ("Avalanche",),
    "DOT": ("Polkadot",),
    "LINK": ("Chainlink",),
    "LTC": ("Litecoin",),
    "BCH": ("Bitcoin Cash",),
    "ETC": ("Ethereum Classic",),
    "TRX": ("Tron",),
    "TON": ("Toncoin",),
    "SUI": ("Sui",),
    "APT": ("Aptos",),
    "ARB": ("Arbitrum",),
    "ATOM": ("Cosmos",),
    "POL": ("Polygon",),
    "MATIC": ("Polygon",),
    "SHIB": ("Shiba Inu",),
    "PEPE": ("Pepe",),
    "FIL": ("Filecoin",),
    "UNI": ("Uniswap",),
    "AAVE": ("Aave",),
    "HYPE": ("Hyperliquid",),
    "ENA": ("Ethena",),
    "WLD": ("Worldcoin",),
    "TIA": ("Celestia",),
    "INJ": ("Injective",),
    "HBAR": ("Hedera",),
    "ICP": ("Internet Computer",),
    "TAO": ("Bittensor",),
    "XMR": ("Monero",),
    "ZEC": ("Zcash",),
    "ONDO": ("Ondo",),
}
# Tickers that are also common acronyms or words only match with a "$" prefix.
AMBIGUOUS_TICKERS = frozenset(
    {"AI", "ONE", "GAS", "SUN", "MAX", "ME", "IO", "SEC", "CEO", "NFT", "DAO", "ETF", "USD"}
    | {"ACT", "ANY", "BIG", "GOOD", "HIGH", "LOW", "NOT", "WIN", "JOB", "OM", "IP", "TOP", "FUN"}
)
TRACKING_PARAMS = frozenset({"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src"})
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")
_SPACE = re.compile(r"\s+")
_TAG_LIKE = re.compile(r"<\s*/?\s*[A-Za-z!][^>]*>")


class FeedError(Exception):
    """A feed could not be fetched or understood. The message is safe to show users."""


class _TextExtractor(HTMLParser):
    SKIP = frozenset({"script", "style", "noscript", "iframe", "template", "object", "svg"})
    BREAK = frozenset({"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip_depth += 1
        elif tag in self.BREAK:
            self.parts.append(" ")

    def handle_startendtag(self, tag, attrs):
        if tag in self.BREAK:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip_depth = max(0, self.skip_depth - 1)
        elif tag in self.BREAK:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.skip_depth:
            self.parts.append(data)


def _strip_markup(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    parser.close()
    return "".join(parser.parts)


def clean_text(value: object, limit: int | None = None) -> str:
    """Return plain text: no tags, no entities, no control characters, single spaces."""
    if not isinstance(value, str) or not value:
        return ""
    text = _strip_markup(value)
    # Feeds frequently double-encode (&amp;lt;p&amp;gt;). Decode and strip again, bounded.
    for _ in range(2):
        decoded = html.unescape(text)
        if _TAG_LIKE.search(decoded):
            text = _strip_markup(decoded)
        else:
            text = decoded
            break
    text = _TAG_LIKE.sub(" ", text)
    text = _SPACE.sub(" ", _CONTROL.sub("", text)).strip()
    if limit is not None and len(text) > limit:
        cut = text[: limit - 1]
        space = cut.rfind(" ")
        text = (cut[:space] if space > limit // 2 else cut).rstrip(" ,.;:-") + "…"
    return text


def safe_url(value: object) -> str | None:
    """Return a canonical http(s) URL without tracking parameters, or None if unsafe."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > MAX_URL or _CONTROL.search(value) or _SPACE.search(value):
        return None
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    if parts.username is not None or parts.password is not None:
        return None
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    ]
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", urlencode(query), ""))


def item_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:20]


def base_asset(symbol: str) -> str:
    return symbol.split("/", 1)[0]


class CoinTagger:
    """Tags text with base assets from the active symbol list (ticker or known name)."""

    def __init__(self, symbols: Iterable[str]):
        self.order: dict[str, int] = {}
        ticker_map: dict[str, str] = {}
        for index, symbol in enumerate(symbols):
            base = base_asset(symbol)
            self.order.setdefault(base, index)
            ticker_map[base] = base
            core = re.sub(r"^1000+", "", base)  # 1000PEPE -> PEPE
            if core and core != base:
                ticker_map.setdefault(core, base)
        self.ticker_map = ticker_map
        self.ambiguous = {t for t in ticker_map if len(t) <= 2 or t in AMBIGUOUS_TICKERS}
        self.ticker_re = (
            re.compile(
                r"(?<![A-Za-z0-9$])(\$?)("
                + "|".join(re.escape(t) for t in sorted(ticker_map, key=len, reverse=True))
                + r")(?![A-Za-z0-9])"
            )
            if ticker_map
            else None
        )
        # Every known name is matched (longest first) so "Bitcoin Cash" never counts as
        # Bitcoin, even when BCH is not traded. Names for untraded assets map to None.
        core_to_base = {core: base for core, base in ticker_map.items()}
        self.name_map: dict[str, str | None] = {}
        for ticker, names in COIN_ALIASES.items():
            for name in names:
                target = core_to_base.get(ticker)
                if self.name_map.get(name) is None:
                    self.name_map[name] = target
        names = sorted(self.name_map, key=len, reverse=True)
        self.name_re = re.compile(
            r"(?<![A-Za-z0-9])(" + "|".join(re.escape(n) for n in names) + r")(?![A-Za-z0-9])",
            re.IGNORECASE,
        )
        self.name_lookup = {n.upper(): n for n in self.name_map}

    def tag(self, *texts: str) -> tuple[str, ...]:
        found: set[str] = set()
        for text in texts:
            if not text:
                continue
            if self.ticker_re is not None:
                for match in self.ticker_re.finditer(text):
                    ticker = match.group(2)
                    if ticker in self.ambiguous and not match.group(1):
                        continue
                    found.add(self.ticker_map[ticker])
            for match in self.name_re.finditer(text):
                raw = match.group(1)
                name = self.name_lookup.get(raw.upper())
                if name is None or raw not in (name, name.upper()):
                    continue  # "ether" or "Tron" in lowercase prose is not a coin mention
                target = self.name_map[name]
                if target is not None:
                    found.add(target)
        return tuple(sorted(found, key=lambda base: self.order.get(base, 1 << 30)))


@dataclass(frozen=True, slots=True)
class NewsItem:
    id: str
    source: str
    title: str
    summary: str
    url: str
    published_at: datetime
    symbols: tuple[str, ...]
    search_text: str = field(repr=False, compare=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "title": self.title,
            "summary": self.summary,
            "url": self.url,
            "published_at": self.published_at.isoformat(),
            "symbols": list(self.symbols),
        }


def _entry_time(entry, now: datetime) -> datetime:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                stamp = datetime.fromtimestamp(calendar.timegm(value), UTC)
            except (OverflowError, ValueError, TypeError, OSError):
                continue
            return min(stamp, now)
    return now


def parse_feed(
    body: bytes,
    source: str,
    tagger: CoinTagger,
    base_url: str | None = None,
    now: datetime | None = None,
) -> list[NewsItem]:
    """Parse untrusted RSS/Atom bytes into plain-text items. CPU-bound: call via to_thread."""
    if not isinstance(body, bytes):
        raise TypeError("Feed body must be bytes")  # never let feedparser fetch a URL
    now = now or utc_now()
    headers = {"content-location": base_url} if base_url else {}
    parsed = feedparser.parse(io.BytesIO(body), response_headers=headers, sanitize_html=True)
    entries = parsed.get("entries") or []
    if not entries and (parsed.get("bozo") or not parsed.get("version")):
        raise FeedError("Feed unreadable")
    items: list[NewsItem] = []
    seen: set[str] = set()
    for entry in entries[:MAX_ENTRIES_PER_FEED]:
        title = clean_text(entry.get("title"), MAX_TITLE)
        url = safe_url(entry.get("link"))
        if not title or url is None:
            continue
        identifier = item_id(url)
        if identifier in seen:
            continue
        seen.add(identifier)
        summary = clean_text(entry.get("summary") or entry.get("description"), MAX_SUMMARY)
        if summary.casefold() == title.casefold():
            summary = ""
        items.append(
            NewsItem(
                id=identifier,
                source=source,
                title=title,
                summary=summary,
                url=url,
                published_at=_entry_time(entry, now),
                symbols=tagger.tag(title, summary),
                search_text=f"{title} {summary}".casefold(),
            )
        )
    return items


@dataclass
class SourceState:
    source: NewsSource
    status: Literal["pending", "ok", "error"] = "pending"
    error: str | None = None
    last_success: datetime | None = None
    last_attempt: datetime | None = None
    failures: int = 0
    retry_at: float = 0.0
    etag: str | None = None
    last_modified: str | None = None
    items: tuple[NewsItem, ...] = ()

    def to_dict(self) -> dict:
        return {
            "name": self.source.name,
            "status": self.status,
            "error": self.error,
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "item_count": len(self.items),
        }


def _describe(exc: BaseException) -> str:
    if isinstance(exc, FeedError):
        return str(exc)
    if isinstance(exc, TimeoutError | httpx2.TimeoutException):
        return "Timed out"
    if isinstance(exc, httpx2.TooManyRedirects):
        return "Too many redirects"
    if isinstance(exc, httpx2.TransportError):
        return "Connection failed"
    return "Feed unavailable"


def _stop_executor(executor: ProcessPoolExecutor) -> None:
    """Shut a parser pool down without waiting on a possibly hung worker."""
    processes = list((getattr(executor, "_processes", None) or {}).values())
    executor.shutdown(wait=False, cancel_futures=True)
    for process in processes:
        with suppress(Exception):
            process.kill()
            process.join(timeout=5)


def _header(value: str | None) -> str | None:
    return value if value and len(value) <= 200 and not _CONTROL.search(value) else None


async def _require_https(request: httpx2.Request) -> None:
    # Runs for the first request and every redirect hop, before anything is sent.
    if request.url.scheme != "https":
        raise FeedError("Insecure redirect refused")


_worker_taggers: dict[tuple[str, ...], CoinTagger] = {}


def _worker_init() -> None:
    # Ctrl+C is handled by the server process, which shuts this pool down cleanly.
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def _worker_ready() -> int:
    return os.getpid()


def _parse_in_worker(
    body: bytes, source: str, symbols: tuple[str, ...], base_url: str | None
) -> list[NewsItem]:
    tagger = _worker_taggers.get(symbols)
    if tagger is None:
        tagger = _worker_taggers[symbols] = CoinTagger(symbols)
    return parse_feed(body, source, tagger, base_url)


class NewsService:
    """Polls feeds in the background and serves an immutable in-memory snapshot.

    ``parser="process"`` (default) parses in a single spawned worker process. feedparser's
    C-level regex and expat work holds the GIL, so a worker *thread* can still stall the
    event loop by 50-300 ms on large feeds; a separate process cannot. ``"thread"`` exists
    for tests that patch the parser in-process.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        parser: Literal["process", "thread"] = "process",
    ):
        self.parser = parser
        self.executor: ProcessPoolExecutor | None = None
        self.executor_lock = asyncio.Lock()
        self.poll_seconds = settings.news_poll_seconds
        self.symbols = tuple(settings.symbols)
        self.tagger = CoinTagger(self.symbols)
        self.sources = [SourceState(source) for source in settings.news_feeds]
        self.source_names = {state.source.name for state in self.sources}
        self.transport = transport
        self.clock = clock
        self.client: httpx2.AsyncClient | None = None
        self.items: tuple[NewsItem, ...] = ()
        self.updated_at: datetime | None = None
        self.semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)
        self.client_lock = asyncio.Lock()

    def _build_client(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            timeout=httpx2.Timeout(10, connect=5),
            follow_redirects=True,
            max_redirects=3,
            headers={"User-Agent": USER_AGENT, "Accept": ACCEPT},
            limits=httpx2.Limits(max_connections=8, max_keepalive_connections=4),
            event_hooks={"request": [_require_https]},
            transport=self.transport,
        )

    async def _client(self) -> httpx2.AsyncClient:
        # Building the TLS context loads CA certificates synchronously (~100+ ms), so it
        # happens in a worker thread rather than on the trading event loop.
        async with self.client_lock:
            if self.client is None:
                self.client = await asyncio.to_thread(self._build_client)
            return self.client

    @staticmethod
    def _start_executor() -> ProcessPoolExecutor:
        # Runs in a worker thread: spawning and warming the process blocks for ~0.5 s.
        executor = ProcessPoolExecutor(
            max_workers=1,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_worker_init,
        )
        try:
            executor.submit(_worker_ready).result(timeout=60)
        except BaseException:
            _stop_executor(executor)
            raise
        return executor

    async def _parse(self, body: bytes, source: str, base_url: str) -> list[NewsItem]:
        if self.parser == "thread":
            return await asyncio.to_thread(parse_feed, body, source, self.tagger, base_url)
        async with self.executor_lock:
            if self.executor is None:
                self.executor = await asyncio.to_thread(self._start_executor)
            executor = self.executor
        loop = asyncio.get_running_loop()
        try:
            async with asyncio.timeout(PARSE_TIMEOUT_SECONDS):
                return await loop.run_in_executor(
                    executor, _parse_in_worker, body, source, self.symbols, base_url
                )
        except (TimeoutError, BrokenProcessPool) as exc:
            # A hung or crashed parser must not block later sources: replace the worker.
            async with self.executor_lock:
                if self.executor is executor:
                    self.executor = None
            await asyncio.to_thread(_stop_executor, executor)
            raise FeedError("Parser restarted") from exc

    async def _fetch(self, state: SourceState) -> tuple[bytes, str, str | None, str | None] | None:
        headers = {}
        if state.etag:
            headers["If-None-Match"] = state.etag
        if state.last_modified:
            headers["If-Modified-Since"] = state.last_modified
        client = await self._client()
        async with client.stream("GET", state.source.url, headers=headers) as response:
            if response.url.scheme != "https":
                raise FeedError("Insecure redirect refused")
            if response.status_code == 304:
                return None
            if response.status_code != 200:
                raise FeedError(f"HTTP {response.status_code}")
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
                raise FeedError("Response too large")
            chunks, total = [], 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > MAX_BODY_BYTES:
                    raise FeedError("Response too large")
                chunks.append(chunk)
            return (
                b"".join(chunks),
                str(response.url),
                _header(response.headers.get("etag")),
                _header(response.headers.get("last-modified")),
            )

    async def _refresh(self, state: SourceState) -> None:
        async with self.semaphore:
            state.last_attempt = utc_now()
            try:
                async with asyncio.timeout(SOURCE_TIMEOUT_SECONDS):
                    fetched = await self._fetch(state)
                if fetched is not None:
                    body, final_url, etag, modified = fetched
                    items = await self._parse(body, state.source.name, final_url)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                state.failures += 1
                delay = min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * 2 ** (state.failures - 1))
                state.retry_at = self.clock() + delay
                state.status = "error"
                state.error = _describe(exc)
                logger.warning("News source %s failed: %s", state.source.name, state.error)
                return
            if fetched is not None:
                state.items = tuple(items)
                state.etag, state.last_modified = etag, modified
            state.failures = 0
            state.retry_at = 0.0
            state.status = "ok"
            state.error = None
            state.last_success = utc_now()

    def _rebuild(self) -> None:
        merged: dict[str, NewsItem] = {}
        for state in self.sources:
            for item in state.items:
                current = merged.get(item.id)
                if current is None or item.published_at < current.published_at:
                    merged[item.id] = item
        ordered = sorted(merged.values(), key=lambda i: (i.published_at, i.id), reverse=True)
        self.items = tuple(ordered[:MAX_ITEMS])  # atomic swap; readers never see partial data
        self.updated_at = utc_now()

    async def poll_once(self) -> None:
        now = self.clock()
        due = [state for state in self.sources if state.retry_at <= now]
        if due:
            await asyncio.gather(*(self._refresh(state) for state in due))
        self._rebuild()

    async def run(self) -> None:
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("News poll failed")
            await asyncio.sleep(self.poll_seconds)

    def query(
        self,
        source: str | None = None,
        q: str | None = None,
        symbol: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        if source is not None and source not in self.source_names:
            raise EngineError("unsupported_news_filter", "Unknown news source", 422)
        if symbol is not None and symbol not in self.symbols:
            raise EngineError("unsupported_news_filter", "Unknown market symbol", 422)
        items: Iterable[NewsItem] = self.items
        if source is not None:
            items = (i for i in items if i.source == source)
        if symbol is not None:
            base = base_asset(symbol)
            items = (i for i in items if base in i.symbols)
        terms = clean_text(q or "").casefold().split()[:10]
        if terms:
            items = (i for i in items if all(t in i.search_text for t in terms))
        matched = list(items)
        return {
            "enabled": True,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "total": len(matched),
            "items": [item.to_dict() for item in matched[offset : offset + limit]],
            "sources": [state.to_dict() for state in self.sources],
        }

    async def close(self) -> None:
        try:
            if self.client is not None:
                client, self.client = self.client, None
                await asyncio.wait_for(client.aclose(), timeout=5)
        finally:
            if self.executor is not None:
                executor, self.executor = self.executor, None
                await asyncio.to_thread(_stop_executor, executor)
