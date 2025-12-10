"""
交易机器人主类
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass

from .base import BaseComponent, BaseConfig
from .exceptions import TradingBotException

@dataclass
class BotConfig(BaseConfig):
    """机器人配置"""
    trading_enabled: bool = True
    max_position_size: float = 0.01
    leverage: int = 10
    test_mode: bool = True
    cycle_interval: int = 15  # 分钟

class TradingBot(BaseComponent):
    """交易机器人主类"""

    def __init__(self, config: Optional[BotConfig] = None):
        """初始化交易机器人"""
        super().__init__(config or BotConfig(name="AlphaTradingBot"))
        self.logger = logging.getLogger(__name__)
        self._running = False
        self._start_time = None

    async def initialize(self) -> bool:
        """初始化机器人"""
        try:
            self.logger.info("正在初始化交易机器人...")

            # 初始化交易引擎
            from ..exchange import TradingEngine
            self.trading_engine = TradingEngine()
            await self.trading_engine.initialize()

            # 初始化策略管理器
            from ..strategies import StrategyManager
            self.strategy_manager = StrategyManager()
            await self.strategy_manager.initialize()

            # 初始化风控管理器
            from ..exchange.trading import RiskManager
            self.risk_manager = RiskManager()
            await self.risk_manager.initialize()

            self._initialized = True
            self.logger.info("交易机器人初始化成功")
            return True

        except Exception as e:
            self.logger.error(f"初始化失败: {e}")
            return False

    async def cleanup(self) -> None:
        """清理资源"""
        if hasattr(self, 'trading_engine'):
            await self.trading_engine.cleanup()
        if hasattr(self, 'strategy_manager'):
            await self.strategy_manager.cleanup()
        if hasattr(self, 'risk_manager'):
            await self.risk_manager.cleanup()

    async def start(self) -> None:
        """启动机器人"""
        if not self._initialized:
            raise TradingBotException("机器人未初始化")

        self._running = True
        self._start_time = datetime.now()
        self.logger.info("交易机器人已启动")

        try:
            while self._running:
                # 执行一次交易循环
                await self._trading_cycle()

                # 等待下一个周期
                await asyncio.sleep(self.config.cycle_interval * 60)

        except Exception as e:
            self.logger.error(f"交易循环异常: {e}")
            raise

    async def stop(self) -> None:
        """停止机器人"""
        self._running = False
        self.logger.info("交易机器人已停止")

    async def _trading_cycle(self) -> None:
        """执行一次交易循环"""
        try:
            # 1. 获取市场数据
            market_data = await self.trading_engine.get_market_data()

            # 2. 生成交易信号
            signals = await self.strategy_manager.generate_signals(market_data)

            # 3. 风险评估
            risk_assessment = await self.risk_manager.assess_risk(signals)

            # 4. 执行交易
            if risk_assessment.can_trade:
                await self.trading_engine.execute_trades(risk_assessment.trades)

            # 5. 更新状态
            await self._update_status()

        except Exception as e:
            self.logger.error(f"交易循环执行失败: {e}")

    async def _update_status(self) -> None:
        """更新机器人状态"""
        # 这里可以添加状态更新逻辑
        pass

    def get_status(self) -> Dict[str, Any]:
        """获取机器人状态"""
        status = super().get_status()
        status.update({
            'running': self._running,
            'start_time': self._start_time.isoformat() if self._start_time else None,
            'uptime': self.get_uptime(),
            'trades_executed': getattr(self, 'trade_count', 0),
            'profit_loss': getattr(self, 'total_pnl', 0.0)
        })
        return status