import { useEffect, useState } from 'react';
import { ArrowRight, Newspaper } from '../icons';
import { api, message } from '../api';
import { baseAsset } from '../format';
import { newsQuery } from '../news';
import type { NewsResponse } from '../types';
import { NewsArticle } from './News';

const REFRESH_MS = 60000;

/** Three latest headlines for the selected market, below the chart. Pauses while hidden. */
export function NewsStrip({ token, symbol, enabled, active, onViewAll }: {
  token: string; symbol: string; enabled: boolean; active: boolean; onViewAll: () => void;
}) {
  const [data, setData] = useState<{ symbol: string; response: NewsResponse } | null>(null);
  const [error, setError] = useState('');
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled || !active) return;
    const controller = new AbortController(); let disposed = false; let timer: number | undefined;
    const load = () => void api<NewsResponse>(token, newsQuery({ symbol, limit: 3, offset: 0 }), { signal: controller.signal })
      .then(response => { if (!disposed) { setData({ symbol, response }); setError(''); setNow(Date.now()); } })
      .catch(err => { if (!disposed) setError(message(err)); })
      .finally(() => { if (!disposed) timer = window.setTimeout(load, REFRESH_MS); });
    load();
    return () => { disposed = true; controller.abort(); clearTimeout(timer); };
  }, [token, symbol, enabled, active]);
  if (!enabled) return null;
  const base = baseAsset(symbol);
  const items = data?.symbol === symbol ? data.response.items : null;
  return <section className="news-strip" aria-labelledby="news-strip-heading">
    <div className="news-strip-heading"><h2 id="news-strip-heading"><Newspaper size={15} aria-hidden="true" /> Latest {base} news</h2><button className="button compact text-button" onClick={onViewAll}>View all <ArrowRight size={14} aria-hidden="true" /></button></div>
    {items === null ? <p className="news-strip-note small-note muted" role="status">{error ? `News unavailable. ${error}` : 'Loading headlines…'}</p>
      : items.length === 0 ? <p className="news-strip-note small-note muted">No recent headlines mention {base}.</p>
      : <div className="news-strip-list">{items.map(item => <NewsArticle key={item.id} item={item} now={now} compact />)}</div>}
  </section>;
}
