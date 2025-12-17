"""
交易引擎主模块
整合所有交易组件，提供统一的交易接口
"""

import asyncio
import traceback
from typing import Dict, Any, List, Optional
from datetime import datetime
import logging
from dataclasses import dataclass

from ..core.base import BaseComponent, BaseConfig
from ..core.exceptions import TradingBotException
from .client import ExchangeClient
from .models import (
    OrderResult, PositionInfo, TradeResult, ExchangeConfig,
    OrderStatus, TradeSide, RiskAssessmentResult,
    MarketOrderRequest, LimitOrderRequest, TPSLRequest
)
from .trading import OrderManager, PositionManager, RiskManager, TradeExecutor

logger = logging.getLogger(__name__)

@dataclass
class TradingEngineConfig(BaseConfig):
    """交易引擎配置"""
    enable_trading: bool = True
    test_mode: bool = False
    max_daily_trades: int = 50
    enable_auto_close: bool = True
    trading_hours_only: bool = False

class TradingEngine(BaseComponent):
    """交易引擎主类"""

    def __init__(self, config: Optional[TradingEngineConfig] = None):
        # 如果没有提供配置，创建默认配置
        if config is None:
            config = TradingEngineConfig(name="TradingEngine")
        super().__init__(config)
        self.config = config

        # 创建组件实例
        self.exchange_client = ExchangeClient()
        self.order_manager = OrderManager(self.exchange_client)
        self.position_manager = PositionManager()
        self.risk_manager = RiskManager()
        self.trade_executor = TradeExecutor(
            self.exchange_client,
            self.order_manager,
            self.position_manager,
            self.risk_manager
        )

        # 状态管理
        self.is_trading_active = False
        self.daily_trade_count = 0
        self.last_trade_time = None
        self.engine_stats: Dict[str, Any] = {}

    async def initialize(self) -> bool:
        """初始化交易引擎"""
        try:
            logger.info(f"正在初始化交易引擎... 测试模式: {self.config.test_mode}")

            # 初始化数据管理器
            try:
                from ..data import create_data_manager
                self.data_manager = await create_data_manager()
                logger.info("数据管理器初始化成功")
            except Exception as e:
                logger.warning(f"数据管理器初始化失败: {e}，将继续运行但不保存历史数据")
                self.data_manager = None

            # 检查是否为测试模式
            if self.config.test_mode:
                logger.info("测试模式：跳过真实交易所初始化")
                # 初始化各组件（测试模式）
                await self.order_manager.initialize()
                await self.position_manager.initialize()
                await self.risk_manager.initialize()
                await self.trade_executor.initialize()

                self._initialized = True
                logger.info("交易引擎测试模式初始化成功")
                return True

            # 正常模式：初始化交易所客户端
            logger.info("正常模式：初始化交易所客户端")
            await self.exchange_client.initialize()

            # 初始化各组件
            await self.order_manager.initialize()
            await self.position_manager.initialize()
            await self.risk_manager.initialize()
            await self.trade_executor.initialize()

            self._initialized = True
            logger.info("交易引擎初始化成功")
            return True

        except Exception as e:
            logger.error(f"交易引擎初始化失败: {e}")
            logger.error(traceback.format_exc())
            return False

    async def cleanup(self) -> None:
        """清理资源"""
        if not self.config.test_mode:
            await self.exchange_client.cleanup()
        # 测试模式下不需要清理交易所客户端
        await self.order_manager.cleanup()
        await self.position_manager.cleanup()
        await self.risk_manager.cleanup()
        await self.trade_executor.cleanup()

    async def get_market_data(self, symbol: str = "BTC/USDT:USDT") -> Dict[str, Any]:
        """获取市场数据"""
        try:
            # 测试模式下使用模拟数据
            if self.config.test_mode:
                import random
                base_price = 50000.0
                price_variation = random.uniform(-0.01, 0.01)
                current_price = base_price * (1 + price_variation)

                # 生成模拟订单簿
                bids = []
                asks = []
                for i in range(10):
                    bid_price = current_price - (i + 1) * 10
                    ask_price = current_price + (i + 1) * 10
                    bid_volume = random.uniform(0.1, 1.0)
                    ask_volume = random.uniform(0.1, 1.0)
                    bids.append([bid_price, bid_volume])
                    asks.append([ask_price, ask_volume])

                # 生成模拟OHLCV数据
                ohlcv_data = []
                timestamps = []
                opens = []
                highs = []
                lows = []
                closes = []
                volumes = []

                # 生成100根15分钟K线数据
                for i in range(100):
                    timestamp = int(datetime.now().timestamp() * 1000) - (100 - i) * 15 * 60 * 1000
                    if i == 0:
                        open_price = base_price
                    else:
                        open_price = closes[-1]

                    # 生成随机波动
                    high_price = open_price * (1 + random.uniform(0, 0.01))
                    low_price = open_price * (1 - random.uniform(0, 0.01))
                    close_price = open_price * (1 + random.uniform(-0.005, 0.005))
                    volume = random.uniform(100, 1000)

                    ohlcv_data.append([timestamp, open_price, high_price, low_price, close_price, volume])
                    timestamps.append(timestamp)
                    opens.append(open_price)
                    highs.append(high_price)
                    lows.append(low_price)
                    closes.append(close_price)
                    volumes.append(volume)

                # 计算24小时平均成交量
                avg_volume_24h = sum(volumes) / len(volumes) if volumes else random.uniform(500, 2000)

                market_data = {
                    'symbol': symbol,
                    'price': current_price,
                    'bid': current_price - 10,
                    'ask': current_price + 10,
                    'volume': random.uniform(100, 1000),
                    'avg_volume_24h': avg_volume_24h,  # 添加24小时平均成交量
                    'high': current_price * 1.02,
                    'low': current_price * 0.98,
                    'timestamp': datetime.now(),
                    'orderbook': {
                        'bids': bids,  # 前10档买单
                        'asks': asks   # 前10档卖单
                    },
                    # 添加OHLCV数据（使用不同的键名避免冲突）
                    'ohlcv': ohlcv_data,
                    'timestamps': timestamps,
                    'open_prices': opens,
                    'high_prices': highs,
                    'low_prices': lows,
                    'close_prices': closes,
                    'volumes': volumes,
                    'period': '15m',
                    'change_percent': ((closes[-1] - closes[-2]) / closes[-2] * 100) if len(closes) >= 2 else 0,
                    'last_kline_time': datetime.fromtimestamp(timestamps[-1]/1000).isoformat() if timestamps else ''
                }

                # 保存市场数据快照
                if self.data_manager:
                    try:
                        market_snapshot = {
                            'symbol': symbol,
                            'price': current_price,
                            'bid': current_price - 10,
                            'ask': current_price + 10,
                            'volume': random.uniform(100, 1000),
                            'high': current_price * 1.02,
                            'low': current_price * 0.98,
                            'open': opens[-1] if opens else current_price,
                            'close': closes[-1] if closes else current_price,
                            'change_percent': ((closes[-1] - closes[-2]) / closes[-2] * 100) if len(closes) >= 2 else 0,
                            'market_state': 'normal'
                        }
                        await self.data_manager.save_market_data(market_snapshot)
                    except Exception as e:
                        logger.warning(f"保存市场数据失败: {e}")

                return market_data

            # 正常模式：从交易所获取真实数据
            ticker = await self.exchange_client.fetch_ticker(symbol)
            orderbook = await self.exchange_client.fetch_order_book(symbol)

            # 获取OHLCV数据用于技术指标计算
            ohlcv_data = []
            timestamps = []
            opens = []
            highs = []
            lows = []
            closes = []
            volumes = []

            try:
                # 获取多时间框架数据 - 增强版
                multi_timeframe_data = {}
                ohlcv_data = []
                timestamps = []
                opens = []
                highs = []
                lows = []
                closes = []
                volumes = []

                # 获取15分钟K线（主时间框架）- 使用增强的错误处理
                try:
                    ohlcv_15m = await self.exchange_client.fetch_ohlcv(symbol, timeframe='15m', limit=100)
                    if ohlcv_15m and len(ohlcv_15m) >= 50:
                        ohlcv_data = ohlcv_15m
                        timestamps = [candle[0] for candle in ohlcv_15m]
                        opens = [candle[1] for candle in ohlcv_15m]
                        highs = [candle[2] for candle in ohlcv_15m]
                        lows = [candle[3] for candle in ohlcv_15m]
                        closes = [candle[4] for candle in ohlcv_15m]
                        volumes = [candle[5] for candle in ohlcv_15m]
                        multi_timeframe_data['15m'] = ohlcv_15m
                        logger.info(f"成功获取15分钟K线数据: {len(ohlcv_15m)} 根")
                    else:
                        logger.warning(f"15分钟K线数据不足: {len(ohlcv_15m) if ohlcv_15m else 0} 根")
                except Exception as e:
                    logger.warning(f"获取15分钟K线数据失败: {type(e).__name__}: {e}")

                # 获取1小时K线（次要时间框架）- 即使失败也不影响主逻辑
                try:
                    ohlcv_1h = await self.exchange_client.fetch_ohlcv(symbol, timeframe='1h', limit=50)
                    if ohlcv_1h and len(ohlcv_1h) >= 20:
                        multi_timeframe_data['1h'] = ohlcv_1h
                        logger.info(f"成功获取1小时K线数据: {len(ohlcv_1h)} 根")
                    else:
                        logger.debug(f"1小时K线数据不足: {len(ohlcv_1h) if ohlcv_1h else 0} 根")
                except Exception as e:
                    logger.debug(f"获取1小时K线数据失败: {type(e).__name__}: {e}")

                # 获取4小时K线（长期时间框架）- 可选
                try:
                    ohlcv_4h = await self.exchange_client.fetch_ohlcv(symbol, timeframe='4h', limit=30)
                    if ohlcv_4h and len(ohlcv_4h) >= 15:
                        multi_timeframe_data['4h'] = ohlcv_4h
                        logger.info(f"成功获取4小时K线数据: {len(ohlcv_4h)} 根")
                    else:
                        logger.debug(f"4小时K线数据不足: {len(ohlcv_4h) if ohlcv_4h else 0} 根")
                except Exception as e:
                    logger.debug(f"获取4小时K线数据失败: {type(e).__name__}: {e}")

            except Exception as e:
                logger.warning(f"获取OHLCV数据失败: {type(e).__name__}: {e}，将使用基础数据")

            # 如果没有获取到K线数据，生成模拟数据用于技术指标计算
            if not ohlcv_data and ticker.last > 0:
                logger.info("使用基础价格数据生成模拟K线数据")
                base_price = float(ticker.last)
                current_time = int(datetime.now().timestamp() * 1000)

                # 生成100根模拟K线数据
                for i in range(100):
                    # 每根K线间隔15分钟
                    timestamp = current_time - (99 - i) * 15 * 60 * 1000
                    # 添加小幅随机波动
                    random_factor = 0.002  # 0.2%的波动
                    open_price = base_price * (1 + (i - 50) * random_factor / 50)
                    close_price = base_price * (1 + (i - 49) * random_factor / 50)
                    high_price = max(open_price, close_price) * (1 + random_factor)
                    low_price = min(open_price, close_price) * (1 - random_factor)
                    volume = float(ticker.volume) / 100 if ticker.volume else base_price * 0.1

                    candle = [timestamp, open_price, high_price, low_price, close_price, volume]
                    ohlcv_data.append(candle)
                    timestamps.append(timestamp)
                    opens.append(open_price)
                    highs.append(high_price)
                    lows.append(low_price)
                    closes.append(close_price)
                    volumes.append(volume)

                logger.info(f"生成了 {len(ohlcv_data)} 根模拟K线数据")

            # 计算24小时平均成交量 - 增强版
            avg_volume_24h = sum(volumes) / len(volumes) if volumes else (
                ticker.volume if ticker.volume and ticker.volume > 0 else
                (float(ticker.last) * 0.1 if ticker.last > 0 else 100)  # 备用估算
            )

            # 如果所有数据源都失败，使用备用方案
            if not volumes and not ticker.volume:
                logger.warning("无法获取成交量数据，使用价格估算")
                # 基于价格的保守估算
                estimated_volume = float(ticker.last) * 0.05 if ticker.last > 0 else 50
                volumes = [estimated_volume] * 20  # 生成20个周期的模拟数据
                avg_volume_24h = estimated_volume

            # 计算技术指标（即使没有完整K线数据）
            atr_value = 0
            if closes and len(closes) >= 2:
                # 简化的ATR计算
                atr_sum = 0
                for i in range(1, len(closes)):
                    high_low = highs[i] - lows[i]
                    high_close = abs(highs[i] - closes[i-1])
                    low_close = abs(lows[i] - closes[i-1])
                    atr_sum += max(high_low, high_close, low_close)
                atr_value = atr_sum / (len(closes) - 1) if len(closes) > 1 else 0
            else:
                # 使用价格百分比作为ATR估算
                atr_value = float(ticker.last) * 0.002 if ticker.last > 0 else 100

            # 计算ATR相关指标用于详细输出
            current_price = float(ticker.last) if ticker.last else 0
            atr_percentage = (atr_value / current_price * 100) if current_price > 0 else 0

            logger.info(f"市场数据汇总 - 价格: ${ticker.last}, 24h成交量: {ticker.volume}, "
                       f"平均成交量: {avg_volume_24h:.2f}, ATR: {atr_value:.2f}")

            # 详细ATR数据输出
            logger.info(f"📊 ATR详细数据:")
            logger.info(f"  📈 ATR绝对值: {atr_value:.2f} USDT")
            logger.info(f"  📊 ATR百分比: {atr_percentage:.2f}%")
            logger.info(f"  🎯 当前价格: ${current_price:.2f}")
            logger.info(f"  📏 24h最高价: ${ticker.high}")
            logger.info(f"  📏 24h最低价: ${ticker.low}")
            logger.info(f"  📐 24h价格区间: ${float(ticker.high) - float(ticker.low):.2f} USDT")
            logger.info(f"  💹 24h价格振幅: {((float(ticker.high) - float(ticker.low)) / current_price * 100):.2f}%")

            return {
                'symbol': symbol,
                'price': ticker.last,
                'bid': ticker.bid,
                'ask': ticker.ask,
                'volume': ticker.volume,
                'volume_24h': ticker.volume,  # 显式的24小时成交量字段
                'avg_volume_24h': avg_volume_24h,  # 计算的平均成交量
                'high': ticker.high,
                'low': ticker.low,
                'timestamp': datetime.now(),
                'orderbook': {
                    'bids': orderbook.bids[:10],  # 前10档买单
                    'asks': orderbook.asks[:10]   # 前10档卖单
                },
                # 添加OHLCV数据（使用不同的键名避免冲突）
                'ohlcv': ohlcv_data,
                'timestamps': timestamps,
                'open_prices': opens,
                'high_prices': highs,
                'low_prices': lows,
                'close_prices': closes,
                'volumes': volumes,
                'period': '15m',
                'change_percent': ((closes[-1] - closes[-2]) / closes[-2] * 100) if len(closes) >= 2 else 0,
                'last_kline_time': datetime.fromtimestamp(timestamps[-1]/1000).isoformat() if timestamps else '',
                # 多时间框架数据
                'multi_timeframe': multi_timeframe_data
            }
        except Exception as e:
            logger.error(f"获取市场数据失败: {e}")
            raise

    async def execute_trade(self, trade_request: Dict[str, Any]) -> TradeResult:
        """执行交易"""
        try:
            # 风险评估
            risk_result = await self.risk_manager.assess_trade_risk(trade_request)
            if not risk_result.can_execute:
                return TradeResult(
                    success=False,
                    error_message=f"风险评估未通过: {risk_result.reason}"
                )

            # 执行交易
            result = await self.trade_executor.execute_trade(trade_request)

            # 更新统计
            if result.success:
                self.daily_trade_count += 1
                self.last_trade_time = datetime.now()
                self.engine_stats['total_trades'] = self.engine_stats.get('total_trades', 0) + 1
                self.engine_stats['total_volume'] = self.engine_stats.get('total_volume', 0) + trade_request.get('amount', 0)

                # 保存交易记录到数据管理器
                if self.data_manager:
                    try:
                        trade_data = {
                            'symbol': trade_request.get('symbol', ''),
                            'side': trade_request.get('side', ''),
                            'price': result.price or trade_request.get('price', 0),
                            'amount': trade_request.get('amount', 0),
                            'cost': result.cost or trade_request.get('amount', 0) * (result.price or trade_request.get('price', 0)),
                            'fee': result.fee or 0,
                            'status': 'executed',
                            'order_id': result.order_id or '',
                            'signal_source': trade_request.get('signal_source', ''),
                            'signal_confidence': trade_request.get('confidence', 0),
                            'notes': f"交易执行成功 - {result.message or ''}"
                        }
                        await self.data_manager.save_trade(trade_data)
                    except Exception as e:
                        logger.warning(f"保存交易记录失败: {e}")

            return result

        except Exception as e:
            logger.error(f"执行交易失败: {e}")
            return TradeResult(
                success=False,
                error_message=str(e)
            )

    async def get_position(self, symbol: str = "BTC/USDT:USDT") -> Optional[PositionInfo]:
        """获取仓位信息"""
        return await self.position_manager.get_position(symbol)

    async def get_balance(self) -> Dict[str, Any]:
        """获取账户余额"""
        return await self.exchange_client.fetch_balance()

    async def close_position(self, symbol: str, amount: Optional[float] = None) -> TradeResult:
        """平仓"""
        position = await self.get_position(symbol)
        if not position:
            return TradeResult(
                success=False,
                error_message="没有找到仓位"
            )

        close_amount = amount or position.amount

        trade_request = {
            'symbol': symbol,
            'side': 'sell' if position.side == 'long' else 'buy',
            'amount': close_amount,
            'type': 'market',
            'reason': 'manual_close'
        }

        return await self.execute_trade(trade_request)

    def get_status(self) -> Dict[str, Any]:
        """获取引擎状态"""
        base_status = super().get_status()
        base_status.update({
            'is_trading_active': self.is_trading_active,
            'daily_trade_count': self.daily_trade_count,
            'last_trade_time': self.last_trade_time.isoformat() if self.last_trade_time else None,
            'engine_stats': self.engine_stats
        })
        return base_status

# 全局交易引擎实例
def create_trading_engine() -> TradingEngine:
    """创建交易引擎实例"""
    from ..config import load_config

    config_manager = load_config()

    # 创建交易引擎配置
    engine_config = TradingEngineConfig(
        name="AlphaTradingEngine",
        enable_trading=config_manager.trading.test_mode,
        test_mode=config_manager.trading.test_mode,
        max_daily_trades=config_manager.system.max_history_length,
        enable_auto_close=True,
        trading_hours_only=False
    )

    return TradingEngine(engine_config)