import { useEffect, useRef, useState } from 'react';
import { Stack, X } from '../icons';
import { api, message, uncertain } from '../api';
import { date, number, pair, pnl, tone, price } from '../format';
import type { Position, Snapshot } from '../types';

interface Props { token: string; snapshot: Snapshot; fresh: (symbol: string) => boolean; refresh: () => Promise<void>; onSuccess: (text: string) => void; onClosed: (position: Position) => void; onShare: (position: Position) => void; onWorkflow: (locked: boolean) => void }
export function Positions({ token, snapshot, fresh, refresh, onSuccess, onClosed, onShare, onWorkflow }: Props) {
  const [selected, setSelected] = useState<Position | null>(null);
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [unconfirmed, setUnconfirmed] = useState(false);
  const [error, setError] = useState('');
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { onWorkflow(busy || unconfirmed); return () => onWorkflow(false); }, [busy, unconfirmed, onWorkflow]);
  useEffect(() => {
    if (!unconfirmed && !busy) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [unconfirmed, busy]);
  useEffect(() => { if (selected && !dialog.current?.open) dialog.current?.showModal(); }, [selected]);
  function dismiss() { if (busy || unconfirmed) return; dialog.current?.close(); setSelected(null); setError(''); }
  async function close() {
    if (!selected || busy || !fresh(selected.symbol)) return;
    setBusy(true); setError('');
    try {
      const result = await api<Position>(token, `/positions/${selected.id}/close`, { method: 'POST', headers: { 'Idempotency-Key': key } });
      setUnconfirmed(false); dialog.current?.close(); setSelected(null);
      onSuccess(`Position closed · ${pair(result.symbol)} · net PnL ${pnl(result.net_pnl)} USDT`);
      onClosed(result);
      await refresh();
    } catch (err) {
      const unknown = uncertain(err); setUnconfirmed(unknown);
      setError(message(err) + (unknown ? ' Outcome unconfirmed. Retry with the same request key.' : ''));
      await refresh();
    } finally { setBusy(false); }
  }
  return <section className="positions-section" aria-labelledby="positions-heading">
    <div className="section-heading"><div className="flex items-center gap-2"><h2 id="positions-heading">Open positions</h2><span className="count">{snapshot.positions.length}</span></div><span className="muted small-note">PnL before exit fees</span></div>
    {!snapshot.positions.length ? <div className="empty-state positions-empty"><Stack size={27} weight="light" /><div><h3>No open positions</h3><p>Your positions will appear here after a paper order fills.</p></div></div> : <div className="table-scroll" role="region" aria-label="Open position details" tabIndex={0}><table className="positions-table">
      <thead><tr><th>Market / Side</th><th className="numeric">Size</th><th className="numeric">Entry / Mark</th><th className="numeric">Margin</th><th className="numeric">Unrealized PnL</th><th className="numeric">SL / TP</th><th><span className="sr-only">Action</span></th></tr></thead>
      <tbody>{snapshot.positions.map(p => <tr key={p.id}>
        <td><strong>{pair(p.symbol)}</strong>{p.actor === 'agent' && <span className="actor-badge" title="Opened by the Hermes agent">HERMES</span>}<div className="cell-sub"><span className={p.side === 'long' ? 'positive' : 'negative'}>{p.side.toUpperCase()}</span> {p.leverage}× · Isolated</div>{p.pending_exit_reason && <div className="warning-text small-note">Exit pending: {p.pending_exit_reason.replaceAll('_', ' ')}</div>}</td>
        <td className="numeric mono">{number(p.quantity, 6)}</td>
        <td className="numeric mono">{price(p.entry_price)}<div className="cell-sub">{fresh(p.symbol) ? price(p.mark_price) : 'Quote stale'}</div></td>
        <td className="numeric mono">{number(p.margin)}<div className="cell-sub">USDT</div></td>
        <td className={`numeric mono ${tone(fresh(p.symbol) ? p.unrealized_pnl : null)}`}>{fresh(p.symbol) ? pnl(p.unrealized_pnl) : '—'}<div className="cell-sub">{fresh(p.symbol) ? 'USDT' : 'Valuation paused'}</div></td>
        <td className="numeric mono">{price(p.stop_loss)}<div className="cell-sub">{price(p.take_profit)}</div></td>
        <td><div className="position-actions"><button className="button compact secondary" disabled={!fresh(p.symbol)} title={!fresh(p.symbol) ? 'A fresh quote is required to close' : 'Close entire paper position'} onClick={() => { setSelected(p); setKey(crypto.randomUUID()); setError(''); setUnconfirmed(false); }}>Close</button><button className="button compact secondary" aria-label="Share PnL card" disabled={!fresh(p.symbol) || p.quote_stale !== false || p.unrealized_pnl == null} title={!fresh(p.symbol) ? 'A fresh valuation is required to share' : 'Share a frozen paper PnL snapshot'} onClick={() => onShare(p)}>Share</button></div></td>
      </tr>)}</tbody>
    </table></div>}
    <dialog ref={dialog} className="modal" onCancel={e => { if (busy || unconfirmed) e.preventDefault(); else dismiss(); }} aria-labelledby="close-title">
      {selected && <><div className="section-heading"><h2 id="close-title">Close paper position?</h2><button className="icon-button" aria-label="Cancel close" disabled={busy || unconfirmed} onClick={dismiss}><X size={19} /></button></div>
        <p className="modal-pair">{pair(selected.symbol)} <span className={selected.side === 'long' ? 'positive' : 'negative'}>{selected.side.toUpperCase()} {selected.leverage}×</span></p>
        <dl className="detail-list"><div><dt>Quantity</dt><dd>{number(selected.quantity, 6)}</dd></div><div><dt>Entry price</dt><dd>{price(selected.entry_price)} USDT</dd></div><div><dt>Opened</dt><dd>{date(selected.opened_at)}</dd></div></dl>
        <p className="muted">The entire position will close at available depth plus simulated slippage. The final price and net PnL may differ from the current quote.</p>
        {error && <p role="alert" className="form-error">{error}</p>}
        {!fresh(selected.symbol) && <p className="warning-text">A fresh execution quote is required.</p>}
        <div className="modal-actions"><button className="button secondary" onClick={dismiss} disabled={busy || unconfirmed}>Keep position</button><button className="button primary" disabled={busy || !fresh(selected.symbol)} onClick={() => void close()}>{busy ? 'Closing…' : unconfirmed ? 'Retry same close' : 'Close paper position'}</button></div>
      </>}
    </dialog>
  </section>;
}