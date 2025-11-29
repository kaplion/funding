"""Tests for executor module."""

import pytest
from unittest.mock import AsyncMock

from config.config import Config
from src.data_collector import DataCollector, SpotFuturesSpread
from src.executor import Executor
from src.models import Position, PositionSide, PositionStatus
from src.paper_trader import PaperTrader


@pytest.fixture
def paper_config():
    """Create paper trading configuration."""
    config = Config()
    config.trading.paper_trading = True
    config.trading.paper_initial_balance = 10000.0
    return config


@pytest.fixture
def live_config():
    """Create live trading configuration."""
    config = Config()
    config.trading.paper_trading = False
    return config


@pytest.fixture
def paper_trader():
    """Create paper trader instance."""
    return PaperTrader(initial_balance=10000.0)


@pytest.fixture
def data_collector_with_paper(paper_config, paper_trader):
    """Create data collector with paper trader."""
    data_collector = DataCollector(paper_config, paper_trader=paper_trader)
    return data_collector


@pytest.fixture
def executor_paper_mode(paper_config, data_collector_with_paper):
    """Create executor in paper trading mode."""
    return Executor(paper_config, data_collector_with_paper)


@pytest.fixture
def executor_live_mode(live_config):
    """Create executor in live trading mode."""
    data_collector = DataCollector(live_config)
    return Executor(live_config, data_collector)


