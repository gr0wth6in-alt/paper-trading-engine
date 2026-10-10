from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class OpenOrder(Model):
    symbol: str = Field(min_length=1, max_length=60)
    side: Literal["long", "short"]
    allocation_pct: Decimal | None = Field(default=None, ge=Decimal("0.02"), le=Decimal("0.05"))
    leverage: int | None = Field(default=None, ge=1, le=20, strict=True)
    stop_loss: Decimal | None = Field(default=None, gt=0, le=Decimal("1e12"))
    take_profit: Decimal | None = Field(default=None, gt=0, le=Decimal("1e12"))
    strategy: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)


REASON_PATTERN = r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$"
STRATEGY_PATTERN = r"^[A-Za-z0-9 ._:/+()-]+$"


class AgentOrder(Model):
    """Entry request from the autonomous agent. Stop-loss and a written reason are required."""

    symbol: str = Field(min_length=1, max_length=60)
    side: Literal["long", "short"]
    allocation_pct: Decimal = Field(ge=Decimal("0.02"), le=Decimal("0.05"))
    leverage: int = Field(ge=1, le=20, strict=True)
    stop_loss: Decimal = Field(gt=0, le=Decimal("1e12"))
    take_profit: Decimal | None = Field(default=None, gt=0, le=Decimal("1e12"))
    reason: str = Field(min_length=20, max_length=2000, pattern=REASON_PATTERN)
    strategy: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=STRATEGY_PATTERN
    )


class AgentClose(Model):
    reason: str = Field(min_length=10, max_length=2000, pattern=REASON_PATTERN)


class AgentControlRequest(Model):
    reason: str | None = Field(default=None, max_length=300, pattern=REASON_PATTERN)


class Position(Model):
    id: str
    exchange: str
    symbol: str
    side: Literal["long", "short"]
    status: Literal["open", "closed"] = "open"
    margin_mode: Literal["isolated"] = "isolated"
    leverage: int
    allocation_pct: Decimal
    allocation_budget: Decimal
    quantity: Decimal
    entry_price: Decimal
    entry_notional: Decimal
    margin: Decimal
    entry_fee: Decimal
    fee_rate: Decimal
    slippage_bps: Decimal
    maintenance_margin_rate: Decimal
    entry_reference_price: Decimal
    entry_quote_age_ms: Decimal
    entry_spread_bps: Decimal
    opened_at: datetime
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    strategy: str | None = None
    notes: str | None = None
    pending_exit_reason: Literal["stop_loss", "take_profit", "liquidation"] | None = None
    triggered_at: datetime | None = None
    exit_price: Decimal | None = None
    exit_fee: Decimal | None = None
    exit_quote_age_ms: Decimal | None = None
    exit_reference_price: Decimal | None = None
    closed_at: datetime | None = None
    exit_reason: Literal["manual", "stop_loss", "take_profit", "liquidation"] | None = None
    gross_pnl: Decimal | None = None
    net_pnl: Decimal | None = None
    isolated_loss_adjustment: Decimal = Decimal("0")
    # v2: who opened the position, and the agent's written exit rationale.
    actor: Literal["operator", "agent"] = "operator"
    exit_notes: str | None = Field(default=None, max_length=2000)


class Journal(Model):
    trade_id: str
    created_at: datetime
    status: Literal["pending"] = "pending"
    provider: Literal["disabled"] = "disabled"
    attempts: int = 0
    local_summary: str
    metrics: dict
    ai_output: None = None


class EngineError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)
