# Verification notes

## Hermes autonomous agent and VPS deployment — 2026-10-10

Spec: `docs/superpowers/specs/2026-10-10-hermes-agent.md`. Guide: `DEPLOYMENT.md`.

- Dependency: `mcp==2.3.0` as the optional `agent` extra (uses the pinned `httpx2`).
  `requirements.lock` matches `pip freeze`; `pip check` clean.
- Backend: **286 passed, 3 skipped** (`bash -n` checks run only on Linux) with
  `-W error::DeprecationWarning`; Ruff lint and format clean. New coverage: operator/agent
  route matrix and WebSocket rejection, settings validation, `configure --agent-token`,
  schema v1→v2 migration, pause/resume persistence, cooldown boundary (899 s vs 900 s),
  daily breaker on realized and unrealized loss with UTC reset, stale-quote fail-closed,
  1% risk cap boundary (93.90 rejected vs 93.91 needed), stop beyond liquidation, ownership,
  idempotent replays, close-all partial failures, MCP tool list, schema validation before
  any HTTP call, structured errors, loopback-only engine URL, HTTP mode bearer token,
  Hermes kit tool names, deploy unit files and guide references.
- A temporary copy of the real `data/paper-apex.db` migrated v1→v2 with identical row
  counts and wallet. Test isolation: stray `PAPER_*` shell variables no longer affect tests.
- MCP over real stdio against a running engine (temporary database): 8 tools listed;
  `get_guardrails` reported paused and a 100 USDT risk cap on 10,000 USDT.
- Frontend: **35 Vitest tests**, TypeScript and production build passed; **13 Playwright
  tests in Edge**, including the Hermes bar (pause, confirmed resume, HERMES badge), axe
  WCAG 2.1 AA scans and no overflow at 360/768 px.
- `deploy/package-release.ps1` produced a 0.4 MB archive with `frontend/dist`; it contained
  no `.env`, `data/`, databases, `.venv` or `node_modules`.
- Python 3.13 (target VPS: Debian 13.4, Python 3.13.5): `pip download --only-binary`
  found cp313/abi3 wheels for all 64 pinned Linux packages (plus uvloop) on both
  manylinux x86_64 and aarch64. A temporary Python 3.13.9 venv installed
  `requirements.lock` and ran the backend suite on Windows: **286 passed, 3 skipped** with
  `-W error::DeprecationWarning`.
- **Not verified here:** anything on the VPS (OS image, how SumoPod runs Hermes, systemd
  sandbox, swap, ApeX reachability from the VPS region, Hermes loading the MCP server and
  skill). `DEPLOYMENT.md` steps 0, 9 and 12 check these on the server.

## Crypto news feed — 2026-10-10

Spec: `docs/superpowers/specs/2026-10-10-news-feed.md` (includes the dependency decision).

- Dependencies: `httpx2==2.13.1` (moved to runtime and pinned) and `feedparser==6.0.14`
  (+ `feedparser-sgmllib==2.1.0`). `httpx2` was checked and is legitimate: it is the
  maintained httpx fork that Starlette 1.7's TestClient imports. Unused legacy
  `httpx`/`httpcore` were uninstalled. `requirements.lock` matches `pip freeze`; `pip check` clean.
- Backend: **202 tests passed** with `-W error::DeprecationWarning`; Ruff lint and format
  passed. New tests cover config validation, HTML/entity/XXE handling, unsafe links,
  tagging, per-source backoff, 304s, size caps, insecure redirects, timeouts, parser
  process isolation and replacement, API auth/validation/503, lifespan shutdown, and the
  store-lock release when startup fails.
- Frontend: **30 Vitest tests** (including a source scan that forbids raw-HTML injection
  APIs) and **12 Playwright tests in Edge** (`PLAYWRIGHT_CHANNEL=msedge`) passed, including
  an axe WCAG 2.1 AA scan of the News view and no horizontal overflow at 360/768 px.
  `npm run build` succeeded.
- Event-loop lag: in a live poll with feeds parsed in a thread, the loop stalled for up to
  338 ms, because feedparser holds the GIL. Parsing moved to a spawned worker process, and
  the CA-loading client setup moved to a thread. Repeated live polls then measured
  28–39 ms maximum lag, the same as polls that skipped parsing (26–42 ms of network work).
