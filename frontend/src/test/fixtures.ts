import type { AgentLimits, AgentState, Config, NewsResponse, Position, Snapshot } from '../types';

export const token = 'test-only-token-not-a-production-secret-123456';
export const config: Config = {
  exchange: 'okx', symbols: ['BTC/USDT:USDT', 'ETH/USDT:USDT'], mode: 'paper', margin_mode: 'isolated', hermes: 'disabled',
  feed_enabled: true, default_leverage: 10, max_leverage: 20, default_allocation_pct: '0.02',
  min_allocation_pct: '0.02', max_allocation_pct: '0.05', taker_fee_rate: '0.0006', slippage_bps: '2',
  max_quote_age_seconds: 5, timeframes: ['1m', '5m', '15m', '1h', '4h', '1d'], news_enabled: true,
};
export const agentLimits: AgentLimits = {
  enabled: true, min_open_interval_seconds: 900, daily_loss_pct: '0.03', max_open_positions: 3,
  max_leverage: 10, max_risk_per_trade_pct: '0.01',
};
export function agentState(overrides: Partial<AgentState> = {}): AgentState {
  return {
    enabled: true, paused: false, pause_reason: null, changed_at: null, changed_by: 'operator', day: '2026-10-10',
    daily_pnl: '-12.5', daily_loss: '12.5', daily_loss_limit: '300', breaker_tripped: false, breaker_resets_at: null,
    valuation_complete: true, cooldown_remaining_seconds: 0, min_open_interval_seconds: 900, open_positions: 1,
    max_open_positions: 3, max_leverage: 10, max_risk_per_trade_pct: '0.01', max_risk_per_trade_usdt: '100', daily_loss_pct: '0.03',
    ...overrides,
  };
}
export function newsResponse(overrides: Partial<NewsResponse> = {}): NewsResponse {
  return {
    enabled: true, updated_at: new Date().toISOString(), total: 2,
    items: [
      { id: 'n1', source: 'CoinDesk', title: 'Bitcoin climbs past resistance', summary: 'Buyers returned after the open.', url: 'https://www.coindesk.com/markets/btc', published_at: new Date(Date.now() - 5 * 60000).toISOString(), symbols: ['BTC'] },
      { id: 'n2', source: 'Decrypt', title: 'Ethereum fees fall', summary: '', url: 'https://decrypt.co/1/eth', published_at: new Date(Date.now() - 3 * 3600000).toISOString(), symbols: ['ETH'] },
    ],
    sources: [
      { name: 'CoinDesk', status: 'ok', error: null, last_success: new Date().toISOString(), item_count: 1 },
      { name: 'Decrypt', status: 'ok', error: null, last_success: new Date().toISOString(), item_count: 1 },
    ],
    ...overrides,
  };
}
export function snapshot(): Snapshot {
  return {
    type: 'snapshot', mode: 'paper', exchange: 'okx', revision: 1, timestamp: new Date().toISOString(),
    account: { currency: 'USDT', initial_balance: '10000', wallet_balance: '10000', reserved_margin: '0', available_balance: '10000', unrealized_pnl: '0', equity: '10000', estimated_settlement_equity: '10000', valuation_complete: true },
    positions: [], markets: {
      'BTC/USDT:USDT': { status: 'connected', error: null, stale: false, age_ms: 50, bid: '65420.1', ask: '65420.2', received_at_ms: Date.now(), exchange_timestamp_ms: Date.now(), freshness_basis: 'exchange_and_receipt' },
      'ETH/USDT:USDT': { status: 'connected', error: null, stale: false, age_ms: 50, bid: '2640.1', ask: '2640.2', received_at_ms: Date.now(), exchange_timestamp_ms: Date.now(), freshness_basis: 'exchange_and_receipt' },
    }, journaling: { provider: 'disabled', recent: [] },
  };
}
export function position(): Position {
  return {
    id: 'test-position-123', exchange: 'okx', symbol: 'BTC/USDT:USDT', side: 'long', status: 'open',
    leverage: 10, quantity: '0.03', entry_price: '65300', margin: '195.90', entry_fee: '1.1754',
    stop_loss: '63000', take_profit: '69000', opened_at: new Date().toISOString(),
    closed_at: null, exit_price: null, exit_fee: null, exit_reason: null, net_pnl: null, gross_pnl: null,
    strategy: 'test-strategy', notes: 'Recorded test rationale', pending_exit_reason: null,
    triggered_at: null, isolated_loss_adjustment: '0', mark_price: '65420.10', unrealized_pnl: '3.603', quote_stale: false,
  };
}