"""Main bot module for orchestrating the funding rate arbitrage strategy."""

import asyncio
import logging
import signal as signal_module
import sys
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.config import Config, load_config
from src.accounting import Accounting
from src.data_collector import DataCollector
from src.executor import Executor
from src.models import (
    Position,
    PositionSide,
    PositionStatus,
    create_async_session_factory,
    init_database,
)
from src.notifications import NotificationManager
from src.risk_manager import RiskManager
from src.strategy import Signal, Strategy


logger = logging.getLogger(__name__)


class FundingBot:
    """Main bot class for funding rate arbitrage."""

    def __init__(self, config: Config):
        self.config = config

        # Initialize components
        self.data_collector = DataCollector(config)
        self.strategy = Strategy(config, self.data_collector)
        self.executor = Executor(config, self.data_collector)
        self.risk_manager = RiskManager(config, self.data_collector)
        self.accounting = Accounting(config)
        self.notifications = NotificationManager(config)

        # Database
        self._engine = None
        self._session_factory = None

        # Control flags
        self._running = False
        self._shutdown_event = asyncio.Event()

        # State tracking
        self._last_funding_check: datetime | None = None
        self._last_snapshot: datetime | None = None

    async def initialize(self) -> None:
        """Initialize bot components."""
        logger.info("Initializing Funding Bot...")

        # Create logs directory
        log_dir = Path(self.config.logging.log_file).parent
        log_dir.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._engine = await init_database(self.config.database_url)
        self._session_factory = create_async_session_factory(self._engine)

        # Initialize exchange connections
        await self.data_collector.initialize()

        # Initialize notifications
        await self.notifications.initialize()

        logger.info("Bot initialization complete")

    async def shutdown(self) -> None:
        """Shutdown bot components."""
        logger.info("Shutting down Funding Bot...")

        # Close exchange connections
        await self.data_collector.close()

        # Close notifications
        await self.notifications.close()

        # Close database engine
        if self._engine:
            await self._engine.dispose()

        logger.info("Bot shutdown complete")

    def _get_session(self) -> AsyncSession:
        """Get database session."""
        if not self._session_factory:
            raise RuntimeError("Bot not initialized")
        return self._session_factory()

    async def _get_all_positions(self, session: AsyncSession) -> list[Position]:
        """Get all positions from database."""
        stmt = select(Position)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def _get_open_positions(self, session: AsyncSession) -> list[Position]:
        """Get open positions from database."""
        stmt = select(Position).where(Position.status == PositionStatus.OPEN)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def _process_entry_signals(
        self,
        session: AsyncSession,
        positions: list[Position],
        total_equity: float,
    ) -> None:
        """Process entry signals and open new positions."""
        # Scan for opportunities
        signals = await self.strategy.scan_opportunities(positions, total_equity)

        if not signals:
            logger.debug("No entry signals found")
            return

        # Rank opportunities
        ranked_signals = self.strategy.rank_opportunities(signals)

        # Process top signals (limited by max positions)
        open_count = len([p for p in positions if p.status == PositionStatus.OPEN])
        remaining_slots = self.config.strategy.max_positions - open_count

        for signal in ranked_signals[:remaining_slots]:
            if signal.signal == Signal.HOLD:
                continue

            # Check position limits
            allowed, reason = self.risk_manager.check_position_limits(
                positions=positions,
                new_position_value=signal.position_size_usdt,
                symbol=signal.symbol,
                total_equity=total_equity,
            )

            if not allowed:
                logger.info(f"Position rejected for {signal.symbol}: {reason}")
                continue

            # Determine position side
            if signal.signal == Signal.ENTER_LONG_SPOT_SHORT_PERP:
                side = PositionSide.LONG_SPOT_SHORT_PERP
            else:
                side = PositionSide.SHORT_SPOT_LONG_PERP

            # Execute entry
            logger.info(f"Opening position: {signal.symbol} - {signal.reason}")

            result = await self.executor.open_position(
                symbol=signal.symbol,
                side=side,
                position_size_usdt=signal.position_size_usdt,
                entry_funding_rate=signal.funding_rate,
            )

            if result.success and result.position:
                # Save position to database
                session.add(result.position)
                if result.spot_order:
                    session.add(result.spot_order)
                if result.futures_order:
                    session.add(result.futures_order)
                await session.commit()

                # Send notification
                await self.notifications.notify_position_opened(result.position)

                logger.info(
                    f"Position opened successfully: {signal.symbol} "
                    f"size=${result.position.position_value:.2f}"
                )
            else:
                logger.error(
                    f"Failed to open position for {signal.symbol}: {result.error}"
                )
                await self.notifications.notify_error(
                    error=result.error or "Unknown error",
                    context=f"Opening position for {signal.symbol}",
                )

    async def _process_exit_signals(self, session: AsyncSession) -> None:
        """Process exit signals and close positions."""
        # Get open positions
        open_positions = await self._get_open_positions(session)

        if not open_positions:
            return

        # Evaluate positions for exit
        exit_signals = await self.strategy.evaluate_positions(open_positions)

        for signal in exit_signals:
            if signal.signal != Signal.EXIT:
                continue

            # Find position
            position = next(
                (p for p in open_positions if p.symbol == signal.symbol), None
            )
            if not position:
                continue

            # Execute exit
            logger.info(f"Closing position: {signal.symbol} - {signal.reason}")

            result = await self.executor.close_position(position)

            if result.success and result.position:
                # Update position in database
                await session.commit()

                # Send notification
                await self.notifications.notify_position_closed(
                    result.position, reason=signal.reason
                )

                logger.info(
                    f"Position closed: {signal.symbol} "
                    f"P&L=${result.position.realized_pnl:.2f}"
                )
            else:
                logger.error(
                    f"Failed to close position for {signal.symbol}: {result.error}"
                )

    async def _check_risk_positions(self, session: AsyncSession) -> None:
        """Check for positions that need to be closed due to risk."""
        open_positions = await self._get_open_positions(session)

        if not open_positions:
            return

        # Get positions to close due to risk
        positions_to_close = await self.risk_manager.get_positions_to_close(
            open_positions
        )

        for position in positions_to_close:
            logger.warning(f"Closing position due to risk: {position.symbol}")

            result = await self.executor.close_position(position)

            if result.success:
                await session.commit()
                await self.notifications.notify_position_closed(
                    position, reason="Risk management"
                )

        # Check and send risk alerts
        metrics = await self.risk_manager.calculate_risk_metrics(open_positions)
        for alert in metrics.alerts:
            await self.notifications.notify_risk_alert(alert)

    async def _check_funding_payments(self, session: AsyncSession) -> None:
        """Check and record funding payments for open positions."""
        now = datetime.utcnow()

        # Only check around funding times (every 8 hours: 0:00, 8:00, 16:00 UTC)
        hour = now.hour
        minute = now.minute

        # Check within 5 minutes after funding time
        funding_hours = [0, 8, 16]
        should_check = any(
            hour == h and 0 <= minute <= 5 for h in funding_hours
        )

        if not should_check:
            return

        # Avoid duplicate checks
        if self._last_funding_check:
            time_since_check = now - self._last_funding_check
            if time_since_check < timedelta(minutes=10):
                return

        self._last_funding_check = now

        open_positions = await self._get_open_positions(session)

        for position in open_positions:
            # Get current funding rate
            funding_data = await self.data_collector.get_funding_rate(position.symbol)

            if not funding_data:
                continue

            # Calculate funding payment
            # For short perpetual (positive funding), we receive funding
            # For long perpetual (negative funding), we receive funding
            funding_rate = funding_data.funding_rate
            position_value = position.futures_quantity * funding_data.mark_price

            if position.side.value == "long_spot_short_perp":
                # Short perp: positive funding = we receive
                payment_amount = position_value * funding_rate
            else:
                # Long perp: negative funding = we receive (sign flipped)
                payment_amount = -position_value * funding_rate

            # Record payment
            await self.accounting.record_funding_payment(
                session=session,
                position=position,
                funding_rate=funding_rate,
                payment_amount=payment_amount,
                funding_time=now,
            )

            # Send notification (optional, can be noisy)
            if abs(payment_amount) > 0.01:  # Only notify for significant payments
                await self.notifications.notify_funding_received(
                    symbol=position.symbol,
                    funding_rate=funding_rate,
                    payment_amount=payment_amount,
                    position_value=position_value,
                )

    async def _save_snapshot(self, session: AsyncSession) -> None:
        """Save account snapshot periodically."""
        now = datetime.utcnow()

        # Save snapshot every 5 minutes
        if self._last_snapshot:
            time_since_snapshot = now - self._last_snapshot
            if time_since_snapshot < timedelta(minutes=5):
                return

        self._last_snapshot = now

        # Get account data
        balance = await self.data_collector.get_account_balance()
        margin_ratio = await self.data_collector.get_margin_ratio()
        positions = await self._get_all_positions(session)

        # Save snapshot
        await self.accounting.save_account_snapshot(
            session=session,
            positions=positions,
            spot_balance=balance.get("spot_total", 0),
            futures_balance=balance.get("futures_total", 0),
            margin_ratio=margin_ratio,
        )

    async def run_once(self) -> None:
        """Run one iteration of the bot loop."""
        async with self._get_session() as session:
            try:
                # Check if trading should be paused
                positions = await self._get_all_positions(session)
                should_pause, reason = await self.risk_manager.should_pause_trading(
                    positions
                )

                if should_pause:
                    logger.warning(f"Trading paused: {reason}")
                    # Still check risk and record funding even when paused
                    await self._check_risk_positions(session)
                    await self._check_funding_payments(session)
                    await self._save_snapshot(session)
                    return

                # Get account balance
                balance = await self.data_collector.get_account_balance()
                total_equity = balance.get("total_equity", 0)

                if total_equity <= 0:
                    logger.warning("No account equity available")
                    return

                # Process exit signals first
                await self._process_exit_signals(session)

                # Process entry signals
                await self._process_entry_signals(session, positions, total_equity)

                # Check risk positions
                await self._check_risk_positions(session)

                # Check funding payments
                await self._check_funding_payments(session)

                # Save snapshot
                await self._save_snapshot(session)

            except Exception as e:
                logger.error(f"Error in bot loop iteration: {e}", exc_info=True)
                await self.notifications.notify_error(
                    error=str(e), context="Bot loop iteration"
                )

    async def run(self) -> None:
        """Run the bot main loop."""
        self._running = True
        self._shutdown_event.clear()

        await self.notifications.notify_bot_started()
        logger.info("Bot started - entering main loop")

        try:
            while self._running and not self._shutdown_event.is_set():
                await self.run_once()

                # Wait for recheck interval or shutdown
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=self.config.strategy.recheck_interval,
                    )
                except asyncio.TimeoutError:
                    pass  # Normal timeout, continue loop

        except Exception as e:
            logger.error(f"Fatal error in bot loop: {e}", exc_info=True)
            await self.notifications.notify_error(error=str(e), context="Bot main loop")
        finally:
            self._running = False
            await self.notifications.notify_bot_stopped()
            logger.info("Bot stopped")

    async def stop(self) -> None:
        """Stop the bot."""
        logger.info("Stopping bot...")
        self._running = False
        self._shutdown_event.set()


