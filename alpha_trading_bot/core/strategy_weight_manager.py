"""策略权重管理模块

从 AdaptiveTradingBot 中提取的策略权重更新逻辑
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class StrategyWeightManager:
    """策略权重管理器"""

    def __init__(
        self,
        strategy_library: Any,
        simple_learning: Any,
    ):
        self._strategy_library = strategy_library
        self._simple_learning = simple_learning

    def update_strategy_weights(self, trade: Any) -> None:
        """根据交易结果更新策略权重（学习闭环）"""
        if not trade:
            return

        if trade.outcome.value == "win":
            performance_score = min(1.0, 0.5 + (trade.pnl_percent or 0) * 10)
        else:
            performance_score = max(0.0, 0.5 - abs(trade.pnl_percent or 0) * 5)

        strategy_type = trade.signal_type
        if strategy_type in ["buy", "sell"]:
            for strategy in self._strategy_library.strategies.values():
                if strategy.strategy_type.value == f"{strategy_type}_following":
                    strategy.update_weight(performance_score)
                    logger.info(
                        f"[学习] 更新{strategy.name}权重: {strategy.weight:.2f} "
                        f"(得分: {performance_score:.2f})"
                    )
                    break

        try:
            if hasattr(trade, "signal_type"):
                provider = getattr(trade, "signal_provider", "unknown")
                confidence = getattr(trade, "confidence", 0.5)
                outcome = trade.outcome.value
                pnl = trade.pnl_percent or 0

                self._simple_learning.online_update(
                    provider=provider,
                    confidence=confidence,
                    outcome=outcome,
                    pnl_percent=pnl,
                )
                logger.info(f"[学习] 在线学习更新完成: {provider}")
        except Exception as e:
            logger.warning(f"[学习] 在线学习更新失败: {e}")
