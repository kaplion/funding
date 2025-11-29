"""SQLAlchemy models for Funding Rate Arbitrage Bot."""

from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    Enum,
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class PositionStatus(str, PyEnum):
    """Position status enumeration."""

    PENDING = "pending"
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"
    ERROR = "error"


class PositionSide(str, PyEnum):
    """Position side enumeration."""

    LONG_SPOT_SHORT_PERP = "long_spot_short_perp"  # Positive funding
    SHORT_SPOT_LONG_PERP = "short_spot_long_perp"  # Negative funding


class OrderSide(str, PyEnum):
    """Order side enumeration."""

    BUY = "buy"
    SELL = "sell"


class OrderType(str, PyEnum):
    """Order type enumeration."""

    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, PyEnum):
    """Order status enumeration."""

    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class Position(Base):
    """Position model for tracking arbitrage positions."""

    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(Enum(PositionSide), nullable=False)
    status = Column(Enum(PositionStatus), default=PositionStatus.PENDING, nullable=False)

    # Spot position details
    spot_quantity = Column(Float, nullable=False, default=0)
    spot_entry_price = Column(Float, nullable=False, default=0)
    spot_exit_price = Column(Float, nullable=True)

    # Futures position details
    futures_quantity = Column(Float, nullable=False, default=0)
    futures_entry_price = Column(Float, nullable=False, default=0)
    futures_exit_price = Column(Float, nullable=True)
    futures_leverage = Column(Integer, default=1)

    # Funding tracking
    entry_funding_rate = Column(Float, nullable=False, default=0)
    accumulated_funding = Column(Float, default=0)
    funding_payments_count = Column(Integer, default=0)

    # P&L tracking
    spot_pnl = Column(Float, default=0)
    futures_pnl = Column(Float, default=0)
    total_fees = Column(Float, default=0)
    realized_pnl = Column(Float, default=0)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    opened_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Notes and metadata
    notes = Column(Text, nullable=True)

    # Relationships
    orders = relationship("Order", back_populates="position", cascade="all, delete-orphan")
    funding_payments = relationship(
        "FundingPayment", back_populates="position", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Position(id={self.id}, symbol={self.symbol}, status={self.status})>"

    @property
    def position_value(self) -> float:
        """Calculate current position value in USDT."""
        return self.spot_quantity * self.spot_entry_price

    @property
    def net_pnl(self) -> float:
        """Calculate net P&L including funding and fees."""
        return (
            self.spot_pnl
            + self.futures_pnl
            + self.accumulated_funding
            - self.total_fees
        )


class Order(Base):
    """Order model for tracking all orders."""

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=True)
    exchange_order_id = Column(String(100), nullable=True, index=True)

    symbol = Column(String(20), nullable=False)
    side = Column(Enum(OrderSide), nullable=False)
    order_type = Column(Enum(OrderType), nullable=False)
    status = Column(Enum(OrderStatus), default=OrderStatus.PENDING, nullable=False)

    # Order details
    is_futures = Column(Boolean, default=False)
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=True)  # Limit price
    filled_quantity = Column(Float, default=0)
    filled_price = Column(Float, nullable=True)  # Average fill price
    fee = Column(Float, default=0)
    fee_currency = Column(String(10), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    filled_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    position = relationship("Position", back_populates="orders")

    def __repr__(self) -> str:
        return f"<Order(id={self.id}, symbol={self.symbol}, side={self.side}, status={self.status})>"


class FundingPayment(Base):
    """Funding payment model for tracking funding rate payments."""

    __tablename__ = "funding_payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=False)

    symbol = Column(String(20), nullable=False, index=True)
    funding_rate = Column(Float, nullable=False)
    payment_amount = Column(Float, nullable=False)
    position_value = Column(Float, nullable=False)

    # Timestamps
    funding_time = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationship
    position = relationship("Position", back_populates="funding_payments")

    def __repr__(self) -> str:
        return f"<FundingPayment(id={self.id}, symbol={self.symbol}, amount={self.payment_amount})>"


class FundingRateHistory(Base):
    """Historical funding rate data."""

    __tablename__ = "funding_rate_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    funding_rate = Column(Float, nullable=False)
    funding_time = Column(DateTime, nullable=False, index=True)
    mark_price = Column(Float, nullable=True)

    # Unique constraint on symbol + funding_time
    __table_args__ = (
        # Index for faster lookups
        {"sqlite_autoincrement": True},
    )

    def __repr__(self) -> str:
        return f"<FundingRateHistory(symbol={self.symbol}, rate={self.funding_rate})>"


class AccountSnapshot(Base):
    """Account snapshot for tracking equity over time."""

    __tablename__ = "account_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Balances
    spot_balance = Column(Float, default=0)
    futures_balance = Column(Float, default=0)
    total_equity = Column(Float, default=0)

    # P&L metrics
    unrealized_pnl = Column(Float, default=0)
    realized_pnl = Column(Float, default=0)
    total_funding_earned = Column(Float, default=0)
    total_fees_paid = Column(Float, default=0)

    # Risk metrics
    margin_ratio = Column(Float, nullable=True)
    open_positions_count = Column(Integer, default=0)

    # Timestamp
    snapshot_time = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<AccountSnapshot(equity={self.total_equity}, time={self.snapshot_time})>"


class BotState(Base):
    """Bot state for persistence across restarts."""

    __tablename__ = "bot_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(50), unique=True, nullable=False)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<BotState(key={self.key})>"


# Database connection utilities
def get_engine(database_url: str, echo: bool = False):
    """Create synchronous database engine."""
    return create_engine(database_url, echo=echo)


def get_async_engine(database_url: str, echo: bool = False):
    """Create asynchronous database engine."""
    # Convert sqlite:/// to sqlite+aiosqlite:///
    if database_url.startswith("sqlite:///"):
        database_url = database_url.replace("sqlite:///", "sqlite+aiosqlite:///")
    return create_async_engine(database_url, echo=echo)


def create_session_factory(engine):
    """Create synchronous session factory."""
    return sessionmaker(bind=engine)


def create_async_session_factory(engine):
    """Create asynchronous session factory."""
    return sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def init_database(database_url: str):
    """Initialize database and create all tables."""
    engine = get_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine
