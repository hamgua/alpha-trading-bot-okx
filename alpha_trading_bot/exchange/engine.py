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

                return {
                    'symbol': symbol,
                    'price': current_price,
                    'bid': current_price - 10,
                    'ask': current_price + 10,
                    'volume': random.uniform(100, 1000),
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
                # 获取最近100根15分钟K线
                ohlcv = await self.exchange_client.fetch_ohlcv(symbol, timeframe='15m', limit=100)
                if ohlcv and len(ohlcv) >= 50:
                    ohlcv_data = ohlcv
                    timestamps = [candle[0] for candle in ohlcv]
                    opens = [candle[1] for candle in ohlcv]
                    highs = [candle[2] for candle in ohlcv]
                    lows = [candle[3] for candle in ohlcv]
                    closes = [candle[4] for candle in ohlcv]
                    volumes = [candle[5] for candle in ohlcv]
            except Exception as e:
                logger.warning(f"获取OHLCV数据失败: {e}，将使用基础数据")

            return {
                'symbol': symbol,
                'price': ticker.last,
                'bid': ticker.bid,
                'ask': ticker.ask,
                'volume': ticker.volume,
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
                'last_kline_time': datetime.fromtimestamp(timestamps[-1]/1000).isoformat() if timestamps else ''
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