import Decimal from 'decimal.js';
import { pair, pnl, price } from '../format';
import type { Position } from '../types';

export function cardModel(position: Position, showAmount: boolean) {
  const closed = position.status === 'closed';
  const value = closed ? position.net_pnl : position.unrealized_pnl;
  if ((!closed && position.quote_stale !== false) || value == null) throw new Error('A fresh valuation is required to share this position.');
  const margin = new Decimal(position.margin), amount = new Decimal(value);
  if (!margin.isFinite() || margin.lte(0) || !amount.isFinite()) throw new Error('PnL data is unavailable.');
  const roe = amount.div(margin).mul(100);
  const signed = (d: Decimal) => d.isZero() ? '0.00' : d.abs().lt('0.005') ? `${d.isNegative() ? '-' : '+'}<0.01` : pnl(d.toString());
  return {
    pair: pair(position.symbol), side: position.side.toUpperCase(), leverage: `${position.leverage}× isolated`,
    roe: `${signed(roe)}%`, amount: showAmount ? `${signed(amount)} USDT` : null,
    state: amount.gt(0) ? 'profit' as const : amount.lt(0) ? 'loss' as const : 'neutral' as const,
    basis: closed ? 'Realized · after fees' : 'Unrealized · before fees',
    entry: price(position.entry_price), end: price(closed ? position.exit_price : position.mark_price),
    endLabel: closed ? 'Exit price' : 'Mark price', disclaimer: 'Paper trade · simulated',
  };
}
export type CardModel = ReturnType<typeof cardModel>;

export async function drawCard(canvas: HTMLCanvasElement, model: CardModel, image: HTMLImageElement, capturedAt: string): Promise<Blob> {
  await document.fonts.ready;
  canvas.width = 1200; canvas.height = 675;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Image export is unavailable in this browser.');
  const accent = model.state === 'profit' ? '#63d3a6' : model.state === 'loss' ? '#f28b91' : '#b7bdc5';
  ctx.fillStyle = '#14191c'; ctx.fillRect(0, 0, 1200, 675);
  ctx.fillStyle = model.state === 'profit' ? '#1d382e' : model.state === 'loss' ? '#402529' : '#2a3037';
  ctx.fillRect(744, 0, 456, 675);
  const text = (value: string, x: number, y: number, size: number, color = '#e5e7eb', width = 650) => {
    ctx.fillStyle = color; ctx.font = `500 ${size}px "Geist Variable", sans-serif`;
    while (ctx.measureText(value).width > width && size > 14) { size -= 1; ctx.font = `500 ${size}px "Geist Variable", sans-serif`; }
    ctx.fillText(value, x, y);
  };
  text('PAPER / TERMINAL', 48, 58, 21, '#b7bdc5');
  text(model.pair, 48, 150, 44);
  text(`${model.side}   /   ${model.leverage}`, 48, 192, 23, '#b7bdc5');
  text(model.roe, 42, 324, 100, accent);
  text('Return on initial margin', 48, 365, 23, '#b7bdc5');
  text(model.basis, 48, 401, 23, accent);
  if (model.amount) text(model.amount, 48, 447, 29, accent);
  ctx.strokeStyle = '#414950'; ctx.beginPath(); ctx.moveTo(48, 482); ctx.lineTo(696, 482); ctx.stroke();
  text('Entry price', 48, 519, 20, '#b7bdc5'); text(model.endLabel, 382, 519, 20, '#b7bdc5');
  text(model.entry, 48, 555, 28, '#e5e7eb', 305); text(model.end, 382, 555, 28, '#e5e7eb', 314);
  const ratio = Math.min(400 / image.naturalWidth, 450 / image.naturalHeight);
  const w = image.naturalWidth * ratio, h = image.naturalHeight * ratio;
  ctx.drawImage(image, 772 + (400 - w) / 2, 110 + (450 - h) / 2, w, h);
  text(model.disclaimer, 48, 621, 24, '#e8bb72');
  text(`Captured ${new Date(capturedAt).toISOString().replace('T', ' ').slice(0, 19)} UTC`, 48, 652, 17, '#b7bdc5');
  text(model.state === 'profit' ? 'GREEN DAY.' : model.state === 'loss' ? 'STILL LEARNING.' : 'FLAT IS A RESULT.', 774, 606, 24, accent, 398);
  return new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('PNG export failed. Try again.')), 'image/png'));
}