def setup_logging(config: Config) -> None:
    """Setup logging configuration."""
    import io

    log_level = getattr(logging, config.logging.level.upper(), logging.INFO)

    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Setup root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Console handler with UTF-8 encoding for Windows to avoid UnicodeEncodeError
    # This is a standard fix for Windows console encoding issues
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler (if enabled)
    if config.logging.log_to_file:
        log_path = Path(config.logging.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        from logging.handlers import RotatingFileHandler

        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=config.logging.max_file_size * 1024 * 1024,
            backupCount=config.logging.backup_count,
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


async def main(config_path: str | None = None) -> None:
    """Main entry point."""
    # Load configuration
    config = load_config(config_path)

    # Setup logging
    setup_logging(config)

    logger.info("Starting Binance Funding Rate Arbitrage Bot")

    # Create bot instance
    bot = FundingBot(config)

    # Setup signal handlers (Unix only - Windows doesn't support add_signal_handler)
    if sys.platform != "win32":
        loop = asyncio.get_event_loop()

        def signal_handler():
            logger.info("Received shutdown signal")
            asyncio.create_task(bot.stop())

        for sig in (signal_module.SIGINT, signal_module.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)

    try:
        # Initialize bot
        await bot.initialize()

        # Run bot
        await bot.run()

    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
        await bot.stop()

    finally:
        # Shutdown
        await bot.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
