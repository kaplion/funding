"""Risk management module for position monitoring and risk controls."""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from config.config import Config
from src.data_collector import DataCollector
from src.models import Position, PositionStatus


logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    """Risk level enumeration."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    def __lt__(self, other):
        """Compare risk levels."""
        if not isinstance(other, RiskLevel):
            return NotImplemented
        order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        return order.index(self) < order.index(other)

    def __le__(self, other):
        """Compare risk levels."""
        if not isinstance(other, RiskLevel):
            return NotImplemented
        return self == other or self < other

    def __gt__(self, other):
        """Compare risk levels."""
        if not isinstance(other, RiskLevel):
            return NotImplemented
        return not self <= other

    def __ge__(self, other):
        """Compare risk levels."""
        if not isinstance(other, RiskLevel):
            return NotImplemented
        return not self < other


@dataclass
class RiskAlert:
    """Risk alert information."""

    level: RiskLevel
    alert_type: str
    message: str
    symbol: str | None = None
    value: float | None = None
    threshold: float | None = None
    timestamp: datetime | None = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


@dataclass
class RiskMetrics:
    """Current risk metrics."""

    margin_ratio: float | None
    total_equity: float
    total_position_value: float
    position_count: int
    max_position_value: float
    min_liquidation_distance: float | None
    current_drawdown: float
    risk_level: RiskLevel
    alerts: list[RiskAlert]


class RiskManager:
    """Manages risk for the trading bot."""

    def __init__(self, config: Config, data_collector: DataCollector):
        self.config = config
        self.data_collector = data_collector
        self._peak_equity: float = 0
        self._alerts_history: list[RiskAlert] = []

    async def calculate_risk_metrics(
        self,
        positions: list[Position],
    ) -> RiskMetrics:
        """Calculate current risk metrics.

        Args:
            positions: List of all positions

        Returns:
            RiskMetrics with current values
        """
        # Get account data
        balance = await self.data_collector.get_account_balance()
        margin_ratio = await self.data_collector.get_margin_ratio()
        futures_positions = await self.data_collector.get_futures_positions()

        total_equity = balance.get("total_equity", 0)

        # Update peak equity
        if total_equity > self._peak_equity:
            self._peak_equity = total_equity

        # Calculate drawdown
        drawdown = 0
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - total_equity) / self._peak_equity

        # Calculate position metrics
        active_positions = [p for p in positions if p.status == PositionStatus.OPEN]
        position_count = len(active_positions)
        total_position_value = sum(p.position_value for p in active_positions)
        max_position_value = max(
            (p.position_value for p in active_positions), default=0
        )

        # Find minimum liquidation distance
        min_liq_distance = None
        if futures_positions:
            for fp in futures_positions:
                liq_price = fp.get("liquidation_price", 0)
                if liq_price > 0:
                    # Find corresponding position
                    symbol = fp["symbol"].replace("/USDT:USDT", "USDT")
                    for pos in active_positions:
                        if pos.symbol == symbol:
                            current_price = pos.futures_entry_price
                            if current_price > 0:
                                distance = abs(current_price - liq_price) / current_price
                                if min_liq_distance is None or distance < min_liq_distance:
                                    min_liq_distance = distance

        # Determine risk level and generate alerts
        alerts = []
        risk_level = RiskLevel.LOW

        # Check margin ratio
        if margin_ratio is not None:
            if margin_ratio >= self.config.risk.margin_ratio_critical:
                risk_level = RiskLevel.CRITICAL
                alerts.append(
                    RiskAlert(
                        level=RiskLevel.CRITICAL,
                        alert_type="margin_ratio",
                        message=f"Critical margin ratio: {margin_ratio:.2%}",
                        value=margin_ratio,
                        threshold=self.config.risk.margin_ratio_critical,
                    )
                )
            elif margin_ratio >= self.config.risk.margin_ratio_warning:
                if risk_level < RiskLevel.HIGH:
                    risk_level = RiskLevel.HIGH
                alerts.append(
                    RiskAlert(
                        level=RiskLevel.HIGH,
                        alert_type="margin_ratio",
                        message=f"High margin ratio: {margin_ratio:.2%}",
                        value=margin_ratio,
                        threshold=self.config.risk.margin_ratio_warning,
                    )
                )

        # Check liquidation distance
        if min_liq_distance is not None:
            if min_liq_distance < self.config.risk.min_liquidation_distance:
                if risk_level < RiskLevel.HIGH:
                    risk_level = RiskLevel.HIGH
                alerts.append(
                    RiskAlert(
                        level=RiskLevel.HIGH,
                        alert_type="liquidation_distance",
                        message=f"Low liquidation distance: {min_liq_distance:.2%}",
                        value=min_liq_distance,
                        threshold=self.config.risk.min_liquidation_distance,
                    )
                )

        # Check drawdown
        if drawdown >= self.config.risk.max_drawdown:
            if risk_level < RiskLevel.HIGH:
                risk_level = RiskLevel.HIGH
            alerts.append(
                RiskAlert(
                    level=RiskLevel.HIGH,
                    alert_type="drawdown",
                    message=f"Max drawdown reached: {drawdown:.2%}",
                    value=drawdown,
                    threshold=self.config.risk.max_drawdown,
                )
            )

        # Set medium risk if we have some positions
        if risk_level == RiskLevel.LOW and position_count > 0:
            risk_level = RiskLevel.MEDIUM

        # Store alerts
        self._alerts_history.extend(alerts)

        return RiskMetrics(
            margin_ratio=margin_ratio,
            total_equity=total_equity,
            total_position_value=total_position_value,
            position_count=position_count,
            max_position_value=max_position_value,
            min_liquidation_distance=min_liq_distance,
            current_drawdown=drawdown,
            risk_level=risk_level,
            alerts=alerts,
        )

    def check_position_limits(
        self,
        positions: list[Position],
        new_position_value: float,
        symbol: str,
        total_equity: float,
    ) -> tuple[bool, str | None]:
        """Check if a new position can be opened within limits.

        Args:
            positions: Existing positions
            new_position_value: Value of new position
            symbol: Symbol for new position
            total_equity: Total account equity

        Returns:
            Tuple of (allowed, rejection_reason)
        """
        active_positions = [p for p in positions if p.status == PositionStatus.OPEN]

        # Check max positions
        if len(active_positions) >= self.config.strategy.max_positions:
            return False, f"Maximum position count ({self.config.strategy.max_positions}) reached"

        # Check if already have position in symbol
        symbol_positions = [p for p in active_positions if p.symbol == symbol]
        if symbol_positions:
            return False, f"Already have position in {symbol}"

        # Check max coin allocation
        symbol_allocation = sum(p.position_value for p in symbol_positions) / total_equity if total_equity > 0 else 0
        new_allocation = new_position_value / total_equity if total_equity > 0 else 0

        if symbol_allocation + new_allocation > self.config.risk.max_coin_allocation:
            return False, f"Would exceed max allocation for {symbol}"

        # Check total allocation
        total_allocation = sum(p.position_value for p in active_positions) / total_equity if total_equity > 0 else 0
        position_size_pct = self.config.strategy.position_size_pct

        # Allow up to max_positions * position_size_pct
        max_total_allocation = self.config.strategy.max_positions * position_size_pct
        if total_allocation + new_allocation > max_total_allocation:
            return False, "Would exceed total allocation limit"

        return True, None

    async def should_pause_trading(
        self,
        positions: list[Position],
    ) -> tuple[bool, str | None]:
        """Check if trading should be paused due to risk.

        Args:
            positions: Current positions

        Returns:
            Tuple of (should_pause, reason)
        """
        metrics = await self.calculate_risk_metrics(positions)

        # Pause on critical risk
        if metrics.risk_level == RiskLevel.CRITICAL:
            return True, "Critical risk level reached"

        # Pause on max drawdown
        if metrics.current_drawdown >= self.config.risk.max_drawdown:
            return True, f"Max drawdown ({metrics.current_drawdown:.2%}) exceeded"

        return False, None

    async def get_positions_to_close(
        self,
        positions: list[Position],
    ) -> list[Position]:
        """Get list of positions that should be closed due to risk.

        Args:
            positions: Current positions

        Returns:
            List of positions to close
        """
        metrics = await self.calculate_risk_metrics(positions)
        positions_to_close = []

        # On critical risk, close all positions
        if metrics.risk_level == RiskLevel.CRITICAL:
            positions_to_close = [
                p for p in positions if p.status == PositionStatus.OPEN
            ]
            logger.warning(f"Critical risk - closing all {len(positions_to_close)} positions")
            return positions_to_close

        # Check individual positions
        active_positions = [p for p in positions if p.status == PositionStatus.OPEN]
        futures_positions = await self.data_collector.get_futures_positions()

        for position in active_positions:
            # Check liquidation distance for each position
            symbol = position.symbol
            for fp in futures_positions:
                fp_symbol = fp["symbol"].replace("/USDT:USDT", "USDT")
                if fp_symbol == symbol:
                    liq_price = fp.get("liquidation_price", 0)
                    if liq_price > 0:
                        current_price = position.futures_entry_price
                        if current_price > 0:
                            distance = abs(current_price - liq_price) / current_price
                            if distance < self.config.risk.min_liquidation_distance * 0.5:
                                logger.warning(
                                    f"Position {symbol} liquidation distance too low: {distance:.2%}"
                                )
                                positions_to_close.append(position)
                                break

        return positions_to_close

    def get_recent_alerts(self, limit: int = 50) -> list[RiskAlert]:
        """Get recent risk alerts.

        Args:
            limit: Maximum number of alerts to return

        Returns:
            List of recent alerts
        """
        return self._alerts_history[-limit:]

    def clear_alerts(self) -> None:
        """Clear alert history."""
        self._alerts_history.clear()

    def reset_peak_equity(self, current_equity: float) -> None:
        """Reset peak equity for drawdown calculation.

        Args:
            current_equity: Current equity to set as new peak
        """
        self._peak_equity = current_equity
        logger.info(f"Peak equity reset to ${current_equity:.2f}")
