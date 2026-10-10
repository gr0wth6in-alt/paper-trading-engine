import { useEffect, useRef, useState } from 'react';
import { Pause, Play, Robot, WarningCircle, X } from '../icons';
import { api, message } from '../api';
import { number, pair } from '../format';
import type { AgentLimits, AgentState, CloseAllResult } from '../types';

type Confirm = 'resume' | 'close-all' | null;

export function cooldownLabel(seconds: number): string {
  const total = Math.max(0, Math.ceil(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

export function hermesStatus(agent: AgentState): { label: string; tone: 'muted' | 'warning-text' | 'negative' | 'positive' } {
  if (!agent.enabled) return { label: 'Disabled', tone: 'muted' };
  if (agent.paused) return { label: 'Paused', tone: 'warning-text' };
  if (agent.breaker_tripped) return { label: 'Breaker tripped', tone: 'negative' };
  if ((agent.cooldown_remaining_seconds ?? 0) > 0) return { label: `Cooldown ${cooldownLabel(agent.cooldown_remaining_seconds ?? 0)}`, tone: 'warning-text' };
  return { label: 'Active', tone: 'positive' };
}

function useModal(open: boolean) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) { if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open', ''); }
    if (!open && dialog.open) { if (typeof dialog.close === 'function') dialog.close(); else dialog.removeAttribute('open'); }
  }, [open]);
  return ref;
}

/** Operator controls for the autonomous Hermes agent. Limits are enforced by the engine. */
export function HermesBar({ token, agent, limits, refresh, onToast }: {
  token: string; agent: AgentState; limits: AgentLimits; refresh: () => Promise<void>; onToast: (text: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [failures, setFailures] = useState<CloseAllResult['failed']>([]);
  const dialog = useModal(confirm !== null);
  const status = hermesStatus(agent);
  const riskPct = number(Number(limits.max_risk_per_trade_pct) * 100, 1);
  const lossPct = number(Number(limits.daily_loss_pct) * 100, 1);

  async function act(path: 'pause' | 'resume' | 'close-all') {
    if (busy) return;
    setBusy(true); setError('');
    try {
      if (path === 'close-all') {
        const result = await api<CloseAllResult>(token, '/agent/close-all', { method: 'POST' });
        setFailures(result.failed);
        onToast(`Closed ${result.closed.length} Hermes position${result.closed.length === 1 ? '' : 's'}${result.failed.length ? ` · ${result.failed.length} could not close` : ''}`);
        if (!result.failed.length) setConfirm(null);
      } else {
        await api<AgentState>(token, `/agent/${path}`, { method: 'POST' });
        onToast(path === 'pause' ? 'Hermes paused. New entries are blocked; stops keep running.' : 'Hermes resumed. Engine limits stay in force.');
        setConfirm(null);
      }
      await refresh();
    } catch (err) { setError(message(err)); }
    finally { setBusy(false); }
  }
  function dismiss() { if (busy) return; setConfirm(null); setFailures([]); setError(''); }

  return <section className="hermes-bar" aria-labelledby="hermes-heading">
    <div className="hermes-identity"><Robot size={18} aria-hidden="true" /><div><h2 id="hermes-heading">Hermes agent</h2><span className={`hermes-status ${status.tone}`} role="status">{status.label}</span></div></div>
    <dl className="hermes-stats">
      <div><dt>Today's loss</dt><dd className="mono">{agent.daily_loss != null ? number(agent.daily_loss) : '—'} <small>/ {number(agent.daily_loss_limit)} USDT</small></dd></div>
      <div><dt>Risk per trade</dt><dd className="mono">≤ {number(agent.max_risk_per_trade_usdt)} <small>USDT · {riskPct}%</small></dd></div>
      <div><dt>Open positions</dt><dd className="mono">{agent.open_positions ?? 0} <small>/ {limits.max_open_positions}</small></dd></div>
      <div><dt>Entry interval</dt><dd className="mono">{Math.round(limits.min_open_interval_seconds / 60)} <small>min</small></dd></div>
    </dl>
    <div className="hermes-actions">
      {agent.paused
        ? <button className="button compact primary" disabled={busy} onClick={() => { setError(''); setConfirm('resume'); }}><Play size={14} aria-hidden="true" /> Resume Hermes</button>
        : <button className="button compact primary" disabled={busy} onClick={() => void act('pause')}><Pause size={14} aria-hidden="true" /> Pause Hermes</button>}
      <button className="button compact secondary" disabled={busy || !agent.open_positions} onClick={() => { setError(''); setFailures([]); setConfirm('close-all'); }}>Close all Hermes positions</button>
    </div>
    {agent.paused && agent.pause_reason && <p className="hermes-note small-note muted">{agent.pause_reason}</p>}
    {agent.breaker_tripped && <p className="hermes-note small-note negative"><WarningCircle size={13} aria-hidden="true" /> Daily loss limit reached. New entries resume {agent.breaker_resets_at ? `at ${new Date(agent.breaker_resets_at).toUTCString().slice(17, 22)} UTC` : 'tomorrow (UTC)'}.</p>}
    {error && !confirm && <p className="hermes-note small-note negative" role="alert">{error}</p>}
    <dialog ref={dialog} className="modal" aria-labelledby="hermes-confirm-title" onCancel={e => { e.preventDefault(); dismiss(); }}>
      {confirm && <>
        <div className="section-heading"><h2 id="hermes-confirm-title">{confirm === 'resume' ? 'Resume Hermes?' : 'Close all Hermes positions?'}</h2><button className="icon-button" aria-label="Cancel" disabled={busy} onClick={dismiss}><X size={19} /></button></div>
        {confirm === 'resume' ? <>
          <p>Hermes may open paper positions on its own. The engine enforces these limits whatever the agent asks:</p>
          <dl className="detail-list">
            <div><dt>Entries</dt><dd>1 per {Math.round(limits.min_open_interval_seconds / 60)} min</dd></div>
            <div><dt>Daily loss breaker</dt><dd>{lossPct}% of start-of-day wallet</dd></div>
            <div><dt>Risk at stop-loss</dt><dd>≤ {riskPct}% of wallet</dd></div>
            <div><dt>Stop-loss</dt><dd>Required on every entry</dd></div>
            <div><dt>Open positions / leverage</dt><dd>{limits.max_open_positions} / {limits.max_leverage}×</dd></div>
          </dl>
        </> : <>
          <p>Every open Hermes position closes at available depth plus simulated slippage. Your manual positions are not affected.</p>
          {failures.length > 0 && <ul className="hermes-failures small-note" aria-label="Positions that could not close">{failures.map(f => <li key={f.id}>{pair(f.symbol)}: {f.message}</li>)}</ul>}
        </>}
        {error && <p role="alert" className="form-error">{error}</p>}
        <div className="modal-actions"><button className="button secondary" disabled={busy} onClick={dismiss}>Cancel</button><button className="button primary" disabled={busy} onClick={() => void act(confirm === 'resume' ? 'resume' : 'close-all')}>{busy ? 'Working…' : confirm === 'resume' ? 'Resume Hermes' : failures.length ? 'Retry close all' : 'Close all Hermes positions'}</button></div>
      </>}
    </dialog>
  </section>;
}
