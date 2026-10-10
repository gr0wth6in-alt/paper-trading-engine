import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { HermesBar, cooldownLabel, hermesStatus } from './HermesBar';
import { agentLimits, agentState, token } from '../test/fixtures';

beforeEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
function mount(state = agentState()) {
  const refresh = vi.fn().mockResolvedValue(undefined); const onToast = vi.fn();
  render(<HermesBar token={token} agent={state} limits={agentLimits} refresh={refresh} onToast={onToast} />);
  return { refresh, onToast };
}

it('labels every status', () => {
  expect(hermesStatus({ enabled: false }).label).toBe('Disabled');
  expect(hermesStatus(agentState({ paused: true, breaker_tripped: true })).label).toBe('Paused');
  expect(hermesStatus(agentState({ breaker_tripped: true })).label).toBe('Breaker tripped');
  expect(hermesStatus(agentState({ cooldown_remaining_seconds: 754.2 })).label).toBe('Cooldown 12:35');
  expect(hermesStatus(agentState()).label).toBe('Active');
  expect(cooldownLabel(59.1)).toBe('1:00');
});

it('shows limits and pauses immediately with the operator token', async () => {
  const fetch = vi.fn().mockResolvedValue(json(agentState({ paused: true }))); vi.stubGlobal('fetch', fetch);
  const { refresh, onToast } = mount();
  expect(screen.getByRole('status')).toHaveTextContent('Active');
  expect(screen.getByText(/≤ 100.00/)).toBeVisible();
  expect(screen.getByText('12.50')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: /Pause Hermes/ }));
  await waitFor(() => expect(onToast).toHaveBeenCalledWith(expect.stringContaining('Hermes paused')));
  expect(String(fetch.mock.calls[0][0])).toBe('/api/v1/agent/pause');
  expect(fetch.mock.calls[0][1].method).toBe('POST');
  expect(fetch.mock.calls[0][1].headers.Authorization).toBe(`Bearer ${token}`);
  expect(refresh).toHaveBeenCalled();
});

it('requires confirmation listing the enforced limits before resuming', async () => {
  const fetch = vi.fn().mockResolvedValue(json(agentState())); vi.stubGlobal('fetch', fetch);
  mount(agentState({ paused: true, pause_reason: 'Initial state: resume from the terminal' }));
  expect(screen.getByText('Initial state: resume from the terminal')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: /Resume Hermes/ }));
  expect(fetch).not.toHaveBeenCalled();
  const dialog = screen.getByRole('dialog', { name: 'Resume Hermes?' });
  expect(within(dialog).getByText('1 per 15 min')).toBeVisible();
  expect(within(dialog).getByText('≤ 1.0% of wallet')).toBeVisible();
  expect(within(dialog).getByText('Required on every entry')).toBeVisible();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Resume Hermes' }));
  await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
  expect(String(fetch.mock.calls[0][0])).toBe('/api/v1/agent/resume');
});

it('close all reports per-position failures and keeps the dialog open', async () => {
  const fetch = vi.fn().mockResolvedValue(json({ closed: [], failed: [{ id: 'a', symbol: 'BTC/USDT:USDT', code: 'stale_quote', message: 'The live order book is too old' }] }));
  vi.stubGlobal('fetch', fetch);
  const { onToast } = mount();
  fireEvent.click(screen.getByRole('button', { name: 'Close all Hermes positions' }));
  const dialog = screen.getByRole('dialog', { name: 'Close all Hermes positions?' });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Close all Hermes positions' }));
  expect(await within(dialog).findByText('BTC/USDT: The live order book is too old')).toBeVisible();
  expect(within(dialog).getByRole('button', { name: 'Retry close all' })).toBeVisible();
  expect(onToast).toHaveBeenCalledWith('Closed 0 Hermes positions · 1 could not close');
});

it('surfaces API errors and shows the breaker warning', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ error: { code: 'agent_disabled', message: 'The agent API is not configured' } }, 503)));
  mount(agentState({ breaker_tripped: true, breaker_resets_at: '2026-10-11T00:00:00+00:00', open_positions: 0 }));
  expect(screen.getByText(/Daily loss limit reached/)).toHaveTextContent('00:00 UTC');
  expect(screen.getByRole('button', { name: 'Close all Hermes positions' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: /Pause Hermes/ }));
  expect(await screen.findByRole('alert')).toHaveTextContent('The agent API is not configured');
});
