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
                    logger.info(f"准备设置杠杆: {self.config.leverage}x for {self.config.symbol}")
                    logger.info(f"当前配置: exchange={self.config.exchange}, symbol={self.config.symbol}, leverage={self.config.leverage}")
                    success = await self.set_leverage(self.config.leverage, self.config.symbol)
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
                    volume=random.uniform(100, 1000)
                )

            ticker = await self.exchange.fetch_ticker(symbol)

            # 添加调试日志，查看实际获取的ticker数据
            logger.info(f"从交易所获取的ticker数据: symbol={symbol}, last={ticker.get('last')}, volume={ticker.get('volume')}, baseVolume={ticker.get('baseVolume')}")

            # OKX交易所的特殊处理：24小时成交量在baseVolume字段而不是volume字段
            volume = ticker.get('volume')
            if volume is None or volume == 0:
                volume = ticker.get('baseVolume', 0)
                if volume > 0:
                    logger.info(f"使用baseVolume作为成交量: {volume}")
                else:
                    logger.warning(f"交易所返回的成交量为0，symbol={symbol}")

            # Handle missing fields gracefully
            return TickerData(
                symbol=symbol,
                bid=ticker.get('bid', 0),
                ask=ticker.get('ask', 0),
                last=ticker.get('last', 0),
                high=ticker.get('high', 0),
                low=ticker.get('low', 0),
                volume=volume
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

            # 验证最小交易量
            if symbol in self.exchange.markets:
                market = self.exchange.markets[symbol]
                min_amount = market.get('limits', {}).get('amount', {}).get('min', 0)
                amount_precision = market.get('precision', {}).get('amount', 0)

                if min_amount and amount < min_amount:
                    logger.error(f"订单数量 {amount} 小于交易所最小交易量 {min_amount} for {symbol}")
                    return OrderResult(
                        success=False,
                        error_message=f"订单数量必须大于等于 {min_amount}"
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
                            logger.info(f"根据交易所精度({amount_precision})调整订单数量至: {amount} (倍数: {multiplier})")
                        else:
                            # 其他情况，按正常四舍五入处理
                            precision_int = int(amount_precision)
                            amount = round(amount, precision_int)
                            logger.info(f"根据交易所精度调整订单数量至: {amount}")
                    except (ValueError, TypeError):
                        # 如果精度无效，保持原数量
                        logger.warning(f"交易所精度格式无效: {amount_precision}，保持原数量: {amount}")

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
            # 简化日志 - 只在有仓位时显示关键信息
            positions = await self.exchange.fetch_positions([symbol] if symbol else None)

            if positions and len(positions) > 0:
                # 只记录简要信息
                for pos in positions:
                    if pos.get('contracts', 0) != 0:  # 有实际仓位
                        logger.info(f"获取仓位: {pos.get('symbol', 'unknown')} {pos.get('side', 'unknown')} {pos.get('contracts', 0)} 张")
            else:
                logger.debug(f"未获取到仓位信息: {symbol}")

            # 如果没有指定符号，返回所有仓位
            if not symbol:
                return positions

            # 如果指定了符号，过滤出指定符号的仓位
            filtered_positions = [pos for pos in positions if pos.get('symbol') == symbol]
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
            logger.info(f"算法订单关键词检测: {'cancel cross-margin tp/sl' in error_lower}")

            # 检查是否是因为存在算法订单导致的错误
            # OKX错误码59669表示存在活跃的算法订单
            if '59669' in error_msg or any(keyword in error_lower for keyword in [
                'cancel cross-margin tp/sl',
                'trailing, trigger, and chase orders',
                'stop bots before adjusting your leverage',
                'cancel.*orders.*before.*adjusting.*leverage'
            ]):
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
            elif any(keyword in error_lower for keyword in ['already exist', '已存在', 'duplicate', '重复']):
                logger.info(f"杠杆设置已存在，无需重复设置: {e}")
                return True  # 视为成功，因为杠杆已经设置
            else:
                logger.error(f"设置杠杆失败: {e}")
                return False

    async def _save_and_cancel_algo_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """保存并取消算法订单"""
        try:
            # 转换符号格式
            inst_id = symbol.replace('/USDT:USDT', '-USDT-SWAP').replace('/', '-')
            logger.info(f"[_save_and_cancel_algo_orders] 转换符号: {symbol} -> {inst_id}")

            # 获取当前算法订单
            algo_orders = await self.exchange.private_get_trade_orders_algo_pending({
                'instId': inst_id,
                'ordType': 'trigger'
            })

            orders_data = algo_orders.get('data', [])
            if not orders_data:
                return []

            logger.info(f"发现 {len(orders_data)} 个活跃算法订单，正在取消...")

            # 取消所有算法订单
            cancel_params = [{'algoId': order['algoId'], 'instId': order['instId']} for order in orders_data]
            await self.exchange.private_post_trade_cancel_algos(cancel_params)

            logger.info(f"已取消 {len(orders_data)} 个算法订单")
            return orders_data

        except Exception as e:
            logger.error(f"保存并取消算法订单失败: {e}")
            return []

    async def _restore_algo_orders(self, symbol: str, orders: List[Dict[str, Any]]) -> None:
        """恢复算法订单"""
        try:
            for order in orders:
                try:
                    # 重新创建算法订单
                    params = {
                        'instId': order['instId'],
                        'triggerPx': order['triggerPx'],
                        'orderPx': order['ordPx'],
                        'triggerPxType': order.get('triggerPxType', 'last'),
                        'tdMode': order['tdMode'],
                        'ordType': order['ordType'],
                        'side': order['side'],
                        'sz': order['sz']
                    }

                    await self.exchange.private_post_trade_order_algo(params)
                    logger.info(f"恢复算法订单成功: {order['algoId']}")

                except Exception as restore_error:
                    logger.error(f"恢复单个算法订单失败 {order['algoId']}: {restore_error}")

        except Exception as e:
            logger.error(f"恢复算法订单过程失败: {e}")

    async def fetch_ohlcv(self, symbol: str, timeframe: str = '5m', limit: int = 100) -> List[List[float]]:
        """获取K线数据 - 增强版"""
        try:
            # 添加参数验证
            if not symbol or not timeframe:
                raise ValueError("symbol和timeframe不能为空")

            # 限制请求数量，避免交易所限流
            limit = min(limit, 200)

            # 尝试获取数据
            ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

            # 验证返回数据
            if not ohlcv or not isinstance(ohlcv, list):
                logger.warning(f"获取到空的K线数据: {symbol}, {timeframe}")
                return []

            # 验证数据格式
            valid_candles = []
            for candle in ohlcv:
                if isinstance(candle, list) and len(candle) >= 6:
                    # 验证时间戳和价格数据
                    if all(isinstance(x, (int, float)) for x in candle[:6]):
                        valid_candles.append(candle)
                    else:
                        logger.warning(f"无效的K线数据格式: {candle}")
                else:
                    logger.warning(f"跳过无效的K线数据: {candle}")

            logger.info(f"成功获取 {len(valid_candles)}/{len(ohlcv)} 根K线数据: {symbol}, {timeframe}")
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