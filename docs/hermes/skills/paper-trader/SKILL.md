---
name: paper-trader
description: Run one disciplined paper-trading cycle via the paper MCP
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [trading, paper, mcp]
    category: finance
---

# Paper trader cycle

Everything here is **paper trading**: virtual money and simulated fills on a local engine.
No real order is possible through these tools. Never look for, suggest or use any way to
trade real funds, exchange accounts or API keys.

## When to Use

On every scheduled run (cron, every 15 minutes) and when the user asks for a trading cycle.
One run = one cycle. Do at most one new entry per run.

## Procedure

1. Call `get_guardrails`.
   - If `paused` is true, `breaker_tripped` is true or `can_open_now` is false: do not open
     anything. Only do step 2, then report and stop.
2. Call `get_overview` and review `my_open_positions`.
   - For each position, call `get_market` and, if the thesis may have changed,
     `get_candles` (15m) and `get_news` for that symbol.
   - Close with `close_position` only when the recorded thesis is clearly invalidated.
     Give a concrete `reason` (what changed, with numbers). Stops and targets already run
     inside the engine, so do not close just because of normal noise.
3. If opening is allowed, pick at most 3 candidates from `live_symbols`. For each:
   `get_market` (spread, quote age), `get_candles` on 15m and 1h, `get_news` for the symbol.
4. Open only when the setup is clear. Skip when the spread is wide, quotes are stale, the
   candles are choppy, or news is ambiguous. **Doing nothing is a valid outcome.**
5. Size every entry so the loss at the stop fits `max_risk_per_trade_usdt`:
   - loss at stop ≈ |entry − stop| × quantity, plus about 0.1% of notional in fees.
   - quantity ≈ wallet × allocation_pct × leverage ÷ entry.
   - Start from `allocation_pct` "0.02" and leverage 3–5; tighten the stop or lower leverage
     before raising allocation. Never exceed `max_leverage`.
   - `stop_loss` is required. Place it at the price that invalidates the idea, not at an
     arbitrary percentage. `take_profit` is optional.
6. Call `open_position` with a `reason` of 2–4 sentences: setup, timeframe, the level that
   invalidates it, and the news context. Add a short `strategy` label (e.g. `breakout-15m`).
7. Report: what you checked, what you did or why you did nothing, and current daily loss
   versus `daily_loss_limit`.

## Pitfalls

- Engine errors come back as `{"error": {"code", "message"}}`. Read the message.
  - `agent_risk_limit`: the message states the estimated loss and the maximum; resize once
    (lower leverage or tighter stop) and retry at most once.
  - `agent_cooldown`, `agent_paused`, `agent_daily_loss_limit`, `agent_position_limit`:
    do not retry this run.
  - `agent_stop_beyond_liquidation`: the stop is too far for the leverage; lower leverage.
  - `stale_quote`, `feed_unavailable`, `agent_valuation_unavailable`: market data is not
    live; do nothing this run.
- Never retry an `open_position` call that may have succeeded; call `get_overview` first.
- Do not try to influence the engine limits; they are enforced server-side and the operator
  controls pause and resume from the terminal.

## Verification

`get_overview` shows any new position in `my_open_positions` with the strategy prefix
`hermes:`; its reason appears in the terminal Journal after it closes.
