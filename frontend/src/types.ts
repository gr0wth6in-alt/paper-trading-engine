export type Side = 'long' | 'short';
export interface Config {
  exchange: string; symbols: string[]; mode: 'paper'; margin_mode: 'isolated'; hermes: 'disabled' | 'paused' | 'active';
  agent?: AgentLimits;
  feed_enabled: boolean; default_leverage: number; max_leverage: number;
  default_allocation_pct: string; min_allocation_pct: string; max_allocation_pct: string;
  taker_fee_rate: string; slippage_bps: string; max_quote_age_seconds: number; timeframes: string[];
  news_enabled: boolean;
}
export interface AgentLimits {
  enabled: boolean; min_open_interval_seconds: number; daily_loss_pct: string;
  max_open_positions: number; max_leverage: number; max_risk_per_trade_pct: string;
}
/** Live Hermes guardrail state from the snapshot (`{enabled:false}` when no agent token). */
export interface AgentState {
  enabled: boolean; paused?: boolean; pause_reason?: string | null; changed_at?: string | null;
  changed_by?: string | null; day?: string; daily_pnl?: string | null; daily_loss?: string | null;
  daily_loss_limit?: string; breaker_tripped?: boolean; breaker_resets_at?: string | null;
  valuation_complete?: boolean; cooldown_remaining_seconds?: number; min_open_interval_seconds?: number;
  open_positions?: number; max_open_positions?: number; max_leverage?: number;
  max_risk_per_trade_pct?: string; max_risk_per_trade_usdt?: string; daily_loss_pct?: string;
}
export interface CloseAllResult { closed: Position[]; failed: { id: string; symbol: string; code: string; message: string }[] }
/** Every text field is plain text, already stripped of markup by the backend. */
export interface NewsItem {
  id: string; source: string; title: string; summary: string; url: string;
  published_at: string; symbols: string[];
}
export interface NewsSourceStatus {
  name: string; status: 'pending' | 'ok' | 'error'; error: string | null;
  last_success: string | null; item_count: number;
}
export interface NewsResponse {
  enabled: true; updated_at: string | null; total: number; items: NewsItem[]; sources: NewsSourceStatus[];
}
export interface Market {
  price_tick?: string | null; close_only?: boolean;
  status: string; error: string | null; stale: boolean; age_ms: number | null;
  bid: string | null; ask: string | null; received_at_ms: number | null;
  exchange_timestamp_ms: number | null; freshness_basis: string;
}
export interface Account {
  currency: string; initial_balance: string; wallet_balance: string; reserved_margin: string;
  available_balance: string; unrealized_pnl: string | null; equity: string | null;
  estimated_settlement_equity: string | null; valuation_complete: boolean;
}
export interface Position {
  id: string; exchange: string; symbol: string; side: Side; status: 'open' | 'closed';
  leverage: number; quantity: string; entry_price: string; margin: string; entry_fee: string;
  stop_loss: string | null; take_profit: string | null; opened_at: string;
  closed_at: string | null; exit_price: string | null; exit_fee: string | null;
  exit_reason: string | null; net_pnl: string | null; gross_pnl: string | null;
  strategy: string | null; notes: string | null; pending_exit_reason: string | null;
  triggered_at: string | null; isolated_loss_adjustment: string;
  mark_price?: string | null; unrealized_pnl?: string | null; quote_stale?: boolean;
  blocked_exit?: string | null;
  actor?: 'operator' | 'agent'; exit_notes?: string | null;
}
export interface Journal {
  trade_id: string; created_at: string; status: string; provider: string; local_summary: string;
  attempts: number; ai_output: null;
  metrics: { trade: Position; total_fees_usdt: string; return_on_margin_pct: string;
    duration_seconds: string; entry_slippage_bps: string; exit_slippage_bps: string; limitations: string[];
    actor?: 'operator' | 'agent'; entry_rationale?: string | null; exit_rationale?: string | null };
}
export interface Snapshot {
  type: 'snapshot'; mode: 'paper'; exchange: string; revision: number; timestamp: string;
  account: Account; positions: Position[]; markets: Record<string, Market>;
  journaling: { provider: string; recent: Journal[] };
  agent?: AgentState;
}
export interface Order {
  symbol: string; side: Side; allocation_pct: string; leverage: number;
  stop_loss?: string; take_profit?: string; strategy?: string; notes?: string;
}
export interface Candle {
  time: number; open: number; high: number; low: number; close: number; volume: number; closed: boolean;
}
export interface CandleResponse {
  symbol: string; exchange: string; timeframe: string; source: string;
  fetched_at: string; candles: Candle[];
}