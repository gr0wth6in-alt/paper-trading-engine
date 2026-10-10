# Paper Trading Engine

A local FastAPI backend and React trading terminal for paper trading on public CCXT Pro order books. All balances,
positions, and fills are virtual. There are no exchange credentials, private API calls, or
real-order routes. An optional Hermes agent can paper-trade through an MCP tool server under
engine-enforced limits (see "Hermes agent"). To run it on a VPS, see [DEPLOYMENT.md](DEPLOYMENT.md).

## Run on Windows

Installed location: `C:\Users\Sulihin\Videos\New folder\paper-trading-engine`.

In this already-installed workspace, double-click **`start.cmd`** and keep its terminal
window open. After it prints `Uvicorn running on http://127.0.0.1:8000`, open
**http://127.0.0.1:8000** on the same computer. This serves the trading frontend.
The launcher leaves startup errors visible rather than closing immediately.

The frontend build is in `frontend/dist`. If missing, `start.cmd` builds it (requires Node.js).
Run `build-frontend.cmd` after frontend source changes. Full frontend development and testing
instructions are in [`frontend/README.md`](frontend/README.md). API docs remain at `/docs`.

Python 3.12 is the tested runtime. From PowerShell in this folder:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m paper_engine.configure
.venv\Scripts\python.exe -m paper_engine
```

The environment and dependencies have already been installed in this workspace. On later
runs, only the final command is needed. Configuration lives in the git-ignored `.env`;
the configure command generates a random token and never overwrites an existing file.
On Linux/macOS, use `python3.12` and `.venv/bin/python` instead.

To reproduce the tested Windows dependency versions instead of resolving newer ones:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.lock
.venv\Scripts\python.exe -m pip install -e . --no-deps
```

`requirements.lock` records the Windows Python 3.12 environment, including test tools;
use `pyproject.toml` for a different platform.

- Trading terminal: `http://127.0.0.1:8000`
- Interactive API documentation: `http://127.0.0.1:8000/docs`
- Liveness: `http://127.0.0.1:8000/health`
- Read-only snapshot stream: `ws://127.0.0.1:8000/ws`

Use **Authorize** in the API documentation with `PAPER_API_TOKEN` from your local `.env`.
The trading terminal has its own connection screen for that same token, held in memory only.
Do not paste tokens into chat or commit them. No VPS/admin-console access is required.

The supplied `.env.example` and this workspace's `.env` select **ApeX Omni** public data,
with startup top-volume selection and `PAPER_DB_PATH=data/paper-apex.db`.
Supported feeds are `apex`, `okx`, `binance`, and `bybit`. Without an explicit exchange
setting, the code retains its original OKX default for compatibility.
Use a different `PAPER_DB_PATH` when changing exchanges; the engine rejects reuse of an
account database for another venue. Run **one process and one worker**, without hot reload.
A file lock prevents two processes from owning the same database.

### ApeX public data and paper execution

`PAPER_SYMBOL_SELECTION=top_volume` selects **35 active USDT linear perpetuals** each startup
by descending 24-hour quote volume (USDT), skipping invalid metadata, stale, empty, one-sided
or crossed books. Public requests are paced; allow roughly 30 seconds or longer before the
server is ready. Startup fails rather than silently accepting fewer valid markets. No intraday
re-ranking occurs. Set `PAPER_SYMBOL_SELECTION=fixed` to use `PAPER_SYMBOLS` instead.
`PAPER_TOP_SYMBOLS_COUNT` can be set from 1 to 35. Other exchanges require fixed selection.

Existing open positions outside the new list retain their subscriptions and appear in Positions,
but are **close-only**. A delisted/unavailable retained market remains blocked, not synthetically
closed. A selected market is not always executable: quiet books may exceed five seconds of age.
Throttled REST depth refresh supplements WebSocket depth; old or identical snapshots never
renew freshness or refill consumed paper liquidity. Neither tickers nor candles execute orders.

### PnL sharing and entry artwork

