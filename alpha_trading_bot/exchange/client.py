"""
精简版交易所客户端 - 保留核心功能
使用组合模式：集成 AccountService, MarketDataService, OrderService
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import ccxt

from .account_service import AccountService, create_account_service
from .instrument_service import InstrumentService
from .market_data import MarketDataService, create_market_data_service
from .models.instruments import InstrumentSpec
from .models.orders import OrderIntent, OrderResult, OrderStatus
from .okx_raw import (
    ensure_okx_success,
    get_callable,
    okx_inst_id_from_symbol,
    parse_okx_algo_orders,
    parse_okx_orders,
)
from .order_service import OrderService, create_order_service
from .raw_executor import OkxRawExecutor

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
        self._raw_executor: Optional[OkxRawExecutor] = None
        self._instrument_service: Optional[InstrumentService] = None
        self._instrument_spec: Optional[InstrumentSpec] = None

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
        self._raw_executor = OkxRawExecutor(self.exchange)
        self._instrument_service = InstrumentService(self.exchange, self.symbol)
        self._instrument_spec = await self._instrument_service.load()

        await asyncio.get_event_loop().run_in_executor(
            None, lambda: self.exchange.fetch_time()
        )
        logger.info("交易所客户端初始化完成")

    @property
    def instrument_spec(self) -> InstrumentSpec:
        """返回已初始化的 OKX 合约规格。"""
        if self._instrument_spec is None:
            raise RuntimeError("instrument metadata is not initialized")
        return self._instrument_spec

    def normalize_order_size(self, amount: float) -> float:
        """按合约规格向下归一化下单数量。"""
        return self.instrument_spec.normalize_size(amount)

    def normalize_trigger_price(self, price: float, position_side: str) -> float:
        """按持仓方向归一化触发价格。"""
        rounding = "up" if position_side == "short" else "down"
        return self.instrument_spec.normalize_price(price, rounding)

    def calculate_notional_usdt(self, amount: float, price: float) -> float:
        """根据合约规格计算 USDT 名义价值。"""
        return self.instrument_spec.notional_usdt(amount, price)

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
            raise RuntimeError("OKX raw set-leverage endpoint is unavailable")
        logger.info(f"设置杠杆: {leverage}x for {target_symbol}")

    def _get_okx_set_leverage_method(self):
        return get_callable(
            self.exchange,
            "private_post_account_set_leverage",
            "privatePostAccountSetLeverage",
        )

    def _set_okx_leverage_direct(self, leverage: int, symbol: str) -> None:
        """绕过 ccxt load_markets，直接调用 OKX 设置杠杆接口。"""
        method = self._get_okx_set_leverage_method()
        if method is None:
            raise RuntimeError("OKX raw set-leverage endpoint is unavailable")

        params = {
            "instId": okx_inst_id_from_symbol(symbol),
            "lever": str(leverage),
            "mgnMode": "cross",
        }
        response = method(params)
        if isinstance(response, dict):
            ensure_okx_success(response, "set leverage")

    def _get_raw_executor(self) -> OkxRawExecutor:
        """获取 raw executor，兼容测试中直接注入 exchange 的旧用法。"""
        if (
            self._raw_executor is None
            or self._raw_executor.exchange is not self.exchange
        ):
            self._raw_executor = OkxRawExecutor(self.exchange)
        return self._raw_executor

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

    @property
    def last_query_failed(self) -> bool:
        """最后一次 get_position_with_retry 是否因异常失败"""
        if self._account_service is not None:
            return self._account_service._last_query_failed
        return False

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
        intent: OrderIntent = OrderIntent.OPEN,
        position_side: str = "",
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
            symbol, side, amount, price, order_type, intent, position_side
        )

    async def create_order_with_status(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        order_type: str = "market",
        intent: OrderIntent = OrderIntent.OPEN,
        position_side: str = "",
    ) -> OrderResult:
        """创建订单并返回状态。"""
        if self.test_mode:
            simulated_id = f"SIMULATED_ORDER_{side.upper()}_{int(time.time())}"
            logger.warning(
                "[交易保护] TEST_MODE=true，跳过真实下单: "
                f"side={side}, amount={amount}, symbol={symbol}"
            )
            return OrderResult(
                order_id=simulated_id,
                status=OrderStatus.CLOSED,
                symbol=symbol,
                side=side,
                order_type=order_type,
                requested_amount=amount,
                filled_amount=amount,
                remaining_amount=0.0,
                average_price=price or 0.0,
            )

        return await self._order_service.create_order_with_status(
            symbol, side, amount, price, order_type, intent, position_side
        )

    async def get_order_status(self, order_id: str, symbol: str) -> OrderResult:
        """查询普通订单状态。"""
        return await self._order_service.get_order_status(order_id, symbol)

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
            method = get_callable(
                self.exchange,
                "private_get_trade_orders_pending",
                "privateGetTradeOrdersPending",
            )
            if method is not None:
                params = {"instId": okx_inst_id_from_symbol(symbol)}
                orders = await self._get_raw_executor().call(
                    "private_get_trade_orders_pending",
                    "privateGetTradeOrdersPending",
                    params,
                    parser=lambda response: parse_okx_orders(response, symbol),
                )
            else:
                raise RuntimeError("OKX raw open-orders endpoint is unavailable")
            return orders
        except Exception as e:
            logger.error(f"[订单查询] 获取开放订单失败: {e}")
            return []

    async def get_algo_orders(self, symbol: str) -> list:
        """获取当前未成交算法订单（止损单、止盈单等）"""
        try:
            method = get_callable(
                self.exchange,
                "private_get_trade_orders_algo_pending",
                "privateGetTradeOrdersAlgoPending",
            )
            if method is not None:
                params = {
                    "instId": okx_inst_id_from_symbol(symbol),
                    "ordType": "conditional",
                }
                algo_orders = await self._get_raw_executor().call(
                    "private_get_trade_orders_algo_pending",
                    "privateGetTradeOrdersAlgoPending",
                    params,
                    parser=lambda response: parse_okx_algo_orders(response, symbol),
                )
            else:
                raise RuntimeError("OKX raw algo-orders endpoint is unavailable")
            return algo_orders
        except Exception as e:
            logger.error(f"[算法订单查询] 获取算法订单失败: {e}")
            return []

    async def get_algo_order_history(
        self, symbol: str, algo_id: str = "", limit: int = 20
    ) -> list:
        """获取算法订单历史（用于确认止损/止盈触发）。"""
        try:
            method = get_callable(
                self.exchange,
                "private_get_trade_orders_algo_history",
                "privateGetTradeOrdersAlgoHistory",
            )
            if method is not None:
                params = {
                    "instId": okx_inst_id_from_symbol(symbol),
                    "ordType": "conditional",
                    "limit": str(limit),
                }
                if algo_id:
                    params["algoId"] = algo_id
                algo_orders = await self._get_raw_executor().call(
                    "private_get_trade_orders_algo_history",
                    "privateGetTradeOrdersAlgoHistory",
                    params,
                    parser=lambda response: parse_okx_algo_orders(response, symbol),
                )
            else:
                raise RuntimeError("OKX raw algo-order-history endpoint is unavailable")
            return algo_orders
        except Exception as e:
            logger.error(f"[算法订单查询] 获取算法订单历史失败: {e}")
            return []

    async def cleanup(self) -> None:
        """清理"""
        if self.exchange:
            logger.info("交易所客户端清理完成")
