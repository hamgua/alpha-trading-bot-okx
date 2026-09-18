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
        """根据交易结果更新策略权重（学习闭环）

        dream 2026-09-16-loss-root-cause / R4 修复:
        1. 策略权重: 原来把 trade.signal_type ("buy"/"sell") 拼成
           "buy_following" 去匹配策略类型 (trend_following 等), 永不命中,
           策略权重从未被更新。现在按 trade.strategy_name (开仓时记录的
           实际决策策略) 匹配。
        2. 在线学习: 原来 getattr(trade, "signal_provider", "unknown")
           因字段不存在永远得到 "unknown"。现在 TradeRecord 带真实
           provider; 无信息时跳过, 不再污染 unknown 桶。
        """
        if not trade:
            return

        if trade.outcome.value == "win":
            performance_score = min(1.0, 0.5 + (trade.pnl_percent or 0) * 10)
        else:
            performance_score = max(0.0, 0.5 - abs(trade.pnl_percent or 0) * 5)

        # 按开仓时记录的实际策略名匹配并更新权重
        strategy_name = getattr(trade, "strategy_name", "") or ""
        if strategy_name:
            for strategy in self._strategy_library.strategies.values():
                if strategy.strategy_type.value == strategy_name:
                    strategy.update_weight(performance_score)
                    logger.info(
                        f"[学习] 更新{strategy.name}权重: {strategy.weight:.2f} "
                        f"(得分: {performance_score:.2f}, 结果: {trade.outcome.value}, "
                        f"PnL: {trade.pnl_percent or 0:+.2%})"
                    )
                    break

        # 在线学习: 仅在有真实 provider 信息时更新, 避免污染 unknown 桶
        provider = getattr(trade, "signal_provider", "") or ""
        if provider and provider != "unknown":
            try:
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