- **Share** on an open position captures a frozen unrealized result, before fees. Fresh valuation
  is required. Closed trades have Share in History, and manual close confirmation offers Share
  closed result. Closed ROE uses net PnL after fees divided by initial isolated margin.
- The card includes large ROE, pair, side, leverage, entry and mark/exit prices, a UTC capture
  time and **Paper trade · simulated**. It never includes balance, token, quantity, strategy or
  notes. **Show USDT amount** is off by default; ROE is not multiplied by leverage again.
- Download produces a **1200×675 PNG**. Share uses the browser's native file-sharing dialog
  when supported; Copy image requires clipboard support and permission. Download is always
  offered. Cards are generated locally, not uploaded by this application.
- **Entry splash** in the order ticket controls a 1.6-second confirmed-fill overlay. Click or
  press Esc to dismiss. Only this preference is stored in localStorage. Failed/unconfirmed
  requests do not trigger a splash. Reduced-motion users receive a static presentation.
- Built-in original frogs work without files: three profit, three loss and two entry variants,
  plus a neutral drawing. Drop your own art into `memes/profit`, `memes/loss`, or `memes/entry`.
  `PAPER_MEMES_DIR` overrides the root. PNG/JPG/WebP/GIF, up to 5 MiB and 50 listed files per
  category; no SVG or linked paths. Use images you have rights to share; image text is part
  of the exported card and is not privacy-filtered. GIFs export as a still frame.
- Share/Shuffle rescans folders; entry art preloads on connection, after each splash and every
  minute. No restart is needed for file changes. Unreadable images fall back to built-in art.
  Local listing and files require the API token in the Authorization header, never in URLs.

See `memes/README.md` for local artwork instructions.

### News feed

The **News** tab aggregates public RSS/Atom headlines from CoinDesk, Cointelegraph, Decrypt,
The Block, Bitcoin Magazine, CryptoPotato and Bitcoinist. It offers source filter, search,
a "related to current market" filter, relative times and links to the original article.
The Terminal shows the three latest headlines for the selected market under the chart.

- RSS only: no API keys, no scraping. Requests are plain public GETs with no credentials.
- A background task polls every `PAPER_NEWS_POLL_SECONDS` (default 300, range 60–3600)
  and keeps the newest 500 items **in memory only**. Nothing is written to SQLite, so the
  list is empty for a few seconds after each restart.
- Fetching is async with a 10 s request timeout, 2 MiB body cap, https-only redirects and
  conditional requests. Parsing runs in one spawned worker process: feedparser's C-level
  work holds the GIL, so a thread could still stall the trading loop. A hung parser is
  replaced. Each source backs off on its own (5 to 60 minutes) after failures.
- All feed HTML is stripped to plain text on the backend. Only http/https links are kept,
  and tracking parameters are removed. The frontend renders text only and opens links with
  `rel="noopener noreferrer"`.
- Coin tags come from the active symbol list: tickers match case-sensitively (`BTC`, `$ETH`),
  plus a basic name map (Bitcoin, Ethereum/Ether, Solana...). Common-word names such as Near
  or Link are deliberately not matched.
- `PAPER_NEWS_ENABLED=false` disables the poller (the API returns 503 `news_disabled`).
  `PAPER_NEWS_FEEDS` replaces the sources with a JSON list of 1–20 https entries:
  `[{"name":"CoinDesk","url":"https://www.coindesk.com/arc/outboundfeeds/rss/"}]`.
- Publishers may rate-limit (CryptoPotato returned HTTP 429 during repeated testing).
  Failing sources are listed on the News page; healthy sources keep working.

### Hermes agent

Set `PAPER_AGENT_TOKEN` (`python -m paper_engine.configure --agent-token`) to enable the
agent API. Hermes connects through `python -m paper_engine.mcp_server` (install with
`pip install -e ".[agent]"`), which exposes `get_overview`, `get_market`, `get_candles`,
`get_news`, `get_history`, `get_guardrails`, `open_position` and `close_position`. Setup files
are in `docs/hermes/`.

