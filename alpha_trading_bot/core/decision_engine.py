"""决策引擎模块

从 AdaptiveTradingBot 中提取的交易决策逻辑

增强功能：
- 风险收益比(R/R)门禁
- 市场结构判断
- 交易员级仓位管理建议
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# R/R比门禁阈值
MIN_RR_RATIO = 1.5  # 最低可接受R/R比
GOOD_RR_RATIO = 2.0  # 良好R/R比


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
        signal = ai_signal.upper()
        technical = market_data.get("technical", {})
        has_position = market_data.get("has_position", False)
        atr_percent = technical.get("atr_percent", 0)
        rsi = technical.get("rsi", 50)

        # 安全模式处理
        is_safe_mode = (
            selected.strategy_type == "safe_mode"
            or "safe_mode" in selected.strategy_type
        )
        if is_safe_mode:
            trend_direction = technical.get("trend_direction", "neutral")
            is_downtrend = trend_direction == "down"

            if is_downtrend and signal == "SHORT":
                logger.info("[安全] 下跌趋势中，安全模式允许 SHORT 信号")
            elif not has_position:
                logger.info("[安全] 安全模式触发，但无持仓，跳过降低仓位")
                return {
                    "action": "skip",
                    "reason": "安全模式: 无持仓无需降低",
                    "confidence": selected.confidence,
                    "strategy": "safe_mode",
                }
            else:
                logger.warning(f"[安全] 安全模式触发，降低仓位: {selected.reasons}")
                return {
                    "action": "reduce",
                    "reason": f"安全模式降低仓位: {selected.reasons}",
                    "confidence": selected.confidence * 0.5,
                    "strategy": "safe_mode",
                }

        # BUY 信号处理
        if signal == "BUY":
            if atr_percent > 0.40:
                logger.warning(
                    f"[高波动] ATR%={atr_percent * 100:.1f}% > 40%，高波动市场禁止开仓"
                )
                return {"action": "skip", "reason": "高波动市场禁止开仓",
                        "confidence": selected.confidence, "strategy": selected.strategy_type}

            # R/R比门禁：从integrator结果中获取
            rr_ratio = market_data.get("risk_reward_ratio", 0)
            market_structure = market_data.get("market_structure", "sideways")

            if rr_ratio > 0 and rr_ratio < MIN_RR_RATIO:
                logger.warning(
                    f"[R/R门禁] R/R={rr_ratio:.2f} < {MIN_RR_RATIO}，风险收益比不足，禁止开仓"
                )
                return {"action": "skip",
                        "reason": f"R/R={rr_ratio:.2f}不足(最低{MIN_RR_RATIO})",
                        "confidence": selected.confidence, "strategy": selected.strategy_type}

            # 市场结构判断：下跌结构中禁止做多
            if market_structure == "bearish":
                logger.warning(
                    f"[市场结构] 下跌结构中禁止做多"
                )
                return {"action": "skip", "reason": "市场结构为下跌，禁止做多",
                        "confidence": selected.confidence, "strategy": selected.strategy_type}

            # 仓位建议：基于R/R比
            position_advice = ""
            if rr_ratio >= GOOD_RR_RATIO:
                position_advice = f"R/R={rr_ratio:.2f}良好，正常仓位"
            elif rr_ratio >= MIN_RR_RATIO:
                position_advice = f"R/R={rr_ratio:.2f}勉强，建议减仓"

            result = {"action": "open", "reason": "AI信号买入",
                      "confidence": selected.confidence, "strategy": selected.strategy_type}
            if position_advice:
                result["position_advice"] = position_advice
            return result

        # SHORT 信号处理
        if signal == "SHORT":
            if atr_percent > 0.40:
                logger.warning(
                    f"[高波动] ATR%={atr_percent * 100:.1f}% > 40%，高波动市场禁止做空"
                )
                return {"action": "skip", "reason": "高波动市场禁止做空",
                        "confidence": selected.confidence, "strategy": selected.strategy_type}
            if rsi < 40:
                logger.warning(f"[RSI超卖] RSI={rsi:.1f} < 40，RSI超卖禁止做空")
                return {"action": "skip", "reason": "RSI超卖禁止做空",
                        "confidence": selected.confidence, "strategy": selected.strategy_type}
            if not has_position and self._config.trading.allow_short_selling:
                return {"action": "sell", "reason": "AI信号做空",
                        "confidence": selected.confidence, "strategy": selected.strategy_type}
            if has_position:
                return {"action": "close", "reason": "AI信号SHORT+有持仓，平仓",
                        "confidence": selected.confidence, "strategy": selected.strategy_type}
            return {"action": "skip", "reason": "禁止做空（未开启做空功能）",
                    "confidence": selected.confidence, "strategy": selected.strategy_type}

        # SELL 信号处理
        if signal == "SELL":
            if not has_position:
                return {"action": "skip", "reason": "SELL信号+无持仓，忽略",
                        "confidence": selected.confidence, "strategy": selected.strategy_type}
            if selected.signal.upper() == "SELL":
                return {"action": "close", "reason": "AI+策略共振卖出",
                        "confidence": selected.confidence, "strategy": selected.strategy_type}
            return {"action": "close", "reason": "AI信号卖出",
                    "confidence": selected.confidence, "strategy": selected.strategy_type}

        # HOLD 信号处理
        if signal == "HOLD":
            if atr_percent > 0.40:
                logger.warning(
                    f"[高波动] ATR%={atr_percent * 100:.1f}% > 40%，HOLD信号下完全停仓"
                )
                return {"action": "skip",
                        "reason": f"AI-HOLD+高波动停仓(ATR={atr_percent * 100:.1f}%)",
                        "confidence": selected.confidence, "strategy": selected.strategy_type}
            if selected.signal.upper() == "HOLD":
                return {"action": "skip", "reason": "AI和策略都是HOLD",
                        "confidence": selected.confidence, "strategy": selected.strategy_type}
            logger.warning(
                f"[决策] AI-HOLD但策略={selected.signal}，保守处理"
            )
            return {"action": "skip",
                    "reason": f"AI-HOLD覆盖策略({selected.signal})",
                    "confidence": selected.confidence, "strategy": selected.strategy_type}

        # 未知信号 - 使用策略信号
        if selected.signal.upper() != "HOLD":
            action = "open" if selected.signal.upper() == "BUY" else "close"
            return {"action": action, "reason": f"策略信号: {selected.signal}",
                    "confidence": selected.confidence, "strategy": selected.strategy_type}

        return {"action": "skip", "reason": "AI和策略都是HOLD",
                "confidence": selected.confidence, "strategy": selected.strategy_type}
