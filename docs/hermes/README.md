# Hermes integration kit

Files for connecting a Hermes Agent to the paper engine. Full server setup is in
[`../../DEPLOYMENT.md`](../../DEPLOYMENT.md), section 11.

| File | Purpose |
| --- | --- |
| `config.example.yaml` | `mcp_servers.paper` entry for `~/.hermes/config.yaml` (3 options) |
| `skills/paper-trader/SKILL.md` | The trading procedure Hermes follows each run |
| `../../deploy/hermes-mcp.sh` | Wrapper that loads the agent token from a protected file |

## What Hermes can and cannot do

The MCP server (`python -m paper_engine.mcp_server`) exposes exactly these tools:
`get_overview`, `get_market`, `get_candles`, `get_news`, `get_history`, `get_guardrails`,
`open_position`, `close_position`.

There is no tool to pause, resume, change limits, or touch your manual positions. The engine
enforces every limit itself, whatever Hermes sends:

- one entry per 15 minutes, at most 3 open Hermes positions, leverage ≤ 10×
- a stop-loss on every entry, and loss at the stop ≤ 1% of wallet
- a daily loss breaker at 3% of the start-of-day wallet (UTC), reset at 00:00 UTC
- a fresh database starts **paused**; resume from the terminal's Hermes bar

## Install the skill

```bash
mkdir -p ~/.hermes/skills/finance
cp -r /opt/paper-trading-engine/docs/hermes/skills/paper-trader ~/.hermes/skills/finance/
hermes chat --toolsets skills -q "Show me the paper-trader skill"
```

## Schedule it

```bash
hermes cron create "every 15m" \
  "Run one paper-trading cycle with the paper MCP tools. Follow the skill exactly; doing nothing is fine." \
  --skill paper-trader
hermes cron list
```

Cron runs cannot create more cron jobs (Hermes blocks it).

## LLM cost

Every 15 minutes is about 96 runs a day. Each run makes several tool calls, so pick the
model deliberately and pin a cheaper one for cron only:

```bash
hermes config set cron.model <model-name>
```

Use a longer interval (`"every 30m"`, `"every 1h"`) to cut cost. The engine cooldown stays
at 15 minutes either way.

## Pause and stop

- Terminal: **Pause Hermes** blocks new entries immediately. Stops and targets keep running.
- **Close all Hermes positions** closes only Hermes-owned positions.
- Stop scheduling entirely: `hermes cron list`, then pause or remove the job.
