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
