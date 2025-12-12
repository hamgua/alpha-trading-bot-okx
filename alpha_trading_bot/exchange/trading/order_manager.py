"""
订单管理器 - 处理订单的创建、更新和取消
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from ...core.base import BaseComponent, BaseConfig
from ..models import OrderResult, OrderStatus, TradeSide

logger = logging.getLogger(__name__)

class OrderManagerConfig(BaseConfig):
    """订单管理器配置"""
    enable_limit_orders: bool = True
    maker_ratio: float = 0.5
    price_buffer: float = 0.001
    timeout: int = 30
    retry_limit: int = 3

class OrderManager(BaseComponent):
    """订单管理器"""

    def __init__(self, exchange_client, config: Optional[OrderManagerConfig] = None):
        # 如果没有提供配置，创建默认配置
        if config is None:
            config = OrderManagerConfig(name="OrderManager")
        super().__init__(config)
        self.exchange_client = exchange_client
        self.active_orders: Dict[str, OrderResult] = {}
        self.order_history: List[OrderResult] = []

    async def initialize(self) -> bool:
        """初始化订单管理器"""
        logger.info("正在初始化订单管理器...")
        self._initialized = True
        return True

    async def cleanup(self) -> None:
        """清理资源"""
        # 取消所有活动订单
        for order_id, order in self.active_orders.items():
            try:
                await self.exchange_client.cancel_order(order_id, order.symbol)
            except Exception as e:
                logger.error(f"取消订单失败 {order_id}: {e}")

    async def create_market_order(self, symbol: str, side: TradeSide, amount: float, reduce_only: bool = False) -> OrderResult:
        """创建市价单"""
        order_request = {
            'symbol': symbol,
            'type': 'market',
            'side': side.value,
            'amount': amount,
            'reduce_only': reduce_only
        }

        result = await self.exchange_client.create_order(order_request)

        if result.success:
            self.active_orders[result.order_id] = result
            self.order_history.append(result)
            logger.info(f"市价单创建成功: {symbol} {side.value} {amount}")
        else:
            logger.error(f"市价单创建失败: {result.error_message}")

        return result

    async def create_limit_order(self, symbol: str, side: TradeSide, amount: float, price: float, reduce_only: bool = False) -> OrderResult:
        """创建限价单"""
        if not self.config.enable_limit_orders:
            # 如果禁用限价单，转为市价单
            logger.info("限价单已禁用，转为市价单")
            return await self.create_market_order(symbol, side, amount, reduce_only)

        order_request = {
            'symbol': symbol,
            'type': 'limit',
            'side': side.value,
            'amount': amount,
            'price': price,
            'reduce_only': reduce_only,
            'post_only': True  # 只做maker
        }

        result = await self.exchange_client.create_order(order_request)

        if result.success:
            self.active_orders[result.order_id] = result
            self.order_history.append(result)
            logger.info(f"限价单创建成功: {symbol} {side.value} {amount} @ {price}")
        else:
            logger.error(f"限价单创建失败: {result.error_message}")

        return result

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """取消订单"""
        try:
            success = await self.exchange_client.cancel_order(order_id, symbol)
            if success and order_id in self.active_orders:
                self.active_orders[order_id].status = OrderStatus.CANCELED
                logger.info(f"订单取消成功: {order_id}")
            return success
        except Exception as e:
            logger.error(f"取消订单失败 {order_id}: {e}")
            return False

    async def cancel_all_orders(self, symbol: str) -> int:
        """取消所有订单"""
        canceled_count = 0
        orders_to_cancel = list(self.active_orders.values())

        for order in orders_to_cancel:
            if order.symbol == symbol and order.status in [OrderStatus.OPEN, OrderStatus.PENDING]:
                if await self.cancel_order(order.order_id, symbol):
                    canceled_count += 1

        logger.info(f"已取消 {canceled_count} 个订单")
        return canceled_count

    async def update_order_status(self, order_id: str, symbol: str) -> Optional[OrderResult]:
        """更新订单状态"""
        if order_id not in self.active_orders:
            return None

        try:
            result = await self.exchange_client.fetch_order(order_id, symbol)
            if result.success:
                self.active_orders[order_id] = result
                logger.debug(f"订单状态更新: {order_id} - {result.status}")
            return result
        except Exception as e:
            logger.error(f"更新订单状态失败 {order_id}: {e}")
            return None

    async def update_all_orders(self) -> None:
        """更新所有活动订单状态"""
        orders_to_update = list(self.active_orders.items())

        for order_id, order in orders_to_update:
            if order.status in [OrderStatus.OPEN, OrderStatus.PENDING]:
                await self.update_order_status(order_id, order.symbol)

    def get_active_orders(self, symbol: Optional[str] = None) -> List[OrderResult]:
        """获取活动订单"""
        if symbol:
            return [order for order in self.active_orders.values() if order.symbol == symbol]
        return list(self.active_orders.values())

    def get_order_history(self, symbol: Optional[str] = None, limit: int = 100) -> List[OrderResult]:
        """获取订单历史"""
        orders = self.order_history
        if symbol:
            orders = [order for order in orders if order.symbol == symbol]
        return orders[-limit:]  # 返回最近的订单

    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        base_status = super().get_status()
        base_status.update({
            'active_orders_count': len(self.active_orders),
            'total_orders_count': len(self.order_history),
            'recent_orders': len([o for o in self.order_history[-10:] if o.timestamp])
        })
        return base_status