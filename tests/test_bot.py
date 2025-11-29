"""Tests for bot module."""

import sys
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from config.config import Config
from src.bot import FundingBot, main


@pytest.fixture
def config():
    """Create test configuration."""
    return Config()


@pytest.fixture
def mock_bot(config):
    """Create mock bot instance."""
    with patch('src.bot.DataCollector'), \
         patch('src.bot.Strategy'), \
         patch('src.bot.Executor'), \
         patch('src.bot.RiskManager'), \
         patch('src.bot.Accounting'), \
         patch('src.bot.NotificationManager'):
        bot = FundingBot(config)
        return bot


class TestFundingBot:
    """Tests for FundingBot class."""

    def test_bot_initialization(self, mock_bot):
        """Test bot initializes with correct state."""
        assert mock_bot._running is False
        assert mock_bot._shutdown_event is not None

    async def test_bot_stop(self, mock_bot):
        """Test bot stop sets flags correctly."""
        mock_bot._running = True
        await mock_bot.stop()
        assert mock_bot._running is False
        assert mock_bot._shutdown_event.is_set()


class TestSignalHandlerPlatform:
    """Tests for platform-aware signal handler setup."""

    def test_sys_module_imported(self):
        """Test that sys module is imported in bot module."""
        from src import bot
        assert hasattr(bot, 'sys') or 'sys' in dir(bot)

    def test_sys_platform_check(self):
        """Test that sys.platform is available for platform detection."""
        assert hasattr(sys, 'platform')
        assert isinstance(sys.platform, str)

    @patch('src.bot.load_config')
    @patch('src.bot.setup_logging')
    @patch('src.bot.FundingBot')
    async def test_signal_handler_not_setup_on_windows(
        self, mock_bot_class, mock_setup_logging, mock_load_config
    ):
        """Test that signal handlers are not set up on Windows."""
        mock_config = MagicMock()
        mock_load_config.return_value = mock_config
        
        mock_bot_instance = AsyncMock()
        mock_bot_instance.initialize = AsyncMock()
        mock_bot_instance.run = AsyncMock()
        mock_bot_instance.shutdown = AsyncMock()
        mock_bot_instance.stop = AsyncMock()
        mock_bot_class.return_value = mock_bot_instance

        # Mock sys.platform to simulate Windows
        with patch('src.bot.sys.platform', 'win32'):
            with patch('asyncio.get_event_loop') as mock_get_loop:
                mock_loop = MagicMock()
                mock_get_loop.return_value = mock_loop
                
                try:
                    await main()
                except Exception:
                    pass  # We don't care about other errors in this test
                
                # On Windows, add_signal_handler should NOT be called
                mock_loop.add_signal_handler.assert_not_called()

    @patch('src.bot.load_config')
    @patch('src.bot.setup_logging')
    @patch('src.bot.FundingBot')
    async def test_signal_handler_setup_on_unix(
        self, mock_bot_class, mock_setup_logging, mock_load_config
    ):
        """Test that signal handlers are set up on Unix."""
        mock_config = MagicMock()
        mock_load_config.return_value = mock_config
        
        mock_bot_instance = AsyncMock()
        mock_bot_instance.initialize = AsyncMock()
        mock_bot_instance.run = AsyncMock()
        mock_bot_instance.shutdown = AsyncMock()
        mock_bot_instance.stop = AsyncMock()
        mock_bot_class.return_value = mock_bot_instance

        # Mock sys.platform to simulate Unix/Linux
        with patch('src.bot.sys.platform', 'linux'):
            with patch('asyncio.get_event_loop') as mock_get_loop:
                mock_loop = MagicMock()
                mock_get_loop.return_value = mock_loop
                
                try:
                    await main()
                except Exception:
                    pass  # We don't care about other errors in this test
                
                # On Unix, add_signal_handler should be called (twice: SIGINT, SIGTERM)
                assert mock_loop.add_signal_handler.call_count == 2


class TestPaperTradingMode:
    """Tests for paper trading mode in FundingBot."""

    def test_bot_creates_paper_trader_when_enabled(self):
        """Test that FundingBot creates PaperTrader when paper_trading is True."""
        config = Config()
        config.trading.paper_trading = True
        config.trading.paper_initial_balance = 10000.0

        with patch('src.bot.DataCollector'), \
             patch('src.bot.Strategy'), \
             patch('src.bot.Executor'), \
             patch('src.bot.RiskManager'), \
             patch('src.bot.Accounting'), \
             patch('src.bot.NotificationManager'):
            bot = FundingBot(config)
            assert bot._paper_trader is not None
            assert bot._paper_trader.initial_balance == 10000.0

    def test_bot_no_paper_trader_when_disabled(self):
        """Test that FundingBot does not create PaperTrader when paper_trading is False."""
        config = Config()
        config.trading.paper_trading = False

        with patch('src.bot.DataCollector'), \
             patch('src.bot.Strategy'), \
             patch('src.bot.Executor'), \
             patch('src.bot.RiskManager'), \
             patch('src.bot.Accounting'), \
             patch('src.bot.NotificationManager'):
            bot = FundingBot(config)
            assert bot._paper_trader is None

    def test_bot_passes_paper_trader_to_data_collector(self):
        """Test that FundingBot passes PaperTrader to DataCollector."""
        config = Config()
        config.trading.paper_trading = True
        config.trading.paper_initial_balance = 5000.0

        with patch('src.bot.Strategy'), \
             patch('src.bot.Executor'), \
             patch('src.bot.RiskManager'), \
             patch('src.bot.Accounting'), \
             patch('src.bot.NotificationManager'):
            bot = FundingBot(config)
            # Verify the data_collector has the paper_trader set
            assert bot.data_collector._paper_trader is not None
            assert bot.data_collector._paper_trader.initial_balance == 5000.0
