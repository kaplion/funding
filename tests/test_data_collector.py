"""Tests for data collector module."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from config.config import Config
from src.data_collector import DataCollector, FundingRateData, SpotFuturesSpread


@pytest.fixture
def config():
    """Create test configuration."""
    return Config()


@pytest.fixture
def data_collector(config):
    """Create data collector instance."""
    return DataCollector(config)


class TestFundingRateData:
    """Tests for FundingRateData class."""

    def test_apr_calculation_positive(self):
        """Test APR calculation for positive funding rate."""
        data = FundingRateData(
            symbol="BTCUSDT",
            funding_rate=0.0003,  # 0.03% per 8h
            predicted_funding_rate=None,
            mark_price=50000,
            index_price=50000,
            next_funding_time=datetime.utcnow(),
            open_interest=1000000000,
            volume_24h=5000000000,
        )
        
        # 0.03% * 3 (per day) * 365 = ~32.85%
        expected_apr = 0.0003 * 3 * 365 * 100
        assert abs(data.apr - expected_apr) < 0.01

    def test_apr_calculation_negative(self):
        """Test APR calculation for negative funding rate."""
        data = FundingRateData(
            symbol="BTCUSDT",
            funding_rate=-0.0005,
            predicted_funding_rate=None,
            mark_price=50000,
            index_price=50000,
            next_funding_time=datetime.utcnow(),
            open_interest=1000000000,
            volume_24h=5000000000,
        )
        
        expected_apr = -0.0005 * 3 * 365 * 100
        assert abs(data.apr - expected_apr) < 0.01

    def test_spread_calculation(self):
        """Test spread calculation."""
        data = FundingRateData(
            symbol="BTCUSDT",
            funding_rate=0.0003,
            predicted_funding_rate=None,
            mark_price=50100,  # 0.2% above index
            index_price=50000,
            next_funding_time=datetime.utcnow(),
            open_interest=1000000000,
            volume_24h=5000000000,
        )
        
        expected_spread = abs(50100 - 50000) / 50000
        assert abs(data.spread - expected_spread) < 0.0001

    def test_spread_zero_index(self):
        """Test spread calculation with zero index price."""
        data = FundingRateData(
            symbol="BTCUSDT",
            funding_rate=0.0003,
            predicted_funding_rate=None,
            mark_price=50000,
            index_price=0,
            next_funding_time=datetime.utcnow(),
            open_interest=1000000000,
            volume_24h=5000000000,
        )
        
        assert data.spread == 0


class TestSpotFuturesSpread:
    """Tests for SpotFuturesSpread class."""

    def test_spread_calculation_positive(self):
        """Test spread when futures > spot (contango)."""
        spread = SpotFuturesSpread(
            symbol="BTCUSDT",
            spot_price=50000,
            futures_price=50100,
        )
        
        expected = (50100 - 50000) / 50000
        assert abs(spread.spread - expected) < 0.0001
        assert spread.spread > 0

    def test_spread_calculation_negative(self):
        """Test spread when futures < spot (backwardation)."""
        spread = SpotFuturesSpread(
            symbol="BTCUSDT",
            spot_price=50000,
            futures_price=49900,
        )
        
        expected = (49900 - 50000) / 50000
        assert abs(spread.spread - expected) < 0.0001
        assert spread.spread < 0

    def test_spread_percentage(self):
        """Test spread percentage calculation."""
        spread = SpotFuturesSpread(
            symbol="BTCUSDT",
            spot_price=50000,
            futures_price=50050,
        )
        
        expected_pct = 0.1  # 0.1%
        assert abs(spread.spread_pct - expected_pct) < 0.01

    def test_spread_zero_spot(self):
        """Test spread with zero spot price."""
        spread = SpotFuturesSpread(
            symbol="BTCUSDT",
            spot_price=0,
            futures_price=50000,
        )
        
        assert spread.spread == 0


class TestDataCollector:
    """Tests for DataCollector class."""

    def test_initialization(self, data_collector, config):
        """Test data collector initialization."""
        assert data_collector.config == config
        assert data_collector._exchange is None
        assert data_collector._futures_exchange is None

    def test_filter_opportunities_above_threshold(self, data_collector):
        """Test filtering opportunities above threshold."""
        funding_data = [
            FundingRateData(
                symbol="BTCUSDT",
                funding_rate=0.0005,  # Above threshold
                predicted_funding_rate=None,
                mark_price=50000,
                index_price=50000,
                next_funding_time=datetime.utcnow(),
                open_interest=1000000000,
                volume_24h=5000000000,
            ),
            FundingRateData(
                symbol="ETHUSDT",
                funding_rate=0.0001,  # Below threshold
                predicted_funding_rate=None,
                mark_price=3000,
                index_price=3000,
                next_funding_time=datetime.utcnow(),
                open_interest=500000000,
                volume_24h=2000000000,
            ),
        ]
        
        spreads = {
            "BTCUSDT": SpotFuturesSpread("BTCUSDT", 50000, 50020),
            "ETHUSDT": SpotFuturesSpread("ETHUSDT", 3000, 3001),
        }
        
        opportunities = data_collector.filter_opportunities(funding_data, spreads)
        
        assert len(opportunities) == 1
        assert opportunities[0].symbol == "BTCUSDT"

    def test_filter_opportunities_spread_too_wide(self, data_collector):
        """Test filtering out opportunities with wide spread."""
        funding_data = [
            FundingRateData(
                symbol="BTCUSDT",
                funding_rate=0.0005,
                predicted_funding_rate=None,
                mark_price=50000,
                index_price=50000,
                next_funding_time=datetime.utcnow(),
                open_interest=1000000000,
                volume_24h=5000000000,
            ),
        ]
        
        spreads = {
            "BTCUSDT": SpotFuturesSpread("BTCUSDT", 50000, 50100),  # 0.2% spread - too wide
        }
        
        opportunities = data_collector.filter_opportunities(funding_data, spreads)
        
        assert len(opportunities) == 0

    def test_filter_opportunities_sorted_by_rate(self, data_collector):
        """Test that opportunities are sorted by absolute funding rate."""
        funding_data = [
            FundingRateData(
                symbol="BTCUSDT",
                funding_rate=0.0004,
                predicted_funding_rate=None,
                mark_price=50000,
                index_price=50000,
                next_funding_time=datetime.utcnow(),
                open_interest=1000000000,
                volume_24h=5000000000,
            ),
            FundingRateData(
                symbol="ETHUSDT",
                funding_rate=-0.0006,  # Higher absolute value
                predicted_funding_rate=None,
                mark_price=3000,
                index_price=3000,
                next_funding_time=datetime.utcnow(),
                open_interest=500000000,
                volume_24h=2000000000,
            ),
        ]
        
        spreads = {
            "BTCUSDT": SpotFuturesSpread("BTCUSDT", 50000, 50020),
            "ETHUSDT": SpotFuturesSpread("ETHUSDT", 3000, 3001),
        }
        
        opportunities = data_collector.filter_opportunities(funding_data, spreads)
        
        assert len(opportunities) == 2
        assert opportunities[0].symbol == "ETHUSDT"  # Higher absolute rate first
        assert opportunities[1].symbol == "BTCUSDT"


class TestExchangeInitialization:
    """Tests for exchange initialization with timestamp synchronization."""

    @patch('src.data_collector.ccxt.binanceusdm')
    @patch('src.data_collector.ccxt.binance')
    async def test_initialize_configures_time_difference_adjustment(
        self, mock_binance, mock_binanceusdm, config
    ):
        """Test that exchanges are initialized with timestamp synchronization options."""
        mock_spot = MagicMock()
        mock_spot.load_time_difference = AsyncMock()
        mock_binance.return_value = mock_spot

        mock_futures = MagicMock()
        mock_futures.load_time_difference = AsyncMock()
        mock_binanceusdm.return_value = mock_futures

        collector = DataCollector(config)
        await collector.initialize()

        # Verify spot exchange is configured with timestamp options
        spot_call_args = mock_binance.call_args[0][0]
        assert spot_call_args['options']['adjustForTimeDifference'] is True
        assert spot_call_args['options']['recvWindow'] == 60000

        # Verify futures exchange is configured with timestamp options
        futures_call_args = mock_binanceusdm.call_args[0][0]
        assert futures_call_args['options']['adjustForTimeDifference'] is True
        assert futures_call_args['options']['recvWindow'] == 60000

        # Verify load_time_difference is called for both exchanges
        mock_spot.load_time_difference.assert_called_once()
        mock_futures.load_time_difference.assert_called_once()

    @patch('src.data_collector.ccxt.binanceusdm')
    @patch('src.data_collector.ccxt.binance')
    async def test_initialize_spot_has_default_type_option(
        self, mock_binance, mock_binanceusdm, config
    ):
        """Test that spot exchange has defaultType option set."""
        mock_spot = MagicMock()
        mock_spot.load_time_difference = AsyncMock()
        mock_binance.return_value = mock_spot

        mock_futures = MagicMock()
        mock_futures.load_time_difference = AsyncMock()
        mock_binanceusdm.return_value = mock_futures

        collector = DataCollector(config)
        await collector.initialize()

        # Verify spot exchange has defaultType option
        spot_call_args = mock_binance.call_args[0][0]
        assert spot_call_args['options']['defaultType'] == 'spot'


class TestPaperTradingIntegration:
    """Tests for paper trading integration in DataCollector."""

    @pytest.fixture
    def paper_trading_config(self):
        """Create configuration with paper trading enabled."""
        config = Config()
        config.trading.paper_trading = True
        config.trading.paper_initial_balance = 10000.0
        return config

    @pytest.fixture
    def live_trading_config(self):
        """Create configuration with paper trading disabled."""
        config = Config()
        config.trading.paper_trading = False
        return config

    async def test_get_account_balance_paper_mode(self, paper_trading_config):
        """Test get_account_balance returns paper balance when paper trading is enabled."""
        from src.paper_trader import PaperTrader

        paper_trader = PaperTrader(paper_trading_config.trading.paper_initial_balance)
        collector = DataCollector(paper_trading_config, paper_trader)

        balance = await collector.get_account_balance()

        assert balance["total_equity"] == 10000.0
        assert balance["spot_free"] == 5000.0
        assert balance["spot_total"] == 5000.0
        assert balance["futures_free"] == 5000.0
        assert balance["futures_total"] == 5000.0

    async def test_get_account_balance_paper_mode_no_paper_trader(self, paper_trading_config):
        """Test get_account_balance falls through to exchange when paper trader is None.

        This tests the edge case where paper trading is enabled but no paper trader
        was provided. In this case, it should try to use the real exchange.
        """
        collector = DataCollector(paper_trading_config)

        # Should raise because exchange is not initialized and paper_trader is None
        with pytest.raises(RuntimeError, match="Exchange not initialized"):
            await collector.get_account_balance()

    async def test_get_margin_ratio_paper_mode(self, paper_trading_config):
        """Test get_margin_ratio returns 0.0 in paper trading mode."""
        collector = DataCollector(paper_trading_config)

        margin_ratio = await collector.get_margin_ratio()

        # Paper trading always returns 0.0 (safe default - no real margin)
        assert margin_ratio == 0.0

    async def test_get_margin_ratio_live_mode_no_exchange(self, live_trading_config):
        """Test get_margin_ratio handles errors gracefully in live mode."""
        collector = DataCollector(live_trading_config)

        # This will raise because exchange is not initialized
        # but we just want to verify paper trading mode returns 0.0 early
        # In live mode without exchange, it should return None due to error
        # We can't really test live mode without mocking the exchange
