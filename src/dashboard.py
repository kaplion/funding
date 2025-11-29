"""Web dashboard for monitoring the funding bot."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.config import Config
from src.accounting import Accounting
from src.data_collector import DataCollector
from src.models import (
    Position,
    PositionStatus,
    create_async_session_factory,
    get_async_engine,
)
from src.risk_manager import RiskManager


logger = logging.getLogger(__name__)


class Dashboard:
    """Web dashboard for the funding bot."""

    def __init__(
        self,
        config: Config,
        data_collector: DataCollector | None = None,
        risk_manager: RiskManager | None = None,
        accounting: Accounting | None = None,
    ):
        self.config = config
        self.data_collector = data_collector
        self.risk_manager = risk_manager
        self.accounting = accounting or Accounting(config)

        # FastAPI app
        self.app = FastAPI(
            title="Funding Rate Arbitrage Bot",
            description="Dashboard for monitoring funding rate arbitrage positions",
            version="1.0.0",
        )

        # Bot control state
        self._bot_running = False
        self._bot_instance = None

        # Setup routes
        self._setup_routes()

        # Setup static files and templates
        base_path = Path(__file__).parent.parent
        templates_path = base_path / "templates"
        static_path = base_path / "static"

        if templates_path.exists():
            self.templates = Jinja2Templates(directory=str(templates_path))
        else:
            self.templates = None

        if static_path.exists():
            self.app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

        # Database session factory
        self._session_factory = None

    def set_bot_instance(self, bot) -> None:
        """Set the bot instance for control."""
        self._bot_instance = bot

    async def _get_session(self) -> AsyncSession:
        """Get database session."""
        if not self._session_factory:
            engine = get_async_engine(self.config.database_url)
            self._session_factory = create_async_session_factory(engine)
        return self._session_factory()

    def _setup_routes(self) -> None:
        """Setup API routes."""

        @self.app.get("/", response_class=HTMLResponse)
        async def index(request: Request):
            """Render main dashboard page."""
            if self.templates:
                return self.templates.TemplateResponse(
                    "dashboard.html", {"request": request}
                )
            return HTMLResponse("<h1>Funding Bot Dashboard</h1><p>Templates not found</p>")

        @self.app.get("/api/status")
        async def get_status():
            """Get bot status."""
            return {
                "running": self._bot_running,
                "timestamp": datetime.utcnow().isoformat(),
            }

        @self.app.get("/api/overview")
        async def get_overview():
            """Get dashboard overview data."""
            try:
                async with await self._get_session() as session:
                    # Get positions
                    stmt = select(Position)
                    result = await session.execute(stmt)
                    positions = list(result.scalars().all())

                    # Get balances
                    balance = {"total_equity": 0, "spot_total": 0, "futures_total": 0}
                    margin_ratio = None
                    if self.data_collector:
                        try:
                            balance = await self.data_collector.get_account_balance()
                            margin_ratio = await self.data_collector.get_margin_ratio()
                        except Exception:
                            pass

                    # Calculate P&L
                    account_pnl = await self.accounting.calculate_account_pnl(
                        session, positions, balance.get("total_equity", 0)
                    )

                    # Count positions
                    open_positions = [p for p in positions if p.status == PositionStatus.OPEN]

                    return {
                        "total_equity": balance.get("total_equity", 0),
                        "spot_balance": balance.get("spot_total", 0),
                        "futures_balance": balance.get("futures_total", 0),
                        "total_pnl": account_pnl.total_pnl,
                        "total_pnl_pct": account_pnl.total_pnl_pct,
                        "realized_pnl": account_pnl.realized_pnl,
                        "unrealized_pnl": account_pnl.unrealized_pnl,
                        "total_funding": account_pnl.total_funding_income,
                        "total_fees": account_pnl.total_trading_fees,
                        "daily_apr": account_pnl.daily_apr,
                        "weekly_apr": account_pnl.weekly_apr,
                        "monthly_apr": account_pnl.monthly_apr,
                        "annualized_apr": account_pnl.annualized_apr,
                        "open_positions_count": len(open_positions),
                        "margin_ratio": margin_ratio,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
            except Exception as e:
                logger.error(f"Error getting overview: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/api/positions")
        async def get_positions():
            """Get all positions."""
            try:
                async with await self._get_session() as session:
                    stmt = select(Position).order_by(Position.created_at.desc())
                    result = await session.execute(stmt)
                    positions = result.scalars().all()

                    return {
                        "positions": [
                            {
                                "id": p.id,
                                "symbol": p.symbol,
                                "side": p.side.value,
                                "status": p.status.value,
                                "spot_quantity": p.spot_quantity,
                                "spot_entry_price": p.spot_entry_price,
                                "spot_exit_price": p.spot_exit_price,
                                "futures_quantity": p.futures_quantity,
                                "futures_entry_price": p.futures_entry_price,
                                "futures_exit_price": p.futures_exit_price,
                                "futures_leverage": p.futures_leverage,
                                "entry_funding_rate": p.entry_funding_rate,
                                "accumulated_funding": p.accumulated_funding,
                                "funding_payments_count": p.funding_payments_count,
                                "spot_pnl": p.spot_pnl,
                                "futures_pnl": p.futures_pnl,
                                "total_fees": p.total_fees,
                                "realized_pnl": p.realized_pnl,
                                "position_value": p.position_value,
                                "net_pnl": p.net_pnl,
                                "created_at": p.created_at.isoformat() if p.created_at else None,
                                "opened_at": p.opened_at.isoformat() if p.opened_at else None,
                                "closed_at": p.closed_at.isoformat() if p.closed_at else None,
                            }
                            for p in positions
                        ]
                    }
            except Exception as e:
                logger.error(f"Error getting positions: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/api/positions/open")
        async def get_open_positions():
            """Get open positions only."""
            try:
                async with await self._get_session() as session:
                    stmt = (
                        select(Position)
                        .where(Position.status == PositionStatus.OPEN)
                        .order_by(Position.opened_at.desc())
                    )
                    result = await session.execute(stmt)
                    positions = result.scalars().all()

                    position_data = []
                    for p in positions:
                        # Get current funding rate if available
                        current_funding_rate = p.entry_funding_rate
                        if self.data_collector:
                            try:
                                funding_data = await self.data_collector.get_funding_rate(
                                    p.symbol
                                )
                                if funding_data:
                                    current_funding_rate = funding_data.funding_rate
                            except Exception:
                                pass

                        position_data.append({
                            "id": p.id,
                            "symbol": p.symbol,
                            "side": p.side.value,
                            "position_value": p.position_value,
                            "entry_funding_rate": p.entry_funding_rate,
                            "current_funding_rate": current_funding_rate,
                            "accumulated_funding": p.accumulated_funding,
                            "net_pnl": p.net_pnl,
                            "opened_at": p.opened_at.isoformat() if p.opened_at else None,
                            "duration_hours": (
                                (datetime.utcnow() - p.opened_at).total_seconds() / 3600
                                if p.opened_at
                                else 0
                            ),
                        })

                    return {"positions": position_data}
            except Exception as e:
                logger.error(f"Error getting open positions: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/api/funding-history")
        async def get_funding_history(days: int = 30, symbol: str | None = None):
            """Get funding payment history."""
            try:
                async with await self._get_session() as session:
                    history = await self.accounting.get_funding_history(
                        session, symbol=symbol, days=days
                    )
                    return {"funding_history": history}
            except Exception as e:
                logger.error(f"Error getting funding history: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/api/equity-history")
        async def get_equity_history(days: int = 30):
            """Get equity history for charts."""
            try:
                async with await self._get_session() as session:
                    history = await self.accounting.get_equity_history(session, days=days)
                    return {"equity_history": history}
            except Exception as e:
                logger.error(f"Error getting equity history: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/api/performance")
        async def get_performance():
            """Get performance by symbol."""
            try:
                async with await self._get_session() as session:
                    stmt = select(Position)
                    result = await session.execute(stmt)
                    positions = list(result.scalars().all())

                    performance = await self.accounting.get_performance_by_symbol(
                        session, positions
                    )
                    return {"performance": list(performance.values())}
            except Exception as e:
                logger.error(f"Error getting performance: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/api/risk-metrics")
        async def get_risk_metrics():
            """Get current risk metrics."""
            try:
                if not self.risk_manager:
                    return {
                        "margin_ratio": None,
                        "risk_level": "unknown",
                        "alerts": [],
                    }

                async with await self._get_session() as session:
                    stmt = select(Position).where(Position.status == PositionStatus.OPEN)
                    result = await session.execute(stmt)
                    positions = list(result.scalars().all())

                    metrics = await self.risk_manager.calculate_risk_metrics(positions)

                    return {
                        "margin_ratio": metrics.margin_ratio,
                        "total_equity": metrics.total_equity,
                        "total_position_value": metrics.total_position_value,
                        "position_count": metrics.position_count,
                        "min_liquidation_distance": metrics.min_liquidation_distance,
                        "current_drawdown": metrics.current_drawdown,
                        "risk_level": metrics.risk_level.value,
                        "alerts": [
                            {
                                "level": a.level.value,
                                "type": a.alert_type,
                                "message": a.message,
                                "symbol": a.symbol,
                                "timestamp": a.timestamp.isoformat() if a.timestamp else None,
                            }
                            for a in metrics.alerts
                        ],
                    }
            except Exception as e:
                logger.error(f"Error getting risk metrics: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/api/funding-rates")
        async def get_funding_rates():
            """Get current funding rates."""
            try:
                if not self.data_collector:
                    return {"funding_rates": []}

                funding_rates = await self.data_collector.get_all_funding_rates()

                return {
                    "funding_rates": [
                        {
                            "symbol": f.symbol,
                            "funding_rate": f.funding_rate,
                            "apr": f.apr,
                            "mark_price": f.mark_price,
                            "open_interest": f.open_interest,
                            "volume_24h": f.volume_24h,
                            "next_funding_time": f.next_funding_time.isoformat(),
                        }
                        for f in sorted(
                            funding_rates, key=lambda x: abs(x.funding_rate), reverse=True
                        )[:50]  # Top 50 by funding rate
                    ]
                }
            except Exception as e:
                logger.error(f"Error getting funding rates: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/api/bot/start")
        async def start_bot():
            """Start the bot."""
            if self._bot_running:
                return {"status": "already_running"}

            if self._bot_instance:
                try:
                    asyncio.create_task(self._bot_instance.run())
                    self._bot_running = True
                    return {"status": "started"}
                except Exception as e:
                    logger.error(f"Error starting bot: {e}")
                    raise HTTPException(status_code=500, detail=str(e))

            return {"status": "no_bot_instance"}

        @self.app.post("/api/bot/stop")
        async def stop_bot():
            """Stop the bot."""
            if not self._bot_running:
                return {"status": "not_running"}

            if self._bot_instance:
                try:
                    await self._bot_instance.stop()
                    self._bot_running = False
                    return {"status": "stopped"}
                except Exception as e:
                    logger.error(f"Error stopping bot: {e}")
                    raise HTTPException(status_code=500, detail=str(e))

            return {"status": "no_bot_instance"}

        @self.app.get("/api/config")
        async def get_config():
            """Get current configuration."""
            return {
                "strategy": {
                    "min_funding_rate": self.config.strategy.min_funding_rate,
                    "max_spread": self.config.strategy.max_spread,
                    "position_size_pct": self.config.strategy.position_size_pct,
                    "max_positions": self.config.strategy.max_positions,
                    "recheck_interval": self.config.strategy.recheck_interval,
                },
                "risk": {
                    "max_coin_allocation": self.config.risk.max_coin_allocation,
                    "margin_ratio_warning": self.config.risk.margin_ratio_warning,
                    "margin_ratio_critical": self.config.risk.margin_ratio_critical,
                    "min_liquidation_distance": self.config.risk.min_liquidation_distance,
                    "max_drawdown": self.config.risk.max_drawdown,
                },
                "trading": {
                    "prefer_limit_orders": self.config.trading.prefer_limit_orders,
                    "limit_order_timeout": self.config.trading.limit_order_timeout,
                    "default_leverage": self.config.trading.default_leverage,
                    "min_order_value": self.config.trading.min_order_value,
                },
            }

    def set_bot_running(self, running: bool) -> None:
        """Set bot running state."""
        self._bot_running = running


def create_dashboard(
    config: Config,
    data_collector: DataCollector | None = None,
    risk_manager: RiskManager | None = None,
    accounting: Accounting | None = None,
) -> Dashboard:
    """Create dashboard instance.

    Args:
        config: Bot configuration
        data_collector: Data collector instance
        risk_manager: Risk manager instance
        accounting: Accounting instance

    Returns:
        Dashboard instance
    """
    return Dashboard(
        config=config,
        data_collector=data_collector,
        risk_manager=risk_manager,
        accounting=accounting,
    )


# Global app instance for uvicorn
app = None


def get_app():
    """Get or create FastAPI app instance."""
    global app
    if app is None:
        from config.config import load_config

        config = load_config()
        dashboard = create_dashboard(config)
        app = dashboard.app
    return app


# Create app instance for uvicorn
app = get_app()


if __name__ == "__main__":
    import uvicorn

    from config.config import load_config

    config = load_config()
    dashboard = create_dashboard(config)

    print("Starting Funding Bot Dashboard...")
    print("Access at: http://localhost:8000")

    uvicorn.run(
        dashboard.app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
