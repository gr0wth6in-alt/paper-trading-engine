import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { agentLimits, agentState, config, newsResponse, position, snapshot, token } from '../src/test/fixtures';
import { readFile } from 'node:fs/promises';

async function setup(page: Page, options: { stale?: boolean; chartError?: boolean; noSocket?: boolean } = {}) {
  const state = snapshot();
  const orders: { body: unknown; key: string | undefined }[] = [];
  const closes: string[] = [];
  const newsRequests: string[] = [];
  if (options.stale) for (const market of Object.values(state.markets)) { market.stale = true; market.status = 'disconnected'; market.bid = null; market.ask = null; market.age_ms = null; }
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (route.request().headers()['authorization'] !== `Bearer ${token}`) return route.fulfill({ status: 401, json: { detail: 'Invalid token' } });
    if (path.endsWith('/config')) return route.fulfill({ json: config });
    if (path.endsWith('/status')) return route.fulfill({ json: state });
    if (path.endsWith('/memes')) return route.fulfill({ json: { profit: [], loss: [], entry: [] } });
    if (path.endsWith('/candles')) {
      if (options.chartError) return route.fulfill({ status: 503, json: { error: { message: 'Exchange connectivity unavailable.' } } });
      const start = Math.floor(Date.now() / 300000) * 300 - 60 * 300;
      return route.fulfill({ json: { symbol: config.symbols[0], exchange: 'okx', timeframe: '5m', fetched_at: new Date().toISOString(), source: 'exchange_ohlcv', candles: Array.from({ length: 60 }, (_, i) => {
        const open = 64800 + i * 10 + Math.sin(i) * 45;
        const close = open + (i % 3 ? 25 : -32);
        return { time: start + i * 300, open, high: Math.max(open, close) + 30, low: Math.min(open, close) - 25, close, volume: 1, closed: true };
      }) } });
    }
    if (path.endsWith('/orders')) {
      orders.push({ body: route.request().postDataJSON(), key: route.request().headers()['idempotency-key'] });
      state.positions = [position()]; state.account.reserved_margin = '195.90'; state.account.available_balance = '9802.9246';
      return route.fulfill({ status: 201, json: position() });
    }
    if (path.endsWith('/close')) { closes.push(route.request().headers()['idempotency-key']); state.positions = []; return route.fulfill({ json: { ...position(), status: 'closed', net_pnl: '2.43', exit_price: '65420.10' } }); }
    if (path.endsWith('/trades') || path.endsWith('/journals')) return route.fulfill({ json: [] });
    if (path.endsWith('/news')) {
      newsRequests.push(url.search);
      const body = newsResponse();
      body.items.push({ id: 'hostile', source: 'Decrypt', title: '<img src=x onerror="window.pwned=1">Solana upgrade', summary: '<script>window.pwned=2</script>', url: 'javascript:alert(1)', published_at: new Date(Date.now() - 86400000).toISOString(), symbols: [] });
      const symbol = url.searchParams.get('symbol'); const source = url.searchParams.get('source'); const q = url.searchParams.get('q')?.toLowerCase();
      body.items = body.items.filter(i => (!symbol || i.symbols.includes(symbol.split('/')[0])) && (!source || i.source === source) && (!q || i.title.toLowerCase().includes(q)));
      body.total = body.items.length;
      return route.fulfill({ json: body });
    }
    return route.fulfill({ status: 404, json: {} });
  });
  await page.routeWebSocket('**/ws', socket => {
    let timer: ReturnType<typeof setInterval>;
    socket.onMessage(raw => {
      const auth = JSON.parse(String(raw));
      expect(auth.token).toBe(token);
      if (options.noSocket) return;
      const send = () => { state.timestamp = new Date().toISOString(); socket.send(JSON.stringify(state)); };
      send(); timer = setInterval(send, 500);
    });
    socket.onClose(() => clearInterval(timer));
  });
  await page.goto('/');
  return { state, orders, closes, newsRequests };
}
async function login(page: Page) {
  await page.getByLabel('Local API token').fill(token);
  await page.getByRole('button', { name: 'Connect to paper engine' }).click();
  await expect(page.getByRole('heading', { name: 'Place an order' })).toBeVisible();
}

