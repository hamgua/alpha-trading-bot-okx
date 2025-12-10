"""
交易所客户端 - 基于CCXT的OKX交易所封装
"""

import asyncio
import ccxt.async_support as ccxt
from typing import Dict, Any, Optional, List
from datetime import datetime
import logging

from ..core.exceptions import ExchangeError
from .models import ExchangeConfig, TickerData, OrderBookData, BalanceData, OrderResult, OrderStatus, TradeSide

logger = logging.getLogger(__name__)

class ExchangeClient:
    """交易所客户端"""

    def __init__(self):
        self.exchange = None
        self.config = None
        self._initialized = False

    async def initialize(self) -> bool:
        """初始化交易所客户端"""
        try:
            from ..config import load_config
            config_manager = load_config()

            self.config = ExchangeConfig(
                exchange=config_manager.exchange.exchange,
                api_key=config_manager.exchange.api_key,
                secret=config_manager.exchange.secret,
                password=config_manager.exchange.password,
                sandbox=config_manager.exchange.sandbox,
                symbol=config_manager.exchange.symbol,
                leverage=config_manager.trading.leverage,
                margin_mode=config_manager.trading.margin_mode
            )

            # 创建交易所实例
            exchange_class = getattr(ccxt, self.config.exchange)
            self.exchange = exchange_class({
                'apiKey': self.config.api_key,
                'secret': self.config.secret,
                'password': self.config.password,
                'sandbox': self.config.sandbox,
                'options': {
                    'defaultType': 'future',
                    'marginMode': self.config.margin_mode,
                    'leverage': self.config.leverage
                },
                'enableRateLimit': True,
                'timeout': self.config.timeout
            })

            # 加载市场数据
            await self.exchange.load_markets()

            # 设置杠杆（如果是合约交易）
            if hasattr(self.exchange, 'set_leverage'):
                try:
                    await self.exchange.set_leverage(
                        self.config.leverage,
                        self.config.symbol
                    )
                except Exception as e:
                    logger.warning(f"设置杠杆失败: {e}")

            self._initialized = True
            logger.info(f"交易所客户端初始化成功: {self.config.exchange}")
            return True

        except Exception as e:
            logger.error(f"交易所客户端初始化失败: {e}")
            raise ExchangeError(f"交易所初始化失败: {e}")

    async def cleanup(self) -> None:
        """清理资源"""
        if self.exchange:
            await self.exchange.close()
            self.exchange = None

    async def fetch_ticker(self, symbol: str) -> TickerData:
        """获取行情数据"""
        try:
            ticker = await self.exchange.fetch_ticker(symbol)
            return TickerData(
                symbol=symbol,
                bid=ticker['bid'],
                ask=ticker['ask'],
                last=ticker['last'],
                high=ticker['high'],
                low=ticker['low'],
                volume=ticker['volume']
            )
        except Exception as e:
            logger.error(f"获取行情数据失败: {e}")
            raise ExchangeError(f"获取行情数据失败: {e}")

    async def fetch_order_book(self, symbol: str, limit: int = 20) -> OrderBookData:
        """获取订单簿数据"""
        try:
            orderbook = await self.exchange.fetch_order_book(symbol, limit)
            return OrderBookData(
                symbol=symbol,
                bids=orderbook['bids'],
                asks=orderbook['asks']
            )
        except Exception as e:
            logger.error(f"获取订单簿数据失败: {e}")
            raise ExchangeError(f"获取订单簿数据失败: {e}")

    async def fetch_balance(self) -> BalanceData:
        """获取账户余额"""
        try:
            balance = await self.exchange.fetch_balance()
            usdt_balance = balance.get('USDT', {})
            return BalanceData(
                total=usdt_balance.get('total', 0),
                free=usdt_balance.get('free', 0),
                used=usdt_balance.get('used', 0),
                currency='USDT'
            )
        except Exception as e:
            logger.error(f"获取账户余额失败: {e}")
            raise ExchangeError(f"获取账户余额失败: {e}")

    async def create_order(self, order_request: Dict[str, Any]) -> OrderResult:
        """创建订单"""
        try:
            symbol = order_request['symbol']
            type_ = order_request.get('type', 'market')
            side = order_request['side']
            amount = order_request['amount']
            price = order_request.get('price')

            params = {}
            if 'reduce_only' in order_request:
                params['reduceOnly'] = order_request['reduce_only']
            if 'post_only' in order_request:
                params['postOnly'] = order_request['post_only']
            if 'client_order_id' in order_request:
                params['clientOrderId'] = order_request['client_order_id']

            order = await self.exchange.create_order(
                symbol=symbol,
                type=type_,
                side=side,
                amount=amount,
                price=price,
                params=params
            )

            return OrderResult(
                success=True,
                order_id=order['id'],
                client_order_id=order.get('clientOrderId'),
                symbol=order['symbol'],
                side=TradeSide(order['side']),
                amount=order['amount'],
                price=order.get('price', 0),
                filled_amount=order.get('filled', 0),
                average_price=order.get('average', 0),
                status=OrderStatus(order['status'])
            )

        except Exception as e:
            logger.error(f"创建订单失败: {e}")
            return OrderResult(
                success=False,
                error_message=str(e)
            )

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """取消订单"""
        try:
            result = await self.exchange.cancel_order(order_id, symbol)
            return True
        except Exception as e:
            logger.error(f"取消订单失败: {e}")
            return False

    async def fetch_order(self, order_id: str, symbol: str) -> OrderResult:
        """获取订单详情"""
        try:
            order = await self.exchange.fetch_order(order_id, symbol)
            return OrderResult(
                success=True,
                order_id=order['id'],
                client_order_id=order.get('clientOrderId'),
                symbol=order['symbol'],
                side=TradeSide(order['side']),
                amount=order['amount'],
                price=order.get('price', 0),
                filled_amount=order.get('filled', 0),
                average_price=order.get('average', 0),
                status=OrderStatus(order['status'])
            )
        except Exception as e:
            logger.error(f"获取订单详情失败: {e}")
            return OrderResult(
                success=False,
                error_message=str(e)
            )

    async def fetch_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取仓位信息"""
        try:
            positions = await self.exchange.fetch_positions([symbol] if symbol else None)
            return positions
        except Exception as e:
            logger.error(f"获取仓位信息失败: {e}")
            raise ExchangeError(f"获取仓位信息失败: {e}")

    async def set_leverage(self, leverage: int, symbol: str) -> bool:
        """设置杠杆"""
        try:
            await self.exchange.set_leverage(leverage, symbol)
            return True
        except Exception as e:
            logger.error(f"设置杠杆失败: {e}")
            return False

    async def fetch_ohlcv(self, symbol: str, timeframe: str = '5m', limit: int = 100) -> List[List[float]]:
        """获取K线数据"""
        try:
            ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            return ohlcv
        except Exception as e:
            logger.error(f"获取K线数据失败: {e}")
            raise ExchangeError(f"获取K线数据失败: {e}")