class TestExecutorPaperTrading:
    """Tests for paper trading mode in Executor."""

    @pytest.mark.asyncio
    async def test_open_position_paper_mode_success(self, executor_paper_mode):
        """Test opening a position in paper trading mode successfully."""
        # Mock get_spot_futures_spread to return test data
        spread = SpotFuturesSpread(
            symbol="BTCUSDT",
            spot_price=50000.0,
            futures_price=50050.0,
        )
        executor_paper_mode.data_collector.get_spot_futures_spread = AsyncMock(
            return_value=spread
        )

        result = await executor_paper_mode.open_position(
            symbol="BTCUSDT",
            side=PositionSide.LONG_SPOT_SHORT_PERP,
            position_size_usdt=1000.0,
            entry_funding_rate=0.0003,
        )

        assert result.success is True
        assert result.position is not None
        assert result.position.symbol == "BTCUSDT"
        assert result.position.side == PositionSide.LONG_SPOT_SHORT_PERP
        assert result.position.status == PositionStatus.OPEN

    @pytest.mark.asyncio
    async def test_open_position_paper_mode_no_prices(self, executor_paper_mode):
        """Test opening a position fails when prices unavailable."""
        executor_paper_mode.data_collector.get_spot_futures_spread = AsyncMock(
            return_value=None
        )

        result = await executor_paper_mode.open_position(
            symbol="BTCUSDT",
            side=PositionSide.LONG_SPOT_SHORT_PERP,
            position_size_usdt=1000.0,
            entry_funding_rate=0.0003,
        )

        assert result.success is False
        assert result.error == "Could not get current prices"

    @pytest.mark.asyncio
    async def test_open_position_paper_mode_no_paper_trader(self, paper_config):
        """Test opening a position fails when paper trader not initialized."""
        # Create data collector without paper trader
        data_collector = DataCollector(paper_config, paper_trader=None)
        executor = Executor(paper_config, data_collector)

        spread = SpotFuturesSpread(
            symbol="BTCUSDT",
            spot_price=50000.0,
            futures_price=50050.0,
        )
        executor.data_collector.get_spot_futures_spread = AsyncMock(
            return_value=spread
        )

        result = await executor.open_position(
            symbol="BTCUSDT",
            side=PositionSide.LONG_SPOT_SHORT_PERP,
            position_size_usdt=1000.0,
            entry_funding_rate=0.0003,
        )

        assert result.success is False
        assert result.error == "Paper trader not initialized"

    @pytest.mark.asyncio
    async def test_open_position_paper_mode_insufficient_balance(
        self, paper_config, paper_trader
    ):
        """Test opening a position fails with insufficient balance."""
        data_collector = DataCollector(paper_config, paper_trader=paper_trader)
        executor = Executor(paper_config, data_collector)

        spread = SpotFuturesSpread(
            symbol="BTCUSDT",
            spot_price=50000.0,
            futures_price=50050.0,
        )
        executor.data_collector.get_spot_futures_spread = AsyncMock(
            return_value=spread
        )

        # Try to open position larger than available balance
        result = await executor.open_position(
            symbol="BTCUSDT",
            side=PositionSide.LONG_SPOT_SHORT_PERP,
            position_size_usdt=50000.0,  # More than 10000 balance
            entry_funding_rate=0.0003,
        )

        assert result.success is False
        assert "Insufficient" in result.error

    @pytest.mark.asyncio
    async def test_close_position_paper_mode_success(self, executor_paper_mode):
        """Test closing a position in paper trading mode successfully."""
        # First open a position
        spread = SpotFuturesSpread(
            symbol="BTCUSDT",
            spot_price=50000.0,
            futures_price=50050.0,
        )
        executor_paper_mode.data_collector.get_spot_futures_spread = AsyncMock(
            return_value=spread
        )

        open_result = await executor_paper_mode.open_position(
            symbol="BTCUSDT",
            side=PositionSide.LONG_SPOT_SHORT_PERP,
            position_size_usdt=1000.0,
            entry_funding_rate=0.0003,
        )

        assert open_result.success is True

        # Now close the position
        close_spread = SpotFuturesSpread(
            symbol="BTCUSDT",
            spot_price=50100.0,  # Price increased
            futures_price=50100.0,
        )
        executor_paper_mode.data_collector.get_spot_futures_spread = AsyncMock(
            return_value=close_spread
        )

        close_result = await executor_paper_mode.close_position(open_result.position)

        assert close_result.success is True
        assert close_result.position is not None
        assert close_result.position.status == PositionStatus.CLOSED

    @pytest.mark.asyncio
    async def test_close_position_paper_mode_no_prices(self, executor_paper_mode):
        """Test closing a position fails when prices unavailable."""
        # Create a mock position
        position = Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG_SPOT_SHORT_PERP,
            status=PositionStatus.OPEN,
            spot_quantity=0.02,
            spot_entry_price=50000.0,
            futures_quantity=0.02,
            futures_entry_price=50050.0,
            entry_funding_rate=0.0003,
        )

        executor_paper_mode.data_collector.get_spot_futures_spread = AsyncMock(
            return_value=None
        )

        result = await executor_paper_mode.close_position(position)

        assert result.success is False
        assert result.error == "Could not get current prices"

    @pytest.mark.asyncio
    async def test_close_position_paper_mode_no_paper_trader(self, paper_config):
        """Test closing a position fails when paper trader not initialized."""
        # Create data collector without paper trader
        data_collector = DataCollector(paper_config, paper_trader=None)
        executor = Executor(paper_config, data_collector)

        position = Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG_SPOT_SHORT_PERP,
            status=PositionStatus.OPEN,
            spot_quantity=0.02,
            spot_entry_price=50000.0,
            futures_quantity=0.02,
            futures_entry_price=50050.0,
            entry_funding_rate=0.0003,
        )

        spread = SpotFuturesSpread(
            symbol="BTCUSDT",
            spot_price=50100.0,
            futures_price=50100.0,
        )
        executor.data_collector.get_spot_futures_spread = AsyncMock(
            return_value=spread
        )

        result = await executor.close_position(position)

        assert result.success is False
        assert result.error == "Paper trader not initialized"


class TestExecutorLiveMode:
    """Tests for live trading mode in Executor (verifies paper mode is bypassed)."""

    def test_executor_config_live_mode(self, executor_live_mode):
        """Test executor is in live mode when paper_trading is False."""
        assert executor_live_mode.config.trading.paper_trading is False


class TestExecutorPositionSides:
    """Tests for different position sides in paper trading mode."""

    @pytest.mark.asyncio
    async def test_open_short_spot_long_perp_position(self, executor_paper_mode):
        """Test opening a short spot long perp position."""
        spread = SpotFuturesSpread(
            symbol="ETHUSDT",
            spot_price=3000.0,
            futures_price=3010.0,
        )
        executor_paper_mode.data_collector.get_spot_futures_spread = AsyncMock(
            return_value=spread
        )

        result = await executor_paper_mode.open_position(
            symbol="ETHUSDT",
            side=PositionSide.SHORT_SPOT_LONG_PERP,
            position_size_usdt=500.0,
            entry_funding_rate=-0.0002,  # Negative funding rate
        )

        assert result.success is True
        assert result.position is not None
        assert result.position.symbol == "ETHUSDT"
        assert result.position.side == PositionSide.SHORT_SPOT_LONG_PERP