test('auth, chart, paper order, close, and history workflow', async ({ page }) => {
  const { orders, closes } = await setup(page);
  await login(page);
  await expect(page.getByText('Execution feed live')).toBeVisible();
  await expect(page.getByText(/Closed candle|Forming candle/)).toBeVisible();
  await page.getByRole('button', { name: /Review paper long/ }).click();
  expect(orders).toHaveLength(0);
  await page.getByRole('button', { name: 'Confirm paper long' }).click();
  await expect(page.getByRole('button', { name: 'Close', exact: true })).toBeVisible();
  expect(orders).toHaveLength(1); expect(orders[0].key).toBeTruthy();
  expect(orders[0].body).toMatchObject({ allocation_pct: '0.02', leverage: 10, side: 'long' });
  await page.screenshot({ path: 'test-results/terminal-desktop.png', fullPage: true });
  await page.getByRole('button', { name: 'Close', exact: true }).click();
  await page.getByRole('button', { name: 'Close paper position', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'No open positions' })).toBeVisible();
  expect(closes).toHaveLength(1);
  await page.getByRole('button', { name: 'History', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'No closed trades yet' })).toBeVisible();
  await page.getByRole('button', { name: 'Journal', exact: true }).click();
  await expect(page.getByText('Local summaries active')).toBeVisible();
  expect(await page.evaluate(() => Object.keys(localStorage).length + Object.keys(sessionStorage).length)).toBe(0);
});

test('confirmed entry splash and private PNG sharing from open and closed trades', async ({ page }) => {
  await setup(page); await login(page);
  await page.getByRole('button', { name: /Review paper long/ }).click();
  await expect(page.getByRole('dialog', { name: 'Paper position opened' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Confirm paper long' }).click();
  const splash = page.getByRole('dialog', { name: 'Paper position opened' });
  await expect(splash).toBeVisible();
  await page.screenshot({ path: 'test-results/entry-frog.png' });
  await page.keyboard.press('Escape');
  await expect(splash).toHaveCount(0);
  await page.getByRole('button', { name: 'Share PnL card', exact: true }).click();
  const modal = page.getByRole('dialog', { name: 'Share PnL card' });
  await expect(modal.getByText('Unrealized · before fees')).toBeVisible();
  await expect(modal.getByLabel('Show USDT amount')).not.toBeChecked();
  await expect(modal.getByRole('img', { name: /Paper trade/ })).toBeVisible();
  await expect(modal.getByRole('button', { name: 'Download PNG' })).toBeEnabled();
  expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()).violations).toEqual([]);
  await page.evaluate(() => {
    Object.defineProperty(navigator, 'share', { configurable: true, value: async () => { throw new DOMException('Cancelled', 'AbortError'); } });
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { write: async () => { throw new DOMException('Denied', 'NotAllowedError'); } } });
  });
  if (await modal.getByRole('button', { name: 'Share', exact: true }).count()) {
    await modal.getByRole('button', { name: 'Share', exact: true }).click();
    await expect(modal.getByRole('alert')).toHaveCount(0);
  }
  await modal.getByRole('button', { name: 'Copy image' }).click();
  await expect(modal.getByRole('alert')).toContainText('Clipboard access was denied');
  await modal.getByLabel('Show USDT amount').check();
  await expect(modal.getByRole('button', { name: 'Download PNG' })).toBeEnabled();
  await page.screenshot({ path: 'test-results/pnl-profit.png' });
  const downloadPromise = page.waitForEvent('download');
  await modal.getByRole('button', { name: 'Download PNG' }).click();
  const download = await downloadPromise;
  const png = await readFile((await download.path())!);
  expect(png.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a');
  expect(png.readUInt32BE(16)).toBe(1200); expect(png.readUInt32BE(20)).toBe(675);
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Close', exact: true }).click();
  await page.getByRole('button', { name: 'Close paper position', exact: true }).click();
  await page.getByRole('button', { name: 'Share closed result' }).click();
  await expect(modal.getByText('Realized · after fees')).toBeVisible();
});

