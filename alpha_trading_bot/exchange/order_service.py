"""
订单服务 - 下单、撤单、止损止盈
增强版：订单状态确认、部分成交处理
"""

import asyncio
import logging
from typing import Dict, Optional

from .models.orders import OrderResult, OrderStatus, StopOrderResult

logger = logging.getLogger(__name__)


class OrderService:
    """订单服务（带状态确认）"""

    def __init__(self, exchange, symbol: str):
        self.exchange = exchange
        self.symbol = symbol
        self._stop_orders: Dict[str, str] = {}

    async def create_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        order_type: str = "market",
    ) -> str:
        """创建订单（向后兼容，返回order_id）"""
        result = await self.create_order_with_status(
            symbol, side, amount, price, order_type
        )
        return result.order_id

    async def create_order_with_status(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        order_type: str = "market",
    ) -> OrderResult:
        """
        创建订单并返回完整状态

        Args:
            symbol: 交易对
            side: 方向 (buy/sell)
            amount: 数量
            price: 价格（限价单）
            order_type: 订单类型 (market/limit)

        Returns:
            OrderResult: 订单执行结果
        """
        params = {
            "tdMode": "cross",
            "posMode": "one_way",
        }

        logger.info(
            f"[订单创建] 提交订单: symbol={symbol}, side={side}, "
            f"type={order_type}, amount={amount}, price={price}"
        )

        try:
            order = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.exchange.create_order(
                    symbol=symbol,
                    type=order_type,
                    side=side,
                    amount=amount,
                    price=price,
                    params=params,
                ),
            )

            result = self._parse_order_response(order, amount)

            if result.is_rejected:
                logger.error(
                    f"[订单创建] 订单被拒绝: ID={result.order_id}, "
                    f"原因={result.error_message}"
                )
            elif result.is_partially_filled:
                logger.warning(
                    f"[订单创建] 部分成交: ID={result.order_id}, "
                    f"已成交={result.filled_amount}, 剩余={result.remaining_amount}"
                )
            else:
                logger.info(
                    f"[订单创建] 订单成功: ID={result.order_id}, "
                    f"状态={result.status.value}, 成交={result.filled_amount}"
                )

            return result

        except Exception as e:
            logger.error(f"[订单创建] 订单异常: {e}")
            return OrderResult(
                order_id="",
                status=OrderStatus.REJECTED,
                symbol=symbol,
                side=side,
                order_type=order_type,
                requested_amount=amount,
                filled_amount=0,
                remaining_amount=amount,
                average_price=0,
                error_message=str(e),
            )

    def _parse_order_response(
        self, order: Dict, requested_amount: float
    ) -> OrderResult:
        """解析交易所订单响应"""
        order_id = order.get("id", "")
        status_str = order.get("status", "unknown").lower()
        symbol = order.get("symbol", "")
        side = order.get("side", "")
        order_type = order.get("type", "market")

        filled = float(order.get("filled", 0) or 0)
        remaining = float(order.get("remaining", 0) or 0)
        avg_price = float(order.get("average", 0) or 0)

        status_map = {
            "open": OrderStatus.OPEN,
            "closed": OrderStatus.CLOSED,
            "canceled": OrderStatus.CANCELED,
            "cancelled": OrderStatus.CANCELED,
            "rejected": OrderStatus.REJECTED,
            "expired": OrderStatus.EXPIRED,
        }
        status = status_map.get(status_str, OrderStatus.UNKNOWN)

        error_message = None
        error_code = None
        if status == OrderStatus.REJECTED:
            info = order.get("info", {})
            error_message = info.get("sMsg", "订单被拒绝")
            error_code = info.get("sCode", "")

        return OrderResult(
            order_id=str(order_id),
            status=status,
            symbol=symbol,
            side=side,
            order_type=order_type,
            requested_amount=requested_amount,
            filled_amount=filled,
            remaining_amount=remaining,
            average_price=avg_price,
            error_message=error_message,
            error_code=error_code,
        )

    async def create_stop_loss(
        self,
        symbol: str,
        side: str,
        amount: float,
        stop_price: float,
    ) -> str:
        """创建止损单（向后兼容）"""
        result = await self.create_stop_loss_with_status(
            symbol, side, amount, stop_price
        )
        return result.order_id

    async def create_stop_loss_with_status(
        self,
        symbol: str,
        side: str,
        amount: float,
        stop_price: float,
    ) -> StopOrderResult:
        """
        创建止损单并返回状态

        Args:
            symbol: 交易对
            side: 方向
            amount: 数量
            stop_price: 止损价

        Returns:
            StopOrderResult: 止损单执行结果
        """
        params = {
            "tdMode": "cross",
            "posMode": "one_way",
            "stopLossPrice": stop_price,
            "closePosition": True,
        }

        logger.info(
            f"[止损单创建] 提交止损单: symbol={symbol}, side={side}, "
            f"amount={amount}, stop_price={stop_price}"
        )

        try:
            order = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.exchange.create_order(
                    symbol=symbol,
                    type="limit",
                    side=side,
                    amount=amount,
                    price=stop_price * 0.999,
                    params=params,
                ),
            )

            algo_id = order.get("info", {}).get("algoId", order.get("id", ""))
            self._stop_orders[str(stop_price)] = str(algo_id)

            logger.info(
                f"[止损单创建] 止损单成功: ID={algo_id}, 止损价={stop_price}, 数量={amount}"
            )

            return StopOrderResult(
                order_id=str(algo_id),
                stop_price=stop_price,
                amount=amount,
                status=OrderStatus.OPEN,
            )

        except Exception as e:
            logger.error(f"[止损单创建] 止损单失败: {e}")
            return StopOrderResult(
                order_id="",
                stop_price=stop_price,
                amount=amount,
                status=OrderStatus.REJECTED,
                error_message=str(e),
            )

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """取消订单"""
        try:
            logger.info(f"[订单取消] 取消订单: ID={order_id}, symbol={symbol}")
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: self.exchange.cancel_order(order_id, symbol)
            )
            logger.info(f"[订单取消] 订单取消成功: {order_id}")
            return True
        except Exception as e:
            logger.error(f"[订单取消] 取消订单失败: {order_id}, 错误={e}")
            return False

    async def get_order_status(self, order_id: str, symbol: str) -> OrderResult:
        """
        查询订单状态

        Args:
            order_id: 订单ID
            symbol: 交易对

        Returns:
            OrderResult: 订单状态
        """
        try:
            order = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self.exchange.fetch_order(order_id, symbol)
            )
            return self._parse_order_response(order, order.get("amount", 0))
        except Exception as e:
            logger.error(f"[订单查询] 查询订单状态失败: {order_id}, 错误={e}")
            return OrderResult(
                order_id=order_id,
                status=OrderStatus.UNKNOWN,
                symbol=symbol,
                side="",
                order_type="",
                requested_amount=0,
                filled_amount=0,
                remaining_amount=0,
                average_price=0,
                error_message=str(e),
            )

    def get_stop_order_id(self, stop_price: float) -> Optional[str]:
        """获取止损单ID"""
        return self._stop_orders.get(str(stop_price))


def create_order_service(exchange, symbol: str) -> OrderService:
    """创建订单服务实例"""
    return OrderService(exchange, symbol)
