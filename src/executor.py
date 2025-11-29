"""Order execution module for spot and futures trades."""

import asyncio
import logging
from datetime import datetime

import ccxt.async_support as ccxt

from config.config import Config
from src.data_collector import DataCollector
from src.models import (
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PositionSide,
    PositionStatus,
)


logger = logging.getLogger(__name__)


class ExecutionResult:
    """Result of order execution."""

    def __init__(
        self,
        success: bool,
        order: Order | None = None,
        error: str | None = None,
    ):
        self.success = success
        self.order = order
        self.error = error


class PositionExecutionResult:
    """Result of position execution (spot + futures)."""

    def __init__(
        self,
        success: bool,
        position: Position | None = None,
        spot_order: Order | None = None,
        futures_order: Order | None = None,
        error: str | None = None,
    ):
        self.success = success
        self.position = position
        self.spot_order = spot_order
        self.futures_order = futures_order
        self.error = error


class Executor:
    """Executes trades on spot and futures markets."""

    def __init__(self, config: Config, data_collector: DataCollector):
        self.config = config
        self.data_collector = data_collector

    @property
    def exchange(self) -> ccxt.binance:
        """Get spot exchange instance."""
        return self.data_collector.exchange

    @property
    def futures_exchange(self) -> ccxt.binanceusdm:
        """Get futures exchange instance."""
        return self.data_collector.futures_exchange

    def _get_base_symbol(self, symbol: str) -> str:
        """Extract base symbol (e.g., BTC from BTCUSDT)."""
        return symbol.replace("USDT", "")

    def _get_spot_symbol(self, symbol: str) -> str:
        """Convert to CCXT spot symbol format."""
        base = self._get_base_symbol(symbol)
        return f"{base}/USDT"

    def _get_futures_symbol(self, symbol: str) -> str:
        """Convert to CCXT futures symbol format."""
        base = self._get_base_symbol(symbol)
        return f"{base}/USDT:USDT"

    async def _place_spot_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float | None = None,
        order_type: OrderType = OrderType.LIMIT,
    ) -> ExecutionResult:
        """Place a spot order.

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            side: Buy or sell
            quantity: Order quantity
            price: Limit price (required for limit orders)
            order_type: Market or limit

        Returns:
            ExecutionResult with order details
        """
        try:
            ccxt_symbol = self._get_spot_symbol(symbol)
            ccxt_side = "buy" if side == OrderSide.BUY else "sell"
            ccxt_type = "limit" if order_type == OrderType.LIMIT else "market"

            # Create order object for tracking
            order = Order(
                symbol=symbol,
                side=side,
                order_type=order_type,
                status=OrderStatus.PENDING,
                is_futures=False,
                quantity=quantity,
                price=price,
            )

            # Place the order
            if order_type == OrderType.LIMIT and price:
                result = await self.exchange.create_order(
                    symbol=ccxt_symbol,
                    type=ccxt_type,
                    side=ccxt_side,
                    amount=quantity,
                    price=price,
                )
            else:
                result = await self.exchange.create_order(
                    symbol=ccxt_symbol,
                    type="market",
                    side=ccxt_side,
                    amount=quantity,
                )

            # Update order with exchange response
            order.exchange_order_id = str(result.get("id", ""))
            order.filled_quantity = float(result.get("filled", 0) or 0)
            order.filled_price = float(result.get("average", 0) or result.get("price", 0) or 0)

            # Calculate fee
            fee_info = result.get("fee", {})
            if fee_info:
                order.fee = float(fee_info.get("cost", 0) or 0)
                order.fee_currency = fee_info.get("currency", "USDT")

            # Update status
            status = result.get("status", "").lower()
            if status == "closed" or order.filled_quantity >= quantity:
                order.status = OrderStatus.FILLED
                order.filled_at = datetime.utcnow()
            elif status == "canceled":
                order.status = OrderStatus.CANCELLED
            elif order.filled_quantity > 0:
                order.status = OrderStatus.PARTIALLY_FILLED
            else:
                order.status = OrderStatus.PENDING

            logger.info(
                f"Spot order placed: {symbol} {side.value} {quantity} "
                f"@ {order.filled_price} (status: {order.status.value})"
            )

            return ExecutionResult(success=True, order=order)

        except ccxt.InsufficientFunds as e:
            logger.error(f"Insufficient funds for spot order: {e}")
            return ExecutionResult(success=False, error=f"Insufficient funds: {e}")

        except ccxt.ExchangeError as e:
            logger.error(f"Exchange error placing spot order: {e}")
            return ExecutionResult(success=False, error=str(e))

    async def _place_futures_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float | None = None,
        order_type: OrderType = OrderType.LIMIT,
        reduce_only: bool = False,
    ) -> ExecutionResult:
        """Place a futures order.

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            side: Buy or sell
            quantity: Order quantity
            price: Limit price (required for limit orders)
            order_type: Market or limit
            reduce_only: Whether this is a reduce-only order

        Returns:
            ExecutionResult with order details
        """
        try:
            ccxt_symbol = self._get_futures_symbol(symbol)
            ccxt_side = "buy" if side == OrderSide.BUY else "sell"
            ccxt_type = "limit" if order_type == OrderType.LIMIT else "market"

            # Create order object for tracking
            order = Order(
                symbol=symbol,
                side=side,
                order_type=order_type,
                status=OrderStatus.PENDING,
                is_futures=True,
                quantity=quantity,
                price=price,
            )

            # Prepare extra params
            params = {}
            if reduce_only:
                params["reduceOnly"] = True

            # Place the order
            if order_type == OrderType.LIMIT and price:
                result = await self.futures_exchange.create_order(
                    symbol=ccxt_symbol,
                    type=ccxt_type,
                    side=ccxt_side,
                    amount=quantity,
                    price=price,
                    params=params,
                )
            else:
                result = await self.futures_exchange.create_order(
                    symbol=ccxt_symbol,
                    type="market",
                    side=ccxt_side,
                    amount=quantity,
                    params=params,
                )

            # Update order with exchange response
            order.exchange_order_id = str(result.get("id", ""))
            order.filled_quantity = float(result.get("filled", 0) or 0)
            order.filled_price = float(result.get("average", 0) or result.get("price", 0) or 0)

            # Calculate fee
            fee_info = result.get("fee", {})
            if fee_info:
                order.fee = float(fee_info.get("cost", 0) or 0)
                order.fee_currency = fee_info.get("currency", "USDT")

            # Update status
            status = result.get("status", "").lower()
            if status == "closed" or order.filled_quantity >= quantity:
                order.status = OrderStatus.FILLED
                order.filled_at = datetime.utcnow()
            elif status == "canceled":
                order.status = OrderStatus.CANCELLED
            elif order.filled_quantity > 0:
                order.status = OrderStatus.PARTIALLY_FILLED
            else:
                order.status = OrderStatus.PENDING

            logger.info(
                f"Futures order placed: {symbol} {side.value} {quantity} "
                f"@ {order.filled_price} (status: {order.status.value})"
            )

            return ExecutionResult(success=True, order=order)

        except ccxt.InsufficientFunds as e:
            logger.error(f"Insufficient funds for futures order: {e}")
            return ExecutionResult(success=False, error=f"Insufficient funds: {e}")

        except ccxt.ExchangeError as e:
            logger.error(f"Exchange error placing futures order: {e}")
            return ExecutionResult(success=False, error=str(e))

    async def _wait_for_order_fill(
        self,
        order: Order,
        is_futures: bool,
        timeout: int = 30,
    ) -> Order:
        """Wait for an order to be filled.

        Args:
            order: Order to wait for
            is_futures: Whether this is a futures order
            timeout: Timeout in seconds

        Returns:
            Updated order
        """
        if not order.exchange_order_id:
            return order

        exchange = self.futures_exchange if is_futures else self.exchange
        symbol = (
            self._get_futures_symbol(order.symbol)
            if is_futures
            else self._get_spot_symbol(order.symbol)
        )

        start_time = datetime.utcnow()
        while (datetime.utcnow() - start_time).seconds < timeout:
            try:
                result = await exchange.fetch_order(
                    order.exchange_order_id, symbol
                )

                order.filled_quantity = float(result.get("filled", 0) or 0)
                order.filled_price = float(
                    result.get("average", 0) or result.get("price", 0) or 0
                )

                status = result.get("status", "").lower()
                if status == "closed" or order.filled_quantity >= order.quantity:
                    order.status = OrderStatus.FILLED
                    order.filled_at = datetime.utcnow()
                    return order
                elif status == "canceled":
                    order.status = OrderStatus.CANCELLED
                    return order

            except ccxt.ExchangeError as e:
                logger.warning(f"Error checking order status: {e}")

            await asyncio.sleep(1)

        return order

    async def _cancel_order(
        self,
        order: Order,
        is_futures: bool,
    ) -> bool:
        """Cancel an order.

        Args:
            order: Order to cancel
            is_futures: Whether this is a futures order

        Returns:
            True if cancelled successfully
        """
        if not order.exchange_order_id:
            return True

        exchange = self.futures_exchange if is_futures else self.exchange
        symbol = (
            self._get_futures_symbol(order.symbol)
            if is_futures
            else self._get_spot_symbol(order.symbol)
        )

        try:
            await exchange.cancel_order(order.exchange_order_id, symbol)
            order.status = OrderStatus.CANCELLED
            return True
        except ccxt.ExchangeError as e:
            logger.error(f"Error cancelling order: {e}")
            return False

    async def set_futures_leverage(self, symbol: str, leverage: int) -> bool:
        """Set leverage for a futures symbol.

        Args:
            symbol: Trading pair
            leverage: Leverage to set

        Returns:
            True if successful
        """
        try:
            ccxt_symbol = self._get_futures_symbol(symbol)
            await self.futures_exchange.set_leverage(leverage, ccxt_symbol)
            logger.info(f"Set leverage for {symbol} to {leverage}x")
            return True
        except ccxt.ExchangeError as e:
            logger.error(f"Error setting leverage: {e}")
            return False

    async def open_position(
        self,
        symbol: str,
        side: PositionSide,
        position_size_usdt: float,
        entry_funding_rate: float,
    ) -> PositionExecutionResult:
        """Open a delta-neutral position.

        Args:
            symbol: Trading pair
            side: Position side (long_spot_short_perp or short_spot_long_perp)
            position_size_usdt: Total position size in USDT
            entry_funding_rate: Current funding rate

        Returns:
            PositionExecutionResult with details
        """
        logger.info(f"Opening position: {symbol} {side.value} ${position_size_usdt}")

        # Paper trading mode - use paper trader
        if self.config.trading.paper_trading:
            return await self._open_paper_position(
                symbol, side, position_size_usdt, entry_funding_rate
            )

        # Create position object
        position = Position(
            symbol=symbol,
            side=side,
            status=PositionStatus.PENDING,
            entry_funding_rate=entry_funding_rate,
        )

        # Set leverage
        leverage = self.config.trading.default_leverage
        await self.set_futures_leverage(symbol, leverage)
        position.futures_leverage = leverage

        # Get current prices
        spread = await self.data_collector.get_spot_futures_spread(symbol)
        if not spread:
            return PositionExecutionResult(
                success=False,
                error="Could not get current prices",
            )

        spot_price = spread.spot_price
        futures_price = spread.futures_price

        # Calculate quantities
        spot_quantity = position_size_usdt / spot_price
        futures_quantity = position_size_usdt / futures_price

        # Determine order sides
        if side == PositionSide.LONG_SPOT_SHORT_PERP:
            spot_side = OrderSide.BUY
            futures_side = OrderSide.SELL
        else:
            spot_side = OrderSide.SELL
            futures_side = OrderSide.BUY

        # Execute orders concurrently
        prefer_limit = self.config.trading.prefer_limit_orders
        order_type = OrderType.LIMIT if prefer_limit else OrderType.MARKET

        spot_result, futures_result = await asyncio.gather(
            self._place_spot_order(
                symbol=symbol,
                side=spot_side,
                quantity=spot_quantity,
                price=spot_price if prefer_limit else None,
                order_type=order_type,
            ),
            self._place_futures_order(
                symbol=symbol,
                side=futures_side,
                quantity=futures_quantity,
                price=futures_price if prefer_limit else None,
                order_type=order_type,
            ),
        )

        # Wait for fills if using limit orders
        if prefer_limit:
            timeout = self.config.trading.limit_order_timeout

            if spot_result.order and spot_result.order.status != OrderStatus.FILLED:
                spot_result.order = await self._wait_for_order_fill(
                    spot_result.order, is_futures=False, timeout=timeout
                )

            if futures_result.order and futures_result.order.status != OrderStatus.FILLED:
                futures_result.order = await self._wait_for_order_fill(
                    futures_result.order, is_futures=True, timeout=timeout
                )

            # Convert to market if not filled
            if spot_result.order and spot_result.order.status != OrderStatus.FILLED:
                await self._cancel_order(spot_result.order, is_futures=False)
                remaining = spot_quantity - spot_result.order.filled_quantity
                if remaining > 0:
                    market_result = await self._place_spot_order(
                        symbol=symbol,
                        side=spot_side,
                        quantity=remaining,
                        order_type=OrderType.MARKET,
                    )
                    if market_result.success:
                        spot_result.order.filled_quantity += market_result.order.filled_quantity
                        spot_result.order.fee += market_result.order.fee

            if futures_result.order and futures_result.order.status != OrderStatus.FILLED:
                await self._cancel_order(futures_result.order, is_futures=True)
                remaining = futures_quantity - futures_result.order.filled_quantity
                if remaining > 0:
                    market_result = await self._place_futures_order(
                        symbol=symbol,
                        side=futures_side,
                        quantity=remaining,
                        order_type=OrderType.MARKET,
                    )
                    if market_result.success:
                        futures_result.order.filled_quantity += market_result.order.filled_quantity
                        futures_result.order.fee += market_result.order.fee

        # Check if both orders succeeded
        if not spot_result.success or not futures_result.success:
            # Rollback: close any opened position
            if spot_result.success and spot_result.order:
                await self._place_spot_order(
                    symbol=symbol,
                    side=OrderSide.SELL if spot_side == OrderSide.BUY else OrderSide.BUY,
                    quantity=spot_result.order.filled_quantity,
                    order_type=OrderType.MARKET,
                )
            if futures_result.success and futures_result.order:
                await self._place_futures_order(
                    symbol=symbol,
                    side=OrderSide.BUY if futures_side == OrderSide.SELL else OrderSide.SELL,
                    quantity=futures_result.order.filled_quantity,
                    order_type=OrderType.MARKET,
                    reduce_only=True,
                )

            return PositionExecutionResult(
                success=False,
                error=spot_result.error or futures_result.error,
            )

        # Update position with fill details
        spot_order = spot_result.order
        futures_order = futures_result.order

        position.spot_quantity = spot_order.filled_quantity
        position.spot_entry_price = spot_order.filled_price
        position.futures_quantity = futures_order.filled_quantity
        position.futures_entry_price = futures_order.filled_price
        position.total_fees = spot_order.fee + futures_order.fee
        position.status = PositionStatus.OPEN
        position.opened_at = datetime.utcnow()

        # Link orders to position
        spot_order.position_id = position.id
        futures_order.position_id = position.id

        logger.info(
            f"Position opened: {symbol} spot={position.spot_quantity:.6f}@{position.spot_entry_price} "
            f"futures={position.futures_quantity:.6f}@{position.futures_entry_price}"
        )

        return PositionExecutionResult(
            success=True,
            position=position,
            spot_order=spot_order,
            futures_order=futures_order,
        )

    async def close_position(self, position: Position) -> PositionExecutionResult:
        """Close an existing position.

        Args:
            position: Position to close

        Returns:
            PositionExecutionResult with details
        """
        logger.info(f"Closing position: {position.symbol}")

        # Paper trading mode - use paper trader
        if self.config.trading.paper_trading:
            return await self._close_paper_position(position)

        position.status = PositionStatus.CLOSING

        # Determine order sides (opposite of opening)
        if position.side == PositionSide.LONG_SPOT_SHORT_PERP:
            spot_side = OrderSide.SELL
            futures_side = OrderSide.BUY
        else:
            spot_side = OrderSide.BUY
            futures_side = OrderSide.SELL

        # Close both positions with market orders for certainty
        spot_result, futures_result = await asyncio.gather(
            self._place_spot_order(
                symbol=position.symbol,
                side=spot_side,
                quantity=position.spot_quantity,
                order_type=OrderType.MARKET,
            ),
            self._place_futures_order(
                symbol=position.symbol,
                side=futures_side,
                quantity=position.futures_quantity,
                order_type=OrderType.MARKET,
                reduce_only=True,
            ),
        )

        # Calculate P&L
        spot_order = spot_result.order
        futures_order = futures_result.order

        if spot_order:
            position.spot_exit_price = spot_order.filled_price
            if position.side == PositionSide.LONG_SPOT_SHORT_PERP:
                position.spot_pnl = (
                    spot_order.filled_price - position.spot_entry_price
                ) * position.spot_quantity
            else:
                position.spot_pnl = (
                    position.spot_entry_price - spot_order.filled_price
                ) * position.spot_quantity
            position.total_fees += spot_order.fee

        if futures_order:
            position.futures_exit_price = futures_order.filled_price
            if position.side == PositionSide.LONG_SPOT_SHORT_PERP:
                position.futures_pnl = (
                    position.futures_entry_price - futures_order.filled_price
                ) * position.futures_quantity
            else:
                position.futures_pnl = (
                    futures_order.filled_price - position.futures_entry_price
                ) * position.futures_quantity
            position.total_fees += futures_order.fee

        # Calculate realized P&L
        position.realized_pnl = (
            position.spot_pnl
            + position.futures_pnl
            + position.accumulated_funding
            - position.total_fees
        )

        position.status = PositionStatus.CLOSED
        position.closed_at = datetime.utcnow()

        logger.info(
            f"Position closed: {position.symbol} "
            f"Realized P&L: ${position.realized_pnl:.2f} "
            f"(Spot: ${position.spot_pnl:.2f}, Futures: ${position.futures_pnl:.2f}, "
            f"Funding: ${position.accumulated_funding:.2f}, Fees: ${position.total_fees:.2f})"
        )

        return PositionExecutionResult(
            success=True,
            position=position,
            spot_order=spot_order,
            futures_order=futures_order,
        )

    async def _open_paper_position(
        self,
        symbol: str,
        side: PositionSide,
        position_size_usdt: float,
        entry_funding_rate: float,
    ) -> PositionExecutionResult:
        """Open a paper trading position.

        Args:
            symbol: Trading pair
            side: Position side
            position_size_usdt: Position size in USDT
            entry_funding_rate: Current funding rate

        Returns:
            PositionExecutionResult with details
        """
        # Get current prices from real market data
        spread = await self.data_collector.get_spot_futures_spread(symbol)
        if not spread:
            return PositionExecutionResult(
                success=False,
                error="Could not get current prices",
            )

        # Use paper trader to simulate
        paper_trader = self.data_collector._paper_trader
        if not paper_trader:
            return PositionExecutionResult(
                success=False,
                error="Paper trader not initialized",
            )

        result = await paper_trader.open_position(
            symbol=symbol,
            side=side.value,
            size_usdt=position_size_usdt,
            funding_rate=entry_funding_rate,
            spot_price=spread.spot_price,
            futures_price=spread.futures_price,
        )

        if not result.get("success"):
            return PositionExecutionResult(
                success=False,
                error=result.get("error", "Unknown error"),
            )

        # Create Position object for database
        paper_position = result["position"]
        position = Position(
            symbol=symbol,
            side=side,
            status=PositionStatus.OPEN,
            entry_funding_rate=entry_funding_rate,
            spot_quantity=paper_position.spot_quantity,
            spot_entry_price=spread.spot_price,
            futures_quantity=paper_position.futures_quantity,
            futures_entry_price=spread.futures_price,
            futures_leverage=1,
            opened_at=datetime.utcnow(),
            total_fees=result.get("total_fee", 0),
        )

        logger.info(f"[PAPER] Position opened: {symbol} ${position_size_usdt}")

        return PositionExecutionResult(success=True, position=position)

    async def _close_paper_position(
        self, position: Position
    ) -> PositionExecutionResult:
        """Close a paper trading position.

        Args:
            position: Position to close

        Returns:
            PositionExecutionResult with details
        """
        # Get current prices from real market data
        spread = await self.data_collector.get_spot_futures_spread(position.symbol)
        if not spread:
            return PositionExecutionResult(
                success=False,
                error="Could not get current prices",
            )

        # Use paper trader to simulate
        paper_trader = self.data_collector._paper_trader
        if not paper_trader:
            return PositionExecutionResult(
                success=False,
                error="Paper trader not initialized",
            )

        result = await paper_trader.close_position(
            symbol=position.symbol,
            spot_price=spread.spot_price,
            futures_price=spread.futures_price,
        )

        if not result.get("success"):
            return PositionExecutionResult(
                success=False,
                error=result.get("error", "Unknown error"),
            )

        # Update position with close details
        position.spot_exit_price = spread.spot_price
        position.futures_exit_price = spread.futures_price
        position.spot_pnl = result.get("spot_pnl", 0)
        position.futures_pnl = result.get("futures_pnl", 0)
        position.total_fees += result.get("total_fees", 0)
        position.realized_pnl = result.get("realized_pnl", 0)
        position.status = PositionStatus.CLOSED
        position.closed_at = datetime.utcnow()

        logger.info(
            f"[PAPER] Position closed: {position.symbol} "
            f"Realized P&L: ${position.realized_pnl:.2f}"
        )

        return PositionExecutionResult(success=True, position=position)
