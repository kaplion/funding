"""Tests for strategy module."""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from config.config import Config
from src.data_collector import DataCollector, FundingRateData, SpotFuturesSpread
from src.models import Position, PositionSide, PositionStatus
from src.strategy import Signal, Strategy, TradeSignal


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
def strategy(config, mock_data_collector):
    """Create strategy instance."""
    return Strategy(config, mock_data_collector)


class TestStrategy:
    """Tests for Strategy class."""

    def test_calculate_position_size_basic(self, strategy):
        """Test basic position size calculation."""
        total_equity = 10000
        current_allocation = 0
        
        size = strategy.calculate_position_size(total_equity, current_allocation)
        
        # Default position_size_pct is 0.1 (10%)
        assert size == 1000

    def test_calculate_position_size_with_allocation(self, strategy):
        """Test position size with existing allocation."""
        total_equity = 10000
        current_allocation = 0.5  # 50% allocated
        
        size = strategy.calculate_position_size(total_equity, current_allocation)
        
        # Should still return 10% of equity
        assert size == 1000

    def test_calculate_position_size_max_coin_allocation(self, strategy):
        """Test position size respects max coin allocation."""
        total_equity = 10000
        current_allocation = 0
        symbol_allocation = 0.15  # 15% already in this symbol
        
        size = strategy.calculate_position_size(
            total_equity, current_allocation, symbol_allocation
        )
        
        # Max coin allocation is 0.2 (20%), so can only add 5%
        assert size == pytest.approx(500, rel=0.01)

    def test_calculate_position_size_below_minimum(self, strategy):
        """Test position size returns 0 if below minimum."""
        strategy.config.trading.min_order_value = 100
        total_equity = 50  # Very small equity
        
        size = strategy.calculate_position_size(total_equity, 0)
        
        # 10% of 50 = 5, which is below min_order_value of 100
        assert size == 0

    def test_should_enter_positive_funding(self, strategy):
        """Test entry signal for positive funding rate."""
        funding_data = FundingRateData(
            symbol="BTCUSDT",
            funding_rate=0.0005,  # Above threshold
            predicted_funding_rate=None,
            mark_price=50000,
            index_price=50000,
            next_funding_time=datetime.utcnow(),
            open_interest=1000000000,
            volume_24h=5000000000,
        )
        
        spread = SpotFuturesSpread("BTCUSDT", 50000, 50020)
        
        signal = strategy.should_enter_position(
            funding_data=funding_data,
            spread=spread,
            open_positions=[],
            total_equity=10000,
        )
        
        assert signal.signal == Signal.ENTER_LONG_SPOT_SHORT_PERP
        assert signal.symbol == "BTCUSDT"
        assert signal.position_size_usdt == 1000

    def test_should_enter_negative_funding(self, strategy):
        """Test entry signal for negative funding rate."""
        funding_data = FundingRateData(
            symbol="BTCUSDT",
            funding_rate=-0.0005,  # Negative, above threshold in absolute value
            predicted_funding_rate=None,
            mark_price=50000,
            index_price=50000,
            next_funding_time=datetime.utcnow(),
            open_interest=1000000000,
            volume_24h=5000000000,
        )
        
        spread = SpotFuturesSpread("BTCUSDT", 50000, 49980)
        
        signal = strategy.should_enter_position(
            funding_data=funding_data,
            spread=spread,
            open_positions=[],
            total_equity=10000,
        )
        
        assert signal.signal == Signal.ENTER_SHORT_SPOT_LONG_PERP

    def test_should_not_enter_below_threshold(self, strategy):
        """Test no entry when funding rate below threshold."""
        funding_data = FundingRateData(
            symbol="BTCUSDT",
            funding_rate=0.0001,  # Below threshold (0.0003)
            predicted_funding_rate=None,
            mark_price=50000,
            index_price=50000,
            next_funding_time=datetime.utcnow(),
            open_interest=1000000000,
            volume_24h=5000000000,
        )
        
        spread = SpotFuturesSpread("BTCUSDT", 50000, 50020)
        
        signal = strategy.should_enter_position(
            funding_data=funding_data,
            spread=spread,
            open_positions=[],
            total_equity=10000,
        )
        
        assert signal.signal == Signal.HOLD
        assert "below threshold" in signal.reason.lower()

    def test_should_not_enter_spread_too_wide(self, strategy):
        """Test no entry when spread is too wide."""
        funding_data = FundingRateData(
            symbol="BTCUSDT",
            funding_rate=0.0005,
            predicted_funding_rate=None,
            mark_price=50000,
            index_price=50000,
            next_funding_time=datetime.utcnow(),
            open_interest=1000000000,
            volume_24h=5000000000,
        )
        
        # Spread of 0.2% exceeds max_spread of 0.1%
        spread = SpotFuturesSpread("BTCUSDT", 50000, 50100)
        
        signal = strategy.should_enter_position(
            funding_data=funding_data,
            spread=spread,
            open_positions=[],
            total_equity=10000,
        )
        
        assert signal.signal == Signal.HOLD
        assert "spread" in signal.reason.lower()

    def test_should_not_enter_max_positions_reached(self, strategy):
        """Test no entry when max positions reached."""
        funding_data = FundingRateData(
            symbol="BTCUSDT",
            funding_rate=0.0005,
            predicted_funding_rate=None,
            mark_price=50000,
            index_price=50000,
            next_funding_time=datetime.utcnow(),
            open_interest=1000000000,
            volume_24h=5000000000,
        )
        
        spread = SpotFuturesSpread("BTCUSDT", 50000, 50020)
        
        # Create 5 open positions (max)
        open_positions = []
        for i in range(5):
            pos = Position(
                symbol=f"SYMBOL{i}USDT",
                side=PositionSide.LONG_SPOT_SHORT_PERP,
                status=PositionStatus.OPEN,
            )
            open_positions.append(pos)
        
        signal = strategy.should_enter_position(
            funding_data=funding_data,
            spread=spread,
            open_positions=open_positions,
            total_equity=10000,
        )
        
        assert signal.signal == Signal.HOLD
        assert "max positions" in signal.reason.lower()

    def test_should_not_enter_already_have_position(self, strategy):
        """Test no entry when already have position in symbol."""
        funding_data = FundingRateData(
            symbol="BTCUSDT",
            funding_rate=0.0005,
            predicted_funding_rate=None,
            mark_price=50000,
            index_price=50000,
            next_funding_time=datetime.utcnow(),
            open_interest=1000000000,
            volume_24h=5000000000,
        )
        
        spread = SpotFuturesSpread("BTCUSDT", 50000, 50020)
        
        # Already have position in BTCUSDT
        existing_position = Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG_SPOT_SHORT_PERP,
            status=PositionStatus.OPEN,
        )
        
        signal = strategy.should_enter_position(
            funding_data=funding_data,
            spread=spread,
            open_positions=[existing_position],
            total_equity=10000,
        )
        
        assert signal.signal == Signal.HOLD
        assert "already have position" in signal.reason.lower()

    def test_should_exit_funding_dropped(self, strategy):
        """Test exit signal when funding rate drops."""
        position = Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG_SPOT_SHORT_PERP,
            status=PositionStatus.OPEN,
            entry_funding_rate=0.0005,
        )
        
        # Current funding dropped to 0.0001 (below half threshold)
        funding_data = FundingRateData(
            symbol="BTCUSDT",
            funding_rate=0.0001,
            predicted_funding_rate=None,
            mark_price=50000,
            index_price=50000,
            next_funding_time=datetime.utcnow(),
            open_interest=1000000000,
            volume_24h=5000000000,
        )
        
        spread = SpotFuturesSpread("BTCUSDT", 50000, 50020)
        
        signal = strategy.should_exit_position(
            position=position,
            funding_data=funding_data,
            spread=spread,
        )
        
        assert signal.signal == Signal.EXIT

    def test_should_exit_spread_widened(self, strategy):
        """Test exit signal when spread widens."""
        position = Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG_SPOT_SHORT_PERP,
            status=PositionStatus.OPEN,
            entry_funding_rate=0.0005,
        )
        
        funding_data = FundingRateData(
            symbol="BTCUSDT",
            funding_rate=0.0005,  # Still good
            predicted_funding_rate=None,
            mark_price=50000,
            index_price=50000,
            next_funding_time=datetime.utcnow(),
            open_interest=1000000000,
            volume_24h=5000000000,
        )
        
        # Spread widened to 0.25% (2.5x max_spread)
        spread = SpotFuturesSpread("BTCUSDT", 50000, 50125)
        
        signal = strategy.should_exit_position(
            position=position,
            funding_data=funding_data,
            spread=spread,
        )
        
        assert signal.signal == Signal.EXIT
        assert "spread" in signal.reason.lower()

    def test_should_exit_critical_margin(self, strategy):
        """Test exit signal on critical margin ratio."""
        position = Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG_SPOT_SHORT_PERP,
            status=PositionStatus.OPEN,
            entry_funding_rate=0.0005,
        )
        
        funding_data = FundingRateData(
            symbol="BTCUSDT",
            funding_rate=0.0005,
            predicted_funding_rate=None,
            mark_price=50000,
            index_price=50000,
            next_funding_time=datetime.utcnow(),
            open_interest=1000000000,
            volume_24h=5000000000,
        )
        
        spread = SpotFuturesSpread("BTCUSDT", 50000, 50020)
        
        signal = strategy.should_exit_position(
            position=position,
            funding_data=funding_data,
            spread=spread,
            margin_ratio=0.9,  # Above critical threshold (0.85)
        )
        
        assert signal.signal == Signal.EXIT
        assert "margin ratio" in signal.reason.lower()

    def test_should_hold_position(self, strategy):
        """Test hold signal when conditions are still good."""
        position = Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG_SPOT_SHORT_PERP,
            status=PositionStatus.OPEN,
            entry_funding_rate=0.0005,
        )
        
        funding_data = FundingRateData(
            symbol="BTCUSDT",
            funding_rate=0.0004,  # Still above threshold
            predicted_funding_rate=None,
            mark_price=50000,
            index_price=50000,
            next_funding_time=datetime.utcnow(),
            open_interest=1000000000,
            volume_24h=5000000000,
        )
        
        spread = SpotFuturesSpread("BTCUSDT", 50000, 50020)  # Within limits
        
        signal = strategy.should_exit_position(
            position=position,
            funding_data=funding_data,
            spread=spread,
            margin_ratio=0.5,  # Safe margin
        )
        
        assert signal.signal == Signal.HOLD

    def test_rank_opportunities(self, strategy):
        """Test ranking of opportunities."""
        signals = [
            TradeSignal(
                signal=Signal.ENTER_LONG_SPOT_SHORT_PERP,
                symbol="BTCUSDT",
                funding_rate=0.0004,
                spread=0.0003,
                reason="",
                position_size_usdt=1000,
                urgency=4,
            ),
            TradeSignal(
                signal=Signal.ENTER_LONG_SPOT_SHORT_PERP,
                symbol="ETHUSDT",
                funding_rate=0.0008,  # Higher funding
                spread=0.0002,  # Lower spread
                reason="",
                position_size_usdt=1000,
                urgency=8,
            ),
        ]
        
        ranked = strategy.rank_opportunities(signals)
        
        # ETHUSDT should be ranked higher (higher funding, lower spread)
        assert ranked[0].symbol == "ETHUSDT"
        assert ranked[1].symbol == "BTCUSDT"
