"""
精简版交易所客户端 - 保留核心功能
使用组合模式：集成 AccountService, MarketDataService, OrderService
"""

import asyncio
import ccxt
import logging
from typing import Dict, Any, Optional

from .account_service import AccountService, create_account_service
from .market_data import MarketDataService, create_market_data_service
from .order_service import OrderService, create_order_service

logger = logging.getLogger(__name__)


class ExchangeClient:
    """OKX交易所客户端 - 组合模式"""

    def __init__(
        self,
        api_key: str = "",
        secret: str = "",
        password: str = "",
        symbol: str = "BTC/USDT:USDT",
    ):
        self.api_key = api_key
        self.secret = secret
        self.password = password
        self.symbol = symbol
        self.exchange: Optional[ccxt.okx] = None

        # 组合服务
        self._account_service: Optional[AccountService] = None
        self._market_data_service: Optional[MarketDataService] = None
        self._order_service: Optional[OrderService] = None

    async def initialize(self) -> None:
        """初始化"""
        self.exchange = ccxt.okx(
            {
                "apiKey": self.api_key,
                "secret": self.secret,
                "password": self.password,
                "enableRateLimit": True,
                "options": {"defaultType": "future"},
            }
        )

        # 初始化子服务
        self._account_service = create_account_service(self.exchange, self.symbol)
        self._market_data_service = create_market_data_service(
            self.exchange, self.symbol
        )
        self._order_service = create_order_service(self.exchange, self.symbol)

        await asyncio.get_event_loop().run_in_executor(
            None, lambda: self.exchange.fetch_time()
        )
        logger.info("交易所客户端初始化完成")

    async def set_leverage(self, leverage: int) -> None:
        """设置杠杆"""
        market = self.symbol.split("/")[0]
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self.exchange.set_leverage(leverage, self.symbol),
        )
        logger.info(f"设置杠杆: {leverage}x")

    # === 代理方法 - 委托给子服务 ===

    async def get_balance(self) -> float:
        """获取可用USDT余额"""
        return await self._account_service.get_balance()

    async def get_position(self) -> Optional[Dict[str, Any]]:
        """获取当前持仓"""
        return await self._account_service.get_position()

    async def get_ohlcv(self, timeframe: str = "1h", limit: int = 100):
        """获取K线数据"""
        return await self._market_data_service.get_ohlcv(timeframe, limit)

    async def get_market_data(self) -> Dict[str, Any]:
        """获取市场数据 - 包含技术指标"""
        return await self._market_data_service.get_market_data()

    async def calculate_max_contracts(self, price: float, leverage: int) -> float:
        """根据余额和杠杆计算最大可开合约数"""
        return await self._market_data_service.calculate_max_contracts(
            price, leverage, self.get_balance
        )

    async def create_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        order_type: str = "market",
    ) -> str:
        """创建订单"""
        return await self._order_service.create_order(
            symbol, side, amount, price, order_type
        )

    async def create_stop_loss(
        self,
        symbol: str,
        side: str,
        amount: float,
        stop_price: float,
    ) -> str:
        """创建止损单"""
        return await self._order_service.create_stop_loss(
            symbol, side, amount, stop_price
        )

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """取消订单"""
        return await self._order_service.cancel_order(order_id, symbol)

    async def get_open_orders(self, symbol: str) -> list:
        """获取当前未成交订单（普通订单）"""
        try:
            orders = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self.exchange.fetch_open_orders(symbol)
            )
            return orders
        except Exception as e:
            logger.error(f"[订单查询] 获取开放订单失败: {e}")
            return []

    async def get_algo_orders(self, symbol: str) -> list:
        """获取当前未成交算法订单（止损单、止盈单等）"""
        try:
            # OKX: 使用 fetch_open_orders 并传入 ordType 参数来查询算法订单
            algo_orders = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.exchange.fetch_open_orders(
                    symbol, params={"ordType": "conditional", "trigger": True}
                ),
            )
            return algo_orders
        except Exception as e:
            logger.error(f"[算法订单查询] 获取算法订单失败: {e}")
            return []

    async def cleanup(self) -> None:
        """清理"""
        if self.exchange:
            logger.info("交易所客户端清理完成")
