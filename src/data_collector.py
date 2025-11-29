"""Data collector for Binance funding rates and market data."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import ccxt.async_support as ccxt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.config import Config
from src.models import FundingRateHistory

if TYPE_CHECKING:
    from src.paper_trader import PaperTrader


logger = logging.getLogger(__name__)


class FundingRateData:
    """Container for funding rate data."""

    def __init__(
        self,
        symbol: str,
        funding_rate: float,
        predicted_funding_rate: float | None,
        mark_price: float,
        index_price: float,
        next_funding_time: datetime,
        open_interest: float,
        volume_24h: float,
    ):
        self.symbol = symbol
        self.funding_rate = funding_rate
        self.predicted_funding_rate = predicted_funding_rate
        self.mark_price = mark_price
        self.index_price = index_price
        self.next_funding_time = next_funding_time
        self.open_interest = open_interest
        self.volume_24h = volume_24h

    @property
    def apr(self) -> float:
        """Calculate annualized percentage rate from funding rate."""
        # Funding is paid 3 times per day (every 8 hours)
        return self.funding_rate * 3 * 365 * 100

    @property
    def spread(self) -> float:
        """Calculate spread between mark and index price."""
        if self.index_price == 0:
            return 0
        return abs(self.mark_price - self.index_price) / self.index_price

    def __repr__(self) -> str:
        return (
            f"<FundingRateData(symbol={self.symbol}, "
            f"rate={self.funding_rate:.6f}, apr={self.apr:.2f}%)>"
        )


class SpotFuturesSpread:
    """Container for spot/futures spread data."""

    def __init__(
        self,
        symbol: str,
        spot_price: float,
        futures_price: float,
    ):
        self.symbol = symbol
        self.spot_price = spot_price
        self.futures_price = futures_price

    @property
    def spread(self) -> float:
        """Calculate spread percentage."""
        if self.spot_price == 0:
            return 0
        return (self.futures_price - self.spot_price) / self.spot_price

    @property
    def spread_pct(self) -> float:
        """Spread as percentage."""
        return self.spread * 100


class DataCollector:
    """Collects funding rates and market data from Binance."""

    def __init__(self, config: Config, paper_trader: PaperTrader | None = None):
        self.config = config
        self._exchange: ccxt.binance | None = None
        self._futures_exchange: ccxt.binanceusdm | None = None
        self._paper_trader = paper_trader

    async def initialize(self) -> None:
        """Initialize exchange connections."""
        # Initialize spot exchange
        self._exchange = ccxt.binance(
            {
                "apiKey": self.config.binance_api_key,
                "secret": self.config.binance_api_secret,
                "sandbox": self.config.binance_testnet,
                "enableRateLimit": True,
                "options": {
                    "defaultType": "spot",
                    "adjustForTimeDifference": True,
                    "recvWindow": 60000,
                },
            }
        )

        # Initialize futures exchange
        self._futures_exchange = ccxt.binanceusdm(
            {
                "apiKey": self.config.binance_api_key,
                "secret": self.config.binance_api_secret,
                "sandbox": self.config.binance_testnet,
                "enableRateLimit": True,
                "options": {
                    "adjustForTimeDifference": True,
                    "recvWindow": 60000,
                },
            }
        )

        # Load time difference from server
        await self._exchange.load_time_difference()
        await self._futures_exchange.load_time_difference()

        logger.info("Exchange connections initialized")

    async def close(self) -> None:
        """Close exchange connections."""
        if self._exchange:
            await self._exchange.close()
        if self._futures_exchange:
            await self._futures_exchange.close()
        logger.info("Exchange connections closed")

    def set_paper_trader(self, paper_trader: PaperTrader | None) -> None:
        """Set the paper trader instance.

        Args:
            paper_trader: PaperTrader instance
        """
        self._paper_trader = paper_trader

    @property
    def paper_trader(self) -> PaperTrader | None:
        """Get the paper trader instance.

        Returns:
            PaperTrader instance or None if not set
        """
        return self._paper_trader

    @property
    def exchange(self) -> ccxt.binance:
        """Get spot exchange instance."""
        if not self._exchange:
            raise RuntimeError("Exchange not initialized. Call initialize() first.")
        return self._exchange

    @property
    def futures_exchange(self) -> ccxt.binanceusdm:
        """Get futures exchange instance."""
        if not self._futures_exchange:
            raise RuntimeError("Futures exchange not initialized. Call initialize() first.")
        return self._futures_exchange

    async def get_all_funding_rates(self) -> list[FundingRateData]:
        """Get funding rates for all USDT perpetual pairs."""
        try:
            # Fetch all premium index data (includes funding rates)
            premium_index = await self.futures_exchange.fapiPublicGetPremiumIndex()

            # Fetch 24h ticker for volume data
            tickers = await self.futures_exchange.fetch_tickers()

            funding_data = []
            for item in premium_index:
                symbol = item["symbol"]

                # Filter for USDT pairs only
                if not symbol.endswith("USDT"):
                    continue

                # Skip excluded symbols
                if symbol in self.config.filters.excluded_symbols:
                    continue

                # Get volume from tickers
                ccxt_symbol = symbol.replace("USDT", "/USDT:USDT")
                ticker = tickers.get(ccxt_symbol, {})
                volume_24h = float(ticker.get("quoteVolume", 0) or 0)

                # Apply volume filter
                if volume_24h < self.config.filters.min_volume_24h:
                    continue

                funding_rate = float(item.get("lastFundingRate", 0) or 0)
                mark_price = float(item.get("markPrice", 0) or 0)
                index_price = float(item.get("indexPrice", 0) or 0)

                # Parse next funding time
                next_funding_ts = int(item.get("nextFundingTime", 0))
                next_funding_time = datetime.fromtimestamp(next_funding_ts / 1000)

                # Get open interest
                try:
                    oi_data = await self.futures_exchange.fapiPublicGetOpenInterest(
                        {"symbol": symbol}
                    )
                    open_interest = float(oi_data.get("openInterest", 0)) * mark_price
                except (ccxt.ExchangeError, KeyError):
                    open_interest = 0

                # Apply open interest filter
                if open_interest < self.config.filters.min_open_interest:
                    continue

                funding_data.append(
                    FundingRateData(
                        symbol=symbol,
                        funding_rate=funding_rate,
                        predicted_funding_rate=None,  # Will be calculated
                        mark_price=mark_price,
                        index_price=index_price,
                        next_funding_time=next_funding_time,
                        open_interest=open_interest,
                        volume_24h=volume_24h,
                    )
                )

            logger.info(f"Fetched funding rates for {len(funding_data)} pairs")
            return funding_data

        except ccxt.ExchangeError as e:
            logger.error(f"Exchange error fetching funding rates: {e}")
            return []

    async def get_funding_rate(self, symbol: str) -> FundingRateData | None:
        """Get funding rate for a specific symbol."""
        try:
            # Get premium index for the symbol
            premium_index = await self.futures_exchange.fapiPublicGetPremiumIndex(
                {"symbol": symbol}
            )

            # Get ticker for volume
            ccxt_symbol = symbol.replace("USDT", "/USDT:USDT")
            ticker = await self.futures_exchange.fetch_ticker(ccxt_symbol)
            volume_24h = float(ticker.get("quoteVolume", 0) or 0)

            funding_rate = float(premium_index.get("lastFundingRate", 0) or 0)
            mark_price = float(premium_index.get("markPrice", 0) or 0)
            index_price = float(premium_index.get("indexPrice", 0) or 0)

            next_funding_ts = int(premium_index.get("nextFundingTime", 0))
            next_funding_time = datetime.fromtimestamp(next_funding_ts / 1000)

            # Get open interest
            oi_data = await self.futures_exchange.fapiPublicGetOpenInterest(
                {"symbol": symbol}
            )
            open_interest = float(oi_data.get("openInterest", 0)) * mark_price

            return FundingRateData(
                symbol=symbol,
                funding_rate=funding_rate,
                predicted_funding_rate=None,
                mark_price=mark_price,
                index_price=index_price,
                next_funding_time=next_funding_time,
                open_interest=open_interest,
                volume_24h=volume_24h,
            )

        except ccxt.ExchangeError as e:
            logger.error(f"Error fetching funding rate for {symbol}: {e}")
            return None

    async def get_spot_futures_spread(self, symbol: str) -> SpotFuturesSpread | None:
        """Get spot/futures spread for a symbol."""
        try:
            # Convert symbol for CCXT
            base = symbol.replace("USDT", "")
            spot_symbol = f"{base}/USDT"
            futures_symbol = f"{base}/USDT:USDT"

            # Fetch both prices concurrently
            spot_ticker, futures_ticker = await asyncio.gather(
                self.exchange.fetch_ticker(spot_symbol),
                self.futures_exchange.fetch_ticker(futures_symbol),
            )

            spot_price = float(spot_ticker.get("last", 0) or 0)
            futures_price = float(futures_ticker.get("last", 0) or 0)

            return SpotFuturesSpread(
                symbol=symbol,
                spot_price=spot_price,
                futures_price=futures_price,
            )

        except (ccxt.ExchangeError, ccxt.BadSymbol) as e:
            logger.error(f"Error fetching spread for {symbol}: {e}")
            return None

    async def get_historical_funding_rates(
        self,
        symbol: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get historical funding rates for a symbol."""
        try:
            # Use Binance API directly for funding history
            funding_history = await self.futures_exchange.fapiPublicGetFundingRate(
                {"symbol": symbol, "limit": limit}
            )

            return [
                {
                    "symbol": item["symbol"],
                    "funding_rate": float(item["fundingRate"]),
                    "funding_time": datetime.fromtimestamp(
                        int(item["fundingTime"]) / 1000
                    ),
                    "mark_price": float(item.get("markPrice", 0) or 0),
                }
                for item in funding_history
            ]

        except ccxt.ExchangeError as e:
            logger.error(f"Error fetching historical funding for {symbol}: {e}")
            return []

    async def save_funding_rate_history(
        self,
        session: AsyncSession,
        funding_data: list[FundingRateData],
    ) -> None:
        """Save funding rate data to database."""
        now = datetime.utcnow()

        for data in funding_data:
            # Check if we already have this data point
            stmt = select(FundingRateHistory).where(
                FundingRateHistory.symbol == data.symbol,
                FundingRateHistory.funding_time >= now - timedelta(minutes=5),
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if not existing:
                history = FundingRateHistory(
                    symbol=data.symbol,
                    funding_rate=data.funding_rate,
                    funding_time=now,
                    mark_price=data.mark_price,
                )
                session.add(history)

        await session.commit()
        logger.debug(f"Saved funding rate history for {len(funding_data)} symbols")

    async def get_account_balance(self) -> dict[str, float]:
        """Get account balances for spot and futures.

        Returns paper trading balance if paper_trading is enabled.
        """
        # Use paper trader balance if in paper trading mode
        if self.config.trading.paper_trading and self._paper_trader is not None:
            return await self._paper_trader.get_balance()

        try:
            spot_balance = await self.exchange.fetch_balance()
            futures_balance = await self.futures_exchange.fetch_balance()

            # Get USDT balances
            spot_usdt = float(spot_balance.get("USDT", {}).get("free", 0) or 0)
            spot_usdt_total = float(spot_balance.get("USDT", {}).get("total", 0) or 0)

            futures_usdt = float(futures_balance.get("USDT", {}).get("free", 0) or 0)
            futures_usdt_total = float(
                futures_balance.get("USDT", {}).get("total", 0) or 0
            )

            return {
                "spot_free": spot_usdt,
                "spot_total": spot_usdt_total,
                "futures_free": futures_usdt,
                "futures_total": futures_usdt_total,
                "total_equity": spot_usdt_total + futures_usdt_total,
            }

        except ccxt.ExchangeError as e:
            logger.error(f"Error fetching account balance: {e}")
            return {
                "spot_free": 0,
                "spot_total": 0,
                "futures_free": 0,
                "futures_total": 0,
                "total_equity": 0,
            }

    async def get_futures_positions(self) -> list[dict[str, Any]]:
        """Get all open futures positions."""
        try:
            positions = await self.futures_exchange.fetch_positions()

            return [
                {
                    "symbol": pos["symbol"],
                    "side": pos["side"],
                    "contracts": float(pos.get("contracts", 0) or 0),
                    "notional": float(pos.get("notional", 0) or 0),
                    "unrealized_pnl": float(pos.get("unrealizedPnl", 0) or 0),
                    "leverage": int(pos.get("leverage", 1) or 1),
                    "liquidation_price": float(
                        pos.get("liquidationPrice", 0) or 0
                    ),
                    "margin_ratio": float(pos.get("marginRatio", 0) or 0),
                }
                for pos in positions
                if float(pos.get("contracts", 0) or 0) != 0
            ]

        except ccxt.ExchangeError as e:
            logger.error(f"Error fetching futures positions: {e}")
            return []

    async def get_margin_ratio(self) -> float | None:
        """Get current margin ratio for futures account.

        Returns 0.0 for paper trading mode (no real margin).
        """
        # Paper trading mode: return safe default (no real margin)
        if self.config.trading.paper_trading:
            return 0.0

        try:
            # Use CCXT's standard method instead of direct API call
            balance = await self.futures_exchange.fetch_balance()

            # Get margin info from balance
            info = balance.get("info", {})
            total_margin = float(info.get("totalMarginBalance", 0) or 0)
            maintenance_margin = float(info.get("totalMaintMargin", 0) or 0)

            if total_margin == 0:
                return None

            return maintenance_margin / total_margin
        except ccxt.ExchangeError as e:
            logger.error(f"Exchange error fetching margin ratio: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching margin ratio: {e}")
            return None

    def filter_opportunities(
        self,
        funding_data: list[FundingRateData],
        spreads: dict[str, SpotFuturesSpread],
    ) -> list[FundingRateData]:
        """Filter funding rate opportunities based on criteria."""
        opportunities = []

        min_rate = self.config.strategy.min_funding_rate
        max_spread = self.config.strategy.max_spread

        for data in funding_data:
            # Check funding rate threshold (absolute value)
            if abs(data.funding_rate) < min_rate:
                continue

            # Check spread
            spread = spreads.get(data.symbol)
            if spread and abs(spread.spread) > max_spread:
                continue

            opportunities.append(data)

        # Sort by absolute funding rate (highest first)
        opportunities.sort(key=lambda x: abs(x.funding_rate), reverse=True)

        logger.info(f"Found {len(opportunities)} funding opportunities")
        return opportunities