- Live: all 7 default sources returned items (131–167 total). CryptoPotato returned HTTP
  429 after repeated runs and backed off on its own. A real server on a temporary DB served
  `/api/v1/news` (401 without token), and the payload decoded as UTF-8 with no markup.
  After the server was stopped, no orphaned worker processes remained.

## Project relocation — 2026-10-10

- Moved the entire project to `C:\Users\Sulihin\Videos\New folder\paper-trading-engine`.
  The destination was empty; no existing destination files were overwritten. The former
  workspace project directory no longer exists.
- Before/after inventories matched: 21,597 files, 1,447 directories, approximately 344.6 MiB.
  SHA-256 checks matched for 124 project/data/artifact files, including the private `.env`
  and databases. Dependency/cache contents were checked by relative path and file size.
- Refreshed Python environment activation files, installed console launchers and editable
  package paths without upgrading dependencies. Verified activation, imports outside the
  project directory, pip/pytest/uvicorn launchers, and absence of the old root in those files.
- From the new location: 132 pytest tests, 10 Vitest tests and 11 Edge browser tests passed.
  Ruff lint/format, pip check and TypeScript/Vite production build returned exit code 0.
  Browser stderr contained only conflicting terminal-colour environment warnings.
- Configuration resolves database, frontend and artwork inside the new project directory.
  ApeX top-35 selection, fee 0.0006 and five-second freshness remain unchanged. Private
  configuration and database checksums also remained unchanged through verification.
- Evidence is saved under this project's `data` directory in `relocation-inventory.log`,
  `relocation-backend.log`/`.err`, and `relocation-frontend.log`/`.err`.
  Historical logs retain their original paths; README and specification/plan roots were updated.
- No live trading server was started by this relocation. Run `start.cmd` from the new folder
  and keep its console open. The earlier token-rotation reminder still applies.

## Top-35 selection, PnL cards and splash — 2026-10-10

### Automated evidence

- Backend: **132 tests passed**. New tests cover startup ranking, empty/stale/crossed books,
  active filtering, invalid volumes, 35-symbol settings, tiny ticks, close-only retention,
  stale REST refresh and identical snapshot liquidity protection. Existing changed books
  with equal-resolution timestamps remain accepted.
- Image tests cover authentication, missing folders, live additions/removals, 5 MiB limit,
  first-50 listing, PNG/JPG/GIF/WebP signatures and MIME types, SVG rejection, Windows
  alternate streams, traversal and linked-file rejection. Signature checking is not a full
  server-side image decoder; browser decoding failures fall back to built-in art.
- Frontend: **10 Vitest tests passed**; TypeScript and production Vite build passed.
  ROE tests cover net/unrealized basis, initial margin, stale/missing values, neutrality,
  default amount privacy and small prices. Order retry tests confirm no splash callback on
  uncertain failure and one callback after confirmed success.
- **11 Edge browser tests passed** in the final full run (40.7 seconds), including the original
  six terminal checks and five sharing/splash checks:
  open/closed sharing, actual PNG magic bytes and 1200×675 dimensions, clipboard denial,
  cancelled native sharing, unsupported browser fallback, stale sharing disabled, history,
  custom-image authentication/preload, decode fallback, timeout/Esc/click dismissal,
  preference across reload, reduced motion, mobile reflow and axe accessibility.
- `pip check`: no broken requirements. No new package dependencies were added.

Tests use fixture prices. Browser-native OS share destinations and the user's installed
clipboard integrations are not end-to-end tested; permission denial/cancellation are exercised.
The entry and PnL screenshots are test artifacts, not live account results. The full browser
run exceeded the tool's 30-second capture limit; its completed output was read from
`frontend/e2e-final.log`, with empty `frontend/e2e-final.err`. Concurrent verification commands
also hit that capture limit; reruns completed with 132 pytest tests, 10 Vitest tests and a
successful build. Ruff lint and format passed across all 27 Python source/test files.

### Bounded live check

