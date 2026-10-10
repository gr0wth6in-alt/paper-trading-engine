# Paper Terminal frontend

React, TypeScript, Vite, Tailwind CSS, Decimal.js, and TradingView Lightweight Charts.
The built app is served by the Python backend at `/`. All fonts, icons, and scripts are
bundled locally; the dashboard does not require a UI CDN.

## Everyday use

From the project root, run `start.cmd` and keep that terminal open. Open
http://127.0.0.1:8000 on the same computer. Paste the `PAPER_API_TOKEN` from the root
`.env` into the connection screen. This is not an exchange key or VPS password.

The token lives only in React memory. Reloading requires reconnecting. Never put it in
`VITE_*` environment variables, source code, screenshots, browser storage, or URLs.
An unresolved order warns before reload; resolve it with **Retry same paper order** or
**Retry same close** to reuse its idempotency key.

The frontend is not a managed Windows service. Chat-started processes are temporary;
launching `start.cmd` yourself avoids relying on those processes surviving a tool call.

## Build and development

```powershell
cd frontend
npm ci
npm run build
```

Or run `build-frontend.cmd` from the project root. Restart the backend after the first build
so it mounts `/assets`. Node is required for building, not for serving the compiled app.

For hot reload, run the backend in one terminal and `npm run dev` here in another.
Vite listens on `127.0.0.1:5173` and proxies REST/WebSocket traffic to port 8000. Add
`http://127.0.0.1:5173` to `PAPER_CORS_ORIGINS` for the development WebSocket and restart
the backend. Production uses same-origin loopback and needs no CORS configuration.

## Behavior

- Initial account and settings are loaded via authenticated REST. The WebSocket then sends
  complete account snapshots every second. A stalled socket or quote disables execution
  and removes floating valuation numbers. Reconnection uses bounded backoff.
- The order ticket defaults to the engine's allocation and leverage configuration. Decimal
  estimates are not fill promises: final depth walking, market precision, risk checks,
  account updates, and PnL remain entirely backend-controlled.
- Entry requires review and confirmation; closing a full position requires confirmation.
  Duplicate clicks are blocked. Network-uncertain retries keep the original request key,
  side, symbol, and payload, with edited inputs and disconnect disabled.
- Execution quotes and exchange OHLCV are separate. The chart requests up to 200 candles,
  refreshes every 20 seconds, and offers 1m/5m/15m/1h/4h/1d. Latest-candle OHLC is also text.
  Current bid/ask snapshots are not used to invent candles. Failed refreshes are labelled.
- History and journal views load 20 records at a time. Metrics are recorded trade facts,
  not invented account performance. Hermes is explicitly disabled.
- Test fixtures exist only in test modules; the production bundle has no demo feed.

## Tests

```powershell
npm test
npx playwright install chromium
npm run test:e2e
```

Browser tests intercept network requests with labelled test fixtures. They verify order
review/submission, close confirmation, missing data, authentication, accessibility, keyboard
focus, and mobile reflow. They are not evidence of live exchange connectivity. Production
must still pass the backend's separate `python -m paper_engine.smoke` connectivity check.

Screenshots from browser tests are written under git-ignored `test-results/`.

## License notice

This product includes TradingView Lightweight Charts, licensed under Apache-2.0.
See [`NOTICE`](NOTICE) and the installed `lightweight-charts/LICENSE` for the required
copyright and license text. Chart attribution and a link to TradingView remain visible in
the app.