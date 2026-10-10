import Decimal from 'decimal.js';
import type { Config, Market, Side } from './types';

export function number(value: string | number | null | undefined, places = 2): string {
  if (value === null || value === undefined || value === '') return '—';
  try {
    const d = new Decimal(value);
    if (!d.isFinite()) return '—';
    const [integer, fraction] = d.toFixed(places).split('.');
    return integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (fraction ? `.${fraction}` : '');
  } catch { return '—'; }
}
export function pnl(value: string | null | undefined): string {
  return value != null && new Decimal(value).gt(0) ? `+${number(value)}` : number(value);
}
export function price(value: string | number | null | undefined): string {
  if (value == null) return '—';
  try {
    const d = new Decimal(value);
    const places = d.isZero() || d.abs().gte(1) ? Math.max(2, Math.min(6, d.decimalPlaces())) : Math.min(18, Math.max(4, d.decimalPlaces()));
    return number(value, places);
  } catch { return '—'; }
}
export function tone(value: string | null | undefined): string {
  if (value == null) return 'muted';
  return new Decimal(value).gt(0) ? 'positive' : new Decimal(value).lt(0) ? 'negative' : 'muted';
}
export function pair(symbol: string) { return symbol.split(':')[0]; }
export function baseAsset(symbol: string) { return symbol.split('/')[0]; }
export function date(value: string | null) {
  if (!value) return '—';
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value));
}
export function timeAgo(value: string | null, now: number = Date.now()): string {
  if (!value) return '—';
  const stamp = Date.parse(value);
  if (!Number.isFinite(stamp)) return '—';
  const seconds = Math.max(0, Math.floor((now - stamp) / 1000));
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return days < 30 ? `${days}d ago` : date(value);
}
export function age(ms: number | null) {
  if (ms === null) return 'No quote';
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}
export function preview(wallet: string, allocation: string, leverage: number, side: Side, market: Market | undefined, config: Config) {
  const margin = new Decimal(wallet).mul(allocation).div(100);
  const notional = margin.mul(leverage);
  const reference = side === 'long' ? market?.ask : market?.bid;
  const price = reference ? new Decimal(reference).mul(new Decimal(1).plus(new Decimal(config.slippage_bps).div(10000).mul(side === 'long' ? 1 : -1))) : null;
  return { margin, notional, fee: notional.mul(config.taker_fee_rate), quantity: price && price.gt(0) ? notional.div(price) : null };
}