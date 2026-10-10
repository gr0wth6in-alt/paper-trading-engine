from decimal import Decimal

from paper_engine.models import Journal, Position


def journal_for(position: Position) -> Journal:
    total_fees = position.entry_fee + position.exit_fee
    opener = "Hermes agent" if position.actor == "agent" else "Operator"
    summary = (
        f"{position.side.title()} {position.symbol} closed via {position.exit_reason}. "
        f"Net paper PnL: {position.net_pnl:.8f} USDT; "
        f"fees: {total_fees:.8f} USDT. Opened by {opener}. AI review is disabled."
    )
    return Journal(
        trade_id=position.id,
        created_at=position.closed_at,
        local_summary=summary,
        metrics={
            "trade": position.model_dump(mode="json"),
            "actor": position.actor,
            "entry_rationale": position.notes,
            "exit_rationale": position.exit_notes,
            "total_fees_usdt": str(total_fees),
            "return_on_margin_pct": str(position.net_pnl / position.margin * 100),
            "duration_seconds": str(
                Decimal(str((position.closed_at - position.opened_at).total_seconds()))
            ),
            "entry_slippage_bps": str(
                (position.entry_price - position.entry_reference_price)
                / position.entry_reference_price
                * 10000
                * (1 if position.side == "long" else -1)
            ),
            "exit_slippage_bps": str(
                (position.exit_price - position.exit_reference_price)
                / position.exit_reference_price
                * 10000
                * (-1 if position.side == "long" else 1)
            ),
            "limitations": [
                "Simulated fills, not actual exchange execution",
                "No funding, queue priority, market impact feedback, or exchange-exact liquidation",
                "No psychological inference without recorded trader context",
            ],
        },
    )
