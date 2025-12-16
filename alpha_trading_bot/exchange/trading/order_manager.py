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

    async def create_stop_order(self, symbol: str, side: TradeSide, amount: float, stop_price: float,
                                reduce_only: bool = True, client_order_id: Optional[str] = None) -> OrderResult:
        """创建止损订单（使用交易所的算法订单功能）"""
        try:
            logger.info(f"创建止损订单: {symbol} {side.value} {amount} @ {stop_price}")

            # 构建算法订单参数
            params = {
                'reduceOnly': reduce_only,
                'triggerPx': str(stop_price),  # 触发价格
                'orderPx': '-1',  # -1 表示市价执行
                'triggerPxType': 'last',  # 基于最新价格触发
                'tdMode': 'cross',  # 全仓模式
                'ordType': 'trigger'  # 触发订单类型
            }

            if client_order_id:
                params['clientOrderId'] = client_order_id

            # 使用 CCXT 的 create_order 创建触发订单
            order = await self.exchange_client.exchange.create_order(
                symbol=symbol,
                type='trigger',
                side=side.value.lower(),
                amount=amount,
                price=None,
                params=params
            )

            order_result = OrderResult(
                success=True,
                order_id=order['id'],
                client_order_id=order.get('clientOrderId'),
                symbol=order['symbol'],
                side=side,
                amount=order['amount'],
                price=float(order.get('price', 0)),
                filled_amount=float(order.get('filled', 0)),
                average_price=float(order.get('average', 0)),
                status=OrderStatus(order['status'])
            )

            # 添加到活动订单列表
            self.active_orders[order_result.order_id] = order_result
            self.order_history.append(order_result)

            logger.info(f"止损订单创建成功: {order_result.order_id}")
            return order_result

        except Exception as e:
            logger.error(f"创建止损订单失败: {e}")
            return OrderResult(
                success=False,
                error_message=f"创建止损订单失败: {str(e)}"
            )

    async def create_take_profit_order(self, symbol: str, side: TradeSide, amount: float, take_profit_price: float,
                                     reduce_only: bool = True, client_order_id: Optional[str] = None) -> OrderResult:
        """创建止盈订单（使用交易所的算法订单功能）"""
        try:
            logger.info(f"创建止盈订单: {symbol} {side.value} {amount} @ {take_profit_price}")

            # 构建算法订单参数
            params = {
                'reduceOnly': reduce_only,
                'triggerPx': str(take_profit_price),  # 触发价格
                'orderPx': '-1',  # -1 表示市价执行
                'triggerPxType': 'last',  # 基于最新价格触发
                'tdMode': 'cross',  # 全仓模式
                'ordType': 'trigger'  # 触发订单类型
            }

            if client_order_id:
                params['clientOrderId'] = client_order_id

            # 使用 CCXT 的 create_order 创建触发订单
            order = await self.exchange_client.exchange.create_order(
                symbol=symbol,
                type='trigger',
                side=side.value.lower(),
                amount=amount,
                price=None,
                params=params
            )

            order_result = OrderResult(
                success=True,
                order_id=order['id'],
                client_order_id=order.get('clientOrderId'),
                symbol=order['symbol'],
                side=side,
                amount=order['amount'],
                price=float(order.get('price', 0)),
                filled_amount=float(order.get('filled', 0)),
                average_price=float(order.get('average', 0)),
                status=OrderStatus(order['status'])
            )

            # 添加到活动订单列表
            self.active_orders[order_result.order_id] = order_result
            self.order_history.append(order_result)

            logger.info(f"止盈订单创建成功: {order_result.order_id}")
            return order_result

        except Exception as e:
            logger.error(f"创建止盈订单失败: {e}")
            return OrderResult(
                success=False,
                error_message=f"创建止盈订单失败: {str(e)}"
            )

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

    async def fetch_algo_orders(self, symbol: str) -> List[OrderResult]:
        """获取算法订单（止盈止损订单）"""
        try:
            # 使用CCXT获取未触发的算法订单
            algo_orders = await self.exchange_client.exchange.private_get_trade_orders_algo_pending({
                'instId': symbol,
                'ordType': 'trigger'
            })

            # 转换格式
            orders = []
            for order in algo_orders.get('data', []):
                orders.append(OrderResult(
                    success=True,
                    order_id=order['algoId'],
                    symbol=order['instId'],
                    side=TradeSide(order['side'].lower()),
                    amount=float(order['sz']),
                    price=float(order.get('triggerPx', 0)),
                    filled_amount=0,
                    average_price=0,
                    status=OrderStatus.OPEN
                ))
            return orders
        except Exception as e:
            logger.error(f"获取算法订单失败: {e}")
            return []

    async def cancel_algo_order(self, algo_order_id: str, symbol: str) -> bool:
        """取消算法订单"""
        try:
            await self.exchange_client.exchange.private_post_trade_cancel_algo_order({
                'algoId': algo_order_id,
                'instId': symbol
            })
            logger.info(f"算法订单取消成功: {algo_order_id}")
            return True
        except Exception as e:
            logger.error(f"取消算法订单失败 {algo_order_id}: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        base_status = super().get_status()
        base_status.update({
            'active_orders_count': len(self.active_orders),
            'total_orders_count': len(self.order_history),
            'recent_orders': len([o for o in self.order_history[-10:] if o.timestamp])
        })
        return base_status