import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { OrderTicket } from './OrderTicket';
import { config, position, snapshot, token } from '../test/fixtures';

const callbacks = { onSuccess: vi.fn(), onEntry: vi.fn(), refresh: vi.fn().mockResolvedValue(undefined), onWorkflow: vi.fn() };
beforeEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });
function mount(tradable = true) { const state = snapshot(); return render(<OrderTicket token={token} symbol={config.symbols[0]} config={config} snapshot={state} market={state.markets[config.symbols[0]]} tradable={tradable} {...callbacks} />); }
it('requires review and never submits an order automatically', () => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch); mount();
  expect(screen.getByLabelText('Margin allocation')).toHaveValue(2);
  expect(screen.getByLabelText('Leverage')).toHaveValue('10');
  fireEvent.click(screen.getByRole('button', { name: /Review paper long/ }));
  expect(screen.getByRole('button', { name: 'Confirm paper long' })).toBeVisible();
  expect(fetch).not.toHaveBeenCalled();
});
it('disables execution when quotes are stale', () => {
  mount(false);
  expect(screen.getByRole('button', { name: /Review paper long/ })).toBeDisabled();
  expect(screen.getByText(/Trading paused/)).toBeVisible();
});
it('rejects invalid directional brackets', () => {
  mount(); fireEvent.change(screen.getByLabelText(/Stop loss/), { target: { value: '66000' } });
  fireEvent.click(screen.getByRole('button', { name: /Review paper long/ }));
  expect(screen.getByRole('alert')).toHaveTextContent('below the bid');
});
it('retries an uncertain order with identical payload and idempotency key', async () => {
  const fetch = vi.fn().mockRejectedValueOnce(new TypeError('network lost')).mockResolvedValueOnce(new Response(JSON.stringify(position()), { status: 201 }));
  vi.stubGlobal('fetch', fetch); mount();
  fireEvent.click(screen.getByRole('button', { name: /Review paper long/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm paper long' }));
  await screen.findByRole('button', { name: 'Retry same paper order' });
  expect(callbacks.onEntry).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Margin allocation')).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Retry same paper order' }));
  await waitFor(() => expect(callbacks.onSuccess).toHaveBeenCalledOnce());
  expect(callbacks.onEntry).toHaveBeenCalledOnce();
  expect(fetch.mock.calls[0][1].body).toBe(fetch.mock.calls[1][1].body);
  expect(fetch.mock.calls[0][1].headers['Idempotency-Key']).toBe(fetch.mock.calls[1][1].headers['Idempotency-Key']);
});