"""Tests for accounting module."""

import pytest
from datetime import datetime, timedelta

from config.config import Config
from src.accounting import Accounting, PositionPnL, AccountPnL
from src.models import Position, PositionSide, PositionStatus


@pytest.fixture
def config():
    """Create test configuration."""
    return Config()


@pytest.fixture
def accounting(config):
    """Create accounting instance."""
    return Accounting(config)


class TestAccounting:
    """Tests for Accounting class."""

    @pytest.mark.asyncio
    async def test_calculate_position_pnl_long_spot_short_perp_profit(self, accounting):
        """Test P&L calculation for profitable long spot / short perp position."""
        position = Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG_SPOT_SHORT_PERP,
            status=PositionStatus.CLOSED,
            spot_quantity=0.1,
            spot_entry_price=50000,
            spot_exit_price=51000,  # Price went up - profit on spot
            futures_quantity=0.1,
            futures_entry_price=50000,
            futures_exit_price=51000,  # Price went up - loss on short futures
            accumulated_funding=100,  # Received funding
            total_fees=50,
            opened_at=datetime.utcnow() - timedelta(hours=24),
            closed_at=datetime.utcnow(),
        )
        
        pnl = await accounting.calculate_position_pnl(position)
        
        # Spot: (51000 - 50000) * 0.1 = 100
        # Futures: (50000 - 51000) * 0.1 = -100
        # Funding: 100
        # Fees: -50
        # Net: 100 - 100 + 100 - 50 = 50
        assert pnl.spot_pnl == 100
        assert pnl.futures_pnl == -100
        assert pnl.funding_income == 100
        assert pnl.trading_fees == 50
        assert pnl.net_pnl == 50
        assert pnl.duration_hours == pytest.approx(24, rel=0.1)

    @pytest.mark.asyncio
    async def test_calculate_position_pnl_delta_neutral(self, accounting):
        """Test that delta-neutral position has minimal price P&L."""
        position = Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG_SPOT_SHORT_PERP,
            status=PositionStatus.CLOSED,
            spot_quantity=0.1,
            spot_entry_price=50000,
            spot_exit_price=52000,  # 4% price move
            futures_quantity=0.1,
            futures_entry_price=50000,
            futures_exit_price=52000,  # Same price move
            accumulated_funding=200,
            total_fees=100,
            opened_at=datetime.utcnow() - timedelta(hours=48),
            closed_at=datetime.utcnow(),
        )
        
        pnl = await accounting.calculate_position_pnl(position)
        
        # Spot P&L: +200
        # Futures P&L: -200 (short position loses on price up)
        # Combined price P&L should be ~0
        assert pnl.spot_pnl + pnl.futures_pnl == pytest.approx(0, abs=0.01)
        
        # Net P&L should be funding minus fees
        assert pnl.net_pnl == pytest.approx(100, abs=0.01)  # 200 - 100

    @pytest.mark.asyncio
    async def test_calculate_position_pnl_unrealized(self, accounting):
        """Test P&L calculation for open position."""
        position = Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG_SPOT_SHORT_PERP,
            status=PositionStatus.OPEN,
            spot_quantity=0.1,
            spot_entry_price=50000,
            futures_quantity=0.1,
            futures_entry_price=50000,
            accumulated_funding=50,
            total_fees=20,
            opened_at=datetime.utcnow() - timedelta(hours=8),
        )
        
        pnl = await accounting.calculate_position_pnl(
            position,
            current_spot_price=50500,
            current_futures_price=50500,
        )
        
        # Spot: (50500 - 50000) * 0.1 = 50
        # Futures: (50000 - 50500) * 0.1 = -50
        assert pnl.spot_pnl == 50
        assert pnl.futures_pnl == -50
        assert pnl.net_pnl == pytest.approx(30, abs=0.01)  # 50 - 50 + 50 - 20

    @pytest.mark.asyncio
    async def test_calculate_position_pnl_roi(self, accounting):
        """Test ROI calculation."""
        position = Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG_SPOT_SHORT_PERP,
            status=PositionStatus.CLOSED,
            spot_quantity=0.1,
            spot_entry_price=50000,  # Position value = 5000
            spot_exit_price=50000,
            futures_quantity=0.1,
            futures_entry_price=50000,
            futures_exit_price=50000,
            accumulated_funding=250,  # 5% return from funding
            total_fees=50,
            opened_at=datetime.utcnow() - timedelta(days=30),
            closed_at=datetime.utcnow(),
        )
        
        pnl = await accounting.calculate_position_pnl(position)
        
        # Net P&L = 250 - 50 = 200
        # Position value = 5000
        # ROI = 200/5000 * 100 = 4%
        assert pnl.net_pnl == 200
        assert pnl.roi_pct == pytest.approx(4, rel=0.01)

    def test_estimate_funding_income(self, accounting):
        """Test funding income estimation."""
        position_value = 10000
        funding_rate = 0.0003  # 0.03% per 8h
        hours = 24  # 3 funding periods
        
        estimated = accounting.estimate_funding_income(
            position_value, funding_rate, hours
        )
        
        # 10000 * 0.0003 * 3 = 9
        assert estimated == pytest.approx(9, abs=0.01)

    def test_estimate_funding_income_negative_rate(self, accounting):
        """Test funding income estimation with negative rate."""
        position_value = 10000
        funding_rate = -0.0005  # Negative rate
        hours = 24
        
        estimated = accounting.estimate_funding_income(
            position_value, funding_rate, hours
        )
        
        # For short perp: negative rate means we pay
        # 10000 * -0.0005 * 3 = -15
        assert estimated == pytest.approx(-15, abs=0.01)

    def test_calculate_apr(self, accounting):
        """Test APR calculation."""
        pnl = 100
        equity = 10000
        days = 30
        
        apr = accounting._calculate_apr(pnl, equity, days)
        
        # Daily return = 100/10000/30 = 0.000333
        # APR = 0.000333 * 365 * 100 = 12.17%
        assert apr == pytest.approx(12.17, rel=0.01)

    def test_calculate_apr_zero_equity(self, accounting):
        """Test APR with zero equity."""
        apr = accounting._calculate_apr(100, 0, 30)
        assert apr == 0

    def test_calculate_apr_zero_days(self, accounting):
        """Test APR with zero days."""
        apr = accounting._calculate_apr(100, 10000, 0)
        assert apr == 0


