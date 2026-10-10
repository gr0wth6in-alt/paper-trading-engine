import { describe, expect, it } from 'vitest';
import { number, pnl, preview, tone } from './format';
import { config, snapshot } from './test/fixtures';

describe('financial presentation', () => {
  it('formats decimal strings without binary rounding', () => {
    expect(number('123456789012345678.995')).toBe('123,456,789,012,345,679.00');
    expect(number('0.00000012', 8)).toBe('0.00000012');
    expect(number(null)).toBe('—'); expect(number('NaN')).toBe('—');
  });
  it('pairs profit and loss colors with explicit signs', () => {
    expect(pnl('12')).toBe('+12.00'); expect(pnl('-12')).toBe('-12.00');
    expect(tone('12')).toBe('positive'); expect(tone('-12')).toBe('negative');
    expect(pnl(null)).toBe('—');
  });
  it('computes margin allocation, not stop risk', () => {
    const p = preview('10000', '2', 10, 'long', snapshot().markets['BTC/USDT:USDT'], config);
    expect(p.margin.toString()).toBe('200'); expect(p.notional.toString()).toBe('2000');
    expect(p.fee.toString()).toBe('1.2'); expect(p.quantity?.gt(0)).toBe(true);
    expect(preview('10000', '2', 10, 'short', undefined, config).quantity).toBeNull();
  });
});