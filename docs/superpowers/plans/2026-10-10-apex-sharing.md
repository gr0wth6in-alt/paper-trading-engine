# ApeX market selection and sharing implementation plan

Goal: select 35 active ApeX USDT perpetuals by 24-hour quote volume at startup and add paper-labelled PnL images and an optional entry splash.

Architecture: startup discovery validates public order books before publishing the selected universe. Existing positions outside it remain close-only. Authenticated local image endpoints feed browser Canvas PNG rendering; no new dependencies or external image hosts.

Stack: Python 3.12, FastAPI, CCXT, SQLite, React, TypeScript, decimal.js, Canvas, Vitest, Playwright (Edge).

Root: `C:\Users\Sulihin\Videos\New folder\paper-trading-engine`.
All paths below are relative to this root. This directory has no Git repository; no commits or worktrees will be created.

## Constraints
- Paper-only execution, existing ApeX database, fee 0.0006 and five-second freshness remain unchanged.
- Top 35 at startup, deterministic volume ties, skip inactive/invalid/empty markets; no intraday re-ranking.
- Preserve subscriptions to existing positions; never permit new entries outside the selected list.
- Pace public REST requests explicitly. Failed or stale refreshes cannot renew quote age.
- Original frog artwork by default; user images override by category, served only after authentication.
- Share open and closed trades; ROE = PnL / initial margin * 100, not multiplied by leverage again.
- Closed: net after fees. Open: unrealized before fees, frozen at capture with timestamp.
- Always show paper/simulated label. USDT amount opt-in; no wallet/token/notes/strategy in images.
- Entry splash only after confirmed fill, 1.6 seconds, click/Esc dismiss, persisted opt-out, reduced motion.

## Execution checklist
- [x] Market discovery: failing ranking/depth/startup retention tests; selector kept in feeds.py with config/api integration, close-only retention and quiet REST refresh; regression suite passes.
- [x] Precision: failing format tests, price metadata and small-value chart/table formatting; Vitest and production build pass.
- [x] Images: failing tests/test_memes.py for auth, traversal, signatures, limits, missing files; memes.py and protected endpoints implemented and verified.
- [x] Card model: failing frontend/src/share/card.test.ts for ROE, fees, stale data, privacy, neutral state; Canvas rendering and original frog drawings implemented.
- [x] Share UI: failing browser checks for export and modal behavior; ShareCard connected to positions/history/close confirmation. Fallback and cancellation tested.
- [x] Splash: failing tests for success-only trigger and preload; timeout/dismissal/saved preference verified; EntrySplash and OrderTicket integrated.
- [x] Verify: 132 pytest tests, Ruff lint/format, 10 Vitest tests, TypeScript/Vite build and 11 Edge tests pass. PNG signature/dimensions and accessibility/mobile/fallback flows verified. Read-only ApeX discovery selected 35 markets in 25.52 seconds; fresh feeds varied from 21 to 33 during observation.
- [x] Review: spec and code-quality self-review completed; added UI reviewed against Hallmark gates. README, DESIGN, VERIFICATION, .env.example, local configuration and meme folder instructions updated. No claim of persistent server availability; lifecycle diagnosis remains separate.