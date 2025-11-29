"""Tests for paper trader module."""

import pytest
from datetime import datetime

from src.paper_trader import PaperTrader, PaperPosition


@pytest.fixture
def paper_trader():
    """Create paper trader instance."""
    return PaperTrader(initial_balance=10000.0)


class TestPaperTrader:
    """Tests for PaperTrader class."""

    def test_initialization(self, paper_trader):
        """Test paper trader initializes with correct state."""
        assert paper_trader.initial_balance == 10000.0
        assert paper_trader.spot_balance == 5000.0
        assert paper_trader.futures_balance == 5000.0
        assert len(paper_trader.positions) == 0
        assert len(paper_trader.trade_history) == 0
        assert len(paper_trader.funding_history) == 0

    async def test_get_balance(self, paper_trader):
        """Test get_balance returns correct values."""
        balance = await paper_trader.get_balance()

        assert balance["spot_free"] == 5000.0
        assert balance["spot_total"] == 5000.0
        assert balance["futures_free"] == 5000.0
        assert balance["futures_total"] == 5000.0
        assert balance["total_equity"] == 10000.0

    async def test_open_position_success(self, paper_trader):
        """Test opening a position successfully."""
        result = await paper_trader.open_position(
            symbol="BTCUSDT",
            side="long_spot_short_perp",
            size_usdt=1000.0,
            funding_rate=0.0003,
            spot_price=50000.0,
            futures_price=50050.0,
        )

        assert result["success"] is True
        assert "position_id" in result
        assert "BTCUSDT" in paper_trader.positions
        assert len(paper_trader.trade_history) == 2  # spot + futures

    async def test_open_position_duplicate(self, paper_trader):
        """Test cannot open duplicate position."""
        # First position
        await paper_trader.open_position(
            symbol="BTCUSDT",
            side="long_spot_short_perp",
            size_usdt=1000.0,
            funding_rate=0.0003,
            spot_price=50000.0,
            futures_price=50050.0,
        )

        # Try duplicate
        result = await paper_trader.open_position(
            symbol="BTCUSDT",
            side="long_spot_short_perp",
            size_usdt=1000.0,
            funding_rate=0.0003,
            spot_price=50000.0,
            futures_price=50050.0,
        )

        assert result["success"] is False
        assert "Already have position" in result["error"]

    async def test_open_position_insufficient_balance(self, paper_trader):
        """Test cannot open position with insufficient balance."""
        result = await paper_trader.open_position(
            symbol="BTCUSDT",
            side="long_spot_short_perp",
            size_usdt=50000.0,  # More than available
            funding_rate=0.0003,
            spot_price=50000.0,
            futures_price=50050.0,
        )

        assert result["success"] is False
        assert "Insufficient" in result["error"]

    async def test_close_position_success(self, paper_trader):
        """Test closing a position successfully."""
        # Open position first
        await paper_trader.open_position(
            symbol="BTCUSDT",
            side="long_spot_short_perp",
            size_usdt=1000.0,
            funding_rate=0.0003,
            spot_price=50000.0,
            futures_price=50050.0,
        )

        # Close position
        result = await paper_trader.close_position(
            symbol="BTCUSDT",
            spot_price=50100.0,  # Price increased
            futures_price=50100.0,
        )

        assert result["success"] is True
        assert "realized_pnl" in result
        assert "BTCUSDT" not in paper_trader.positions

    async def test_close_position_not_found(self, paper_trader):
        """Test closing non-existent position."""
        result = await paper_trader.close_position(
            symbol="BTCUSDT",
            spot_price=50000.0,
            futures_price=50000.0,
        )

        assert result["success"] is False
        assert "No position found" in result["error"]

    async def test_process_funding_payments(self, paper_trader):
        """Test funding payment processing."""
        # Open position first
        await paper_trader.open_position(
            symbol="BTCUSDT",
            side="long_spot_short_perp",
            size_usdt=1000.0,
            funding_rate=0.0003,
            spot_price=50000.0,
            futures_price=50050.0,
        )

        # Process funding
        payments = await paper_trader.process_funding(
            funding_rates={"BTCUSDT": 0.0003},
            mark_prices={"BTCUSDT": 50000.0},
        )

        assert len(payments) == 1
        assert payments[0].symbol == "BTCUSDT"
        assert paper_trader.positions["BTCUSDT"].funding_payments_count == 1

    async def test_get_positions(self, paper_trader):
        """Test getting open positions."""
        # Open position
        await paper_trader.open_position(
            symbol="BTCUSDT",
            side="long_spot_short_perp",
            size_usdt=1000.0,
            funding_rate=0.0003,
            spot_price=50000.0,
            futures_price=50050.0,
        )

        positions = await paper_trader.get_positions()

        assert len(positions) == 1
        assert positions[0]["symbol"] == "BTCUSDT"

    def test_get_summary(self, paper_trader):
        """Test getting trading summary."""
        summary = paper_trader.get_summary()

        assert summary["initial_balance"] == 10000.0
        assert summary["total_equity"] == 10000.0
        assert summary["pnl"] == 0
        assert summary["open_positions"] == 0

    def test_reset(self, paper_trader):
        """Test resetting paper trader."""
        # Modify state
        paper_trader.spot_balance = 0
        paper_trader.futures_balance = 0

        # Reset
        paper_trader.reset()

        assert paper_trader.spot_balance == 5000.0
        assert paper_trader.futures_balance == 5000.0
        assert len(paper_trader.positions) == 0


class TestPaperPosition:
    """Tests for PaperPosition dataclass."""

    def test_position_creation(self):
        """Test paper position creation."""
        position = PaperPosition(
            id="test123",
            symbol="BTCUSDT",
            side="long_spot_short_perp",
            spot_quantity=0.02,
            spot_entry_price=50000.0,
            futures_quantity=0.02,
            futures_entry_price=50050.0,
            entry_funding_rate=0.0003,
            opened_at=datetime.utcnow(),
        )

        assert position.id == "test123"
        assert position.symbol == "BTCUSDT"
        assert position.side == "long_spot_short_perp"
        assert position.accumulated_funding == 0.0
        assert position.funding_payments_count == 0
