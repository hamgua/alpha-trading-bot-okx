"""
市场状态管理器 - 整合市场环境检测和表现追踪

职责：
- 市场状态检测（高波动、趋势、震荡等）
- 交易表现追踪
- 市场环境变化通知
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class MarketState:
    """市场状态"""

    regime: str = "unknown"
    trend_direction: str = "neutral"
    trend_strength: float = 0.0
    volatility: str = "normal"
    rsi: float = 50.0
    atr_percent: float = 0.0
    adx: float = 0.0
    bb_position: float = 0.5
    last_update: str = ""


class MarketRegimeManager:
    """市场状态管理器

    整合 MarketRegimeDetector 和 PerformanceTracker，
    提供统一的市场状态查询接口。
    """

    def __init__(self) -> None:
        from alpha_trading_bot.ai.adaptive import (
            MarketRegimeDetector,
            PerformanceTracker,
        )

        self._regime_detector = MarketRegimeDetector()
        self._performance_tracker = PerformanceTracker()
        self._current_state = MarketState()
        logger.info("[MarketRegimeManager] 初始化完成")

    def detect_market_regime(self, market_data: Dict[str, Any]) -> str:
        """检测市场状态

        Args:
            market_data: 市场数据字典

        Returns:
            市场状态字符串 (high_volatility, trending, ranging, normal)
        """
        regime = self._regime_detector.detect(market_data)
        self._current_state.regime = regime

        technical = market_data.get("technical", {})
        self._current_state.rsi = technical.get("rsi", 50)
        self._current_state.trend_direction = technical.get(
            "trend_direction", "neutral"
        )
        self._current_state.trend_strength = technical.get("trend_strength", 0)
        self._current_state.atr_percent = technical.get("atr_percent", 0)
        self._current_state.adx = technical.get("adx", 0)
        self._current_state.bb_position = technical.get("bb_position", 0.5)

        return regime

    def get_market_state(self) -> MarketState:
        """获取当前市场状态"""
        return self._current_state

    def track_performance(self, trade_result: Dict[str, Any]) -> None:
        """追踪交易表现

        Args:
            trade_result: 交易结果字典
        """
        self._performance_tracker.record_trade(trade_result)

    def get_performance_summary(self) -> Dict[str, Any]:
        """获取表现摘要"""
        return self._performance_tracker.get_summary()

    def is_high_volatility(self) -> bool:
        """判断是否高波动市场"""
        return self._current_state.regime == "high_volatility"

    def is_trending(self) -> bool:
        """判断是否趋势市场"""
        return self._current_state.trend_strength > 0.2

    def should_reduce_position(self) -> bool:
        """是否应该降低仓位"""
        return self.is_high_volatility() or self._current_state.rsi > 75
