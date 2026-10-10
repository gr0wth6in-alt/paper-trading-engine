import { useEffect, useState } from 'react';
import { ArrowClockwise, BookOpenText, CheckCircle, ClockCounterClockwise } from '../icons';
import { api, message } from '../api';
import { date, number, pair, pnl, tone, price } from '../format';
import type { Journal, Position } from '../types';

export function History({ token, kind, onShare }: { token: string; kind: 'trades' | 'journals'; onShare: (position: Position) => void }) {
  const [rows, setRows] = useState<(Position | Journal)[]>([]);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); let disposed = false;
    setLoading(true); setError('');
    void api<(Position | Journal)[]>(token, `/${kind}?limit=20&offset=${offset}`, { signal: controller.signal })
      .then(data => { if (!disposed) setRows(data); })
      .catch(err => { if (!disposed) setError(message(err)); })
      .finally(() => { if (!disposed) setLoading(false); });
    return () => { disposed = true; controller.abort(); };
  }, [token, kind, offset, retry]);
  return <section className="history-view" aria-labelledby="history-heading">
    <div className="view-heading"><div><span className="eyebrow">{kind === 'trades' ? 'EXECUTION RECORD' : 'TRADE REVIEW'}</span><h1 id="history-heading">{kind === 'trades' ? 'Trade history' : 'Trading journal'}</h1><p>{kind === 'trades' ? 'Closed paper positions. Fees and execution details included.' : 'Every closed trade has a local summary, including Hermes entry and exit reasons.'}</p></div><button className="button secondary" disabled={loading} onClick={() => setRetry(v => v + 1)}><ArrowClockwise size={16} /> Refresh</button></div>
    {kind === 'journals' && <div className="journal-status"><CheckCircle size={18} className="positive" /><span>Local summaries active</span><span className="divider-text">/</span><span className="muted">AI review of journals deferred</span></div>}
    {loading ? <div className="empty-state" role="status">Loading {kind === 'trades' ? 'closed positions' : 'trade summaries'}…</div> : error ? <div className="error-panel" role="alert"><h3>Could not load {kind === 'trades' ? 'trade history' : 'journals'}</h3><p>{error}</p><button className="button secondary" onClick={() => setRetry(v => v + 1)}>Retry</button></div> : rows.length === 0 ? <div className="empty-state tall">{kind === 'trades' ? <ClockCounterClockwise size={32} weight="light" /> : <BookOpenText size={32} weight="light" />}<h3>{offset ? 'No more records' : kind === 'trades' ? 'No closed trades yet' : 'Your first review starts with a closed trade'}</h3><p>{offset ? 'Return to the previous page to see earlier records.' : 'Open and close a paper position in the terminal. Its execution record will appear here.'}</p></div> : kind === 'trades' ? <div className="table-scroll history-table"><table><thead><tr><th>Market / Side</th><th>Closed</th><th className="numeric">Entry / Exit</th><th className="numeric">Size</th><th className="numeric">Net PnL</th><th>Exit reason</th></tr></thead><tbody>{(rows as Position[]).map(trade => <tr key={trade.id}>
      <td><strong>{pair(trade.symbol)}</strong>{trade.actor === 'agent' && <span className="actor-badge" title="Opened by the Hermes agent">HERMES</span>}<div className={`cell-sub ${trade.side === 'long' ? 'positive' : 'negative'}`}>{trade.side.toUpperCase()} · {trade.leverage}×</div></td><td>{date(trade.closed_at)}<div className="cell-sub">{trade.strategy || 'Manual / unspecified'}</div></td><td className="numeric mono">{price(trade.entry_price)}<div className="cell-sub">{price(trade.exit_price)}</div></td><td className="numeric mono">{number(trade.quantity, 6)}</td><td className={`numeric mono ${tone(trade.net_pnl)}`}>{pnl(trade.net_pnl)}<div className="cell-sub">USDT · after fees</div></td><td><span className="reason">{trade.exit_reason?.replaceAll('_', ' ')}</span><button className="button compact secondary" aria-label={`Share ${pair(trade.symbol)} PnL card`} disabled={trade.net_pnl == null} onClick={() => onShare(trade)}>Share</button></td>
    </tr>)}</tbody></table></div> : <div className="journal-list">{(rows as Journal[]).map(journal => <details key={journal.trade_id} className="journal-entry">
      <summary><BookOpenText size={20} /><span className="journal-entry-title"><strong>{pair(journal.metrics.trade.symbol)} <span className="muted">/ {journal.metrics.trade.side.toUpperCase()}</span>{(journal.metrics.actor ?? journal.metrics.trade.actor) === 'agent' && <span className="actor-badge">HERMES</span>}</strong><span>{date(journal.created_at)} · {journal.metrics.trade.exit_reason?.replaceAll('_', ' ')}</span></span><span className={`mono journal-pnl ${tone(journal.metrics.trade.net_pnl)}`}>{pnl(journal.metrics.trade.net_pnl)} <small>USDT</small></span><span className="journal-expand">Details</span></summary>
      <div className="journal-body"><p>{journal.local_summary}</p><dl className="journal-metrics"><div><dt>Total fees</dt><dd>{number(journal.metrics.total_fees_usdt)} USDT</dd></div><div><dt>Return on margin</dt><dd>{number(journal.metrics.return_on_margin_pct)}%</dd></div><div><dt>Duration</dt><dd>{number(Number(journal.metrics.duration_seconds) / 60, 1)} min</dd></div><div><dt>Entry / exit slippage</dt><dd>{number(journal.metrics.entry_slippage_bps)} / {number(journal.metrics.exit_slippage_bps)} bps</dd></div></dl>
      {(journal.metrics.entry_rationale ?? journal.metrics.trade.notes) && <div className="recorded-notes"><h3>{(journal.metrics.actor ?? journal.metrics.trade.actor) === 'agent' ? 'Hermes entry rationale' : 'Recorded entry rationale'}</h3><p>{journal.metrics.entry_rationale ?? journal.metrics.trade.notes}</p></div>}
      {(journal.metrics.exit_rationale ?? journal.metrics.trade.exit_notes) && <div className="recorded-notes"><h3>Exit rationale</h3><p>{journal.metrics.exit_rationale ?? journal.metrics.trade.exit_notes}</p></div>}
      <p className="small-note muted">AI review: pending integration. No psychological assessment has been generated.</p><ul className="small-note muted">{journal.metrics.limitations.map(text => <li key={text}>{text}</li>)}</ul></div>
    </details>)}</div>}
    <div className="pagination"><span className="muted small-note">{rows.length && !loading && !error ? `Records ${offset + 1}–${offset + rows.length}` : '20 records per page'}</span><div className="flex gap-2"><button className="button secondary" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous</button><button className="button secondary" disabled={rows.length < 20 || loading || !!error} onClick={() => setOffset(offset + 20)}>Next</button></div></div>
  </section>;
}