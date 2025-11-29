"""Strategy module for entry/exit logic."""

import logging
from dataclasses import dataclass
from enum import Enum

from config.config import Config
from src.data_collector import DataCollector, FundingRateData, SpotFuturesSpread
from src.models import Position, PositionSide, PositionStatus


logger = logging.getLogger(__name__)


class Signal(str, Enum):
    """Trading signal enumeration."""

    ENTER_LONG_SPOT_SHORT_PERP = "enter_long_spot_short_perp"
    ENTER_SHORT_SPOT_LONG_PERP = "enter_short_spot_long_perp"
    EXIT = "exit"
    HOLD = "hold"


@dataclass
class TradeSignal:
    """Trade signal with metadata."""

    signal: Signal
    symbol: str
    funding_rate: float
    spread: float
    reason: str
    position_size_usdt: float = 0
    urgency: int = 0  # 0-10, higher = more urgent


class Strategy:
    """Trading strategy for funding rate arbitrage."""

    def __init__(self, config: Config, data_collector: DataCollector):
        self.config = config
        self.data_collector = data_collector

    def calculate_position_size(
        self,
        total_equity: float,
        current_allocation: float,
        symbol_allocation: float = 0,
    ) -> float:
        """Calculate position size based on config and current allocations.

        Args:
            total_equity: Total account equity in USDT
            current_allocation: Current total allocation as percentage (0-1)
            symbol_allocation: Current allocation to the specific symbol (0-1)

        Returns:
            Position size in USDT
        """
        # Base position size
        position_size = total_equity * self.config.strategy.position_size_pct

        # Check max coin allocation
        max_coin_allocation = self.config.risk.max_coin_allocation
        if symbol_allocation + (position_size / total_equity) > max_coin_allocation:
            position_size = (max_coin_allocation - symbol_allocation) * total_equity

        # Ensure minimum order value
        if position_size < self.config.trading.min_order_value:
            return 0

        return max(position_size, 0)

    def should_enter_position(
        self,
        funding_data: FundingRateData,
        spread: SpotFuturesSpread | None,
        open_positions: list[Position],
        total_equity: float,
    ) -> TradeSignal:
        """Determine if a new position should be opened.

        Args:
            funding_data: Funding rate data for the symbol
            spread: Current spot/futures spread
            open_positions: List of currently open positions
            total_equity: Total account equity

        Returns:
            TradeSignal with entry decision
        """
        symbol = funding_data.symbol
        funding_rate = funding_data.funding_rate

        # Check max positions limit
        active_positions = [
            p for p in open_positions if p.status == PositionStatus.OPEN
        ]
        if len(active_positions) >= self.config.strategy.max_positions:
            return TradeSignal(
                signal=Signal.HOLD,
                symbol=symbol,
                funding_rate=funding_rate,
                spread=spread.spread if spread else 0,
                reason="Max positions limit reached",
            )

        # Check if already have position in this symbol
        symbol_positions = [p for p in active_positions if p.symbol == symbol]
        if symbol_positions:
            return TradeSignal(
                signal=Signal.HOLD,
                symbol=symbol,
                funding_rate=funding_rate,
                spread=spread.spread if spread else 0,
                reason="Already have position in this symbol",
            )

        # Check funding rate threshold
        min_funding = self.config.strategy.min_funding_rate
        if abs(funding_rate) < min_funding:
            return TradeSignal(
                signal=Signal.HOLD,
                symbol=symbol,
                funding_rate=funding_rate,
                spread=spread.spread if spread else 0,
                reason=f"Funding rate {funding_rate:.6f} below threshold {min_funding:.6f}",
            )

        # Check spread
        if spread:
            max_spread = self.config.strategy.max_spread
            if abs(spread.spread) > max_spread:
                return TradeSignal(
                    signal=Signal.HOLD,
                    symbol=symbol,
                    funding_rate=funding_rate,
                    spread=spread.spread,
                    reason=f"Spread {spread.spread:.6f} exceeds max {max_spread:.6f}",
                )

        # Calculate position size
        current_allocation = sum(
            p.position_value for p in active_positions
        ) / total_equity if total_equity > 0 else 0

        position_size = self.calculate_position_size(
            total_equity=total_equity,
            current_allocation=current_allocation,
        )

        if position_size == 0:
            return TradeSignal(
                signal=Signal.HOLD,
                symbol=symbol,
                funding_rate=funding_rate,
                spread=spread.spread if spread else 0,
                reason="Position size too small or allocation limit reached",
            )

        # Determine signal based on funding rate direction
        if funding_rate > 0:
            # Positive funding: long spot + short perpetual
            signal = Signal.ENTER_LONG_SPOT_SHORT_PERP
            reason = f"Positive funding {funding_rate:.6f} ({funding_data.apr:.2f}% APR)"
        else:
            # Negative funding: short spot (margin) + long perpetual
            signal = Signal.ENTER_SHORT_SPOT_LONG_PERP
            reason = f"Negative funding {funding_rate:.6f} ({funding_data.apr:.2f}% APR)"

        # Calculate urgency based on funding rate magnitude
        urgency = min(int(abs(funding_rate) / min_funding), 10)

        return TradeSignal(
            signal=signal,
            symbol=symbol,
            funding_rate=funding_rate,
            spread=spread.spread if spread else 0,
            reason=reason,
            position_size_usdt=position_size,
            urgency=urgency,
        )

    def should_exit_position(
        self,
        position: Position,
        funding_data: FundingRateData | None,
        spread: SpotFuturesSpread | None,
        margin_ratio: float | None = None,
    ) -> TradeSignal:
        """Determine if a position should be closed.

        Args:
            position: The position to evaluate
            funding_data: Current funding rate data
            spread: Current spot/futures spread
            margin_ratio: Current margin ratio (if available)

        Returns:
            TradeSignal with exit decision
        """
        symbol = position.symbol

        # Get current values
        current_funding = funding_data.funding_rate if funding_data else 0
        current_spread = spread.spread if spread else 0

        # Check if funding rate dropped below threshold
        min_funding = self.config.strategy.min_funding_rate

        if position.side == PositionSide.LONG_SPOT_SHORT_PERP:
            # For positive funding strategy, exit if funding becomes negative or too low
            if current_funding <= min_funding * 0.5:  # Exit at half threshold
                return TradeSignal(
                    signal=Signal.EXIT,
                    symbol=symbol,
                    funding_rate=current_funding,
                    spread=current_spread,
                    reason=f"Funding rate dropped to {current_funding:.6f}",
                    urgency=5,
                )
        else:
            # For negative funding strategy, exit if funding becomes positive or too high
            if current_funding >= -min_funding * 0.5:
                return TradeSignal(
                    signal=Signal.EXIT,
                    symbol=symbol,
                    funding_rate=current_funding,
                    spread=current_spread,
                    reason=f"Funding rate rose to {current_funding:.6f}",
                    urgency=5,
                )

        # Check if spread widened too much
        max_spread = self.config.strategy.max_spread
        if abs(current_spread) > max_spread * 2:  # Exit at 2x max spread
            return TradeSignal(
                signal=Signal.EXIT,
                symbol=symbol,
                funding_rate=current_funding,
                spread=current_spread,
                reason=f"Spread widened to {current_spread:.6f}",
                urgency=7,
            )

        # Check margin ratio (risk)
        if margin_ratio is not None:
            if margin_ratio >= self.config.risk.margin_ratio_critical:
                return TradeSignal(
                    signal=Signal.EXIT,
                    symbol=symbol,
                    funding_rate=current_funding,
                    spread=current_spread,
                    reason=f"Critical margin ratio: {margin_ratio:.2%}",
                    urgency=10,
                )

        # Continue holding
        return TradeSignal(
            signal=Signal.HOLD,
            symbol=symbol,
            funding_rate=current_funding,
            spread=current_spread,
            reason="Continue holding position",
        )

    async def scan_opportunities(
        self,
        open_positions: list[Position],
        total_equity: float,
    ) -> list[TradeSignal]:
        """Scan market for entry opportunities.

        Args:
            open_positions: List of currently open positions
            total_equity: Total account equity

        Returns:
            List of trade signals for potential entries
        """
        # Get all funding rates
        funding_rates = await self.data_collector.get_all_funding_rates()

        if not funding_rates:
            logger.warning("No funding rates available")
            return []

        # Get spreads for all symbols with good funding rates
        min_funding = self.config.strategy.min_funding_rate
        candidates = [f for f in funding_rates if abs(f.funding_rate) >= min_funding]

        signals = []
        for funding_data in candidates:
            spread = await self.data_collector.get_spot_futures_spread(
                funding_data.symbol
            )
            signal = self.should_enter_position(
                funding_data=funding_data,
                spread=spread,
                open_positions=open_positions,
                total_equity=total_equity,
            )

            if signal.signal != Signal.HOLD:
                signals.append(signal)

        # Sort by urgency (highest first)
        signals.sort(key=lambda x: x.urgency, reverse=True)

        logger.info(f"Found {len(signals)} entry signals")
        return signals

    async def evaluate_positions(
        self,
        positions: list[Position],
    ) -> list[TradeSignal]:
        """Evaluate existing positions for exit signals.

        Args:
            positions: List of positions to evaluate

        Returns:
            List of exit signals
        """
        margin_ratio = await self.data_collector.get_margin_ratio()
        signals = []

        for position in positions:
            if position.status != PositionStatus.OPEN:
                continue

            funding_data = await self.data_collector.get_funding_rate(position.symbol)
            spread = await self.data_collector.get_spot_futures_spread(position.symbol)

            signal = self.should_exit_position(
                position=position,
                funding_data=funding_data,
                spread=spread,
                margin_ratio=margin_ratio,
            )

            if signal.signal == Signal.EXIT:
                signals.append(signal)

        logger.info(f"Found {len(signals)} exit signals")
        return signals

    def rank_opportunities(
        self,
        signals: list[TradeSignal],
    ) -> list[TradeSignal]:
        """Rank entry opportunities by expected return.

        Args:
            signals: List of entry signals

        Returns:
            Ranked list of signals (best first)
        """

        def score(signal: TradeSignal) -> float:
            """Calculate score for a signal."""
            # Higher funding rate = higher score
            funding_score = abs(signal.funding_rate) * 10000

            # Lower spread = higher score
            spread_penalty = abs(signal.spread) * 1000

            # Add urgency bonus
            urgency_bonus = signal.urgency * 10

            return funding_score - spread_penalty + urgency_bonus

        return sorted(signals, key=score, reverse=True)
