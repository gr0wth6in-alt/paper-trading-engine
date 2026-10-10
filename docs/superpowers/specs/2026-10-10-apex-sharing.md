# Approved ApeX selection and sharing specification

Project: `C:\Users\Sulihin\Videos\New folder\paper-trading-engine`.

1. On startup choose 35 active ApeX USDT perpetuals by 24-hour USDT volume. Validate
   metadata and two-sided fresh depth, skipping empty markets. Preserve base-unit quantities,
   isolated accounting, paper-only orders, fee 0.0006, separate ApeX database and five-second
   freshness. No ticker execution. Open positions omitted by ranking stay close-only.
2. Sharing is available from open Positions, closed History and manual close confirmation.
   Render a local 1200×675 PNG with preview, native file sharing where supported, image copy
   and download fallback. Closed ROE is net PnL / margin; open is unrealized PnL / margin.
   Always include the paper/simulated label, basis and capture time. Hide USDT amount by
   default; exclude wallet, token, quantity, strategy and notes. Zero uses neutral grey.
3. Original frog artwork ships in the frontend; user-provided PNG/JPG/WebP/GIF overrides
   by profit/loss/entry category. Limit files to 5 MiB and list at most 50 per category.
   Authenticated APIs only; reject traversal, SVG and links. Refresh without backend restart.
4. A confirmed fill may show a 1.6-second frog splash. Click/Esc dismisses, no click-through,
   reduced-motion disables spatial animation, and a browser-persisted checkbox turns it off.
5. Keep the compact dark terminal; document explicit imagery/motion exceptions in DESIGN.md.
   No exchange credentials, no new external dependencies, no token logging or browser storage.

Server lifecycle investigation is separate. Normal use requires the user to keep start.cmd
open; tool-launched processes are not a persistence mechanism.