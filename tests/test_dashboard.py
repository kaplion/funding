"""Tests for dashboard module."""

import pytest

from config.config import Config
from src.dashboard import Dashboard, create_dashboard


@pytest.fixture
def config():
    """Create test configuration."""
    return Config()


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


class TestDashboardPaperTrading:
    """Tests for paper trading mode in Dashboard."""

    def test_dashboard_creates_paper_trader_when_enabled(self, paper_config):
        """Test that Dashboard creates PaperTrader when paper_trading is True."""
        dashboard = Dashboard(paper_config)
        
        assert dashboard._paper_trader is not None
        assert dashboard._paper_trader.initial_balance == 10000.0

    def test_dashboard_no_paper_trader_when_disabled(self, live_config):
        """Test that Dashboard does not create PaperTrader when paper_trading is False."""
        dashboard = Dashboard(live_config)
        
        assert dashboard._paper_trader is None

    def test_dashboard_creates_data_collector_when_not_provided(self, paper_config):
        """Test that Dashboard creates DataCollector when not provided."""
        dashboard = Dashboard(paper_config)
        
        assert dashboard.data_collector is not None

    def test_dashboard_passes_paper_trader_to_data_collector(self, paper_config):
        """Test that Dashboard passes PaperTrader to its DataCollector."""
        dashboard = Dashboard(paper_config)
        
        assert dashboard.data_collector._paper_trader is not None
        assert dashboard.data_collector._paper_trader.initial_balance == 10000.0
        # Verify they are the same instance
        assert dashboard.data_collector._paper_trader is dashboard._paper_trader

    def test_dashboard_uses_provided_data_collector(self, paper_config):
        """Test that Dashboard uses provided DataCollector instead of creating new one."""
        from src.data_collector import DataCollector
        
        provided_collector = DataCollector(paper_config)
        dashboard = Dashboard(paper_config, data_collector=provided_collector)
        
        assert dashboard.data_collector is provided_collector

    def test_dashboard_paper_trader_balance(self, paper_config):
        """Test that Dashboard's paper trader has correct initial balance."""
        paper_config.trading.paper_initial_balance = 5000.0
        
        dashboard = Dashboard(paper_config)
        
        assert dashboard._paper_trader is not None
        assert dashboard._paper_trader.initial_balance == 5000.0
        assert dashboard._paper_trader.spot_balance == 2500.0
        assert dashboard._paper_trader.futures_balance == 2500.0


class TestCreateDashboard:
    """Tests for create_dashboard function."""

    def test_create_dashboard_paper_mode(self, paper_config):
        """Test create_dashboard with paper trading enabled."""
        dashboard = create_dashboard(paper_config)
        
        assert isinstance(dashboard, Dashboard)
        assert dashboard._paper_trader is not None

    def test_create_dashboard_live_mode(self, live_config):
        """Test create_dashboard with live trading."""
        dashboard = create_dashboard(live_config)
        
        assert isinstance(dashboard, Dashboard)
        assert dashboard._paper_trader is None

    def test_create_dashboard_with_data_collector(self, paper_config):
        """Test create_dashboard with provided data collector."""
        from src.data_collector import DataCollector
        
        collector = DataCollector(paper_config)
        dashboard = create_dashboard(paper_config, data_collector=collector)
        
        assert dashboard.data_collector is collector


class TestDashboardPaperTradingBalance:
    """Tests for paper trading balance in Dashboard."""

    @pytest.mark.asyncio
    async def test_data_collector_returns_paper_balance(self, paper_config):
        """Test that DataCollector returns paper trader balance when in paper mode."""
        dashboard = Dashboard(paper_config)
        
        # The data collector should return the paper trader's balance
        balance = await dashboard.data_collector.get_account_balance()
        
        assert balance["total_equity"] == 10000.0
        assert balance["spot_total"] == 5000.0
        assert balance["futures_total"] == 5000.0

    @pytest.mark.asyncio
    async def test_data_collector_returns_paper_margin_ratio(self, paper_config):
        """Test that DataCollector returns 0.0 margin ratio in paper mode."""
        dashboard = Dashboard(paper_config)
        
        # Paper trading mode should return 0.0 margin ratio
        margin_ratio = await dashboard.data_collector.get_margin_ratio()
        
        assert margin_ratio == 0.0