Read-only `python -m tests.live_selection_check` used public ApeX data and a temporary
database, without placing any order or reading/modifying the user's trading database.
It selected **35 markets in 25.52 seconds**, then sampled feeds for 30 seconds.
Fresh counts at five-second intervals were **21, 23, 26, 33, 26, 23** of 35. No stderr output.
This is **not** a claim that all 35 remain fresh simultaneously. Quiet books remain blocked
by the unchanged five-second rule. Initial verification with a 24-second deadline timed out;
the later 180-second bounded run completed normally. Logs: `live-selection.log` and
`live-selection.err`. The short check ended; it did not leave a server running.

### Review and configuration

Self-review performed against the approved spec, followed by a code-quality/safety pass
(no subagent tool available). Hallmark gate review scoped to added UI: original charcoal
terminal retained, asymmetric result/art export, no gradients or perpetual motion, signed
PnL and explicit paper labels, native modal focus, reduced-motion override, 44px controls,
desktop/mobile screenshots and automated contrast/accessibility checks. Approved frog imagery
and the brief entry animation are documented exceptions in DESIGN.md, not a terminal redesign.

The workspace `.env` now enables top_volume and count 35. Existing API token, database path,
fee 0.0006 and maximum quote age 5 remain unchanged; secrets were not printed. The previously
exposed token has **not** been rotated: replace it privately before further use.

No Git repository exists here, so no commit, branch, worktree, push or PR was created.
Server-disappearance root cause remains outside this feature scope. Port 8000 was not listening
at the end of checks. Run `start.cmd` yourself and keep its console open for normal use.

## ApeX migration — 2026-10-10

Tested on Windows with the project's Python 3.12 environment and CCXT **4.5.85**.
Use `.venv\Scripts\python.exe`, not the unrelated global Python installation.

### Automated checks

- Backend: **118 tests passed** (100 before migration); Ruff lint and format checks passed
  across all 23 Python source/test files. `pip check` found no broken requirements.
- Regression tests failed before implementation: ApeX depth `100` became `0.100`, settings
  rejected `apex`, and smoke output had the wrong quantity step. They now pass, covering
  BTC/ETH base-unit limits and depth, other exchanges' multipliers, invalid contract sizes,
  ApeX paper fills, stale/disconnected execution rejection, CLI support, and DB binding.
- Existing accounting, authentication, public-method-only adapter, and credential-rejection
  tests remain passing. Production code never uses fixture prices.
- Frontend production build passed; **7 Vitest tests** passed with `--maxWorkers=1`.
  The unconstrained run exceeded the tool's 30-second limit.
- **6 Playwright tests passed** with installed Microsoft Edge. Bundled Chromium was absent.
  An initial Edge launch closed before the first test; a complete rerun passed all six
  without retries. These tests use fixtures, not live market data.

### Public data and quantity units

Live metadata returned 138 USDT linear perpetual markets. Only BTC/ETH were exercised
end-to-end; this is not a claim that all 138 were tested.

| Market | CCXT contractSize | Base step/minimum | Maximum quantity |
| --- | --- | --- | --- |
| BTC/USDT:USDT | 0.001 | 0.001 BTC | 50 BTC |
| ETH/USDT:USDT | 0.01 | 0.01 ETH | 1,000 ETH |

The installed adapter maps `contractSize` from `minOrderSize`, precision from `stepSize`,
and passes precision-formatted amounts directly as order size (source inspection only;
no private method was invoked). The engine shares an ApeX-only multiplier of 1 between
metadata, feed, and smoke normalization. Other exchanges retain contract-size conversion.
REST depth returned 100 levels per side for both symbols, preserving base quantities.
Recheck these adapter conventions when upgrading CCXT.

Both smoke commands passed with three timestamped WebSocket updates each. Quote ages were
approximately 0.62–0.87 seconds, with steps of 0.001 BTC and 0.01 ETH.

The authenticated candle API returned **200 candles for all 12 combinations**:
BTC/ETH × 1m, 5m, 15m, 1h, 4h, 1d. Checks covered sorted unique timestamps, timeframe
alignment, valid OHLC bounds, nonnegative volume, and current or most recently closed
candles allowing the service's 15-second cache. Requests took 0.02–0.44 seconds in that
run, not a latency guarantee. No candle-service changes were necessary.

### Live terminal and two-minute observation

