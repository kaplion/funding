"""Notification module for Telegram alerts."""

import logging
from datetime import datetime

from telegram import Bot
from telegram.error import TelegramError

from config.config import Config
from src.models import Position
from src.risk_manager import RiskAlert


logger = logging.getLogger(__name__)


class NotificationManager:
    """Manages notifications via Telegram."""

    def __init__(self, config: Config):
        self.config = config
        self._bot: Bot | None = None
        self._enabled = config.notifications.telegram_enabled

    async def initialize(self) -> None:
        """Initialize Telegram bot."""
        if not self._enabled:
            logger.info("Telegram notifications disabled")
            return

        if not self.config.telegram_bot_token or not self.config.telegram_chat_id:
            logger.warning("Telegram credentials not configured")
            self._enabled = False
            return

        try:
            self._bot = Bot(token=self.config.telegram_bot_token)
            # Test connection
            await self._bot.get_me()
            logger.info("Telegram bot initialized successfully")
        except TelegramError as e:
            logger.error(f"Failed to initialize Telegram bot: {e}")
            self._enabled = False

    async def close(self) -> None:
        """Close notification connections."""
        if self._bot:
            await self._bot.close()

    async def _send_message(self, message: str, parse_mode: str = "HTML") -> bool:
        """Send a message to Telegram.

        Args:
            message: Message text
            parse_mode: HTML or Markdown

        Returns:
            True if sent successfully
        """
        if not self._enabled or not self._bot:
            return False

        try:
            await self._bot.send_message(
                chat_id=self.config.telegram_chat_id,
                text=message,
                parse_mode=parse_mode,
            )
            return True
        except TelegramError as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    async def notify_position_opened(self, position: Position) -> bool:
        """Send notification when a position is opened.

        Args:
            position: The opened position

        Returns:
            True if notification sent
        """
        if not self.config.notifications.notify_on_open:
            return False

        side_emoji = "📈" if position.side.value == "long_spot_short_perp" else "📉"
        position_value = position.spot_quantity * position.spot_entry_price

        message = (
            f"{side_emoji} <b>Position Opened</b>\n\n"
            f"Symbol: <code>{position.symbol}</code>\n"
            f"Side: {position.side.value.replace('_', ' ').title()}\n"
            f"Size: ${position_value:,.2f}\n"
            f"Spot: {position.spot_quantity:.6f} @ ${position.spot_entry_price:,.4f}\n"
            f"Futures: {position.futures_quantity:.6f} @ ${position.futures_entry_price:,.4f}\n"
            f"Funding Rate: {position.entry_funding_rate:.6f} "
            f"({position.entry_funding_rate * 3 * 365 * 100:.2f}% APR)\n"
            f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        )

        return await self._send_message(message)

    async def notify_position_closed(
        self,
        position: Position,
        reason: str = "",
    ) -> bool:
        """Send notification when a position is closed.

        Args:
            position: The closed position
            reason: Reason for closing

        Returns:
            True if notification sent
        """
        if not self.config.notifications.notify_on_close:
            return False

        pnl_emoji = "✅" if position.realized_pnl >= 0 else "❌"

        # Calculate duration
        duration = datetime.utcnow() - (position.opened_at or position.created_at)
        hours = duration.total_seconds() / 3600

        message = (
            f"{pnl_emoji} <b>Position Closed</b>\n\n"
            f"Symbol: <code>{position.symbol}</code>\n"
            f"Duration: {hours:.1f} hours\n\n"
            f"<b>P&L Breakdown:</b>\n"
            f"  Spot P&L: ${position.spot_pnl:,.4f}\n"
            f"  Futures P&L: ${position.futures_pnl:,.4f}\n"
            f"  Funding Income: ${position.accumulated_funding:,.4f}\n"
            f"  Fees: -${position.total_fees:,.4f}\n"
            f"  <b>Net P&L: ${position.realized_pnl:,.4f}</b>\n\n"
            f"Reason: {reason or 'N/A'}\n"
            f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        )

        return await self._send_message(message)

    async def notify_risk_alert(self, alert: RiskAlert) -> bool:
        """Send notification for a risk alert.

        Args:
            alert: The risk alert

        Returns:
            True if notification sent
        """
        if not self.config.notifications.notify_on_risk_warning:
            return False

        level_emoji = {
            "low": "ℹ️",
            "medium": "⚠️",
            "high": "🔶",
            "critical": "🚨",
        }

        emoji = level_emoji.get(alert.level.value, "⚠️")

        message = (
            f"{emoji} <b>Risk Alert: {alert.level.value.upper()}</b>\n\n"
            f"Type: {alert.alert_type.replace('_', ' ').title()}\n"
            f"Message: {alert.message}\n"
        )

        if alert.symbol:
            message += f"Symbol: {alert.symbol}\n"

        if alert.value is not None:
            message += f"Current Value: {alert.value:.4f}\n"

        if alert.threshold is not None:
            message += f"Threshold: {alert.threshold:.4f}\n"

        message += f"\nTime: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"

        return await self._send_message(message)

    async def notify_funding_received(
        self,
        symbol: str,
        funding_rate: float,
        payment_amount: float,
        position_value: float,
    ) -> bool:
        """Send notification when funding is received.

        Args:
            symbol: Trading pair
            funding_rate: The funding rate
            payment_amount: Amount received
            position_value: Position value

        Returns:
            True if notification sent
        """
        emoji = "💰" if payment_amount >= 0 else "💸"

        message = (
            f"{emoji} <b>Funding {'Received' if payment_amount >= 0 else 'Paid'}</b>\n\n"
            f"Symbol: <code>{symbol}</code>\n"
            f"Funding Rate: {funding_rate:.6f}\n"
            f"Amount: ${payment_amount:,.4f}\n"
            f"Position Value: ${position_value:,.2f}\n"
            f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        )

        return await self._send_message(message)

    async def send_daily_summary(
        self,
        total_equity: float,
        daily_pnl: float,
        daily_apr: float,
        open_positions: int,
        total_funding_today: float,
        total_fees_today: float,
    ) -> bool:
        """Send daily summary notification.

        Args:
            total_equity: Current total equity
            daily_pnl: P&L for the day
            daily_apr: Daily APR
            open_positions: Number of open positions
            total_funding_today: Total funding received today
            total_fees_today: Total fees paid today

        Returns:
            True if notification sent
        """
        pnl_emoji = "📈" if daily_pnl >= 0 else "📉"

        message = (
            f"📊 <b>Daily Summary</b>\n\n"
            f"Total Equity: ${total_equity:,.2f}\n"
            f"Daily P&L: {pnl_emoji} ${daily_pnl:,.2f}\n"
            f"Daily APR: {daily_apr:.2f}%\n"
            f"Open Positions: {open_positions}\n\n"
            f"<b>Today's Activity:</b>\n"
            f"  Funding Received: ${total_funding_today:,.4f}\n"
            f"  Fees Paid: ${total_fees_today:,.4f}\n\n"
            f"Date: {datetime.utcnow().strftime('%Y-%m-%d UTC')}"
        )

        return await self._send_message(message)

    async def notify_bot_started(self) -> bool:
        """Send notification when bot starts."""
        message = (
            "🤖 <b>Funding Bot Started</b>\n\n"
            f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"Strategy: Funding Rate Arbitrage\n"
            f"Max Positions: {self.config.strategy.max_positions}\n"
            f"Min Funding Rate: {self.config.strategy.min_funding_rate:.6f}"
        )
        return await self._send_message(message)

    async def notify_bot_stopped(self, reason: str = "") -> bool:
        """Send notification when bot stops."""
        message = (
            "🛑 <b>Funding Bot Stopped</b>\n\n"
            f"Reason: {reason or 'Manual stop'}\n"
            f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        )
        return await self._send_message(message)

    async def notify_error(self, error: str, context: str = "") -> bool:
        """Send notification for an error.

        Args:
            error: Error message
            context: Context where error occurred

        Returns:
            True if notification sent
        """
        message = (
            "❌ <b>Error</b>\n\n"
            f"Context: {context or 'Unknown'}\n"
            f"Error: {error}\n"
            f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        )
        return await self._send_message(message)