test('loss card, fallback export controls, reduced motion and mobile modal', async ({ page }) => {
  const { state } = await setup(page);
  state.positions = [{ ...position(), unrealized_pnl: '-10' }];
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  await page.getByRole('button', { name: 'Share PnL card', exact: true }).click();
  const modal = page.getByRole('dialog', { name: 'Share PnL card' });
  await expect(modal.getByRole('button', { name: 'Download PNG' })).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/pnl-loss-mobile.png' });
  await page.keyboard.press('Escape');
  await page.getByLabel('Entry splash').uncheck();
  expect(await page.evaluate(() => localStorage.getItem('paper-entry-splash'))).toBe('off');
  await page.getByRole('button', { name: /Review paper long/ }).click();
  await page.getByRole('button', { name: 'Confirm paper long' }).click();
  await expect(page.getByRole('dialog', { name: 'Paper position opened' })).toHaveCount(0);
});

test('custom entry art is preloaded, splash expires and preference survives reload', async ({ page }) => {
  let images = 0;
  await setup(page);
  await page.route('**/api/v1/memes', route => route.fulfill({ json: { entry: ['entry.png'], profit: [], loss: [] } }));
  await page.route('**/api/v1/memes/entry/entry.png', route => {
    images++;
    expect(route.request().headers()['authorization']).toBe(`Bearer ${token}`);
    return route.fulfill({ contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ1cAAAAASUVORK5CYII=', 'base64') });
  });
  await login(page);
  await expect.poll(() => images).toBeGreaterThan(0);
  await page.getByRole('button', { name: /Review paper long/ }).click();
  await page.getByRole('button', { name: 'Confirm paper long' }).click();
  const splash = page.getByRole('dialog', { name: 'Paper position opened' });
  await expect(splash).toBeVisible();
  await page.screenshot({ path: 'test-results/entry-splash.png' });
  await expect(splash).toHaveCount(0, { timeout: 2500 });
  await page.getByLabel('Entry splash').uncheck();
  await page.reload(); await login(page);
  await expect(page.getByLabel('Entry splash')).not.toBeChecked();
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain(token);
});

test('click dismissal consumes the click and custom share images fall back on decode failure', async ({ page }) => {
  const { orders } = await setup(page); await login(page);
  await page.getByRole('button', { name: /Review paper long/ }).click();
  await page.getByRole('button', { name: 'Confirm paper long' }).click();
  await page.getByRole('dialog', { name: 'Paper position opened' }).click();
  expect(orders).toHaveLength(1);
  await page.route('**/api/v1/memes', route => route.fulfill({ json: { entry: [], profit: ['broken.png'], loss: [] } }));
  await page.route('**/api/v1/memes/profit/broken.png', route => route.fulfill({ contentType: 'image/png', body: 'broken' }));
  await page.getByRole('button', { name: 'Share PnL card', exact: true }).click();
  await expect(page.getByText('Local image unavailable; using an original frog drawing.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Download PNG' })).toBeEnabled();
});

test('stale positions cannot share and closed history works without share or clipboard APIs', async ({ page }) => {
  const { state } = await setup(page);
  state.positions = [{ ...position(), quote_stale: true, unrealized_pnl: null }];
  await page.evaluate(() => {
    Object.defineProperty(navigator, 'canShare', { value: undefined });
    Object.defineProperty(navigator, 'clipboard', { value: undefined });
  });
  await page.route('**/api/v1/trades?*', route => route.fulfill({ json: [{ ...position(), status: 'closed', net_pnl: '0', exit_price: '65300' }] }));
  await login(page);
  await expect(page.getByRole('button', { name: 'Share PnL card', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'History', exact: true }).click();
  await page.getByRole('button', { name: 'Share BTC/USDT PnL card' }).click();
  const modal = page.getByRole('dialog', { name: 'Share PnL card' });
  await expect(modal.getByRole('button', { name: 'Share', exact: true })).toHaveCount(0);
  await expect(modal.getByRole('button', { name: 'Copy image' })).toBeDisabled();
  await expect(modal.getByRole('button', { name: 'Download PNG' })).toBeEnabled();
  await expect(modal.getByRole('img', { name: /Paper trade/ })).toHaveAttribute('aria-label', /0.00%/);
});

test('stale feeds show honest empty states and block orders', async ({ page }) => {
  await setup(page, { stale: true, chartError: true }); await login(page);
  await expect(page.getByRole('heading', { name: 'Chart feed unavailable' })).toBeVisible();
  await expect(page.getByRole('button', { name: /Review paper long/ })).toBeDisabled();
  await expect(page.getByText('Trading paused', { exact: false })).toBeVisible();
  await page.screenshot({ path: 'test-results/terminal-offline.png', fullPage: true });
});

test('desktop keyboard access and WCAG checks', async ({ page }) => {
  await setup(page);
  const authScan = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(authScan.violations).toEqual([]);
  await login(page);
  await expect(page.getByText('Execution feed live')).toBeVisible();
  await expect(page.locator('[role="img"][aria-label*="candlestick chart"] a')).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'TradingView', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'TradingView', exact: true })).toHaveAttribute('href', 'https://www.tradingview.com/');
  const scan = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(scan.violations).toEqual([]);
  await page.keyboard.press('Tab');
  expect(await page.evaluate(() => document.activeElement !== document.body)).toBe(true);
});

