"""
策略执行管理器 - 整合策略库和策略选择

职责：
- 策略库管理
- 根据市场状态选择合适策略
- 策略权重动态调整
"""

import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class StrategyExecutionManager:
    """策略执行管理器

    整合 StrategyLibrary 和 AdaptiveStrategyManager，
    提供策略选择和执行接口。
    """

    def __init__(self) -> None:
        from ..ai.adaptive.strategy_library import StrategyLibrary
        from ..ai.adaptive.strategy_selector import AdaptiveStrategyManager

        self._strategy_library = StrategyLibrary()
        self._strategy_manager = AdaptiveStrategyManager()
        self._current_strategy: Optional[str] = None
        logger.info("[StrategyExecutionManager] 初始化完成")

    def select_strategy(self, market_state: Dict[str, Any]) -> str:
        """根据市场状态选择策略

        Args:
            market_state: 市场状态字典

        Returns:
            选中的策略名称
        """
        regime = market_state.get("regime", "normal")
        trend = market_state.get("trend_direction", "neutral")
        rsi = market_state.get("rsi", 50)

        if regime == "high_volatility":
            strategy = "safe_mode"
        elif trend == "up" and rsi < 70:
            strategy = "trend_following"
        elif trend == "down" and rsi > 30:
            strategy = "mean_reversion"
        elif regime == "ranging":
            strategy = "breakout"
        else:
            strategy = self._strategy_manager.select_best()

        self._current_strategy = strategy
        return strategy

    def get_strategy_weight(self, strategy_name: str) -> float:
        """获取策略权重

        Args:
            strategy_name: 策略名称

        Returns:
            策略权重 (0.0-1.0)
        """
        return self._strategy_library.get_weight(strategy_name)

    def update_strategy_weight(self, strategy_name: str, weight: float) -> None:
        """更新策略权重

        Args:
            strategy_name: 策略名称
            weight: 新权重
        """
        self._strategy_library.update_weight(strategy_name, weight)
        logger.info(f"[策略权重] {strategy_name}: {weight}")

    def get_enabled_strategies(self) -> List[str]:
        """获取已启用的策略列表"""
        return self._strategy_library.get_enabled_strategies()

    def get_current_strategy(self) -> Optional[str]:
        """获取当前策略"""
        return self._current_strategy

    def get_strategy_info(self, strategy_name: str) -> Dict[str, Any]:
        """获取策略信息"""
        return {
            "name": strategy_name,
            "weight": self.get_strategy_weight(strategy_name),
            "enabled": strategy_name in self.get_enabled_strategies(),
        }
