import { useEffect, useState } from 'react';
import { ArrowClockwise, ArrowUpRight, MagnifyingGlass, Newspaper, WarningCircle } from '../icons';
import { ApiError, api, message } from '../api';
import { date, pair, timeAgo } from '../format';
import { newsQuery, safeHref } from '../news';
import type { NewsItem, NewsResponse } from '../types';

const PAGE = 20;
const REFRESH_MS = 60000;

/** Renders feed text strictly as React text nodes; raw HTML injection is banned (see test). */
export function NewsArticle({ item, now, compact = false }: { item: NewsItem; now: number; compact?: boolean }) {
  const href = safeHref(item.url);
  const title = <>{item.title}{href && <><ArrowUpRight size={13} aria-hidden="true" className="news-external" /><span className="sr-only"> (opens original article in a new tab)</span></>}</>;
  const Heading = compact ? 'h3' : 'h2';
  return <article className={compact ? 'news-item compact' : 'news-item'}>
    <div className="news-meta">
      <span className="news-source">{item.source}</span><span aria-hidden="true">·</span>
      <time dateTime={item.published_at} title={date(item.published_at)}>{timeAgo(item.published_at, now)}</time>
      {item.symbols.length > 0 && <span className="news-tags" aria-label="Mentioned markets">{item.symbols.map(s => <span key={s} className="news-tag">{s}</span>)}</span>}
    </div>
    <Heading className="news-title">{href ? <a href={href} target="_blank" rel="noopener noreferrer">{title}</a> : title}</Heading>
    {!compact && item.summary && <p className="news-summary">{item.summary}</p>}
  </article>;
}

export function NewsDisabled() {
  return <div className="empty-state tall"><Newspaper size={32} weight="light" /><h3>News feed is turned off</h3><p>Set <code>PAPER_NEWS_ENABLED=true</code> in <code>.env</code> and restart <code>start.cmd</code> to aggregate public crypto RSS headlines.</p></div>;
}

export function News({ token, enabled, symbol, related, onRelatedChange }: {
  token: string; enabled: boolean; symbol: string; related: boolean; onRelatedChange: (related: boolean) => void;
}) {
  const [source, setSource] = useState('');
  const [search, setSearch] = useState('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState({ key: '', offset: 0 });
  const [data, setData] = useState<NewsResponse | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState('');
  const [refreshError, setRefreshError] = useState('');
  const [disabled, setDisabled] = useState(!enabled);
  const [retry, setRetry] = useState(0);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => { const timer = window.setTimeout(() => setQ(search.trim()), 300); return () => clearTimeout(timer); }, [search]);
  // Any filter change returns to the first page without an extra request for the old offset.
  const filterKey = `${source}\n${q}\n${related ? symbol : ''}`;
  const offset = page.key === filterKey ? page.offset : 0;
  const setOffset = (value: number) => setPage({ key: filterKey, offset: value });

  const path = newsQuery({ source: source || undefined, q, symbol: related ? symbol : undefined, limit: PAGE, offset });
  useEffect(() => {
    if (disabled) return;
    const controller = new AbortController(); let disposed = false; let timer: number | undefined;
    const load = (silent: boolean) => {
      if (!silent) { setLoading(true); setError(''); }
      void api<NewsResponse>(token, path, { signal: controller.signal })
        .then(result => { if (disposed) return; setData(result); setError(''); setRefreshError(''); setNow(Date.now()); })
        .catch(err => {
          if (disposed) return;
          if (err instanceof ApiError && err.code === 'news_disabled') { setDisabled(true); return; }
          if (silent) setRefreshError(message(err)); else setError(message(err));
        })
        .finally(() => { if (disposed) return; setLoading(false); timer = window.setTimeout(() => load(true), REFRESH_MS); });
    };
    load(false);
    return () => { disposed = true; controller.abort(); clearTimeout(timer); };
  }, [token, path, disabled, retry]);

  const failing = data?.sources.filter(s => s.status === 'error') ?? [];
  const pending = !!data && data.items.length === 0 && data.sources.some(s => s.status === 'pending');
  const filtered = !!(source || q || related);
  const rows = data?.items ?? [];

  return <section className="history-view news-view" aria-labelledby="news-heading">
    <div className="view-heading"><div><span className="eyebrow">MARKET CONTEXT</span><h1 id="news-heading">Crypto news</h1><p>Public RSS headlines from {data ? data.sources.length : 'several'} publishers, newest first. Links open the original article.</p></div><button className="button secondary" disabled={loading || disabled} onClick={() => setRetry(v => v + 1)}><ArrowClockwise size={16} /> Refresh</button></div>
    {disabled ? <NewsDisabled /> : <>
      <div className="news-filters" role="search" aria-label="Filter news">
        <div className="news-filter"><label htmlFor="news-source">Source</label><select id="news-source" value={source} onChange={e => setSource(e.target.value)}><option value="">All sources</option>{data?.sources.map(s => <option key={s.name} value={s.name}>{s.name}</option>)}</select></div>
        <div className="news-filter grow"><label htmlFor="news-search">Search headlines</label><div className="news-search"><MagnifyingGlass size={15} aria-hidden="true" /><input id="news-search" type="search" value={search} maxLength={100} placeholder="e.g. ETF, upgrade, liquidation" autoComplete="off" onChange={e => setSearch(e.target.value)} /></div></div>
        <label className="checkbox-label news-related"><input type="checkbox" checked={related} onChange={e => onRelatedChange(e.target.checked)} />Related to {pair(symbol)}</label>
      </div>
      <div className="news-status small-note" role="status">
        {data?.updated_at && <span className="muted">Updated {timeAgo(data.updated_at, now)} · refreshes every minute</span>}
        {failing.length > 0 && <span className="warning-text"><WarningCircle size={13} aria-hidden="true" /> Unavailable: {failing.map(s => `${s.name}${s.error ? ` (${s.error})` : ''}`).join(', ')}</span>}
        {refreshError && <span className="warning-text">Showing last loaded headlines. {refreshError}</span>}
      </div>
      {loading && !data ? <div className="empty-state" role="status">Loading headlines…</div>
        : error ? <div className="error-panel" role="alert"><h3>Could not load news</h3><p>{error}</p><button className="button secondary" onClick={() => setRetry(v => v + 1)}>Retry</button></div>
        : pending ? <div className="empty-state tall" role="status"><Newspaper size={32} weight="light" /><h3>Fetching first headlines</h3><p>The backend is contacting {data?.sources.length} publishers. This usually takes a few seconds after start.</p></div>
        : rows.length === 0 ? <div className="empty-state tall"><Newspaper size={32} weight="light" /><h3>{offset ? 'No more headlines' : filtered ? 'No headlines match these filters' : 'No headlines available'}</h3><p>{offset ? 'Return to the previous page.' : filtered ? 'Clear the search or choose another source.' : 'All sources are currently unavailable. They are retried automatically.'}</p></div>
        : <div className="news-list" aria-busy={loading}>{rows.map(item => <NewsArticle key={item.id} item={item} now={now} />)}</div>}
      <div className="pagination"><span className="muted small-note">{rows.length && !error ? `Headlines ${offset + 1}–${offset + rows.length} of ${data?.total}` : `${PAGE} headlines per page`}</span><div className="flex gap-2"><button className="button secondary" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button><button className="button secondary" disabled={!data || offset + PAGE >= data.total || loading || !!error} onClick={() => setOffset(offset + PAGE)}>Next</button></div></div>
    </>}
  </section>;
}