class TestPositionPnL:
    """Tests for PositionPnL dataclass."""

    def test_pnl_dataclass(self):
        """Test PositionPnL dataclass creation."""
        pnl = PositionPnL(
            symbol="BTCUSDT",
            spot_pnl=100,
            futures_pnl=-100,
            funding_income=50,
            trading_fees=20,
            net_pnl=30,
            roi_pct=0.6,
            duration_hours=24,
        )
        
        assert pnl.symbol == "BTCUSDT"
        assert pnl.spot_pnl == 100
        assert pnl.futures_pnl == -100
        assert pnl.funding_income == 50
        assert pnl.trading_fees == 20
        assert pnl.net_pnl == 30
        assert pnl.roi_pct == 0.6
        assert pnl.duration_hours == 24


class TestAccountPnL:
    """Tests for AccountPnL dataclass."""

    def test_account_pnl_dataclass(self):
        """Test AccountPnL dataclass creation."""
        account_pnl = AccountPnL(
            total_equity=10000,
            starting_equity=9000,
            total_pnl=1000,
            total_pnl_pct=11.11,
            realized_pnl=800,
            unrealized_pnl=200,
            total_funding_income=600,
            total_trading_fees=100,
            daily_pnl=50,
            weekly_pnl=300,
            monthly_pnl=1000,
            daily_apr=18.25,
            weekly_apr=15.71,
            monthly_apr=13.33,
            annualized_apr=13.33,
        )
        
        assert account_pnl.total_equity == 10000
        assert account_pnl.starting_equity == 9000
        assert account_pnl.total_pnl == 1000
        assert account_pnl.realized_pnl == 800
        assert account_pnl.unrealized_pnl == 200
