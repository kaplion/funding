"""Accounting module for P&L tracking and APR calculations."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.config import Config
from src.models import (
    AccountSnapshot,
    FundingPayment,
    Position,
    PositionStatus,
)


logger = logging.getLogger(__name__)


@dataclass
class PositionPnL:
    """P&L breakdown for a position."""

    symbol: str
    spot_pnl: float
    futures_pnl: float
    funding_income: float
    trading_fees: float
    net_pnl: float
    roi_pct: float
    duration_hours: float


@dataclass
class AccountPnL:
    """Overall account P&L summary."""

    total_equity: float
    starting_equity: float
    total_pnl: float
    total_pnl_pct: float
    realized_pnl: float
    unrealized_pnl: float
    total_funding_income: float
    total_trading_fees: float
    daily_pnl: float
    weekly_pnl: float
    monthly_pnl: float
    daily_apr: float
    weekly_apr: float
    monthly_apr: float
    annualized_apr: float


@dataclass
class PositionMetrics:
    """Metrics for a single position."""

    position: Position
    current_funding_rate: float
    current_spread: float
    unrealized_pnl: float
    liquidation_distance: float | None
    time_in_position: timedelta
    accumulated_funding: float
    estimated_daily_funding: float


class Accounting:
    """Handles P&L tracking and performance calculations."""

    def __init__(self, config: Config):
        self.config = config

    async def calculate_position_pnl(
        self,
        position: Position,
        current_spot_price: float | None = None,
        current_futures_price: float | None = None,
    ) -> PositionPnL:
        """Calculate P&L for a single position.

        Args:
            position: The position to calculate
            current_spot_price: Current spot price (for unrealized)
            current_futures_price: Current futures price (for unrealized)

        Returns:
            PositionPnL with breakdown
        """
        # Use exit prices if closed, otherwise use current prices
        spot_exit = position.spot_exit_price or current_spot_price or position.spot_entry_price
        futures_exit = position.futures_exit_price or current_futures_price or position.futures_entry_price

        # Calculate spot P&L
        if position.side.value == "long_spot_short_perp":
            spot_pnl = (spot_exit - position.spot_entry_price) * position.spot_quantity
            futures_pnl = (position.futures_entry_price - futures_exit) * position.futures_quantity
        else:
            spot_pnl = (position.spot_entry_price - spot_exit) * position.spot_quantity
            futures_pnl = (futures_exit - position.futures_entry_price) * position.futures_quantity

        funding_income = position.accumulated_funding
        trading_fees = position.total_fees

        net_pnl = spot_pnl + futures_pnl + funding_income - trading_fees

        # Calculate ROI
        position_value = position.spot_quantity * position.spot_entry_price
        roi_pct = (net_pnl / position_value * 100) if position_value > 0 else 0

        # Calculate duration
        start_time = position.opened_at or position.created_at
        end_time = position.closed_at or datetime.utcnow()
        duration = end_time - start_time
        duration_hours = duration.total_seconds() / 3600

        return PositionPnL(
            symbol=position.symbol,
            spot_pnl=spot_pnl,
            futures_pnl=futures_pnl,
            funding_income=funding_income,
            trading_fees=trading_fees,
            net_pnl=net_pnl,
            roi_pct=roi_pct,
            duration_hours=duration_hours,
        )

    async def calculate_account_pnl(
        self,
        session: AsyncSession,
        positions: list[Position],
        current_equity: float,
    ) -> AccountPnL:
        """Calculate overall account P&L.

        Args:
            session: Database session
            positions: All positions
            current_equity: Current total equity

        Returns:
            AccountPnL with summary
        """
        now = datetime.utcnow()

        # Get starting equity from first snapshot
        stmt = select(AccountSnapshot).order_by(AccountSnapshot.snapshot_time.asc()).limit(1)
        result = await session.execute(stmt)
        first_snapshot = result.scalar_one_or_none()
        starting_equity = first_snapshot.total_equity if first_snapshot else current_equity

        # Calculate realized P&L from closed positions
        closed_positions = [p for p in positions if p.status == PositionStatus.CLOSED]
        realized_pnl = sum(p.realized_pnl for p in closed_positions)

        # Calculate unrealized P&L from open positions
        open_positions = [p for p in positions if p.status == PositionStatus.OPEN]
        unrealized_pnl = sum(
            p.spot_pnl + p.futures_pnl + p.accumulated_funding - p.total_fees
            for p in open_positions
        )

        # Total funding income
        total_funding = sum(p.accumulated_funding for p in positions)

        # Total trading fees
        total_fees = sum(p.total_fees for p in positions)

        # Calculate total P&L
        total_pnl = realized_pnl + unrealized_pnl
        total_pnl_pct = (total_pnl / starting_equity * 100) if starting_equity > 0 else 0

        # Get P&L for different time periods
        daily_pnl = await self._get_period_pnl(session, now - timedelta(days=1))
        weekly_pnl = await self._get_period_pnl(session, now - timedelta(days=7))
        monthly_pnl = await self._get_period_pnl(session, now - timedelta(days=30))

        # Calculate APRs
        daily_apr = self._calculate_apr(daily_pnl, starting_equity, 1)
        weekly_apr = self._calculate_apr(weekly_pnl, starting_equity, 7)
        monthly_apr = self._calculate_apr(monthly_pnl, starting_equity, 30)

        # Annualized APR based on actual performance
        days_active = (now - (first_snapshot.snapshot_time if first_snapshot else now)).days or 1
        annualized_apr = self._calculate_apr(total_pnl, starting_equity, days_active)

        return AccountPnL(
            total_equity=current_equity,
            starting_equity=starting_equity,
            total_pnl=total_pnl,
            total_pnl_pct=total_pnl_pct,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            total_funding_income=total_funding,
            total_trading_fees=total_fees,
            daily_pnl=daily_pnl,
            weekly_pnl=weekly_pnl,
            monthly_pnl=monthly_pnl,
            daily_apr=daily_apr,
            weekly_apr=weekly_apr,
            monthly_apr=monthly_apr,
            annualized_apr=annualized_apr,
        )

    async def _get_period_pnl(
        self,
        session: AsyncSession,
        start_time: datetime,
    ) -> float:
        """Get P&L for a specific period.

        Args:
            session: Database session
            start_time: Start of period

        Returns:
            P&L for the period
        """
        # Get snapshot at start of period
        stmt = (
            select(AccountSnapshot)
            .where(AccountSnapshot.snapshot_time >= start_time)
            .order_by(AccountSnapshot.snapshot_time.asc())
            .limit(1)
        )
        result = await session.execute(stmt)
        start_snapshot = result.scalar_one_or_none()

        # Get latest snapshot
        stmt = select(AccountSnapshot).order_by(AccountSnapshot.snapshot_time.desc()).limit(1)
        result = await session.execute(stmt)
        end_snapshot = result.scalar_one_or_none()

        if not start_snapshot or not end_snapshot:
            return 0

        return end_snapshot.realized_pnl - start_snapshot.realized_pnl

    def _calculate_apr(
        self,
        pnl: float,
        equity: float,
        days: int,
    ) -> float:
        """Calculate annualized percentage rate.

        Args:
            pnl: P&L for the period
            equity: Base equity
            days: Number of days in period

        Returns:
            APR as percentage
        """
        if equity <= 0 or days <= 0:
            return 0

        daily_return = pnl / equity / days
        apr = daily_return * 365 * 100
        return apr

    async def record_funding_payment(
        self,
        session: AsyncSession,
        position: Position,
        funding_rate: float,
        payment_amount: float,
        funding_time: datetime,
    ) -> FundingPayment:
        """Record a funding payment for a position.

        Args:
            session: Database session
            position: Position receiving funding
            funding_rate: The funding rate
            payment_amount: Amount received/paid
            funding_time: Time of funding

        Returns:
            Created FundingPayment record
        """
        payment = FundingPayment(
            position_id=position.id,
            symbol=position.symbol,
            funding_rate=funding_rate,
            payment_amount=payment_amount,
            position_value=position.position_value,
            funding_time=funding_time,
        )

        session.add(payment)

        # Update position accumulated funding
        position.accumulated_funding += payment_amount
        position.funding_payments_count += 1

        await session.commit()

        logger.info(
            f"Recorded funding payment: {position.symbol} "
            f"rate={funding_rate:.6f} amount=${payment_amount:.4f}"
        )

        return payment

    async def save_account_snapshot(
        self,
        session: AsyncSession,
        positions: list[Position],
        spot_balance: float,
        futures_balance: float,
        margin_ratio: float | None = None,
    ) -> AccountSnapshot:
        """Save current account state as snapshot.

        Args:
            session: Database session
            positions: Current positions
            spot_balance: Spot account balance
            futures_balance: Futures account balance
            margin_ratio: Current margin ratio

        Returns:
            Created AccountSnapshot
        """
        total_equity = spot_balance + futures_balance

        # Calculate P&L metrics
        open_positions = [p for p in positions if p.status == PositionStatus.OPEN]
        closed_positions = [p for p in positions if p.status == PositionStatus.CLOSED]

        unrealized_pnl = sum(
            p.spot_pnl + p.futures_pnl + p.accumulated_funding - p.total_fees
            for p in open_positions
        )
        realized_pnl = sum(p.realized_pnl for p in closed_positions)
        total_funding = sum(p.accumulated_funding for p in positions)
        total_fees = sum(p.total_fees for p in positions)

        snapshot = AccountSnapshot(
            spot_balance=spot_balance,
            futures_balance=futures_balance,
            total_equity=total_equity,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=realized_pnl,
            total_funding_earned=total_funding,
            total_fees_paid=total_fees,
            margin_ratio=margin_ratio,
            open_positions_count=len(open_positions),
        )

        session.add(snapshot)
        await session.commit()

        logger.debug(f"Saved account snapshot: equity=${total_equity:.2f}")

        return snapshot

    async def get_funding_history(
        self,
        session: AsyncSession,
        symbol: str | None = None,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """Get funding payment history.

        Args:
            session: Database session
            symbol: Optional symbol filter
            days: Number of days to retrieve

        Returns:
            List of funding payment records
        """
        start_time = datetime.utcnow() - timedelta(days=days)

        stmt = select(FundingPayment).where(
            FundingPayment.funding_time >= start_time
        )

        if symbol:
            stmt = stmt.where(FundingPayment.symbol == symbol)

        stmt = stmt.order_by(FundingPayment.funding_time.desc())

        result = await session.execute(stmt)
        payments = result.scalars().all()

        return [
            {
                "id": p.id,
                "symbol": p.symbol,
                "funding_rate": p.funding_rate,
                "payment_amount": p.payment_amount,
                "position_value": p.position_value,
                "funding_time": p.funding_time.isoformat(),
            }
            for p in payments
        ]

    async def get_equity_history(
        self,
        session: AsyncSession,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """Get equity history for charting.

        Args:
            session: Database session
            days: Number of days to retrieve

        Returns:
            List of equity snapshots
        """
        start_time = datetime.utcnow() - timedelta(days=days)

        stmt = (
            select(AccountSnapshot)
            .where(AccountSnapshot.snapshot_time >= start_time)
            .order_by(AccountSnapshot.snapshot_time.asc())
        )

        result = await session.execute(stmt)
        snapshots = result.scalars().all()

        return [
            {
                "timestamp": s.snapshot_time.isoformat(),
                "total_equity": s.total_equity,
                "realized_pnl": s.realized_pnl,
                "unrealized_pnl": s.unrealized_pnl,
                "funding_earned": s.total_funding_earned,
            }
            for s in snapshots
        ]

    async def get_performance_by_symbol(
        self,
        session: AsyncSession,
        positions: list[Position],
    ) -> dict[str, dict[str, Any]]:
        """Get performance breakdown by symbol.

        Args:
            session: Database session
            positions: All positions

        Returns:
            Dictionary of symbol -> performance metrics
        """
        performance = {}

        for position in positions:
            symbol = position.symbol
            if symbol not in performance:
                performance[symbol] = {
                    "symbol": symbol,
                    "total_trades": 0,
                    "open_trades": 0,
                    "closed_trades": 0,
                    "total_pnl": 0,
                    "total_funding": 0,
                    "total_fees": 0,
                    "win_count": 0,
                    "loss_count": 0,
                }

            perf = performance[symbol]
            perf["total_trades"] += 1

            if position.status == PositionStatus.OPEN:
                perf["open_trades"] += 1
            elif position.status == PositionStatus.CLOSED:
                perf["closed_trades"] += 1
                if position.realized_pnl > 0:
                    perf["win_count"] += 1
                elif position.realized_pnl < 0:
                    perf["loss_count"] += 1

            perf["total_pnl"] += position.realized_pnl or 0
            perf["total_funding"] += position.accumulated_funding
            perf["total_fees"] += position.total_fees

        # Calculate win rate
        for perf in performance.values():
            total_closed = perf["win_count"] + perf["loss_count"]
            perf["win_rate"] = (
                perf["win_count"] / total_closed * 100 if total_closed > 0 else 0
            )

        return performance

    def estimate_funding_income(
        self,
        position_value: float,
        funding_rate: float,
        hours: int = 24,
    ) -> float:
        """Estimate funding income for a period.

        Args:
            position_value: Position value in USDT
            funding_rate: Current funding rate per 8h
            hours: Number of hours to estimate

        Returns:
            Estimated funding income
        """
        # Funding is paid every 8 hours
        funding_periods = hours / 8
        return position_value * funding_rate * funding_periods