test('mobile and tablet reflow without viewport overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { state } = await setup(page); state.positions = [position()]; await login(page);
  await expect(page.getByText('Execution feed live')).toBeVisible();
  await page.screenshot({ path: 'test-results/terminal-mobile.png', fullPage: true });
  for (const width of [360, 390, 768, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
});

test('socket heartbeat loss disables trading even if last quote was fresh', async ({ page }) => {
  await setup(page, { noSocket: true }); await login(page);
  await expect(page.getByRole('button', { name: /Review paper long/ })).toBeDisabled();
  await expect(page.getByText('Trading and live valuation are paused.', { exact: false })).toBeVisible();
});

test('news strip, news page filters, hostile content and accessibility', async ({ page }) => {
  const { newsRequests } = await setup(page); await login(page);
  const strip = page.getByRole('region', { name: 'Latest BTC news' });
  await expect(strip.getByRole('link', { name: /Bitcoin climbs past resistance/ })).toBeVisible();
  await expect(strip.getByRole('link', { name: /Ethereum fees fall/ })).toHaveCount(0);
  await page.getByLabel('Trading market').selectOption('ETH/USDT:USDT');
  await expect(page.getByRole('region', { name: 'Latest ETH news' }).getByRole('link', { name: /Ethereum fees fall/ })).toBeVisible();
  await page.getByLabel('Trading market').selectOption('BTC/USDT:USDT');
  await page.getByRole('button', { name: /View all/ }).click();
  await expect(page.getByRole('heading', { name: 'Crypto news', level: 1 })).toBeVisible();
  await expect(page.getByLabel(/Related to BTC\/USDT/)).toBeChecked();
  expect(newsRequests.at(-1)).toContain('symbol=BTC%2FUSDT%3AUSDT');
  await page.getByLabel(/Related to BTC\/USDT/).uncheck();
  const hostile = page.getByText('<img src=x onerror="window.pwned=1">Solana upgrade');
  await expect(hostile).toBeVisible();
  await expect(page.locator('.news-list img, .news-list script')).toHaveCount(0);
  await expect(page.locator('.news-list a[href^="javascript"]')).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as { pwned?: number }).pwned)).toBeUndefined();
  const link = page.getByRole('link', { name: /Bitcoin climbs past resistance/ });
  await expect(link).toHaveAttribute('target', '_blank');
  await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  await page.getByLabel('Source').selectOption('Decrypt');
  await expect(page.getByRole('link', { name: /Bitcoin climbs/ })).toHaveCount(0);
  await page.getByLabel('Search headlines').fill('ethereum');
  await expect(page.getByRole('link', { name: /Ethereum fees fall/ })).toBeVisible();
  await expect(page.getByText(/Solana upgrade/)).toHaveCount(0);
  expect(newsRequests.at(-1)).toBe('?source=Decrypt&q=ethereum&limit=20&offset=0');
  await page.getByLabel('Search headlines').fill('');
  await page.getByLabel('Source').selectOption('');
  await page.screenshot({ path: 'test-results/news-desktop.png', fullPage: true });
  const scan = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(scan.violations).toEqual([]);
  for (const width of [360, 768]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await page.screenshot({ path: 'test-results/news-mobile.png', fullPage: true });
});

