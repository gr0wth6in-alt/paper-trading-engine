import { useEffect, useRef } from 'react';
import type { Position } from '../types';
import { pair, price } from '../format';

export function EntrySplash({ image, position, onDismiss }: { image: string; position: Position; onDismiss: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const dismiss = useRef(onDismiss); dismiss.current = onDismiss;
  useEffect(() => {
    const el = dialog.current!; el.showModal();
    const timer = window.setTimeout(() => dismiss.current(), 1600);
    return () => { clearTimeout(timer); el.close(); };
  }, []);
  return <dialog ref={dialog} className="entry-splash" aria-labelledby="entry-title" onCancel={e => { e.preventDefault(); onDismiss(); }} onClick={e => { e.stopPropagation(); onDismiss(); }}>
    <div className="entry-art"><img src={image} alt="Paper entry artwork" width="480" height="480" /></div>
    <div className="entry-copy"><p className="warning-text">Paper trade · simulated</p><h2 id="entry-title">Paper position opened</h2><p className={position.side === 'long' ? 'positive' : 'negative'}>{position.side.toUpperCase()} / {pair(position.symbol)}</p><p>{position.leverage}× isolated · fill {price(position.entry_price)}</p><button className="button secondary" onClick={e => { e.stopPropagation(); onDismiss(); }}>Dismiss splash</button><span className="muted small-note">Click anywhere or press Esc</span></div>
  </dialog>;
}