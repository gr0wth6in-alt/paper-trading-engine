import { expect, it } from 'vitest';
import * as formatting from '../format';
import { position } from '../test/fixtures';

it('preserves tiny coin prices without floating-point loss', () => {
  expect(formatting).toHaveProperty('price');
  const price = (formatting as unknown as { price: (value: string) => string }).price;
  expect(price('0.00000123')).toBe('0.00000123');
  expect(price('65000')).toBe('65,000.00');
});

it('builds a private closed-trade model with net return on initial margin', async () => {
  const { cardModel } = await import('./card');
  const model = cardModel({ ...position(), status: 'closed', margin: '200', net_pnl: '20', exit_price: '66000' }, false);
  expect(model.roe).toBe('+10.00%');
  expect(model.amount).toBeNull();
  expect(model.state).toBe('profit');
  expect(model.basis).toContain('after fees');
  expect(JSON.stringify(model)).not.toMatch(/strategy|notes|token|wallet|quantity/);
  expect(model.disclaimer).toBe('Paper trade · simulated');
});

it('labels unrealized before-fee values and rejects stale or missing valuation', async () => {
  const { cardModel } = await import('./card');
  const p = { ...position(), margin: '200', unrealized_pnl: '-10', quote_stale: false, mark_price: '64000' };
  expect(cardModel(p, true)).toMatchObject({ roe: '-5.00%', amount: '-10.00 USDT', state: 'loss' });
  expect(cardModel(p, false).basis).toContain('before fees');
  expect(() => cardModel({ ...p, quote_stale: true }, false)).toThrow();
  expect(() => cardModel({ ...p, unrealized_pnl: null }, false)).toThrow();
  expect(cardModel({ ...p, unrealized_pnl: '0' }, false).state).toBe('neutral');
});