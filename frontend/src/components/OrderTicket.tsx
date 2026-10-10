import { useEffect, useState } from 'react';
import Decimal from 'decimal.js';
import { Info, LockKey, ArrowUpRight, ArrowDownRight } from '../icons';
import { api, message, uncertain } from '../api';
import { baseAsset, number, pair, preview, price } from '../format';
import type { Config, Market, Order, Position, Side, Snapshot } from '../types';

interface Props { token: string; symbol: string; config: Config; snapshot: Snapshot; market?: Market; tradable: boolean; onSuccess: (text: string) => void; onEntry: (position: Position) => void; splashEnabled?: boolean; onSplashChange?: (enabled: boolean) => void; refresh: () => Promise<void>; onWorkflow: (locked: boolean) => void }
interface Pending { key: string; body: Order }

export function OrderTicket({ token, symbol, config, snapshot, market, tradable, onSuccess, onEntry, splashEnabled = true, onSplashChange, refresh, onWorkflow }: Props) {
  const [side, setSide] = useState<Side>('long');
  const [allocation, setAllocation] = useState(new Decimal(config.default_allocation_pct).mul(100).toString());
  const [leverage, setLeverage] = useState(config.default_leverage);
  const [stop, setStop] = useState('');
  const [target, setTarget] = useState('');
  const [strategy, setStrategy] = useState('');
  const [notes, setNotes] = useState('');
  const [review, setReview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [pending, setPending] = useState<Pending | null>(null);
  const validAllocation = allocation !== '' && Number(allocation) >= 2 && Number(allocation) <= 5;
  const estimate = preview(snapshot.account.wallet_balance, validAllocation ? allocation : '0', leverage, side, market, config);
  const affordable = estimate.margin.plus(estimate.fee).lte(snapshot.account.available_balance);
  const locked = busy || pending !== null;
  useEffect(() => { onWorkflow(locked || review); return () => onWorkflow(false); }, [locked, review, onWorkflow]);
  useEffect(() => {
    if (!pending) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [pending]);

  function validate() {
    if (!validAllocation) return 'Allocate between 2% and 5% as isolated margin.';
    if (!Number.isInteger(leverage) || leverage < 1 || leverage > config.max_leverage) return `Leverage must be between 1× and ${config.max_leverage}×.`;
    if (!tradable) return 'A fresh execution quote is required before placing a paper order.';
    if (!affordable) return 'Available balance cannot cover estimated margin and entry fee.';
    if (stop && (!Number.isFinite(Number(stop)) || Number(stop) <= 0)) return 'Stop loss must be a positive price.';
    if (target && (!Number.isFinite(Number(target)) || Number(target) <= 0)) return 'Take profit must be a positive price.';
    const bid = new Decimal(market!.bid!), ask = new Decimal(market!.ask!);
    if (stop && (side === 'long' ? new Decimal(stop).gte(bid) : new Decimal(stop).lte(ask))) return `Stop loss must be ${side === 'long' ? 'below the bid' : 'above the ask'}.`;
    if (target && (side === 'long' ? new Decimal(target).lte(ask) : new Decimal(target).gte(bid))) return `Take profit must be ${side === 'long' ? 'above the ask' : 'below the bid'}.`;
    return '';
  }
  async function submit() {
    if (busy || !tradable) return;
    const problem = pending ? '' : validate();
    if (problem) { setError(problem); return; }
    const request = pending ?? { key: crypto.randomUUID(), body: {
      symbol, side, allocation_pct: new Decimal(allocation).div(100).toString(), leverage,
      ...(stop ? { stop_loss: stop } : {}), ...(target ? { take_profit: target } : {}),
      ...(strategy.trim() ? { strategy: strategy.trim() } : {}), ...(notes.trim() ? { notes: notes.trim() } : {}),
    } };
    setPending(request); setBusy(true); setError('');
    try {
      const position = await api<Position>(token, '/orders', { method: 'POST', headers: { 'Idempotency-Key': request.key }, body: JSON.stringify(request.body) });
      setPending(null); setReview(false);
      onSuccess(`Paper ${position.side} filled · ${number(position.quantity, 6)} ${baseAsset(position.symbol)} at ${price(position.entry_price)} USDT`);
      onEntry(position);
      await refresh();
    } catch (err) {
      setError(message(err) + (uncertain(err) ? ' Outcome is unconfirmed. Retry the same request to avoid a duplicate position.' : ''));
      if (!uncertain(err)) setPending(null);
    } finally { setBusy(false); }
  }

  return <aside className="order-ticket" aria-labelledby="order-heading">
    <div className="section-heading"><h2 id="order-heading">Place an order</h2><span className="small-label">PAPER</span></div>
    <div className="ticket-mode"><span><LockKey size={13} /> Isolated margin</span><span>Market order</span></div>
    <form onSubmit={event => { event.preventDefault(); const problem = validate(); setError(problem); if (!problem) setReview(true); }}>
      <fieldset disabled={locked || review}>
        <legend className="sr-only">Paper order details</legend>
        <div className="side-control">
          <button type="button" aria-pressed={side === 'long'} className={side === 'long' ? 'long active' : 'long'} onClick={() => { setSide('long'); setError(''); }}><ArrowUpRight size={17} /> Long / Buy</button>
          <button type="button" aria-pressed={side === 'short'} className={side === 'short' ? 'short active' : 'short'} onClick={() => { setSide('short'); setError(''); }}><ArrowDownRight size={17} /> Short / Sell</button>
        </div>
        <div className="form-row label-row"><label htmlFor="allocation">Margin allocation</label><span>2 to 5% of wallet</span></div>
        <div className="input-suffix"><input id="allocation" type="number" min="2" max="5" step="0.1" value={allocation} onChange={e => setAllocation(e.target.value)} required /><span>%</span></div>
        <div className="allocation-presets">{['2', '3', '4', '5'].map(value => <button key={value} type="button" onClick={() => setAllocation(value)} aria-pressed={allocation === value} className={allocation === value ? 'selected' : ''}>{value}%</button>)}</div>
        <div className="form-row label-row"><label htmlFor="leverage">Leverage</label><span className="mono">{leverage}×</span></div>
        <input className="leverage-range" id="leverage" type="range" min="1" max={config.max_leverage} step="1" value={leverage} onChange={e => setLeverage(Number(e.target.value))} />
        <div className="range-labels mono"><span>1×</span><span>{config.default_leverage}× default</span><span>{config.max_leverage}×</span></div>
        <div className="bracket-fields">
          <label htmlFor="stop">Stop loss <span>optional</span><input id="stop" type="number" min="0" step="any" placeholder="Price in USDT" value={stop} onChange={e => setStop(e.target.value)} /></label>
          <label htmlFor="target">Take profit <span>optional</span><input id="target" type="number" min="0" step="any" placeholder="Price in USDT" value={target} onChange={e => setTarget(e.target.value)} /></label>
        </div>
        <details className="notes-fields"><summary>Strategy & trade notes</summary>
          <label htmlFor="strategy">Strategy<input id="strategy" maxLength={120} value={strategy} onChange={e => setStrategy(e.target.value)} placeholder="Optional strategy name" /></label>
          <label htmlFor="notes">Entry rationale<textarea id="notes" maxLength={2000} rows={3} value={notes} onChange={e => setNotes(e.target.value)} placeholder="What is your plan for this trade?" /></label>
        </details>
      </fieldset>
      <div className="estimate">
        <div className="estimate-title">ORDER ESTIMATE <span>USDT</span></div>
        <dl>
          <div><dt>Isolated margin</dt><dd>{number(estimate.margin.toString())}</dd></div>
          <div><dt>Notional value</dt><dd>{number(estimate.notional.toString())}</dd></div>
          <div><dt>Quantity <span>({baseAsset(symbol)})</span></dt><dd>{tradable ? number(estimate.quantity?.toString(), 6) : '—'}</dd></div>
          <div><dt>Entry fee <span>({number(new Decimal(config.taker_fee_rate).mul(100).toString(), 3)}%)</span></dt><dd>{number(estimate.fee.toString())}</dd></div>
        </dl>
        <p>Final size is rounded to market precision. Depth and slippage affect the fill.</p>
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
      {review ? <div className="review-order" role="group" aria-label="Confirm paper order">
        <h3>Confirm {side} · {pair(symbol)}</h3>
        <p>{leverage}× isolated · {allocation}% margin allocation. Paper funds only.</p>
        <button type="button" className="button primary full" disabled={busy || !tradable} onClick={() => void submit()}>{busy ? 'Submitting paper order…' : pending ? 'Retry same paper order' : `Confirm paper ${side}`}</button>
        {!pending && <button type="button" className="button text-button full" disabled={busy} onClick={() => { setReview(false); setError(''); }}>Back to order</button>}
        {pending && <p className="small-note">Request {pending.key.slice(0, 8)} · do not reload while the result is unconfirmed.</p>}
      </div> : <button className="button primary full" disabled={!tradable || !validAllocation || !affordable} type="submit">Review paper {side} <span>{leverage}×</span></button>}
      {!tradable && <p className="disabled-reason">Trading paused · waiting for a fresh execution quote.</p>}
      {tradable && !affordable && <p className="disabled-reason">Insufficient available margin, including the entry fee.</p>}
    </form>
    <label className="checkbox-label splash-setting"><input type="checkbox" checked={splashEnabled} onChange={e => onSplashChange?.(e.target.checked)} />Entry splash</label>
    <div className="risk-note"><Info size={16} /><p>Allocation is margin, not stop-loss risk. At 10×, a 1% adverse move costs about 10% of posted margin, before fees.</p></div>
  </aside>;
}