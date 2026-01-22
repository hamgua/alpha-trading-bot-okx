"""
交易所客户端 - 基于CCXT的OKX交易所封装
"""

import asyncio
import ccxt.async_support as ccxt
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
import logging
import time
from functools import wraps

from ..core.exceptions import ExchangeError
from .models import (
    ExchangeConfig,
    TickerData,
    OrderBookData,
    BalanceData,
    OrderResult,
    OrderStatus,
    TradeSide,
)

logger = logging.getLogger(__name__)


def retry_on_network_error(
    max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0
):
    """网络错误重试装饰器"""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except (
                    ccxt.NetworkError,
                    ccxt.RequestTimeout,
                    ccxt.ExchangeNotAvailable,
                ) as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            f"网络错误 (尝试 {attempt + 1}/{max_retries + 1}): {e}，{current_delay}秒后重试"
                        )
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(f"网络错误，已达到最大重试次数: {e}")
                        raise
                except Exception as e:
                    # 非网络错误直接抛出
                    raise

            if last_exception:
                raise last_exception

        return wrapper

    return decorator


class ExchangeClient:
    """交易所客户端"""

    def __init__(self):
        self.exchange = None
        self.config = None
        self._initialized = False
        self._test_mode = False

    @property
    def is_test_mode(self) -> bool:
        """检查是否处于测试模式"""
        return self._test_mode

    @retry_on_network_error(max_retries=3, delay=1.0)
    async def initialize(self) -> bool:
        """初始化交易所客户端"""
        try:
            from ..config import load_config

            config_manager = load_config()

            # 检查是否为测试模式
            if config_manager.trading.test_mode:
                logger.info("测试模式：使用模拟交易所")
                self._test_mode = True
                # 创建模拟交易所配置
                self.config = ExchangeConfig(
                    exchange=config_manager.exchange.exchange,
                    api_key="test_key",
                    secret="test_secret",
                    password="test_passphrase",
                    sandbox=True,
                    symbol=config_manager.exchange.symbol,
                    leverage=config_manager.trading.leverage,
                    margin_mode=config_manager.trading.margin_mode,
                )

                # 在测试模式下，仍然需要创建交易所实例以支持 markets 等属性访问
                try:
                    exchange_class = getattr(ccxt, self.config.exchange)
                    # 创建测试模式的交易所实例（使用模拟配置）
                    exchange_config = {
                        "apiKey": self.config.api_key,
                        "secret": self.config.secret,
                        "password": self.config.password,
                        "sandbox": self.config.sandbox,
                        "options": {
                            "defaultType": "future",
                            "marginMode": self.config.margin_mode,
                            "leverage": self.config.leverage,
                        },
                        "enableRateLimit": True,
                        "timeout": 30000,  # 30秒超时
                    }
                    self.exchange = exchange_class(exchange_config)
                    # 加载市场数据（测试模式也加载，避免空 markets）
                    await self.exchange.load_markets()
                    logger.info("测试模式交易所实例创建成功")
                except Exception as e:
                    logger.warning(
                        f"测试模式创建交易所实例失败: {e}，将使用空 markets 配置"
                    )

                    # 如果创建失败，创建一个mock exchange对象
                    class MockExchange:
                        def __init__(self):
                            self.markets = {}

                    self.exchange = MockExchange()

                self._initialized = True
                logger.info("交易所客户端测试模式初始化成功")
                return True

            self.config = ExchangeConfig(
                exchange=config_manager.exchange.exchange,
                api_key=config_manager.exchange.api_key,
                secret=config_manager.exchange.secret,
                password=config_manager.exchange.password,
                sandbox=config_manager.exchange.sandbox,
                symbol=config_manager.exchange.symbol,
                leverage=config_manager.trading.leverage,
                margin_mode=config_manager.trading.margin_mode,
            )

            # 获取网络配置
            network_config = config_manager.network

            # 创建交易所实例
            exchange_class = getattr(ccxt, self.config.exchange)

            # 构建交易所配置
            exchange_config = {
                "apiKey": self.config.api_key,
                "secret": self.config.secret,
                "password": self.config.password,
                "sandbox": self.config.sandbox,
                "options": {
                    "defaultType": "future",
                    "marginMode": self.config.margin_mode,
                    "leverage": self.config.leverage,
                },
                "enableRateLimit": True,
                "timeout": network_config.timeout * 1000,  # CCXT uses milliseconds
            }

            # 根据代理开关添加代理配置
            if network_config.proxy_enabled:
                logger.info(f"代理已启用，正在配置代理...")
                if network_config.http_proxy:
                    exchange_config["aiohttp_proxy"] = network_config.http_proxy
                    exchange_config["proxy"] = network_config.http_proxy
                    logger.info(f"使用HTTP代理: {network_config.http_proxy}")
                elif network_config.https_proxy:
                    exchange_config["aiohttp_proxy"] = network_config.https_proxy
                    exchange_config["proxy"] = network_config.https_proxy
                    logger.info(f"使用HTTPS代理: {network_config.https_proxy}")
                else:
                    logger.warning("代理已启用但未配置代理地址")
            else:
                logger.info("代理未启用")

            logger.info(
                f"正在创建交易所实例: {self.config.exchange}, sandbox: {self.config.sandbox}, timeout: {network_config.timeout}s"
            )
            self.exchange = exchange_class(exchange_config)

            # 加载市场数据
            await self.exchange.load_markets()

            # 设置杠杆（如果是合约交易）
            if hasattr(self.exchange, "set_leverage"):
                try:
                    logger.info(
                        f"准备设置杠杆: {self.config.leverage}x for {self.config.symbol}"
                    )
                    logger.info(
                        f"当前配置: exchange={self.config.exchange}, symbol={self.config.symbol}, leverage={self.config.leverage}"
                    )
                    success = await self.set_leverage(
                        self.config.leverage, self.config.symbol
                    )
                    if success:
                        logger.info(f"杠杆设置成功: {self.config.leverage}x")
                    else:
                        logger.warning(f"杠杆设置可能未成功，但系统将继续运行")
                except Exception as e:
                    logger.error(f"设置杠杆异常: {e}")
                    import traceback

                    logger.error(f"详细错误: {traceback.format_exc()}")
                    # 即使杠杆设置失败，系统仍继续运行
                    logger.warning("杠杆设置失败，但系统将继续初始化...")

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

    @retry_on_network_error(max_retries=3, delay=1.0)
    async def fetch_ticker(self, symbol: str) -> TickerData:
        """获取行情数据"""
        try:
            # 测试模式返回模拟数据
            if self._test_mode:
                import random

                base_price = 50000.0
                price_variation = random.uniform(-0.01, 0.01)
                current_price = base_price * (1 + price_variation)

                return TickerData(
                    symbol=symbol,
                    bid=current_price - 10,
                    ask=current_price + 10,
                    last=current_price,
                    high=current_price * 1.02,
                    low=current_price * 0.98,
                    volume=random.uniform(100, 1000),
                )

            ticker = await self.exchange.fetch_ticker(symbol)

            # 添加调试日志，查看实际获取的ticker数据
            logger.info(
                f"从交易所获取的ticker数据: symbol={symbol}, last={ticker.get('last')}, volume={ticker.get('volume')}, baseVolume={ticker.get('baseVolume')}"
            )

            # OKX交易所的特殊处理：24小时成交量在baseVolume字段而不是volume字段
            volume = ticker.get("volume")
            if volume is None or volume == 0:
                volume = ticker.get("baseVolume", 0)
                if volume > 0:
                    logger.info(f"使用baseVolume作为成交量: {volume}")
                else:
                    logger.warning(f"交易所返回的成交量为0，symbol={symbol}")

            # Handle missing fields gracefully
            return TickerData(
                symbol=symbol,
                bid=ticker.get("bid", 0),
                ask=ticker.get("ask", 0),
                last=ticker.get("last", 0),
                high=ticker.get("high", 0),
                low=ticker.get("low", 0),
                volume=volume,
            )
        except Exception as e:
            logger.error(f"获取行情数据失败: {e}")
            raise ExchangeError(f"获取行情数据失败: {e}")

    @retry_on_network_error(max_retries=3, delay=1.0)
    async def fetch_order_book(self, symbol: str, limit: int = 20) -> OrderBookData:
        """获取订单簿数据"""
        try:
            # 测试模式返回模拟数据
            if self._test_mode:
                import random

                base_price = 50000.0

                # 生成模拟买卖盘
                bids = []
                asks = []
                for i in range(limit):
                    bid_price = base_price - (i + 1) * 10
                    ask_price = base_price + (i + 1) * 10
                    bid_volume = random.uniform(0.1, 1.0)
                    ask_volume = random.uniform(0.1, 1.0)

                    bids.append([bid_price, bid_volume])
                    asks.append([ask_price, ask_volume])

                return OrderBookData(symbol=symbol, bids=bids, asks=asks)

            orderbook = await self.exchange.fetch_order_book(symbol, limit)
            return OrderBookData(
                symbol=symbol, bids=orderbook["bids"], asks=orderbook["asks"]
            )
        except Exception as e:
            logger.error(f"获取订单簿数据失败: {e}")
            raise ExchangeError(f"获取订单簿数据失败: {e}")

    @retry_on_network_error(max_retries=3, delay=1.0)
    async def fetch_balance(self) -> BalanceData:
        """获取账户余额"""
        try:
            # 测试模式返回模拟数据
            logger.debug(f"fetch_balance called, test_mode: {self._test_mode}")
            if self._test_mode:
                logger.info("测试模式：返回模拟余额数据")
                return BalanceData(
                    total=10000.0, free=9000.0, used=1000.0, currency="USDT"
                )

            balance = await self.exchange.fetch_balance()
            usdt_balance = balance.get("USDT", {})
            return BalanceData(
                total=usdt_balance.get("total", 0),
                free=usdt_balance.get("free", 0),
                used=usdt_balance.get("used", 0),
                currency="USDT",
            )
        except Exception as e:
            logger.error(f"获取账户余额失败: {e}")
            raise ExchangeError(f"获取账户余额失败: {e}")

    # 添加别名方法以兼容性
    async def get_balance(self) -> BalanceData:
        """获取账户余额（别名方法）"""
        return await self.fetch_balance()

    async def create_order(self, order_request: Dict[str, Any]) -> OrderResult:
        """创建订单"""
        try:
            symbol = order_request["symbol"]
            type_ = order_request.get("type", "market")
            side = order_request["side"]
            amount = order_request["amount"]
            price = order_request.get("price")

            # 测试模式：跳过交易所验证，直接返回模拟订单
            if self._test_mode:
                import uuid

                order_id = str(uuid.uuid4())
                client_order_id = str(uuid.uuid4())

                # 获取请求中的client_order_id（如果存在）
                if "client_order_id" in order_request:
                    client_order_id = order_request["client_order_id"]
                elif "clientOrderId" in order_request:
                    client_order_id = order_request["clientOrderId"]

                # 模拟市价单立即成交
                if type_ == "market":
                    filled_amount = amount
                    status = OrderStatus.CLOSED
                else:
                    filled_amount = 0
                    status = OrderStatus.OPEN

                return OrderResult(
                    success=True,
                    order_id=order_id,
                    client_order_id=client_order_id,
                    symbol=symbol,
                    side=TradeSide(side),
                    amount=amount,
                    price=price or 50000.0,
                    average_price=price or 50000.0,
                    filled_amount=filled_amount,
                    remaining_amount=amount - filled_amount,
                    status=status,
                    type=OrderType(type_),
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )

            # 验证最小交易量（仅在非测试模式下）
            if symbol in self.exchange.markets:
                market = self.exchange.markets[symbol]
                min_amount = market.get("limits", {}).get("amount", {}).get("min", 0)
                amount_precision = market.get("precision", {}).get("amount", 0)

                if min_amount and amount < min_amount:
                    logger.error(
                        f"订单数量 {amount} 小于交易所最小交易量 {min_amount} for {symbol}"
                    )
                    return OrderResult(
                        success=False,
                        error_message=f"订单数量必须大于等于 {min_amount}",
                    )

                # 根据精度调整数量
                if amount_precision and isinstance(amount_precision, int):
                    # 对于整数精度，直接使用
                    amount = round(amount, amount_precision)
                    logger.info(f"根据交易所精度调整订单数量至: {amount}")
                elif amount_precision:
                    # 处理浮点数精度（如0.01）
                    try:
                        # 对于OKX等交易所，精度可能是0.01
                        # 确保数量是精度的整数倍
                        if amount_precision > 0 and amount_precision < 1:
                            # 计算最接近的精度倍数
                            multiplier = round(amount / amount_precision)
                            amount = multiplier * amount_precision
                            logger.info(
                                f"根据交易所精度({amount_precision})调整订单数量至: {amount} (倍数: {multiplier})"
                            )
                        else:
                            # 其他情况，按正常四舍五入处理
                            precision_int = int(amount_precision)
                            amount = round(amount, precision_int)
                            logger.info(f"根据交易所精度调整订单数量至: {amount}")
                    except (ValueError, TypeError):
                        # 如果精度无效，保持原数量
                        logger.warning(
                            f"交易所精度格式无效: {amount_precision}，保持原数量: {amount}"
                        )

            params = {}
            if "reduce_only" in order_request:
                params["reduceOnly"] = order_request["reduce_only"]
            if "post_only" in order_request:
                params["postOnly"] = order_request["post_only"]
            if "client_order_id" in order_request:
                params["clientOrderId"] = order_request["client_order_id"]

            order = await self.exchange.create_order(
                symbol=symbol,
                type=type_,
                side=side,
                amount=amount,
                price=price,
                params=params,
            )

            # 调试：检查订单状态
            logger.info(
                f"[交易所客户端] 订单创建成功 - ID: {order['id']}, 状态: {order.get('status', 'None')}, 数量: {order['amount']}, 价格: {order.get('price', 0)}"
            )

            # 处理可能的None状态
            order_status = order.get("status")
            if order_status is None:
                logger.warning("[交易所客户端] 订单状态为None，使用默认值")
                order_status = "closed"  # 市价单默认已成交

            return OrderResult(
                success=True,
                order_id=order["id"],
                client_order_id=order.get("clientOrderId"),
                symbol=order["symbol"],
                side=TradeSide(order["side"]),
                amount=order["amount"],
                price=order.get("price", 0),
                filled_amount=order.get("filled", 0),
                average_price=order.get("average", 0),
                status=OrderStatus(order_status),
            )

        except Exception as e:
            logger.error(f"创建订单失败: {e}")
            return OrderResult(success=False, error_message=str(e))

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
                order_id=order["id"],
                client_order_id=order.get("clientOrderId"),
                symbol=order["symbol"],
                side=TradeSide(order["side"]),
                amount=order["amount"],
                price=order.get("price", 0),
                filled_amount=order.get("filled", 0),
                average_price=order.get("average", 0),
                status=OrderStatus(order["status"]),
            )
        except Exception as e:
            logger.error(f"获取订单详情失败: {e}")
            return OrderResult(success=False, error_message=str(e))

    async def fetch_positions(
        self, symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """获取仓位信息"""
        try:
            # 测试模式返回模拟仓位数据
            if self._test_mode:
                logger.info(f"测试模式：返回模拟仓位信息: {symbol or 'all'}")
                # 测试模式下返回空列表（表示无持仓）
                # 在实际交易中，仓位信息会被创建并缓存
                return []

            # 简化日志 - 只在有仓位时显示关键信息
            positions = await self.exchange.fetch_positions(
                [symbol] if symbol else None
            )

            if positions and len(positions) > 0:
                # 只记录简要信息
                for pos in positions:
                    if pos.get("contracts", 0) != 0:  # 有实际仓位
                        logger.info(
                            f"获取仓位: {pos.get('symbol', 'unknown')} {pos.get('side', 'unknown')} {pos.get('contracts', 0)} 张"
                        )
            else:
                logger.debug(f"未获取到仓位信息: {symbol}")

            # 如果没有指定符号，返回所有仓位
            if not symbol:
                return positions

            # 如果指定了符号，过滤出指定符号的仓位
            filtered_positions = [
                pos for pos in positions if pos.get("symbol") == symbol
            ]
            return filtered_positions
        except Exception as e:
            logger.error(f"获取仓位信息失败: {e}")
            raise ExchangeError(f"获取仓位信息失败: {e}")

    async def set_leverage(self, leverage: int, symbol: str) -> bool:
        """设置杠杆 - 增强版本，处理算法订单冲突"""
        logger.info(f"[Enhanced set_leverage] 开始设置杠杆: {leverage}x for {symbol}")
        try:
            # 首先尝试直接设置杠杆
            await self.exchange.set_leverage(leverage, symbol)
            logger.info(f"[Enhanced set_leverage] 杠杆设置成功: {leverage}x")
            return True
        except Exception as e:
            error_msg = str(e)
            error_lower = error_msg.lower()

            # 添加详细日志用于调试
            logger.info(f"杠杆设置失败详情: {error_msg}")
            logger.info(f"错误码分析: code=59669 在错误中: {'59669' in error_msg}")
            logger.info(
                f"算法订单关键词检测: {'cancel cross-margin tp/sl' in error_lower}"
            )

            # 检查是否是因为存在算法订单导致的错误
            # OKX错误码59669表示存在活跃的算法订单
            if "59669" in error_msg or any(
                keyword in error_lower
                for keyword in [
                    "cancel cross-margin tp/sl",
                    "trailing, trigger, and chase orders",
                    "stop bots before adjusting your leverage",
                    "cancel.*orders.*before.*adjusting.*leverage",
                ]
            ):
                logger.warning(f"设置杠杆失败，存在活跃算法订单: {e}")
                logger.info("尝试取消算法订单后重新设置杠杆...")

                # 保存现有算法订单
                saved_orders = await self._save_and_cancel_algo_orders(symbol)

                try:
                    # 再次尝试设置杠杆
                    await self.exchange.set_leverage(leverage, symbol)
                    logger.info(f"杠杆设置成功: {leverage}x")

                    # 恢复算法订单
                    if saved_orders:
                        logger.info(f"正在恢复 {len(saved_orders)} 个算法订单...")
                        await self._restore_algo_orders(symbol, saved_orders)

                    return True
                except Exception as retry_error:
                    logger.error(f"重试设置杠杆失败: {retry_error}")
                    return False

            # 检查是否是已存在订单或设置的错误
            elif any(
                keyword in error_lower
                for keyword in ["already exist", "已存在", "duplicate", "重复"]
            ):
                logger.info(f"杠杆设置已存在，无需重复设置: {e}")
                return True  # 视为成功，因为杠杆已经设置
            else:
                logger.error(f"设置杠杆失败: {e}")
                return False

    async def _save_and_cancel_algo_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """保存并取消算法订单"""
        try:
            # 转换符号格式
            inst_id = symbol.replace("/USDT:USDT", "-USDT-SWAP").replace("/", "-")
            logger.info(
                f"[_save_and_cancel_algo_orders] 转换符号: {symbol} -> {inst_id}"
            )

            # 获取当前算法订单
            algo_orders = await self.exchange.private_get_trade_orders_algo_pending(
                {"instId": inst_id, "ordType": "trigger"}
            )

            orders_data = algo_orders.get("data", [])
            if not orders_data:
                return []

            logger.info(f"发现 {len(orders_data)} 个活跃算法订单，正在取消...")

            # 取消所有算法订单
            cancel_params = [
                {"algoId": order["algoId"], "instId": order["instId"]}
                for order in orders_data
            ]
            await self.exchange.private_post_trade_cancel_algos(cancel_params)

            logger.info(f"已取消 {len(orders_data)} 个算法订单")
            return orders_data

        except Exception as e:
            logger.error(f"保存并取消算法订单失败: {e}")
            return []

    async def _restore_algo_orders(
        self, symbol: str, orders: List[Dict[str, Any]]
    ) -> None:
        """恢复算法订单"""
        try:
            for order in orders:
                try:
                    # 重新创建算法订单
                    params = {
                        "instId": order["instId"],
                        "triggerPx": order["triggerPx"],
                        "orderPx": order["ordPx"],
                        "triggerPxType": order.get("triggerPxType", "last"),
                        "tdMode": order["tdMode"],
                        "ordType": order["ordType"],
                        "side": order["side"],
                        "sz": order["sz"],
                    }

                    await self.exchange.private_post_trade_order_algo(params)
                    logger.info(f"恢复算法订单成功: {order['algoId']}")

                except Exception as restore_error:
                    logger.error(
                        f"恢复单个算法订单失败 {order['algoId']}: {restore_error}"
                    )

        except Exception as e:
            logger.error(f"恢复算法订单过程失败: {e}")

    async def fetch_ohlcv(
        self, symbol: str, timeframe: str = "5m", limit: int = 100
    ) -> List[List[float]]:
        """获取K线数据 - 增强版（支持本地缓存和增量更新）"""
        try:
            # 添加参数验证
            if not symbol or not timeframe:
                raise ValueError("symbol和timeframe不能为空")

            # 导入持久化管理器
            from ..data.kline_persistence import get_kline_manager

            kline_manager = get_kline_manager()

            # OKX 交易所单次请求最多返回 300 根 K 线
            MAX_PER_REQUEST = 300
            MAX_TOTAL = 3000  # 最多获取 3000 根 ≈ 10 天

            # 1. 尝试从本地加载历史数据
            local_klines, metadata = kline_manager.load_klines(symbol, timeframe)
            last_local_timestamp = local_klines[-1][0] if local_klines else 0

            # 2. 判断获取策略
            need_fetch = False
            force_full_fetch = False  # 是否强制全量获取

            if not local_klines:
                # 没有本地数据，全量获取
                need_fetch = True
                force_full_fetch = True
            elif len(local_klines) < limit:
                # 本地数据不足，获取完整历史数据
                need_fetch = True
                force_full_fetch = True
            elif metadata:
                # 检查本地数据是否过期（超过 5 分钟）
                last_update = datetime.fromisoformat(metadata.last_update)
                if (datetime.now() - last_update).total_seconds() >= 300:
                    need_fetch = True
                else:
                    need_fetch = False
            else:
                # 没有元数据，保守起见获取新数据
                need_fetch = True

            ohlcv = []

            if need_fetch:
                # 3. 从交易所获取数据
                if force_full_fetch or not local_klines:
                    # 分批获取完整历史数据（OKX 单次最多 300 根）
                    all_klines = []
                    remaining = limit
                    since = None  # 从最新往历史获取

                    while remaining > 0 and len(all_klines) < limit:
                        request_count = min(remaining, MAX_PER_REQUEST)
                        batch = await self.exchange.fetch_ohlcv(
                            symbol, timeframe, limit=request_count, since=since
                        )

                        if not batch:
                            break

                        all_klines.extend(batch)
                        remaining -= len(batch)

                        # 更新 since 为下一批请求的时间戳（往历史方向）
                        since = batch[0][0] - 1

                        logger.info(
                            f"📥 分批获取历史 K 线: 已获取 {len(all_klines)} 根, 还需 {remaining} 根"
                        )

                        await asyncio.sleep(0.1)

                    ohlcv = all_klines
                    if ohlcv:
                        logger.info(f"📥 全量获取完成: {len(ohlcv)} 根 K 线数据")
                else:
                    # 增量获取：先获取少量最新K线，找到新数据的起始点
                    recent_klines = await self.exchange.fetch_ohlcv(
                        symbol, timeframe, limit=min(limit, 100)
                    )

                    if not recent_klines:
                        # API 返回空，使用本地数据
                        ohlcv = local_klines[-limit:] if limit else local_klines
                        logger.warning(
                            f"⚠️ API 返回空数据，使用本地缓存: {len(ohlcv)} 根"
                        )
                    else:
                        # 找到新数据的起始位置（时间戳 > 最后一条本地数据）
                        new_start_idx = 0
                        for i, k in enumerate(recent_klines):
                            if k[0] > last_local_timestamp:
                                new_start_idx = i
                                break

                        # 新数据从 new_start_idx 开始
                        new_klines = recent_klines[new_start_idx:]

                        if new_klines:
                            # 合并本地数据和新数据
                            ohlcv = local_klines + new_klines
                            # 限制数量，保留最近的 limit 条
                            if len(ohlcv) > limit:
                                ohlcv = ohlcv[-limit:]
                            logger.info(
                                f"📥 增量更新: 本地 {len(local_klines)} 根 + 新增 {len(new_klines)} 根 = {len(ohlcv)} 根"
                            )
                        else:
                            # 没有新数据，使用本地数据
                            ohlcv = local_klines[-limit:] if limit else local_klines
                            logger.info(
                                f"📂 无新K线数据，使用本地缓存: {len(ohlcv)} 根"
                            )

                # 4. 保存到本地
                if ohlcv:
                    kline_manager.save_klines(symbol, timeframe, ohlcv)

                # 过滤和截取
                if len(ohlcv) > limit:
                    ohlcv = ohlcv[-limit:]

            # 5. 验证返回数据
            if not ohlcv or not isinstance(ohlcv, list):
                logger.warning(f"获取到空的K线数据: {symbol}, {timeframe}")
                return []

            # 验证数据格式（跳过 open_time[1]，因为它是字符串）
            valid_candles = []
            for candle in ohlcv:
                if isinstance(candle, list) and len(candle) >= 6:
                    # 验证时间戳[0]和价格数据[2-5]（跳过 open_time[1]）
                    if (
                        isinstance(candle[0], int)  # timestamp
                        and isinstance(candle[2], (int, float))  # open_price
                        and isinstance(candle[3], (int, float))  # high_price
                        and isinstance(candle[4], (int, float))  # low_price
                        and isinstance(candle[5], (int, float))  # close_price
                    ):
                        valid_candles.append(candle)
                    else:
                        logger.warning(f"无效的K线数据格式: {candle}")
                else:
                    logger.warning(f"跳过无效的K线数据: {candle}")

            logger.info(
                f"成功获取 {len(valid_candles)}/{len(ohlcv)} 根K线数据: {symbol}, {timeframe}"
            )
            return valid_candles

        except ccxt.NetworkError as e:
            logger.error(f"网络错误导致K线数据获取失败: {e}")
            # 网络错误时返回空数据而不是抛出异常
            return []
        except ccxt.ExchangeError as e:
            logger.error(f"交易所错误导致K线数据获取失败: {e}")
            # 交易所错误时返回空数据
            return []
        except ccxt.RateLimitExceeded as e:
            logger.error(f"触发交易所限流: {e}")
            # 限流时返回空数据
            return []
        except Exception as e:
            logger.error(f"获取K线数据失败: {type(e).__name__}: {e}")
            # 其他异常返回空数据
            return []

    async def close(self) -> None:
        """关闭交易所连接"""
        try:
            if self.exchange:
                await self.exchange.close()
                logger.info("交易所连接已关闭")
        except Exception as e:
            logger.error(f"关闭交易所连接失败: {e}")