The engine enforces every limit itself, under its execution lock, whatever the client sends:

| Guardrail | Default setting |
| --- | --- |
| Fresh database starts paused; resume in the terminal | — |
| Minimum time between Hermes entries | `PAPER_AGENT_MIN_OPEN_INTERVAL_SECONDS=900` |
| Daily loss breaker (realized + unrealized, UTC day) | `PAPER_AGENT_DAILY_LOSS_PCT=0.03` |
| Loss at the stop-loss, fees included | `PAPER_AGENT_MAX_RISK_PER_TRADE_PCT=0.01` |
| Open Hermes positions / leverage | `PAPER_AGENT_MAX_OPEN_POSITIONS=3`, `PAPER_AGENT_MAX_LEVERAGE=10` |

Every Hermes entry needs a stop-loss (beyond entry and inside liquidation) and a written
reason; closes need a reason too. Both reasons are saved in the journal. Hermes can only
close its own positions, and closes are never rate-limited. If an open Hermes position has
no fresh quote, new entries are blocked because the daily loss cannot be verified. The
terminal's Hermes bar shows status and offers **Pause Hermes**, **Resume Hermes** (with
confirmation) and **Close all Hermes positions**. Manual trading is unaffected.

### Network and quantity conventions

ApeX REST candles and WebSocket books were reachable from the tested local network where
OKX requests timed out. Availability depends on your network and jurisdiction; this is not
a guarantee of access throughout Indonesia or permission to bypass exchange restrictions.
No wallet, signing key, exchange API key, deposit, or live order is needed.

The adapter preserves ApeX quantities in base assets (BTC/ETH). CCXT 4.5.85 reports
`minOrderSize` as ApeX `contractSize`; multiplying depth and amount limits by that value
would incorrectly shrink BTC quantities 1,000-fold and ETH quantities 100-fold. Metadata,
live books, and the smoke command share an ApeX-specific multiplier of 1. Other feeds
retain contract-size conversion. Recheck this convention when updating CCXT.

The previous OKX account at `data/paper.db` is left untouched. The ApeX database is a
separate paper account, not a transfer or reset of the old account. To switch back, stop
the server and restore both `PAPER_EXCHANGE=okx` and `PAPER_DB_PATH=data/paper.db`.
The simulated taker fee remains `0.0006`; it is configurable, not an exchange fee quote.
The five-second stale-quote limit and disconnected-feed execution block still apply.

### If the page cannot load

- **Connection refused / site cannot be reached:** run `start.cmd` and keep the window open.
  The service is not installed as a Windows service and does not automatically restart
  after shutdown, reboot, or the temporary development process ending.
- **Using another device or the VPS:** `127.0.0.1` refers to that device, not this Windows
  computer. Use the browser on the computer running the backend; remote deployment is not
  configured. Do not expose port 8000 publicly as a workaround.
- **Check the server directly:** open `http://127.0.0.1:8000/health`. If it returns JSON but
  `/docs` is blank, the documentation's Swagger UI CDN assets may be blocked. Report that
  distinction; a documentation asset problem is different from a stopped backend.
- **401 from an account endpoint:** the service is reachable but requires the local API token.
- **Docs load but trades return 503:** check `/api/v1/markets`; exchange connectivity is
  separate from loading the local API documentation.

`/health` reports service liveness, not market readiness. Check authenticated
`/api/v1/markets`: execution requires `status: connected` and `stale: false`.
If connectivity is unavailable, the API still runs, but refuses fills. Setting
`PAPER_FEED_ENABLED=false` disables subscriptions; it never enables synthetic prices.

## Trading model

| Setting | Default / supported range |
| --- | --- |
| Virtual starting balance | 10,000 USDT; applied only on first database creation |
| Margin mode | Isolated only |
| Margin allocation | 2% default; 2–5% of current wallet balance per position |
| Leverage | 10× default; 1–20×, bounded by `PAPER_MAX_LEVERAGE` |
| Taker fee | 0.06% per fill, configurable; illustrative, not a live exchange fee tier |
| Additional adverse slippage | 2 basis points per fill |
| Maintenance margin rate | 0.5%, simplified fixed rate |
| Maximum quote age | 5 seconds |
| Open positions | 100 by default; configurable up to 1,000 |

