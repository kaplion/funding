"""Tests for risk manager module."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from config.config import Config
from src.data_collector import DataCollector
from src.models import Position, PositionSide, PositionStatus
from src.risk_manager import RiskLevel, RiskManager, RiskAlert


@pytest.fixture
def config():
    """Create test configuration."""
    return Config()


@pytest.fixture
def mock_data_collector(config):
    """Create mock data collector."""
    collector = MagicMock(spec=DataCollector)
    collector.config = config
    return collector


@pytest.fixture
def risk_manager(config, mock_data_collector):
    """Create risk manager instance."""
    return RiskManager(config, mock_data_collector)


class TestRiskManager:
    """Tests for RiskManager class."""

    def test_check_position_limits_within_limits(self, risk_manager):
        """Test position limits check when within limits."""
        positions = []
        
        allowed, reason = risk_manager.check_position_limits(
            positions=positions,
            new_position_value=1000,
            symbol="BTCUSDT",
            total_equity=10000,
        )
        
        assert allowed is True
        assert reason is None

    def test_check_position_limits_max_positions(self, risk_manager):
        """Test position limits when max positions reached."""
        # Create 5 open positions (max)
        positions = []
        for i in range(5):
            pos = Position(
                symbol=f"SYMBOL{i}USDT",
                side=PositionSide.LONG_SPOT_SHORT_PERP,
                status=PositionStatus.OPEN,
                spot_quantity=0.1,
                spot_entry_price=1000,
            )
            positions.append(pos)
        
        allowed, reason = risk_manager.check_position_limits(
            positions=positions,
            new_position_value=1000,
            symbol="NEWUSDT",
            total_equity=10000,
        )
        
        assert allowed is False
        assert "maximum position count" in reason.lower()

    def test_check_position_limits_already_have_symbol(self, risk_manager):
        """Test position limits when already have position in symbol."""
        existing_position = Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG_SPOT_SHORT_PERP,
            status=PositionStatus.OPEN,
            spot_quantity=0.1,
            spot_entry_price=50000,
        )
        
        allowed, reason = risk_manager.check_position_limits(
            positions=[existing_position],
            new_position_value=1000,
            symbol="BTCUSDT",
            total_equity=10000,
        )
        
        assert allowed is False
        assert "already have position" in reason.lower()

    def test_check_position_limits_closed_positions_ignored(self, risk_manager):
        """Test that closed positions are not counted."""
        positions = []
        for i in range(5):
            pos = Position(
                symbol=f"SYMBOL{i}USDT",
                side=PositionSide.LONG_SPOT_SHORT_PERP,
                status=PositionStatus.CLOSED,  # Closed, not counted
                spot_quantity=0.1,
                spot_entry_price=1000,
            )
            positions.append(pos)
        
        allowed, reason = risk_manager.check_position_limits(
            positions=positions,
            new_position_value=1000,
            symbol="NEWUSDT",
            total_equity=10000,
        )
        
        assert allowed is True

    @pytest.mark.asyncio
    async def test_calculate_risk_metrics_low_risk(self, risk_manager, mock_data_collector):
        """Test risk metrics calculation for low risk."""
        mock_data_collector.get_account_balance = AsyncMock(return_value={
            "total_equity": 10000,
            "spot_total": 5000,
            "futures_total": 5000,
        })
        mock_data_collector.get_margin_ratio = AsyncMock(return_value=0.3)
        mock_data_collector.get_futures_positions = AsyncMock(return_value=[])
        
        metrics = await risk_manager.calculate_risk_metrics([])
        
        assert metrics.risk_level == RiskLevel.LOW
        assert metrics.total_equity == 10000
        assert metrics.margin_ratio == 0.3
        assert len(metrics.alerts) == 0

    @pytest.mark.asyncio
    async def test_calculate_risk_metrics_high_margin(self, risk_manager, mock_data_collector):
        """Test risk metrics with high margin ratio."""
        mock_data_collector.get_account_balance = AsyncMock(return_value={
            "total_equity": 10000,
            "spot_total": 5000,
            "futures_total": 5000,
        })
        mock_data_collector.get_margin_ratio = AsyncMock(return_value=0.75)  # Above warning
        mock_data_collector.get_futures_positions = AsyncMock(return_value=[])
        
        metrics = await risk_manager.calculate_risk_metrics([])
        
        assert metrics.risk_level == RiskLevel.HIGH
        assert len(metrics.alerts) == 1
        assert metrics.alerts[0].alert_type == "margin_ratio"
        assert metrics.alerts[0].level == RiskLevel.HIGH

    @pytest.mark.asyncio
    async def test_calculate_risk_metrics_critical_margin(self, risk_manager, mock_data_collector):
        """Test risk metrics with critical margin ratio."""
        mock_data_collector.get_account_balance = AsyncMock(return_value={
            "total_equity": 10000,
            "spot_total": 5000,
            "futures_total": 5000,
        })
        mock_data_collector.get_margin_ratio = AsyncMock(return_value=0.9)  # Above critical
        mock_data_collector.get_futures_positions = AsyncMock(return_value=[])
        
        metrics = await risk_manager.calculate_risk_metrics([])
        
        assert metrics.risk_level == RiskLevel.CRITICAL
        assert len(metrics.alerts) == 1
        assert metrics.alerts[0].level == RiskLevel.CRITICAL

    @pytest.mark.asyncio
    async def test_should_pause_trading_critical(self, risk_manager, mock_data_collector):
        """Test trading pause on critical risk."""
        mock_data_collector.get_account_balance = AsyncMock(return_value={
            "total_equity": 10000,
        })
        mock_data_collector.get_margin_ratio = AsyncMock(return_value=0.9)
        mock_data_collector.get_futures_positions = AsyncMock(return_value=[])
        
        should_pause, reason = await risk_manager.should_pause_trading([])
        
        assert should_pause is True
        assert "critical" in reason.lower()

    @pytest.mark.asyncio
    async def test_should_not_pause_trading_normal(self, risk_manager, mock_data_collector):
        """Test no trading pause under normal conditions."""
        mock_data_collector.get_account_balance = AsyncMock(return_value={
            "total_equity": 10000,
        })
        mock_data_collector.get_margin_ratio = AsyncMock(return_value=0.3)
        mock_data_collector.get_futures_positions = AsyncMock(return_value=[])
        
        # Set initial peak equity to avoid drawdown issues
        risk_manager._peak_equity = 10000
        
        should_pause, reason = await risk_manager.should_pause_trading([])
        
        assert should_pause is False

    def test_get_recent_alerts(self, risk_manager):
        """Test getting recent alerts."""
        # Add some alerts
        for i in range(60):
            risk_manager._alerts_history.append(
                RiskAlert(
                    level=RiskLevel.MEDIUM,
                    alert_type="test",
                    message=f"Alert {i}",
                )
            )
        
        recent = risk_manager.get_recent_alerts(limit=50)
        
        assert len(recent) == 50
        # Should be the most recent 50
        assert recent[-1].message == "Alert 59"

    def test_clear_alerts(self, risk_manager):
        """Test clearing alerts."""
        risk_manager._alerts_history.append(
            RiskAlert(level=RiskLevel.HIGH, alert_type="test", message="Test")
        )
        
        risk_manager.clear_alerts()
        
        assert len(risk_manager._alerts_history) == 0

    def test_reset_peak_equity(self, risk_manager):
        """Test resetting peak equity."""
        risk_manager._peak_equity = 5000
        
        risk_manager.reset_peak_equity(10000)
        
        assert risk_manager._peak_equity == 10000


class TestRiskAlert:
    """Tests for RiskAlert class."""

    def test_alert_creation(self):
        """Test alert creation."""
        alert = RiskAlert(
            level=RiskLevel.HIGH,
            alert_type="margin_ratio",
            message="High margin ratio detected",
            symbol="BTCUSDT",
            value=0.8,
            threshold=0.7,
        )
        
        assert alert.level == RiskLevel.HIGH
        assert alert.alert_type == "margin_ratio"
        assert alert.symbol == "BTCUSDT"
        assert alert.value == 0.8
        assert alert.threshold == 0.7
        assert alert.timestamp is not None

    def test_alert_auto_timestamp(self):
        """Test alert auto-assigns timestamp."""
        alert = RiskAlert(
            level=RiskLevel.LOW,
            alert_type="test",
            message="Test",
        )
        
        assert alert.timestamp is not None
        assert isinstance(alert.timestamp, datetime)
