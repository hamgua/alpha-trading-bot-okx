"""
精简版交易所客户端 - 保留核心功能
使用组合模式：集成 AccountService, MarketDataService, OrderService
"""

import asyncio
import ccxt
import logging
import time
from typing import Dict, Any, Optional, List

from .account_service import AccountService, create_account_service
from .market_data import MarketDataService, create_market_data_service
from .order_service import OrderService, create_order_service

logger = logging.getLogger(__name__)


class ExchangeClient:
    """OKX交易所客户端 - 组合模式"""

    SIMULATED_PREFIX = "SIMULATED_"

    def __init__(
        self,
        api_key: str = "",
        secret: str = "",
        password: str = "",
        symbol: str = "BTC/USDT:USDT",
        allow_short_selling: bool = True,
        test_mode: bool = True,
        max_position_usage: float = 0.30,
    ):
        self.api_key = api_key
        self.secret = secret
        self.password = password
        self.symbol = symbol
        self.allow_short_selling = allow_short_selling
        self.test_mode = test_mode
        self._max_position_usage = max_position_usage
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

        # TEST_MODE=true 时启用交易所沙盒模式，避免误实盘
        try:
            self.exchange.set_sandbox_mode(self.test_mode)
            logger.info(f"交易所沙盒模式: {'开启' if self.test_mode else '关闭'}")
        except Exception as e:
            logger.warning(f"设置交易所沙盒模式失败: {e}")

        # 初始化子服务
        self._account_service = create_account_service(
            self.exchange, self.symbol, self.allow_short_selling
        )
        self._market_data_service = create_market_data_service(
            self.exchange, self.symbol
        )
        self._order_service = create_order_service(self.exchange, self.symbol)

        await asyncio.get_event_loop().run_in_executor(
            None, lambda: self.exchange.fetch_time()
        )
        logger.info("交易所客户端初始化完成")

    async def set_leverage(self, leverage: int, symbol: Optional[str] = None) -> None:
        if leverage is None or not isinstance(leverage, int) or leverage < 1:
            raise ValueError(
                f"Invalid leverage: {leverage}. Must be a positive integer."
            )

        target_symbol = symbol or self.symbol
        if not target_symbol or not isinstance(target_symbol, str):
            raise ValueError(
                f"Invalid symbol: {target_symbol}. Must be a non-empty string."
            )

        if self._get_okx_set_leverage_method() is not None:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._set_okx_leverage_direct(leverage, target_symbol),
            )
        else:
            await self._set_leverage_via_ccxt(leverage, target_symbol)
        logger.info(f"设置杠杆: {leverage}x for {target_symbol}")

    def _get_okx_set_leverage_method(self):
        method = getattr(self.exchange, "private_post_account_set_leverage", None)
        if method is None:
            method = getattr(self.exchange, "privatePostAccountSetLeverage", None)
        return method if callable(method) else None

    async def _set_leverage_via_ccxt(self, leverage: int, symbol: str) -> None:
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.exchange.set_leverage(leverage, symbol),
            )
        except TypeError as e:
            if not self._is_ccxt_markets_keysort_error(e):
                raise
            logger.warning(
                "[杠杆设置] ccxt加载市场时遇到None键排序错误，"
                f"但OKX原始接口不可用: {e}"
            )
            raise RuntimeError("OKX raw set-leverage endpoint is unavailable") from e

    @staticmethod
    def _is_ccxt_markets_keysort_error(error: TypeError) -> bool:
        """判断是否为 ccxt markets_by_id 中混入 None 键导致的排序错误。"""
        message = str(error)
        return "NoneType" in message and "str" in message and "<" in message

    @staticmethod
    def _okx_inst_id_from_symbol(symbol: str) -> str:
        """将 ccxt symbol 转换为 OKX instId。"""
        normalized = symbol.strip()
        if "/" not in normalized:
            return normalized.replace("/", "-").replace(":", "-")

        pair, _, contract_suffix = normalized.partition(":")
        base, quote = pair.split("/", 1)
        if contract_suffix:
            return f"{base}-{quote}-SWAP"
        return f"{base}-{quote}"

    def _set_okx_leverage_direct(self, leverage: int, symbol: str) -> None:
        """绕过 ccxt load_markets，直接调用 OKX 设置杠杆接口。"""
        method = self._get_okx_set_leverage_method()
        if method is None:
            raise RuntimeError("OKX raw set-leverage endpoint is unavailable")

        params = {
            "instId": self._okx_inst_id_from_symbol(symbol),
            "lever": str(leverage),
            "mgnMode": "cross",
        }
        response = method(params)
        if isinstance(response, dict) and str(response.get("code", "0")) != "0":
            raise RuntimeError(f"OKX set leverage failed: {response}")

    # === 代理方法 - 委托给子服务 ===

    async def get_balance(self) -> float:
        """获取可用USDT余额"""
        return await self._account_service.get_balance()

    async def get_position(self) -> Optional[Dict[str, Any]]:
        """获取当前持仓"""
        return await self._account_service.get_position()

    async def get_position_with_retry(
        self, max_retries: int = 3, retry_delay: float = 1.0
    ) -> Optional[Dict[str, Any]]:
        """获取当前持仓（带重试机制）"""
        return await self._account_service.get_position_with_retry(
            max_retries, retry_delay
        )

    async def get_ohlcv(
        self, timeframe: str = "1h", limit: int = 100
    ) -> List[List[float]]:
        """获取K线数据"""
        return await self._market_data_service.get_ohlcv(timeframe, limit)

    async def get_market_data(self) -> Dict[str, Any]:
        """获取市场数据 - 包含技术指标"""
        return await self._market_data_service.get_market_data()

    async def calculate_max_contracts(self, price: float, leverage: int) -> float:
        """根据余额和杠杆计算最大可开合约数"""
        return await self._market_data_service.calculate_max_contracts(
            price, leverage, self.get_balance, self._max_position_usage
        )

    @staticmethod
    def is_simulated_order(order_id: str) -> bool:
        """判断是否为TEST_MODE下生成的模拟订单"""
        return bool(order_id) and order_id.startswith(ExchangeClient.SIMULATED_PREFIX)

    async def create_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        order_type: str = "market",
    ) -> str:
        """创建订单"""
        if self.test_mode:
            simulated_id = f"SIMULATED_ORDER_{side.upper()}_{int(time.time())}"
            logger.warning(
                "[交易保护] TEST_MODE=true，跳过真实下单: "
                f"side={side}, amount={amount}, symbol={symbol}"
            )
            return simulated_id

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
        if self.test_mode:
            simulated_id = f"SIMULATED_STOP_{int(time.time())}"
            logger.warning(
                "[交易保护] TEST_MODE=true，跳过真实止损单: "
                f"side={side}, amount={amount}, stop_price={stop_price}"
            )
            return simulated_id

        return await self._order_service.create_stop_loss(
            symbol, side, amount, stop_price
        )

    async def create_take_profit(
        self,
        symbol: str,
        side: str,
        amount: float,
        take_profit_price: float,
    ) -> str:
        """创建止盈单"""
        if self.test_mode:
            simulated_id = f"SIMULATED_TAKE_PROFIT_{int(time.time())}"
            logger.warning(
                "[交易保护] TEST_MODE=true，跳过真实止盈单: "
                f"side={side}, amount={amount}, "
                f"take_profit_price={take_profit_price}"
            )
            return simulated_id

        return await self._order_service.create_take_profit(
            symbol, side, amount, take_profit_price
        )

    async def cancel_order(self, order_id: str, symbol: str) -> tuple[bool, str]:
        """取消订单

        Returns:
            tuple: (success: bool, reason: str)
        """
        return await self._order_service.cancel_order(order_id, symbol)

    async def cancel_algo_order(self, algo_id: str, symbol: str) -> tuple[bool, str]:
        """取消算法单（止损单、止盈单等）

        Returns:
            tuple: (success: bool, reason: str)
        """
        return await self._order_service.cancel_algo_order(algo_id, symbol)

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