Allocation is **posted margin, not stop-loss risk**. Entry fees are additional, so the
maximum wallet loss in this isolated model is posted margin **plus the entry fee**.
Unrealized profits are not available for new margin. There is no additional portfolio
allocation cap besides available collateral and the position-count limit.

```text
allocation budget = wallet balance × allocation percentage
target notional   = allocation budget × leverage
initial quantity  = target notional / slippage-adjusted best entry-side price
actual margin     = simulated filled notional / leverage
available balance = wallet balance − sum(open isolated margins)
```

The quantity is rounded down to the exchange's base-asset quantity increment. Longs buy
the asks; shorts sell the bids. A volume-weighted fill walks the visible book, then applies
adverse slippage. Long quantities are reduced further when deeper prices would exceed the
allocation budget. Reject the whole order if its initial rounded quantity cannot fit in
visible depth, falls outside exchange size/notional limits, or available funds cannot cover
actual margin plus entry fees. No partial fills are produced.

CCXT derivative depth and quantity precision are normalized from contracts to base-asset
units using the market's contract size. Responses serialize financial decimals as strings;
do not parse them into binary floats for accounting.

### PnL and liquidation

```text
gross PnL = (exit price − entry price) × quantity × direction
direction = +1 for long, −1 for short
exit fee = exit notional × fee rate
settlement = max(gross PnL − exit fee, −isolated margin)
net PnL = settlement − entry fee
```

Wallet balance is debited for the entry fee when opening and updated by settlement when
closing. Margin is reserved, not debited twice. Closed trades store the uncapped gross PnL
and a separate `isolated_loss_adjustment` when synthetic insurance absorbs a gap loss.
Fees, slippage, and maintenance settings are saved on each position and survive restarts
or subsequent configuration changes.

Floating PnL uses the best exit-side quote (bid for longs, ask for shorts). It excludes fees,
depth impact, and slippage. `equity` is wallet plus that gross mark-to-quote PnL.
`estimated_settlement_equity` also estimates exit fees and applies the isolated loss cap,
but still is **not a guaranteed liquidation value**. Missing or stale quotes make aggregate
valuation fields `null`, with `valuation_complete: false`, rather than presenting old prices
as current.

SL/TP are optional entry brackets. They cannot be edited in this MVP. Every accepted fresh
book evaluates triggers against the best exit-side quote. Liquidation takes precedence when:

```text
isolated margin + gross mark-to-quote PnL
    <= current quote notional × (maintenance margin rate + exit fee rate)
```

Triggered exits fill at available depth plus slippage, **not necessarily at the trigger
price**. If there is insufficient depth, the exit remains open and latched in SQLite; it
retries on the next fresh update even if price recovers. Its state is visible as
`pending_exit_reason`, `triggered_at`, and `blocked_exit` in snapshots. Unlatched historical
price crossings during downtime are not reconstructed.

## REST API

