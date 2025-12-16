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
from .models import ExchangeConfig, TickerData, OrderBookData, BalanceData, OrderResult, OrderStatus, TradeSide

logger = logging.getLogger(__name__)

def retry_on_network_error(max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """网络错误重试装饰器"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except (ccxt.NetworkError, ccxt.RequestTimeout, ccxt.ExchangeNotAvailable) as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(f"网络错误 (尝试 {attempt + 1}/{max_retries + 1}): {e}，{current_delay}秒后重试")
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
                    margin_mode=config_manager.trading.margin_mode
                )
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
                margin_mode=config_manager.trading.margin_mode
            )

            # 获取网络配置
            network_config = config_manager.network

            # 创建交易所实例
            exchange_class = getattr(ccxt, self.config.exchange)

            # 构建交易所配置
            exchange_config = {
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
                'timeout': network_config.timeout * 1000  # CCXT uses milliseconds
            }

            # 根据代理开关添加代理配置
            if network_config.proxy_enabled:
                logger.info(f"代理已启用，正在配置代理...")
                if network_config.http_proxy:
                    exchange_config['aiohttp_proxy'] = network_config.http_proxy
                    exchange_config['proxy'] = network_config.http_proxy
                    logger.info(f"使用HTTP代理: {network_config.http_proxy}")
                elif network_config.https_proxy:
                    exchange_config['aiohttp_proxy'] = network_config.https_proxy
                    exchange_config['proxy'] = network_config.https_proxy
                    logger.info(f"使用HTTPS代理: {network_config.https_proxy}")
                else:
                    logger.warning("代理已启用但未配置代理地址")
            else:
                logger.info("代理未启用")

            logger.info(f"正在创建交易所实例: {self.config.exchange}, sandbox: {self.config.sandbox}, timeout: {network_config.timeout}s")
            self.exchange = exchange_class(exchange_config)

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
                    volume=random.uniform(100, 1000)
                )

            ticker = await self.exchange.fetch_ticker(symbol)

            # Handle missing fields gracefully
            return TickerData(
                symbol=symbol,
                bid=ticker.get('bid', 0),
                ask=ticker.get('ask', 0),
                last=ticker.get('last', 0),
                high=ticker.get('high', 0),
                low=ticker.get('low', 0),
                volume=ticker.get('volume', 0)
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

                return OrderBookData(
                    symbol=symbol,
                    bids=bids,
                    asks=asks
                )

            orderbook = await self.exchange.fetch_order_book(symbol, limit)
            return OrderBookData(
                symbol=symbol,
                bids=orderbook['bids'],
                asks=orderbook['asks']
            )
        except Exception as e:
            logger.error(f"获取订单簿数据失败: {e}")
            raise ExchangeError(f"获取订单簿数据失败: {e}")

    @retry_on_network_error(max_retries=3, delay=1.0)
    async def fetch_balance(self) -> BalanceData:
        """获取账户余额"""
        try:
            # 测试模式返回模拟数据
            if self._test_mode:
                return BalanceData(
                    total=10000.0,
                    free=9000.0,
                    used=1000.0,
                    currency='USDT'
                )

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

            # 测试模式返回模拟订单
            if self._test_mode:
                import uuid
                order_id = str(uuid.uuid4())
                client_order_id = params.get('clientOrderId', str(uuid.uuid4()))

                # 模拟市价单立即成交
                if type_ == 'market':
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
                    filled_amount=filled_amount,
                    average_price=50000.0,
                    status=status
                )

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
            logger.info(f"正在获取仓位信息，符号: {symbol}")
            positions = await self.exchange.fetch_positions([symbol] if symbol else None)
            logger.info(f"获取到的原始仓位数据: {positions}")

            # 如果没有指定符号，返回所有仓位
            if not symbol:
                return positions

            # 如果指定了符号，过滤出指定符号的仓位
            filtered_positions = [pos for pos in positions if pos.get('symbol') == symbol]
            logger.info(f"过滤后的仓位数据: {filtered_positions}")
            return filtered_positions
        except Exception as e:
            logger.error(f"获取仓位信息失败: {e}")
            raise ExchangeError(f"获取仓位信息失败: {e}")

    async def set_leverage(self, leverage: int, symbol: str) -> bool:
        """设置杠杆"""
        try:
            await self.exchange.set_leverage(leverage, symbol)
            return True
        except Exception as e:
            error_msg = str(e).lower()
            # 检查是否是已存在订单或设置的错误
            if any(keyword in error_msg for keyword in ['already exist', '已存在', 'duplicate', '重复']):
                logger.info(f"杠杆设置已存在，无需重复设置: {e}")
                return True  # 视为成功，因为杠杆已经设置
            else:
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