"""Configuration management for Funding Rate Arbitrage Bot."""

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings


# Load environment variables
load_dotenv()


class StrategyConfig(BaseSettings):
    """Strategy configuration."""

    min_funding_rate: float = Field(
        default=0.0003, description="Minimum funding rate per 8h"
    )
    max_spread: float = Field(
        default=0.001, description="Maximum spread between spot and futures"
    )
    position_size_pct: float = Field(
        default=0.1, description="Position size as percentage of equity"
    )
    max_positions: int = Field(default=5, description="Maximum concurrent positions")
    recheck_interval: int = Field(default=300, description="Recheck interval in seconds")


class RiskConfig(BaseSettings):
    """Risk management configuration."""

    max_coin_allocation: float = Field(
        default=0.2, description="Max allocation per coin"
    )
    margin_ratio_warning: float = Field(
        default=0.7, description="Margin ratio warning threshold"
    )
    margin_ratio_critical: float = Field(
        default=0.85, description="Margin ratio critical threshold"
    )
    min_liquidation_distance: float = Field(
        default=0.15, description="Minimum liquidation distance"
    )
    max_drawdown: float = Field(
        default=0.1, description="Maximum drawdown before pausing"
    )


class TradingConfig(BaseSettings):
    """Trading configuration."""

    prefer_limit_orders: bool = Field(default=True, description="Prefer limit orders")
    limit_order_timeout: int = Field(
        default=30, description="Limit order timeout in seconds"
    )
    default_leverage: int = Field(default=1, description="Default futures leverage")
    min_order_value: float = Field(default=10, description="Minimum order value in USDT")


class FiltersConfig(BaseSettings):
    """Filters configuration."""

    min_volume_24h: float = Field(default=10000000, description="Minimum 24h volume")
    min_open_interest: float = Field(
        default=5000000, description="Minimum open interest"
    )
    excluded_symbols: list[str] = Field(
        default_factory=lambda: ["USDCUSDT", "BUSDUSDT", "TUSDUSDT"],
        description="Excluded symbols",
    )


class NotificationsConfig(BaseSettings):
    """Notifications configuration."""

    telegram_enabled: bool = Field(default=False, description="Enable Telegram")
    notify_on_open: bool = Field(default=True, description="Notify on position open")
    notify_on_close: bool = Field(default=True, description="Notify on position close")
    notify_on_risk_warning: bool = Field(default=True, description="Notify on risk warning")
    daily_summary_time: str = Field(default="08:00", description="Daily summary time")


class DashboardConfig(BaseSettings):
    """Dashboard configuration."""

    enabled: bool = Field(default=True, description="Enable dashboard")
    host: str = Field(default="0.0.0.0", description="Dashboard host")
    port: int = Field(default=8000, description="Dashboard port")
    refresh_interval: int = Field(default=30, description="Refresh interval")


class LoggingConfig(BaseSettings):
    """Logging configuration."""

    level: str = Field(default="INFO", description="Log level")
    log_to_file: bool = Field(default=True, description="Log to file")
    log_file: str = Field(default="logs/funding_bot.log", description="Log file path")
    max_file_size: int = Field(default=10, description="Max log file size in MB")
    backup_count: int = Field(default=5, description="Number of backup files")


class Config(BaseSettings):
    """Main configuration class."""

    # Binance API credentials from environment
    binance_api_key: str = Field(default="", description="Binance API key")
    binance_api_secret: str = Field(default="", description="Binance API secret")
    binance_testnet: bool = Field(default=False, description="Use testnet")

    # Telegram credentials from environment
    telegram_bot_token: str = Field(default="", description="Telegram bot token")
    telegram_chat_id: str = Field(default="", description="Telegram chat ID")

    # Database
    database_url: str = Field(
        default="sqlite:///./funding_bot.db", description="Database URL"
    )

    # Sub-configurations
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    model_config = {
        "env_prefix": "",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @classmethod
    def from_yaml(cls, config_path: str | Path) -> "Config":
        """Load configuration from YAML file."""
        config_path = Path(config_path)
        if not config_path.exists():
            return cls()

        with open(config_path) as f:
            yaml_config = yaml.safe_load(f) or {}

        return cls._from_dict(yaml_config)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> "Config":
        """Create config from dictionary."""
        # Extract sub-configs
        strategy_data = data.pop("strategy", {})
        risk_data = data.pop("risk", {})
        trading_data = data.pop("trading", {})
        filters_data = data.pop("filters", {})
        notifications_data = data.pop("notifications", {})
        dashboard_data = data.pop("dashboard", {})
        logging_data = data.pop("logging", {})

        # Create sub-config objects
        strategy = StrategyConfig(**strategy_data) if strategy_data else StrategyConfig()
        risk = RiskConfig(**risk_data) if risk_data else RiskConfig()
        trading = TradingConfig(**trading_data) if trading_data else TradingConfig()
        filters = FiltersConfig(**filters_data) if filters_data else FiltersConfig()
        notifications = (
            NotificationsConfig(**notifications_data)
            if notifications_data
            else NotificationsConfig()
        )
        dashboard = (
            DashboardConfig(**dashboard_data) if dashboard_data else DashboardConfig()
        )
        logging_config = (
            LoggingConfig(**logging_data) if logging_data else LoggingConfig()
        )

        # Load API keys from environment
        api_key = os.getenv("BINANCE_API_KEY", "")
        api_secret = os.getenv("BINANCE_API_SECRET", "")
        testnet = os.getenv("BINANCE_TESTNET", "false").lower() == "true"
        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        telegram_chat = os.getenv("TELEGRAM_CHAT_ID", "")
        database_url = os.getenv("DATABASE_URL", "sqlite:///./funding_bot.db")

        return cls(
            binance_api_key=api_key,
            binance_api_secret=api_secret,
            binance_testnet=testnet,
            telegram_bot_token=telegram_token,
            telegram_chat_id=telegram_chat,
            database_url=database_url,
            strategy=strategy,
            risk=risk,
            trading=trading,
            filters=filters,
            notifications=notifications,
            dashboard=dashboard,
            logging=logging_config,
        )


def load_config(config_path: str | Path | None = None) -> Config:
    """Load configuration from file or defaults."""
    if config_path:
        return Config.from_yaml(config_path)

    # Try to find config file in standard locations
    possible_paths = [
        Path("config/config.yaml"),
        Path("config.yaml"),
        Path("config/config.yml"),
    ]

    for path in possible_paths:
        if path.exists():
            return Config.from_yaml(path)

    # Return default config
    return Config()
