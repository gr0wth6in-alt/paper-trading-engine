from decimal import Decimal
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class NewsSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9 .&'-]*$")
    url: str = Field(max_length=500)

    @field_validator("url")
    @classmethod
    def https_only(cls, value: str) -> str:
        try:
            parts = urlsplit(value)
            parts.port  # noqa: B018 - raises ValueError on an invalid port
        except ValueError as exc:
            raise ValueError("News feed URL is invalid") from exc
        if parts.scheme != "https" or not parts.hostname:
            raise ValueError("News feed URLs must use https")
        if parts.username is not None or parts.password is not None:
            raise ValueError("News feed URLs must not contain credentials")
        return value


DEFAULT_NEWS_SOURCES: tuple[NewsSource, ...] = (
    NewsSource(name="CoinDesk", url="https://www.coindesk.com/arc/outboundfeeds/rss/"),
    NewsSource(name="Cointelegraph", url="https://cointelegraph.com/rss"),
    NewsSource(name="Decrypt", url="https://decrypt.co/feed"),
    NewsSource(name="The Block", url="https://www.theblock.co/rss.xml"),
    NewsSource(name="Bitcoin Magazine", url="https://bitcoinmagazine.com/feed"),
    NewsSource(name="CryptoPotato", url="https://cryptopotato.com/feed/"),
    NewsSource(name="Bitcoinist", url="https://bitcoinist.com/feed/"),
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAPER_", env_file=".env", extra="forbid")

    api_token: SecretStr
    db_path: Path = Path("data/paper.db")
    frontend_dist: Path = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    memes_dir: Path = Path(__file__).resolve().parents[1] / "memes"
    exchange: Literal["binance", "bybit", "okx", "apex"] = "okx"
    symbols: list[str] = Field(default_factory=lambda: ["BTC/USDT:USDT", "ETH/USDT:USDT"])
    symbol_selection: Literal["fixed", "top_volume"] = "fixed"
    top_symbols_count: int = Field(default=35, ge=1, le=35)
    feed_enabled: bool = True
    initial_balance: Decimal = Field(default=Decimal("10000"), gt=0, le=Decimal("1e12"))
    default_leverage: int = Field(default=10, ge=1, le=20)
    max_leverage: int = Field(default=20, ge=1, le=20)
    default_allocation_pct: Decimal = Field(
        default=Decimal("0.02"), ge=Decimal("0.02"), le=Decimal("0.05")
    )
    taker_fee_rate: Decimal = Field(default=Decimal("0.0006"), ge=0, le=Decimal("0.01"))
    slippage_bps: Decimal = Field(default=Decimal("2"), ge=0, le=100)
    maintenance_margin_rate: Decimal = Field(default=Decimal("0.005"), gt=0, le=Decimal("0.02"))
    max_quote_age_seconds: float = Field(default=5, gt=0, le=60)
    feed_idle_timeout_seconds: float = Field(default=30, ge=5, le=120)
    cors_origins: list[str] = Field(default_factory=list)
    max_open_positions: int = Field(default=100, ge=1, le=1000)
    news_enabled: bool = True
    news_feeds: list[NewsSource] = Field(default_factory=lambda: list(DEFAULT_NEWS_SOURCES))
    news_poll_seconds: float = Field(default=300, ge=60, le=3600)
    # Hermes / autonomous agent. Unset token = agent API disabled.
    agent_token: SecretStr | None = None
    agent_min_open_interval_seconds: int = Field(default=900, ge=300, le=86400)
    agent_daily_loss_pct: Decimal = Field(
        default=Decimal("0.03"), ge=Decimal("0.005"), le=Decimal("0.2")
    )
    agent_max_open_positions: int = Field(default=3, ge=1, le=10)
    agent_max_leverage: int = Field(default=10, ge=1, le=20)
    agent_max_risk_per_trade_pct: Decimal = Field(
        default=Decimal("0.01"), ge=Decimal("0.001"), le=Decimal("0.05")
    )

    @field_validator("agent_token", mode="before")
    @classmethod
    def blank_agent_token_disables(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def agent_enabled(self) -> bool:
        return self.agent_token is not None

    @model_validator(mode="after")
    def check_settings(self):
        if len(self.api_token.get_secret_value()) < 32:
            raise ValueError("PAPER_API_TOKEN must contain at least 32 characters")
        if self.api_token.get_secret_value().startswith("replace-with-"):
            raise ValueError("Generate a private PAPER_API_TOKEN before starting")
        if self.agent_token is not None:
            agent = self.agent_token.get_secret_value()
            if len(agent) < 32:
                raise ValueError("PAPER_AGENT_TOKEN must contain at least 32 characters")
            if agent.startswith("replace-with-"):
                raise ValueError("Generate a private PAPER_AGENT_TOKEN before starting")
            if agent == self.api_token.get_secret_value():
                raise ValueError("PAPER_AGENT_TOKEN must differ from PAPER_API_TOKEN")
        if self.agent_max_leverage > self.max_leverage:
            raise ValueError("Agent leverage cap exceeds the configured maximum")
        if self.default_leverage > self.max_leverage:
            raise ValueError("Default leverage exceeds the configured maximum")
        if (
            not self.symbols
            or len(self.symbols) > 35
            or len(set(self.symbols)) != len(self.symbols)
        ):
            raise ValueError("Configure between 1 and 35 unique symbols")
        if self.symbol_selection == "top_volume" and self.exchange != "apex":
            raise ValueError("Top-volume selection is supported only for ApeX")
        if any(not s.endswith("/USDT:USDT") for s in self.symbols):
            raise ValueError("Only USDT-settled linear perpetual symbols are supported")
        if "*" in self.cors_origins:
            raise ValueError("Use explicit CORS origins, never a wildcard")
        if not 1 <= len(self.news_feeds) <= 20:
            raise ValueError("Configure between 1 and 20 news feeds")
        names = [source.name.casefold() for source in self.news_feeds]
        urls = [source.url for source in self.news_feeds]
        if len(set(names)) != len(names) or len(set(urls)) != len(urls):
            raise ValueError("News feed names and URLs must be unique")
        return self
