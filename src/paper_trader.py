"""Paper trading simulator for testing without real funds."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
import uuid


logger = logging.getLogger(__name__)


@dataclass
class PaperPosition:
    """Paper trading position."""

    id: str
    symbol: str
    side: str  # "long_spot_short_perp" or "short_spot_long_perp"
    spot_quantity: float
    spot_entry_price: float
    futures_quantity: float
    futures_entry_price: float
    entry_funding_rate: float
    opened_at: datetime
    accumulated_funding: float = 0.0
    funding_payments_count: int = 0


@dataclass
class PaperTrade:
    """Paper trading trade record."""

    id: str
    symbol: str
    side: str  # "buy" or "sell"
    is_futures: bool
    quantity: float
    price: float
    fee: float
    timestamp: datetime


@dataclass
class PaperFundingPayment:
    """Paper funding payment record."""

    position_id: str
    symbol: str
    funding_rate: float
    payment_amount: float
    position_value: float
    funding_time: datetime


class PaperTrader:
    """Paper trading simulator for testing without real funds."""

    def __init__(self, initial_balance: float = 10000.0):
        """Initialize paper trader with virtual balance.

        Args:
            initial_balance: Initial virtual balance in USDT
        """
        self.initial_balance = initial_balance
        self.spot_balance = initial_balance / 2
        self.futures_balance = initial_balance / 2
        self.positions: dict[str, PaperPosition] = {}
        self.trade_history: list[PaperTrade] = []
        self.funding_history: list[PaperFundingPayment] = []
        self.spot_holdings: dict[str, float] = {}  # symbol -> quantity

        logger.info(
            f"Paper trader initialized with ${initial_balance:.2f} "
            f"(spot: ${self.spot_balance:.2f}, futures: ${self.futures_balance:.2f})"
        )

    async def get_balance(self) -> dict[str, float]:
        """Return simulated balance.

        Returns:
            Dictionary with balance information
        """
        # Calculate unrealized P&L from positions
        total_spot_value = self.spot_balance
        for symbol, qty in self.spot_holdings.items():
            # For paper trading, we just use a rough estimate
            # In real implementation, would fetch current prices
            total_spot_value += qty * 100  # Placeholder

        total_equity = self.spot_balance + self.futures_balance

        return {
            "spot_free": self.spot_balance,
            "spot_total": self.spot_balance,
            "futures_free": self.futures_balance,
            "futures_total": self.futures_balance,
            "total_equity": total_equity,
        }

    async def open_position(
        self,
        symbol: str,
        side: str,
        size_usdt: float,
        funding_rate: float,
        spot_price: float,
        futures_price: float,
    ) -> dict[str, Any]:
        """Simulate opening a position.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            side: Position side ("long_spot_short_perp" or "short_spot_long_perp")
            size_usdt: Position size in USDT
            funding_rate: Current funding rate
            spot_price: Current spot price
            futures_price: Current futures price

        Returns:
            Dictionary with position details and success status
        """
        # Check if we already have a position in this symbol
        if symbol in self.positions:
            return {
                "success": False,
                "error": f"Already have position in {symbol}",
            }

        # Calculate quantities
        spot_quantity = size_usdt / spot_price
        futures_quantity = size_usdt / futures_price

        # Calculate fees (0.1% for spot, 0.04% for futures)
        spot_fee = size_usdt * 0.001
        futures_fee = size_usdt * 0.0004
        total_fee = spot_fee + futures_fee

        # Check balance
        required_balance = size_usdt + total_fee
        if side == "long_spot_short_perp":
            # Need USDT in spot to buy asset
            if self.spot_balance < required_balance / 2:
                return {
                    "success": False,
                    "error": f"Insufficient spot balance: {self.spot_balance:.2f}",
                }
            if self.futures_balance < required_balance / 2:
                return {
                    "success": False,
                    "error": f"Insufficient futures balance: {self.futures_balance:.2f}",
                }
        else:
            # For short spot, we need to have the asset or margin
            # Simplified: just check USDT balance
            if self.spot_balance < required_balance / 2:
                return {
                    "success": False,
                    "error": f"Insufficient spot balance: {self.spot_balance:.2f}",
                }
            if self.futures_balance < required_balance / 2:
                return {
                    "success": False,
                    "error": f"Insufficient futures balance: {self.futures_balance:.2f}",
                }

        # Deduct from balances
        self.spot_balance -= (size_usdt / 2 + spot_fee)
        self.futures_balance -= (size_usdt / 2 + futures_fee)

        # Create position
        position_id = str(uuid.uuid4())[:8]
        position = PaperPosition(
            id=position_id,
            symbol=symbol,
            side=side,
            spot_quantity=spot_quantity,
            spot_entry_price=spot_price,
            futures_quantity=futures_quantity,
            futures_entry_price=futures_price,
            entry_funding_rate=funding_rate,
            opened_at=datetime.utcnow(),
        )
        self.positions[symbol] = position

        # Record trades
        spot_trade = PaperTrade(
            id=str(uuid.uuid4())[:8],
            symbol=symbol,
            side="buy" if side == "long_spot_short_perp" else "sell",
            is_futures=False,
            quantity=spot_quantity,
            price=spot_price,
            fee=spot_fee,
            timestamp=datetime.utcnow(),
        )
        futures_trade = PaperTrade(
            id=str(uuid.uuid4())[:8],
            symbol=symbol,
            side="sell" if side == "long_spot_short_perp" else "buy",
            is_futures=True,
            quantity=futures_quantity,
            price=futures_price,
            fee=futures_fee,
            timestamp=datetime.utcnow(),
        )
        self.trade_history.extend([spot_trade, futures_trade])

        logger.info(
            f"Paper position opened: {symbol} {side} "
            f"spot={spot_quantity:.6f}@{spot_price:.2f} "
            f"futures={futures_quantity:.6f}@{futures_price:.2f}"
        )

        return {
            "success": True,
            "position_id": position_id,
            "position": position,
            "spot_trade": spot_trade,
            "futures_trade": futures_trade,
            "total_fee": total_fee,
        }

    async def close_position(
        self,
        symbol: str,
        spot_price: float,
        futures_price: float,
    ) -> dict[str, Any]:
        """Simulate closing a position.

        Args:
            symbol: Trading pair
            spot_price: Current spot price
            futures_price: Current futures price

        Returns:
            Dictionary with close details and realized P&L
        """
        if symbol not in self.positions:
            return {
                "success": False,
                "error": f"No position found for {symbol}",
            }

        position = self.positions[symbol]

        # Calculate P&L
        if position.side == "long_spot_short_perp":
            # Long spot: profit if price went up
            spot_pnl = (spot_price - position.spot_entry_price) * position.spot_quantity
            # Short futures: profit if price went down
            futures_pnl = (
                position.futures_entry_price - futures_price
            ) * position.futures_quantity
        else:
            # Short spot: profit if price went down
            spot_pnl = (
                position.spot_entry_price - spot_price
            ) * position.spot_quantity
            # Long futures: profit if price went up
            futures_pnl = (
                futures_price - position.futures_entry_price
            ) * position.futures_quantity

        # Calculate close fees
        close_spot_value = position.spot_quantity * spot_price
        close_futures_value = position.futures_quantity * futures_price
        spot_fee = close_spot_value * 0.001
        futures_fee = close_futures_value * 0.0004
        total_fee = spot_fee + futures_fee

        # Calculate total realized P&L
        realized_pnl = spot_pnl + futures_pnl + position.accumulated_funding - total_fee

        # Return value to balances
        self.spot_balance += close_spot_value - spot_fee + spot_pnl
        self.futures_balance += close_futures_value - futures_fee + futures_pnl

        # Record close trades
        close_spot_trade = PaperTrade(
            id=str(uuid.uuid4())[:8],
            symbol=symbol,
            side="sell" if position.side == "long_spot_short_perp" else "buy",
            is_futures=False,
            quantity=position.spot_quantity,
            price=spot_price,
            fee=spot_fee,
            timestamp=datetime.utcnow(),
        )
        close_futures_trade = PaperTrade(
            id=str(uuid.uuid4())[:8],
            symbol=symbol,
            side="buy" if position.side == "long_spot_short_perp" else "sell",
            is_futures=True,
            quantity=position.futures_quantity,
            price=futures_price,
            fee=futures_fee,
            timestamp=datetime.utcnow(),
        )
        self.trade_history.extend([close_spot_trade, close_futures_trade])

        # Remove position
        del self.positions[symbol]

        logger.info(
            f"Paper position closed: {symbol} "
            f"realized_pnl=${realized_pnl:.2f} "
            f"(spot: ${spot_pnl:.2f}, futures: ${futures_pnl:.2f}, "
            f"funding: ${position.accumulated_funding:.2f}, fees: ${total_fee:.2f})"
        )

        return {
            "success": True,
            "spot_pnl": spot_pnl,
            "futures_pnl": futures_pnl,
            "accumulated_funding": position.accumulated_funding,
            "total_fees": total_fee,
            "realized_pnl": realized_pnl,
        }

    async def process_funding(
        self,
        funding_rates: dict[str, float],
        mark_prices: dict[str, float],
    ) -> list[PaperFundingPayment]:
        """Simulate funding payments for open positions.

        Args:
            funding_rates: Dictionary of symbol -> funding rate
            mark_prices: Dictionary of symbol -> mark price

        Returns:
            List of funding payments made
        """
        payments = []

        for symbol, position in self.positions.items():
            if symbol not in funding_rates:
                continue

            funding_rate = funding_rates[symbol]
            mark_price = mark_prices.get(symbol, position.futures_entry_price)
            position_value = position.futures_quantity * mark_price

            # Calculate funding payment
            # For short perpetual (long_spot_short_perp): positive funding = we receive
            # For long perpetual (short_spot_long_perp): positive funding = we pay
            if position.side == "long_spot_short_perp":
                payment_amount = position_value * funding_rate
            else:
                payment_amount = -position_value * funding_rate

            # Update position
            position.accumulated_funding += payment_amount
            position.funding_payments_count += 1

            # Update balance
            self.futures_balance += payment_amount

            # Record payment
            payment = PaperFundingPayment(
                position_id=position.id,
                symbol=symbol,
                funding_rate=funding_rate,
                payment_amount=payment_amount,
                position_value=position_value,
                funding_time=datetime.utcnow(),
            )
            payments.append(payment)
            self.funding_history.append(payment)

            logger.debug(
                f"Paper funding payment: {symbol} "
                f"rate={funding_rate:.6f} "
                f"amount=${payment_amount:.4f}"
            )

        return payments

    async def get_positions(self) -> list[dict[str, Any]]:
        """Get all open paper positions.

        Returns:
            List of position dictionaries
        """
        return [
            {
                "id": pos.id,
                "symbol": pos.symbol,
                "side": pos.side,
                "spot_quantity": pos.spot_quantity,
                "spot_entry_price": pos.spot_entry_price,
                "futures_quantity": pos.futures_quantity,
                "futures_entry_price": pos.futures_entry_price,
                "entry_funding_rate": pos.entry_funding_rate,
                "accumulated_funding": pos.accumulated_funding,
                "funding_payments_count": pos.funding_payments_count,
                "opened_at": pos.opened_at.isoformat(),
            }
            for pos in self.positions.values()
        ]

    async def get_trade_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get trade history.

        Args:
            limit: Maximum number of trades to return

        Returns:
            List of trade dictionaries
        """
        return [
            {
                "id": trade.id,
                "symbol": trade.symbol,
                "side": trade.side,
                "is_futures": trade.is_futures,
                "quantity": trade.quantity,
                "price": trade.price,
                "fee": trade.fee,
                "timestamp": trade.timestamp.isoformat(),
            }
            for trade in self.trade_history[-limit:]
        ]

    async def get_funding_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get funding payment history.

        Args:
            limit: Maximum number of payments to return

        Returns:
            List of funding payment dictionaries
        """
        return [
            {
                "position_id": payment.position_id,
                "symbol": payment.symbol,
                "funding_rate": payment.funding_rate,
                "payment_amount": payment.payment_amount,
                "position_value": payment.position_value,
                "funding_time": payment.funding_time.isoformat(),
            }
            for payment in self.funding_history[-limit:]
        ]

    def get_summary(self) -> dict[str, Any]:
        """Get paper trading summary.

        Returns:
            Dictionary with trading summary
        """
        total_funding = sum(p.payment_amount for p in self.funding_history)
        total_fees = sum(t.fee for t in self.trade_history)

        return {
            "initial_balance": self.initial_balance,
            "spot_balance": self.spot_balance,
            "futures_balance": self.futures_balance,
            "total_equity": self.spot_balance + self.futures_balance,
            "pnl": (self.spot_balance + self.futures_balance) - self.initial_balance,
            "pnl_pct": (
                ((self.spot_balance + self.futures_balance) - self.initial_balance)
                / self.initial_balance
                * 100
                if self.initial_balance > 0
                else 0
            ),
            "open_positions": len(self.positions),
            "total_trades": len(self.trade_history),
            "total_funding_payments": len(self.funding_history),
            "total_funding_earned": total_funding,
            "total_fees_paid": total_fees,
        }

    def reset(self) -> None:
        """Reset paper trader to initial state."""
        self.spot_balance = self.initial_balance / 2
        self.futures_balance = self.initial_balance / 2
        self.positions.clear()
        self.trade_history.clear()
        self.funding_history.clear()
        self.spot_holdings.clear()
        logger.info("Paper trader reset to initial state")
