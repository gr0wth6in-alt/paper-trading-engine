# Approved Hermes autonomous paper-trading specification

Project: `C:\Users\Sulihin\Videos\New folder\paper-trading-engine`.

1. The engine moves to the user's 2 vCPU / 2 GB VPS next to Hermes (SumoPod template),
   runs under systemd as user `paper`, one uvicorn worker on `127.0.0.1:8000`. The UI is the
   prebuilt React app served by FastAPI and reached through `ssh -L`. Hermes uses an
   external LLM API. The VPS starts with a fresh database (`data/paper-hermes.db`).
2. Two tokens: `PAPER_API_TOKEN` (operator: UI, manual trades, pause/resume/close-all,
   WebSocket) and `PAPER_AGENT_TOKEN` (Hermes: read-only GETs and agent trade routes only).
   No agent token means the agent API is disabled.
3. Hermes connects only through the MCP tool server (`python -m paper_engine.mcp_server`,
   stdio by default; token-protected Streamable HTTP for containerised Hermes). Eight tools
   with strict input validation; no pause, resume, config or operator tools.
4. Engine-enforced guardrails, under the execution lock: fresh databases start paused;
   one entry per 900 s; daily loss breaker at 3% of the start-of-day wallet (UTC, realized
   plus unrealized, fail closed on stale quotes, reset at 00:00 UTC); mandatory stop-loss
   that triggers before liquidation; loss at the stop including fees ≤ 1% of wallet (user
   choice); ≤ 3 open Hermes positions; leverage ≤ 10×; Hermes closes only its own
   positions; closes never rate-limited. All limits are configurable via `PAPER_AGENT_*`.
5. Entry and exit reasons are stored on the position and in the journal; every Hermes
   attempt and operator control action is written to a capped `agent_events` audit table.
   Schema version 2 adds `agent_control` and `agent_events`; v1 databases migrate in place.
6. UI: a Hermes bar with status, daily loss, risk cap, Pause (immediate), Resume and Close
   all (confirmed), plus a HERMES badge on positions, history and journal entries.
7. `DEPLOYMENT.md` covers OS detection, Ubuntu 24.04 with 22.04/Debian 12 fallbacks,
   transfer by archive or git, venv, `.env`, swap, systemd, permissions, Hermes setup,
   updates, backups and troubleshooting.

## Dependency decision

`mcp==2.3.0` (official MCP Python SDK) is added as the optional `agent` extra. It requires
`httpx2>=2.10`, matching the pinned `httpx2==2.13.1`. No other new direct dependency.