test('Hermes controls: pause blocks entries, resume needs confirmation, badge and a11y', async ({ page }) => {
  const { state } = await setup(page);
  const agentCalls: string[] = [];
  state.agent = agentState({ paused: false, open_positions: 1 });
  state.positions = [{ ...position(), actor: 'agent', notes: 'Breakout with volume' }];
  await page.route('**/api/v1/config', route => route.fulfill({ json: { ...config, hermes: 'active', agent: agentLimits } }));
  await page.route('**/api/v1/agent/*', async route => {
    const path = new URL(route.request().url()).pathname; agentCalls.push(path);
    if (path.endsWith('/pause')) state.agent = agentState({ paused: true, pause_reason: 'Paused from the terminal' });
    if (path.endsWith('/resume')) state.agent = agentState({ paused: false });
    if (path.endsWith('/orders')) return route.fulfill({ status: 409, json: { error: { code: 'agent_paused', message: 'Hermes is paused by the operator' } } });
    return route.fulfill({ json: state.agent });
  });
  await login(page);
  const bar = page.getByRole('region', { name: 'Hermes agent' });
  await expect(bar.getByRole('status')).toHaveText('Active');
  await expect(page.locator('.positions-table .actor-badge')).toHaveText('HERMES');
  await bar.getByRole('button', { name: /Pause Hermes/ }).click();
  await expect(bar.getByRole('status')).toHaveText('Paused');
  expect(agentCalls).toEqual(['/api/v1/agent/pause']);
  const agentOrder = await page.evaluate(async () => (await fetch('/api/v1/agent/orders', { method: 'POST', headers: { Authorization: 'Bearer agent' } })).json());
  expect(agentOrder.error.code).toBe('agent_paused');
  await bar.getByRole('button', { name: /Resume Hermes/ }).click();
  const dialog = page.getByRole('dialog', { name: 'Resume Hermes?' });
  await expect(dialog.getByText('Required on every entry')).toBeVisible();
  expect((await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()).violations).toEqual([]);
  await dialog.getByRole('button', { name: 'Resume Hermes' }).click();
  await expect(bar.getByRole('status')).toHaveText('Active');
  await page.screenshot({ path: 'test-results/hermes-bar.png' });
  const scan = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(scan.violations).toEqual([]);
  for (const width of [360, 768]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await page.screenshot({ path: 'test-results/hermes-mobile.png', fullPage: true });
});

test('invalid token returns an actionable error', async ({ page }) => {
  await setup(page);
  await page.getByLabel('Local API token').fill('wrong-token-that-is-long-enough-but-invalid');
  await page.getByRole('button', { name: 'Connect to paper engine' }).click();
  await expect(page.getByRole('alert')).toContainText('token rejected');
  await expect(page.getByRole('heading', { name: 'Connect your terminal' })).toBeVisible();
});
