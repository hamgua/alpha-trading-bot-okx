"""决策引擎模块

从 AdaptiveTradingBot 中提取的交易决策逻辑
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class DecisionEngine:
    """交易决策引擎"""

    def __init__(self, config: Any):
        self._config = config

    def make_decision(
        self,
        ai_signal: str,
        selected: Any,
        market_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """综合决策 - 融合AI信号和策略选择的结果"""
        is_safe_mode = (
            selected.strategy_type == "safe_mode"
            or "safe_mode" in selected.strategy_type
        )

        technical = market_data.get("technical", {})
        trend_direction = technical.get("trend_direction", "neutral")
        is_downtrend = trend_direction == "down"

        if is_safe_mode and is_downtrend and ai_signal.upper() == "SHORT":
            logger.info("[安全] 下跌趋势中，安全模式允许 SHORT 信号")
        elif is_safe_mode:
            logger.warning(f"[安全] 安全模式触发: {selected.reasons}")
            return {
                "action": "skip",
                "reason": f"安全模式强制暂停: {selected.reasons}",
                "confidence": 1.0,
                "strategy": "safe_mode",
            }
        if ai_signal.upper() == "BUY":
            action = "open"
            reason = "AI信号买入"
        elif ai_signal.upper() == "SHORT":
            has_position = market_data.get("has_position", False)

            if not has_position and self._config.trading.allow_short_selling:
                action = "sell"
                reason = "AI信号做空"
            elif has_position:
                action = "close"
                reason = "AI信号SHORT+有持仓，平仓"
            else:
                action = "skip"
                reason = "禁止做空（未开启做空功能）"
        elif ai_signal.upper() == "SELL":
            has_position = market_data.get("has_position", False)

            if not has_position:
                action = "skip"
                reason = "SELL信号+无持仓，忽略"
            else:
                if selected.signal.upper() == "SELL":
                    action = "close"
                    reason = "AI+策略共振卖出"
                else:
                    action = "close"
                    reason = "AI信号卖出"
        elif ai_signal.upper() in ["SELL", "SHORT"]:
            has_position = market_data.get("has_position", False)

            if ai_signal.upper() == "SHORT":
                if not has_position and self._config.trading.allow_short_selling:
                    action = "sell"
                    reason = "AI信号做空"
                elif has_position:
                    action = "close"
                    reason = "AI信号平仓"
                else:
                    action = "skip"
                    reason = "禁止做空"
            elif ai_signal.upper() == "SELL":
                if selected.signal.upper() == "SELL":
                    action = "close"
                    reason = "AI+策略共振卖出"
                else:
                    action = "close"
                    reason = "AI信号卖出"

        else:
            if selected.signal.upper() != "HOLD":
                action = "open" if selected.signal.upper() == "BUY" else "close"
                reason = f"策略信号: {selected.signal}"
            else:
                action = "skip"
                reason = "AI和策略都是HOLD"

        return {
            "action": action,
            "reason": reason,
            "confidence": selected.confidence,
            "strategy": selected.strategy_type,
        }