The real FastAPI app served the built terminal on loopback. Health and authenticated status
returned 200; unauthenticated status returned 401. A browser check without network fixtures
confirmed the ApeX label, live BTC/ETH, visible candles, symbol/timeframe switching, no
JavaScript page errors, and no token in browser storage. It made no order requests.
The inspected screenshot is at `frontend/test-results/apex-live-desktop.png` (git-ignored).

A read-only authenticated `/ws` monitor observed both symbols for **120.45 seconds**:

| Market | Snapshots | Unique exchange timestamps | Minimum age | Maximum age |
| --- | --- | --- | --- | --- |
| BTC/USDT:USDT | 120 | 114 | 602.2 ms | 2,439.8 ms |
| ETH/USDT:USDT | 120 | 111 | 619.1 ms | 3,187.0 ms |

All observed snapshots were connected and non-stale with exchange-and-receipt freshness
below five seconds. This samples API snapshots once per second, not every upstream update,
and does not guarantee future availability. The first temporary server stopped during an
earlier attempt; that attempt was not counted as a pass. The successful supervised run
shut down cleanly. Evidence: `data/apex-soak-result.json`, `data/apex-supervised.*.log`.

### Configuration and safety

- `.env` and `.env.example` select `apex` and `data/paper-apex.db`; the implicit code default
  remains OKX for compatibility. The ApeX account has 10,000 virtual USDT and zero positions.
- SHA-256 comparisons confirmed the original `data/paper.db`, WAL, and SHM were unchanged.
- The existing local token was preserved. Simulated taker fee stays **0.0006**, not an
  exchange fee quote. Stale/disconnected execution blocks remain unchanged.
- No wallet, exchange credentials, live execution, VPS access, or Hermes requests were added.

### Reproduce

From the project root:

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check paper_engine tests
.venv\Scripts\python.exe -m ruff format --check paper_engine tests
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -m paper_engine.smoke --exchange apex
.venv\Scripts\python.exe -m paper_engine.smoke --exchange apex --symbol ETH/USDT:USDT
cd frontend
npm run build
npm test -- --maxWorkers=1
$env:PLAYWRIGHT_CHANNEL='msedge'
npm run test:e2e
```

The verification server has stopped. Run `start.cmd` and keep its terminal open for normal
use. Terminal: `/`; API docs: `/docs`. Earlier OKX/Bybit/Binance failures below are historical;
they were not retested during this migration. ApeX connectivity here is not proof of access
in every jurisdiction. Never replace unavailable live data with fixtures or relax safety checks.

## Historical backend checks (before frontend and ApeX migration)

Runtime used: Python 3.12.3 on Windows.

At that stage: **88 tests passed**; Ruff lint and formatting checks passed; all source
modules compiled successfully. `requirements.lock` records the tested dependency versions.

A follow-up connection failure was traced to there being no server process listening on
port 8000. Added `start.cmd` for an explicit local launch and a root redirect to `/docs`.
The backend is not a managed service; keep the launcher terminal open while using it.

The FastAPI server was also started on `127.0.0.1:8000`. `/health` returned 200, protected
account access without a token returned 401, and authenticated status returned 200 with
10,000 virtual USDT and no fabricated quotes. Dependency consistency passed `pip check`.
A real local WebSocket client authenticated successfully and received two successive
paper-account snapshots, with Hermes reported as disabled.

The automated suite exercises paper sizing, accounting, long/short exits, gap liquidation,
depth and precision constraints, stale/disconnected data, idempotency and concurrency,
database rollback and restart recovery, persistent journal jobs, REST authentication,
WebSocket authentication, and feed cancellation/reconnection with fake exchange adapters.
No automated fixture data is used by the production feed.

Public connectivity checks were attempted against OKX, Bybit, and Binance. All timed out
during public market-metadata requests from this environment. Therefore **real exchange
WebSocket delivery has not been verified here**. The checks did not reach the subscription
stage, and no virtual or real orders were sent.

Re-run from a network where the selected exchange is available:

```powershell
.venv\Scripts\python.exe -m paper_engine.smoke --exchange okx
```

Success prints three timestamped public order-book updates. A timeout is a failed smoke
test, not permission to replace prices with fixtures or disable freshness checks.

Hermes integration is deferred. No VPS login, stored admin credentials, or outbound
journaling request is part of this project.