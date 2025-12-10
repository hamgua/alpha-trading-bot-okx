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
        super().__init__(config or TradingEngineConfig())
        self.config = config or TradingEngineConfig()

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
            logger.info("正在初始化交易引擎...")

            # 初始化交易所客户端
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
        await self.exchange_client.cleanup()
        await self.order_manager.cleanup()
        await self.position_manager.cleanup()
        await self.risk_manager.cleanup()
        await self.trade_executor.cleanup()

    async def get_market_data(self, symbol: str = "BTC/USDT:USDT") -> Dict[str, Any]:
        """获取市场数据"""
        try:
            ticker = await self.exchange_client.fetch_ticker(symbol)
            orderbook = await self.exchange_client.fetch_order_book(symbol)

            return {
                'symbol': symbol,
                'price': ticker['last'],
                'bid': ticker['bid'],
                'ask': ticker['ask'],
                'volume': ticker['volume'],
                'high': ticker['high'],
                'low': ticker['low'],
                'timestamp': datetime.now(),
                'orderbook': {
                    'bids': orderbook['bids'][:10],  # 前10档买单
                    'asks': orderbook['asks'][:10]   # 前10档卖单
                }
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