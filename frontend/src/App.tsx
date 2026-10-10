import { useEffect, useState } from 'react';
import Decimal from 'decimal.js';
import { ArrowRight, ArrowsClockwise, BookOpenText, ChartBar, CheckCircle, ClockCounterClockwise, Key, Newspaper, Plugs, ShieldCheck, SignOut, TerminalWindow, WarningCircle, X } from './icons';
import { api, message } from './api';
import { age, number, pair, pnl, tone, price } from './format';
import type { Config, Snapshot, Position } from './types';
import { useTerminal } from './useTerminal';
import { Chart } from './components/Chart';
import { OrderTicket } from './components/OrderTicket';
import { Positions } from './components/Positions';
import { History } from './components/History';
import { News } from './components/News';
import { NewsStrip } from './components/NewsStrip';
import { HermesBar } from './components/HermesBar';
import { ShareCard } from './components/ShareCard';
import { EntrySplash } from './components/EntrySplash';
import { pickMeme } from './memes/memes';
import { frogImage } from './memes/frogs';

type Session = { token: string; config: Config; snapshot: Snapshot };
type Page = 'terminal' | 'trades' | 'journals' | 'news';
export function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [notice, setNotice] = useState('');
  return session ? <Terminal session={session} onLogout={() => { setSession(null); setNotice(''); }} onExpired={() => { setSession(null); setNotice('Your token was rejected. Reconnect with the current local API token.'); }} /> : <Connect onConnect={setSession} notice={notice} />;
}

function Brand() { return <div className="brand"><span className="brand-mark"><ChartBar weight="bold" size={22} /></span><span>PAPER<span className="brand-light"> / TERMINAL</span></span></div>; }

function Connect({ onConnect, notice }: { onConnect: (session: Session) => void; notice: string }) {
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(notice);
  async function connect(event: React.FormEvent) {
    event.preventDefault(); if (busy) return; setBusy(true); setError('');
    try {
      const value = token.trim();
      const [config, snapshot] = await Promise.all([api<Config>(value, '/config'), api<Snapshot>(value, '/status')]);
      if (config.mode !== 'paper' || snapshot.mode !== 'paper') throw new Error('This terminal only connects to the paper engine.');
      setToken(''); onConnect({ token: value, config, snapshot });
    } catch (err) { setError(message(err)); }
    finally { setBusy(false); }
  }
  return <div className="connect-page"><header className="app-header"><Brand /><span className="paper-indicator"><ShieldCheck size={15} /> Virtual capital only</span></header>
    <main className="connect-layout" id="main">
      <section className="connect-intro"><div className="eyebrow">LOCAL PAPER ENGINE</div><h1>Paper positions, priced from public order books.</h1><p className="intro-description">Size isolated exposure, manage open positions, and review every closed trade. The engine uses no exchange keys and places no real orders.</p>
        <dl className="connect-rules" aria-label="Engine rules">
          <div><dt>Margin mode</dt><dd>Isolated only</dd></div>
          <div><dt>Allocation per trade</dt><dd className="mono">2 to 5% of wallet</dd></div>
          <div><dt>Default leverage</dt><dd className="mono">10×, set in .env</dd></div>
          <div><dt>Stale quotes</dt><dd>Orders blocked</dd></div>
        </dl>
        <div className="local-note"><TerminalWindow size={16} /><span>Run <code>start.cmd</code> on this computer and keep it open.</span></div>
      </section>
      <section className="connect-form" aria-labelledby="connect-heading"><div className="connect-icon"><Key size={24} weight="light" /></div><span className="eyebrow">LOCAL ENGINE ACCESS</span><h2 id="connect-heading">Connect your terminal</h2><p>Use the API token generated for your local paper engine.</p>
        <form onSubmit={event => void connect(event)}><label htmlFor="api-token">Local API token</label><input id="api-token" type="password" autoComplete="off" autoCapitalize="off" spellCheck={false} value={token} onChange={e => setToken(e.target.value)} placeholder="Paste PAPER_API_TOKEN" required minLength={32} disabled={busy} aria-describedby="token-hint" /><p id="token-hint" className="small-note">Find <code>PAPER_API_TOKEN</code> in the project’s <code>.env</code> file. Do not use an exchange or VPS password.</p>
          {error && <p className="form-error" role="alert">{error}</p>}
          <button type="submit" className="button primary full" disabled={busy || token.trim().length < 32}>{busy ? 'Connecting to backend…' : 'Connect to paper engine'}<ArrowRight size={17} /></button>
        </form><div className="privacy-note"><ShieldCheck size={17} /><p>The token stays in memory for this page session. It is not saved in your browser or included in URLs.</p></div><a className="docs-link" href="/docs" target="_blank" rel="noreferrer">Open API documentation</a>
      </section>
    </main><footer className="connect-footer"><span>Local-first · USDT linear perpetuals</span><span>Paper only · no exchange keys</span></footer>
  </div>;
}