All `/api/v1/*` routes require `Authorization: Bearer <token>`. `PAPER_API_TOKEN` (operator)
may call every route below except the two agent trade routes. `PAPER_AGENT_TOKEN` (Hermes)
may call the read-only GET routes, `/agent/state` and the agent trade routes; operator routes
answer it with 403 `forbidden_for_agent`, and it cannot open the WebSocket.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Public process liveness; no balances |
| GET | `/api/v1/status` | Account, open positions, feed state, recent journals |
| GET | `/api/v1/config` | Authenticated, non-secret client settings |
| GET | `/api/v1/candles?symbol=BTC%2FUSDT%3AUSDT&timeframe=5m` | Up to 200 public OHLCV candles |
| GET | `/api/v1/account` | Wallet, margin, equity and valuation completeness |
| GET | `/api/v1/markets` | Best quotes, freshness, connection status |
| GET | `/api/v1/positions` | Open positions with floating PnL |
| POST | `/api/v1/orders` | Open an isolated paper position |
| POST | `/api/v1/positions/{id}/close` | Close an entire paper position |
| GET | `/api/v1/trades?limit=50&offset=0` | Closed positions, newest opening first |
| GET | `/api/v1/journals?limit=50&offset=0` | Local summaries and pending review jobs |
| GET | `/api/v1/news?source=&q=&symbol=&limit=20&offset=0` | In-memory crypto RSS headlines (see News feed) |
| POST | `/api/v1/agent/orders` | Agent token: open a Hermes position (stop-loss and reason required) |
| POST | `/api/v1/agent/positions/{id}/close` | Agent token: close a Hermes position, body `{"reason"}` |
| GET | `/api/v1/agent/state` | Pause, cooldown, daily loss and limits |
| POST | `/api/v1/agent/pause` · `/resume` | Operator: stop or allow new Hermes entries |
| POST | `/api/v1/agent/close-all` | Operator: close every Hermes position |
| GET | `/api/v1/agent/events?limit=50` | Operator: audit log of Hermes attempts |

Both POST routes require a unique `Idempotency-Key` (8–128 characters, letters, digits,
`.`, `_`, `:`, `-`). Repeating an identical successful request returns its original response
without a second execution, including after restart. Reusing a key for another request
returns 409. Failed requests do not reserve their keys. Equivalent decimal spellings should
be kept identical when retrying. A replayed open response describes the original execution,
not necessarily the current position; query `/positions` or `/trades` for current state.

PowerShell example, with the server running in another terminal:

```powershell
$base = "http://127.0.0.1:8000"
$tokenLine = Get-Content .env | Where-Object { $_ -match '^PAPER_API_TOKEN=' }
$token = ($tokenLine -split '=', 2)[1]
$auth = @{ Authorization = "Bearer $token" }

Invoke-RestMethod "$base/api/v1/markets" -Headers $auth

$entryHeaders = $auth.Clone()
$entryHeaders['Idempotency-Key'] = [guid]::NewGuid().ToString()
$body = @{
    symbol = "BTC/USDT:USDT"
    side = "long"
    allocation_pct = "0.02"
    leverage = 10
    strategy = "manual-paper-test"
} | ConvertTo-Json
$position = Invoke-RestMethod "$base/api/v1/orders" -Method Post `
    -Headers $entryHeaders -ContentType "application/json" -Body $body

Invoke-RestMethod "$base/api/v1/positions" -Headers $auth

$closeHeaders = $auth.Clone()
$closeHeaders['Idempotency-Key'] = [guid]::NewGuid().ToString()
Invoke-RestMethod "$base/api/v1/positions/$($position.id)/close" `
    -Method Post -Headers $closeHeaders
Invoke-RestMethod "$base/api/v1/journals" -Headers $auth
```

Optional `stop_loss` and `take_profit` are positive decimal price strings. Long stops must be
below both entry and the current bid; long targets above both. Short brackets are reversed.
Client-specified quantities, execution prices, and `margin_mode: cross` are rejected.

Validation errors return 422; missing authentication 401; unknown positions 404; insufficient
funds/liquidity or conflicting state 409; unavailable or stale market data 503. Engine errors
use `{"error":{"code":"stale_quote","message":"..."}}`; FastAPI validation uses `detail`.

### WebSocket

Connect to `/ws`, then send `{"token":"<PAPER_API_TOKEN>"}` as the first frame within five
seconds. Tokens are never sent in query strings. The server pushes a **complete snapshot
once per second**, not a tick archive or a guaranteed event log. Intermediate feed ticks
and state changes are coalesced; triggers still run on every accepted book. Query REST
history after reconnecting. The stream includes recent journal jobs and a process-local
revision number that resets on restart.

