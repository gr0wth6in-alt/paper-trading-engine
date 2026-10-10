import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { NewsStrip } from './NewsStrip';
import { newsResponse, token } from '../test/fixtures';

beforeEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });
function stub(body = newsResponse()) {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(body), { status: 200 })));
  vi.stubGlobal('fetch', fetch);
  return fetch;
}
const props = { token, symbol: 'BTC/USDT:USDT', enabled: true, active: true, onViewAll: vi.fn() };

it('requests the three latest headlines for the selected symbol', async () => {
  const fetch = stub(); render(<NewsStrip {...props} />);
  expect(await screen.findByRole('link', { name: /Bitcoin climbs/ })).toHaveAttribute('rel', 'noopener noreferrer');
  expect(screen.getByRole('heading', { name: /Latest BTC news/ })).toBeVisible();
  expect(String(fetch.mock.calls[0][0])).toBe('/api/v1/news?symbol=BTC%2FUSDT%3AUSDT&limit=3&offset=0');
  expect(screen.queryByText('Buyers returned after the open.')).toBeNull(); // compact: no summary
});

it('refetches and hides stale headlines when the symbol changes', async () => {
  const fetch = stub(); const { rerender } = render(<NewsStrip {...props} />);
  await screen.findByRole('link', { name: /Bitcoin climbs/ });
  fetch.mockImplementation(() => new Promise(() => {}));
  rerender(<NewsStrip {...props} symbol="ETH/USDT:USDT" />);
  expect(screen.getByRole('heading', { name: /Latest ETH news/ })).toBeVisible();
  expect(screen.queryByRole('link', { name: /Bitcoin climbs/ })).toBeNull();
  await waitFor(() => expect(String(fetch.mock.calls.at(-1)?.[0])).toContain('symbol=ETH%2FUSDT%3AUSDT'));
});

it('renders nothing and makes no request when news is disabled', () => {
  const fetch = stub(); const { container } = render(<NewsStrip {...props} enabled={false} />);
  expect(container).toBeEmptyDOMElement();
  expect(fetch).not.toHaveBeenCalled();
});

it('does not poll while the terminal view is hidden', () => {
  const fetch = stub(); render(<NewsStrip {...props} active={false} />);
  expect(fetch).not.toHaveBeenCalled();
});

it('shows an empty note and an inline error without breaking the terminal', async () => {
  stub(newsResponse({ total: 0, items: [] })); const { unmount } = render(<NewsStrip {...props} />);
  expect(await screen.findByText('No recent headlines mention BTC.')).toBeVisible();
  unmount();
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
  render(<NewsStrip {...props} />);
  expect(await screen.findByText(/News unavailable/)).toBeVisible();
});

it('View all opens the filtered news page', async () => {
  stub(); const onViewAll = vi.fn(); render(<NewsStrip {...props} onViewAll={onViewAll} />);
  fireEvent.click(screen.getByRole('button', { name: /View all/ }));
  expect(onViewAll).toHaveBeenCalledOnce();
});