function Terminal({ session, onLogout, onExpired }: { session: Session; onLogout: () => void; onExpired: () => void }) {
  const { token, config } = session;
  const { snapshot, live, socketState, elapsed, refreshError, refresh } = useTerminal(token, session.snapshot, onExpired);
  const [page, setPage] = useState<Page>('terminal');
  const [symbol, setSymbol] = useState(config.symbols[0]);
  const [newsRelated, setNewsRelated] = useState(false);
  const [toast, setToast] = useState('');
  const [orderLocked, setOrderLocked] = useState(false);
  const [closeLocked, setCloseLocked] = useState(false);
  const [share, setShare] = useState<{ position: Position; capturedAt: string } | null>(null);
  const [closedResult, setClosedResult] = useState<Position | null>(null);
  const [entry, setEntry] = useState<Position | null>(null);
  const [entryArt, setEntryArt] = useState(() => frogImage('entry', Math.floor(Math.random() * 2)));
  const [splashEnabled, setSplashEnabled] = useState(() => { try { return localStorage.getItem('paper-entry-splash') !== 'off'; } catch { return true; } });
  const sharePosition = (position: Position) => setShare({ position: { ...position }, capturedAt: new Date().toISOString() });
  function changeSplash(enabled: boolean) { setSplashEnabled(enabled); try { localStorage.setItem('paper-entry-splash', enabled ? 'on' : 'off'); } catch { /* Preference remains in memory when storage is blocked. */ } }
  useEffect(() => {
    if (!splashEnabled || entry) return;
    const controller = new AbortController();
    const preload = () => void pickMeme(token, 'entry', controller.signal, Math.floor(Math.random() * 2)).then(result => {
      if (controller.signal.aborted) return;
      const canvas = document.createElement('canvas'); canvas.width = 480; canvas.height = 480;
      const ratio = Math.min(480 / result.image.naturalWidth, 480 / result.image.naturalHeight);
      const w = result.image.naturalWidth * ratio, h = result.image.naturalHeight * ratio;
      canvas.getContext('2d')?.drawImage(result.image, (480 - w) / 2, (480 - h) / 2, w, h);
      setEntryArt(canvas.toDataURL('image/png'));
    }).catch(() => { /* Keep the last decoded drawing on network failure. */ });
    preload();
    const timer = window.setInterval(preload, 60000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [token, entry, splashEnabled]);
  const workflowLocked = orderLocked || closeLocked;
  useEffect(() => { if (!toast) return; const timer = setTimeout(() => setToast(''), 10000); return () => clearTimeout(timer); }, [toast]);
  const market = snapshot.markets[symbol];
  const fresh = (name: string) => {
    const quote = snapshot.markets[name];
    return live && !!quote && quote.status === 'connected' && !quote.stale && !!quote.bid && !!quote.ask && quote.age_ms !== null && quote.age_ms + elapsed <= config.max_quote_age_seconds * 1000;
  };
  const tradable = fresh(symbol);
  const validValuation = live && snapshot.positions.every(p => fresh(p.symbol)) && snapshot.account.valuation_complete;
  const spread = market?.ask && market.bid ? new Decimal(market.ask).minus(market.bid).toString() : null;
  const hermesFooter = !snapshot.agent?.enabled ? 'Hermes not configured' : snapshot.agent.paused ? 'Hermes paused' : 'Hermes active';
  const quoteAge = market?.age_ms != null && Number.isFinite(elapsed) ? market.age_ms + elapsed : null;
  return <div className="terminal-app"><a href="#main" className="skip-link">Skip to trading workspace</a><header className="app-header"><Brand /><nav aria-label="Main navigation">{([
    ['terminal', 'Terminal', ChartBar], ['trades', 'History', ClockCounterClockwise], ['journals', 'Journal', BookOpenText], ['news', 'News', Newspaper],
  ] as const).map(([id, label, Icon]) => <button key={id} className={page === id ? 'active' : ''} aria-current={page === id ? 'page' : undefined} onClick={() => setPage(id)}><Icon size={17} />{label}</button>)}</nav><div className="header-right"><span className="paper-indicator"><ShieldCheck size={14} /> PAPER ONLY</span><button className="icon-button" onClick={onLogout} disabled={workflowLocked} aria-label="Disconnect terminal" title={workflowLocked ? 'Resolve the pending order first' : 'Disconnect terminal'}><SignOut size={19} /></button></div></header>
    <div className="account-bar"><div className="account-identity"><span className="status-square" /><div><strong>Paper account</strong><span>{config.exchange.toUpperCase()} · USDT</span></div></div><div className="account-stat"><span>Wallet balance</span><strong className="mono">{number(snapshot.account.wallet_balance)} <small>USDT</small></strong></div><div className="account-stat"><span>Available margin</span><strong className="mono">{number(snapshot.account.available_balance)}</strong></div><div className="account-stat"><span>Reserved margin</span><strong className="mono">{number(snapshot.account.reserved_margin)}</strong></div><div className="account-stat"><span>Unrealized PnL</span><strong className={`mono ${tone(validValuation ? snapshot.account.unrealized_pnl : null)}`}>{validValuation ? pnl(snapshot.account.unrealized_pnl) : '—'}</strong></div><div className="account-stat equity-stat"><span>Marked equity</span><strong className="mono">{validValuation ? number(snapshot.account.equity) : '—'}</strong></div></div>
    {config.agent?.enabled && snapshot.agent?.enabled && <HermesBar token={token} agent={snapshot.agent} limits={config.agent} refresh={refresh} onToast={text => { setClosedResult(null); setToast(text); }} />}
    {!live && <div className="connection-banner" role="status"><Plugs size={18} /><span><strong>{socketState === 'connecting' ? 'Connecting to live snapshots' : socketState === 'rejected' ? 'Browser connection rejected' : 'Backend connection interrupted'}</strong> · {socketState === 'rejected' ? 'Check the allowed browser origin. REST access alone does not enable trading.' : 'Trading and live valuation are paused. Keep start.cmd open; reconnection is automatic.'}</span><button className="button compact secondary" onClick={() => void refresh()}><ArrowsClockwise size={14} /> Check backend</button></div>}
    <main id="main" className="main-workspace">
      {!live && refreshError && <p className="small-note warning-text mb-3" role="status">{refreshError}</p>}
      <div hidden={page !== 'terminal'}>
        <div className="trading-grid"><section className="market-workspace" aria-labelledby="market-heading"><div className="market-heading"><div className="market-symbol"><span className="asset-token" aria-hidden="true">{symbol.startsWith('BTC') ? 'B' : symbol.split('/')[0].slice(0, 1)}</span><div><label htmlFor="market-select" className="sr-only">Trading market</label><select id="market-select" value={symbol} disabled={workflowLocked} onChange={e => setSymbol(e.target.value)}>{config.symbols.map(s => <option key={s} value={s}>{pair(s)}</option>)}</select><h1 id="market-heading" className="market-subtitle">Linear perpetual <span>· {config.exchange.toUpperCase()}</span></h1></div></div><div className="quote-summary"><span>Best bid</span><strong className="mono">{price(market?.bid)}</strong></div><div className="quote-summary"><span>Best ask</span><strong className="mono">{price(market?.ask)}</strong></div><div className="quote-summary spread-quote"><span>Spread</span><strong className="mono">{price(spread)}</strong></div></div>
        <div className="market-status"><span className={tradable ? 'positive' : 'warning-text'}><span className={`status-dot ${tradable ? 'live' : ''}`} />{tradable ? 'Execution feed live' : market?.status === 'disabled' ? 'Execution feed disabled' : 'Execution feed unavailable'}</span><span className="mono">{age(quoteAge)} <span className="muted">· {market?.freshness_basis === 'receipt_only' ? 'receipt age' : 'quote age'}</span></span></div>
        <Chart token={token} symbol={symbol} config={config} />
        {!tradable && live && <div className="feed-note"><WarningCircle size={16} /><span>{market?.error || (market?.status === 'disabled' ? 'Enable PAPER_FEED_ENABLED in .env and restart to receive public quotes.' : 'Waiting for fresh exchange data. No paper fills are allowed while this feed is unavailable.')}</span></div>}
        <NewsStrip token={token} symbol={symbol} enabled={!!config.news_enabled} active={page === 'terminal'} onViewAll={() => { setNewsRelated(true); setPage('news'); }} />
        </section><OrderTicket key={symbol} token={token} symbol={symbol} config={config} snapshot={snapshot} market={market} tradable={tradable} onSuccess={text => { setClosedResult(null); setToast(text); }} onEntry={position => { if (splashEnabled) setEntry(position); }} splashEnabled={splashEnabled} onSplashChange={changeSplash} refresh={refresh} onWorkflow={setOrderLocked} /></div>
        <Positions token={token} snapshot={snapshot} fresh={fresh} refresh={refresh} onSuccess={setToast} onClosed={setClosedResult} onShare={sharePosition} onWorkflow={setCloseLocked} />
      </div>
      {(page === 'trades' || page === 'journals') && <History key={page} token={token} kind={page} onShare={sharePosition} />}
      {page === 'news' && <News token={token} enabled={!!config.news_enabled} symbol={symbol} related={newsRelated} onRelatedChange={setNewsRelated} />}
    </main>
    <footer className="terminal-footer"><div><span className={`status-dot ${live ? 'live' : ''}`} />{live ? 'Backend connected' : 'Backend reconnecting'}<span className="footer-divider">/</span>Snapshots every second</div><div>Isolated only<span className="footer-divider">/</span>{hermesFooter}<a href="/docs" target="_blank" rel="noreferrer">API docs</a></div></footer>
    {toast && <div className="toast" role="status"><CheckCircle size={21} className="positive" /><span>{toast}</span>{closedResult && <button className="button secondary" aria-label="Share closed result" onClick={() => sharePosition(closedResult)}>Share PnL card</button>}<button className="icon-button" aria-label="Dismiss notification" onClick={() => setToast('')}><X size={17} /></button></div>}
    {share && <ShareCard token={token} {...share} onDismiss={() => setShare(null)} />}
    {entry && <EntrySplash image={entryArt} position={entry} onDismiss={() => setEntry(null)} />}
  </div>;
}