Same-origin loopback browser WebSockets are accepted for the built terminal. Cross-origin
development connections require their exact Origin in `PAPER_CORS_ORIGINS`, for example
`["http://127.0.0.1:5173"]`. The default empty list disables cross-origin REST access.
Non-browser clients can omit Origin. Slow clients are
disconnected, snapshots are not queued, and at most 20 sockets are accepted concurrently.

## Persistence and journaling boundary

SQLite uses WAL, full synchronous commits, foreign keys, and a schema-version check.
Account changes, position updates, and successful idempotency responses commit together.
Each close also inserts its journal job in **the same transaction**. A failure rolls back
the closure instead of losing its review record.

Each job contains an immediate deterministic summary, fill details, fees, net PnL, duration,
return on margin, and slippage measurements. Jobs remain `status: pending`,
`provider: disabled`, `attempts: 0`, and `ai_output: null`. There is deliberately **no worker,
outbound journal request, or fabricated AI analysis** in this version; Hermes trades but does
not write journal reviews. Journals record who opened the trade and Hermes' entry and exit
reasons. A later review adapter can consume these durable jobs without changing execution logic. The job schema
will need worker leasing/retries and validated output when that integration is added.

The database is authoritative; quotes are memory-only and must be reacquired after restart.
Keep every open position's symbol configured or startup will fail. To start a separate paper
account, stop the process and select a new `PAPER_DB_PATH`; changing starting balance alone
does not reset an existing account. Back up the database with SQLite's backup API or after
clean shutdown, not by copying a live WAL database file in isolation.

## Tests and public feed check

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check paper_engine tests
.venv\Scripts\python.exe -m ruff format --check paper_engine tests
.venv\Scripts\python.exe -m paper_engine.smoke --exchange apex
.venv\Scripts\python.exe -m paper_engine.smoke --exchange apex --symbol ETH/USDT:USDT
.venv\Scripts\python.exe -m tests.live_news_check
$env:PAPER_AGENT_TOKEN = "<agent token>"; .venv\Scripts\python.exe -m tests.live_mcp_check
```

`tests.live_mcp_check` starts the MCP server over real stdio against a running engine and
calls only read-only tools.

`tests.live_news_check` is opt-in: it fetches each real RSS source once and reports source
status, tagged counts and the maximum event-loop lag measured during the poll. News tests in
the default suite use `httpx2.MockTransport` and fixture feeds; they make no network requests.

Unit/integration tests use deterministic book fixtures and temporary databases; they make
no exchange, LLM or network requests. The separate, opt-in smoke command loads public market
metadata and reads three real WebSocket updates. It sends no orders and writes no database.

If a public feed times out, check venue availability in your jurisdiction, DNS, firewall,
outbound TLS/WebSocket connectivity, and the system clock. Do not disable TLS validation or
bypass geographic restrictions. Exchange timestamps contribute to quote age when available;
otherwise freshness is receipt-only and the API labels that limitation. A stalled stream is
reconnected with bounded exponential backoff. No zero-latency guarantee is made.

## Limits of this MVP

- No persistent candlestick storage, automatic strategy signals, Pine conversion, funding, inverse
  contracts, spot execution, cross margin, pending limit orders, or partial closes.
- No exchange-exact maintenance tiers, liquidation penalties, mark/index prices, or insurance
  fund accounting. The isolated loss adjustment is a documented simulation assumption.
- Consumed depth cannot be reused within one received snapshot. A later exchange snapshot
  refreshes simulated liquidity; virtual orders never affect the real order book.
- No stop execution while the backend is stopped or the feed is stale/disconnected. Gaps can
  produce worse prices on resumption. A latched trigger survives restart.
- Synchronous SQLite commits briefly block the single event loop. This is a local, low-order-
  rate MVP, not a high-frequency or multi-user matching engine.
- Bind to loopback only. Internet deployment needs a separate authentication, rate-limiting,
  TLS, request-size, backup, and process-supervision review. Do not expose this server as-is.

The project does not use the VPS credentials shared in chat. Rotate that password before
deploying (DEPLOYMENT.md, step 1).