import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { News } from './News';
import { config, newsResponse, token } from '../test/fixtures';
import type { NewsResponse } from '../types';

beforeEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
function stub(...responses: (NewsResponse | Response)[]) {
  const fetch = vi.fn();
  for (const r of responses) fetch.mockResolvedValueOnce(r instanceof Response ? r : json(r));
  const fallback = [...responses].reverse().find(r => !(r instanceof Response)) ?? newsResponse();
  fetch.mockImplementation(() => Promise.resolve(json(fallback)));
  vi.stubGlobal('fetch', fetch);
  return fetch;
}
function mount(props: Partial<Parameters<typeof News>[0]> = {}) {
  const onRelatedChange = vi.fn();
  const view = render(<News token={token} enabled symbol={config.symbols[0]} related={false} onRelatedChange={onRelatedChange} {...props} />);
  return { ...view, onRelatedChange };
}
const lastUrl = (fetch: ReturnType<typeof vi.fn>) => String(fetch.mock.calls.at(-1)?.[0]);

it('renders headlines as external links with source, time and tags', async () => {
  const fetch = stub(newsResponse()); mount();
  const link = await screen.findByRole('link', { name: /Bitcoin climbs past resistance/ });
  expect(link).toHaveAttribute('href', 'https://www.coindesk.com/markets/btc');
  expect(link).toHaveAttribute('target', '_blank');
  expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  const article = link.closest('article')!;
  expect(within(article).getByText('CoinDesk')).toBeVisible();
  expect(within(article).getByText('5m ago')).toHaveAttribute('datetime');
  expect(within(article).getByText('BTC')).toBeVisible();
  expect(within(article).getByText('Buyers returned after the open.')).toBeVisible();
  expect(lastUrl(fetch)).toBe('/api/v1/news?limit=20&offset=0');
  expect(fetch.mock.calls[0][1].headers.Authorization).toBe(`Bearer ${token}`);
});

it('treats hostile feed text as literal text, never markup', async () => {
  const hostile = '<img src=x onerror="window.hacked=1"><script>window.hacked=2</script>';
  stub(newsResponse({ total: 1, items: [{ ...newsResponse().items[0], title: hostile, summary: `<b>bold</b> ${hostile}` }] }));
  const { container } = mount();
  expect(await screen.findByText(hostile)).toBeVisible();
  expect(container.querySelector('img, script, b, iframe')).toBeNull();
  expect((window as unknown as { hacked?: number }).hacked).toBeUndefined();
});

it('renders unsafe URLs as plain text without a link', async () => {
  const items = ['javascript:alert(1)', 'data:text/html,x', '/relative'].map((url, i) => ({ ...newsResponse().items[0], id: `u${i}`, title: `Unsafe ${i}`, url }));
  stub(newsResponse({ total: 3, items })); const { container } = mount();
  await screen.findByText('Unsafe 0');
  expect(container.querySelectorAll('a')).toHaveLength(0);
});

it('sends source, debounced search and related-market filters', async () => {
  const fetch = stub(newsResponse()); const { rerender, onRelatedChange } = mount();
  await screen.findByRole('link', { name: /Bitcoin climbs/ });
  fireEvent.change(screen.getByLabelText('Source'), { target: { value: 'Decrypt' } });
  await waitFor(() => expect(lastUrl(fetch)).toBe('/api/v1/news?source=Decrypt&limit=20&offset=0'));
  fireEvent.change(screen.getByLabelText('Search headlines'), { target: { value: '  ETF flows ' } });
  await waitFor(() => expect(lastUrl(fetch)).toBe('/api/v1/news?source=Decrypt&q=ETF+flows&limit=20&offset=0'));
  fireEvent.click(screen.getByLabelText(/Related to BTC\/USDT/));
  expect(onRelatedChange).toHaveBeenCalledWith(true);
  rerender(<News token={token} enabled symbol={config.symbols[0]} related onRelatedChange={onRelatedChange} />);
  await waitFor(() => expect(lastUrl(fetch)).toBe('/api/v1/news?source=Decrypt&q=ETF+flows&symbol=BTC%2FUSDT%3AUSDT&limit=20&offset=0'));
});

it('pages through results and resets to page one when filters change', async () => {
  const fetch = stub(newsResponse({ total: 45 })); mount();
  await screen.findByText(/Headlines 1–2 of 45/);
  fireEvent.click(screen.getByRole('button', { name: 'Next' }));
  await waitFor(() => expect(lastUrl(fetch)).toContain('offset=20'));
  const before = fetch.mock.calls.length;
  fireEvent.change(screen.getByLabelText('Source'), { target: { value: 'CoinDesk' } });
  await waitFor(() => expect(lastUrl(fetch)).toBe('/api/v1/news?source=CoinDesk&limit=20&offset=0'));
  expect(fetch.mock.calls.slice(before).every(([url]) => !String(url).includes('offset=20'))).toBe(true);
});

it('shows failing sources without hiding healthy ones', async () => {
  const base = newsResponse();
  stub(newsResponse({ sources: [...base.sources, { name: 'Bitcoinist', status: 'error', error: 'HTTP 403', last_success: null, item_count: 0 }] }));
  mount();
  expect(await screen.findByText(/Unavailable: Bitcoinist \(HTTP 403\)/)).toBeVisible();
  expect(screen.getByRole('link', { name: /Bitcoin climbs/ })).toBeVisible();
});

it('shows error with retry, then recovers', async () => {
  const fetch = stub(json({ error: { code: 'boom', message: 'Backend hiccup' } }, 500), newsResponse()); mount();
  expect(await screen.findByRole('alert')).toHaveTextContent('Backend hiccup');
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
  expect(await screen.findByRole('link', { name: /Bitcoin climbs/ })).toBeVisible();
  expect(fetch).toHaveBeenCalledTimes(2);
});

it('shows empty, pending and filtered-empty states', async () => {
  stub(newsResponse({ total: 0, items: [], sources: newsResponse().sources.map(s => ({ ...s, status: 'pending' as const })) }));
  const { unmount } = mount();
  expect(await screen.findByText('Fetching first headlines')).toBeVisible();
  unmount();
  stub(newsResponse({ total: 0, items: [] })); mount({ related: true });
  expect(await screen.findByText('No headlines match these filters')).toBeVisible();
});

it('does not call the backend when news is disabled', () => {
  const fetch = stub(newsResponse()); mount({ enabled: false });
  expect(screen.getByText('News feed is turned off')).toBeVisible();
  expect(fetch).not.toHaveBeenCalled();
});

it('switches to the disabled state when the backend reports news_disabled', async () => {
  stub(json({ error: { code: 'news_disabled', message: 'News feed is disabled' } }, 503)); mount();
  expect(await screen.findByText('News feed is turned off')).toBeVisible();
  expect(screen.queryByRole('alert')).toBeNull();
});

it('never uses dangerouslySetInnerHTML anywhere in the frontend', () => {
  const sources = import.meta.glob('/src/**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
  const offenders = Object.entries(sources).filter(([path, text]) => !path.endsWith('.test.tsx') && /dangerouslySetInnerHTML|\.innerHTML\s*=|insertAdjacentHTML|outerHTML\s*=/.test(text));
  expect(Object.keys(sources).length).toBeGreaterThan(10);
  expect(offenders.map(([path]) => path)).toEqual([]);
});
