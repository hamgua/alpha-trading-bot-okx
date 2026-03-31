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
            logger.warning(f"[安全] 安全模式触发，降低仓位: {selected.reasons}")
            return {
                "action": "reduce",
                "reason": f"安全模式降低仓位: {selected.reasons}",
                "confidence": selected.confidence * 0.5,
                "strategy": "safe_mode",
            }
        if ai_signal.upper() == "BUY":
            atr_percent = technical.get("atr_percent", 0)
            if atr_percent > 0.40:
                logger.warning(
                    f"[高波动] ATR%={atr_percent * 100:.1f}% > 40%，高波动市场禁止开仓"
                )
                action = "skip"
                reason = "高波动市场禁止开仓"
            else:
                action = "open"
                reason = "AI信号买入"
        elif ai_signal.upper() == "SHORT":
            has_position = market_data.get("has_position", False)
            rsi = technical.get("rsi", 50)
            atr_percent = technical.get("atr_percent", 0)

            if atr_percent > 0.40:
                logger.warning(
                    f"[高波动] ATR%={atr_percent * 100:.1f}% > 40%，高波动市场禁止做空"
                )
                action = "skip"
                reason = "高波动市场禁止做空"
            elif rsi < 40:
                logger.warning(f"[RSI超卖] RSI={rsi:.1f} < 40，RSI超卖禁止做空")
                action = "skip"
                reason = "RSI超卖禁止做空"
            elif not has_position and self._config.trading.allow_short_selling:
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
            rsi = technical.get("rsi", 50)
            atr_percent = technical.get("atr_percent", 0)

            if ai_signal.upper() == "SHORT":
                if atr_percent > 0.40:
                    logger.warning(
                        f"[高波动] ATR%={atr_percent * 100:.1f}% > 40%，高波动市场禁止做空"
                    )
                    action = "skip"
                    reason = "高波动市场禁止做空"
                elif rsi < 40:
                    logger.warning(f"[RSI超卖] RSI={rsi:.1f} < 40，RSI超卖禁止做空")
                    action = "skip"
                    reason = "RSI超卖禁止做空"
                elif not has_position and self._config.trading.allow_short_selling:
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
            # AI 信号是 HOLD 时的处理
            if ai_signal.upper() == "HOLD":
                logger.info("[决策] AI信号为HOLD，检查是否需要跳过")
                # ATR > 40% 时完全停仓（atr_percent 是小数形式，0.40 = 40%）
                atr_percent = technical.get("atr_percent", 0)
                if atr_percent > 0.40:
                    logger.warning(
                        f"[高波动] ATR%={atr_percent * 100:.1f}% > 40%，HOLD信号下完全停仓"
                    )
                    action = "skip"
                    reason = f"AI-HOLD+高波动停仓(ATR={atr_percent * 100:.1f}%)"
                else:
                    # AI HOLD + 无明确策略信号 → skip
                    if selected.signal.upper() == "HOLD":
                        action = "skip"
                        reason = "AI和策略都是HOLD"
                    else:
                        # AI HOLD 但策略有信号 → 降级处理
                        logger.warning(
                            f"[决策] AI-HOLD但策略={selected.signal}，保守处理"
                        )
                        action = "skip"
                        reason = f"AI-HOLD覆盖策略({selected.signal})"
            elif selected.signal.upper() != "HOLD":
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
