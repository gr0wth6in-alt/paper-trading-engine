import { useEffect, useMemo, useRef, useState } from 'react';
import type { Position } from '../types';
import { X } from '../icons';
import { message } from '../api';
import { cardModel, drawCard } from '../share/card';
import { pickMeme } from '../memes/memes';

interface Props { token: string; position: Position; capturedAt: string; onDismiss: () => void }
export function ShareCard({ token, position, capturedAt, onDismiss }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [showAmount, setShowAmount] = useState(false);
  const [variant, setVariant] = useState(() => Math.floor(Math.random() * 3));
  const [meme, setMeme] = useState<HTMLImageElement | null>(null);
  const [fallback, setFallback] = useState(false);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const model = useMemo(() => cardModel(position, showAmount), [position, showAmount]);
  useEffect(() => { const el = dialog.current!; el.showModal(); return () => el.close(); }, []);
  useEffect(() => {
    const controller = new AbortController(); setMeme(null); setBlob(null);
    void pickMeme(token, model.state, controller.signal, variant).then(result => {
      if (!controller.signal.aborted) { setMeme(result.image); setFallback(result.fallback); }
    }).catch(err => { if (!controller.signal.aborted) setError(message(err)); });
    return () => controller.abort();
  }, [token, model.state, variant]);
  useEffect(() => {
    let disposed = false; setBlob(null); setError(''); setStatus('');
    if (meme && canvas.current) void drawCard(canvas.current, model, meme, capturedAt)
      .then(result => { if (!disposed) setBlob(result); })
      .catch(err => { if (!disposed) setError(message(err)); });
    return () => { disposed = true; };
  }, [model, meme, capturedAt]);
  const filename = `paper-pnl-${model.pair.replace(/[^a-z0-9]/gi, '-')}-${capturedAt.slice(0, 10)}.png`;
  const file = blob ? new File([blob], filename, { type: 'image/png' }) : null;
  let canShare = false;
  try { canShare = !!file && !!navigator.canShare?.({ files: [file] }); } catch { /* File sharing varies by browser. */ }
  const canCopy = typeof ClipboardItem !== 'undefined' && !!navigator.clipboard?.write;
  function download() {
    if (!blob) return;
    const url = URL.createObjectURL(blob), anchor = document.createElement('a');
    anchor.href = url; anchor.download = filename; document.body.append(anchor); anchor.click(); anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000); setStatus('PNG downloaded.');
  }
  async function share() {
    if (!file) return;
    try { await navigator.share({ files: [file], title: 'Paper trade result' }); setStatus('Shared.'); }
    catch (err) { if (!(err instanceof DOMException && err.name === 'AbortError')) setError('Sharing is unavailable. Use Download PNG instead.'); }
  }
  async function copy() {
    if (!blob) return;
    try { await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]); setStatus('Image copied.'); }
    catch { setError('Clipboard access was denied. Use Download PNG instead.'); }
  }
  return <dialog ref={dialog} className="modal share-modal" aria-labelledby="share-title" onCancel={event => { event.preventDefault(); onDismiss(); }}>
    <div className="section-heading"><h2 id="share-title">Share PnL card</h2><button className="icon-button" aria-label="Close sharing" onClick={onDismiss}><X size={19} /></button></div>
    <p className="share-basis">{model.basis}</p>
    <canvas ref={canvas} className="share-preview" role="img" aria-label={`${model.disclaimer}. ${model.pair}, ${model.side}, ${model.roe} return on initial margin. ${model.basis}. ${model.amount || 'USDT amount hidden.'}`} />
    <div className="share-settings"><label className="checkbox-label"><input type="checkbox" checked={showAmount} onChange={e => { setBlob(null); setShowAmount(e.target.checked); }} />Show USDT amount</label><button className="button secondary" onClick={() => { setBlob(null); setVariant(v => v + 1); }}>Shuffle meme</button></div>
    <p className="small-note muted">{position.status === 'open' ? 'Frozen at capture, not a live or guaranteed exit value. ' : ''}ROE uses initial isolated margin. Paper label is always included. Balance and trade notes are never shared.</p>
    {fallback && <p className="small-note warning-text">Local image unavailable; using an original frog drawing.</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
    <p className="share-status" role="status">{status || (!blob && !error ? 'Preparing PNG…' : '')}</p>
    <div className="share-actions">{canShare && <button className="button secondary" onClick={() => void share()}>Share</button>}<button className="button secondary" disabled={!blob || !canCopy} onClick={() => void copy()}>Copy image</button><button className="button primary" disabled={!blob} onClick={download}>Download PNG</button></div>
    {!canCopy && <p className="small-note muted">Image clipboard is unavailable in this browser. Download PNG works without it.</p>}
  </dialog>;
}