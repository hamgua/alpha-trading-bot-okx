"""
决策引擎模块

从 AdaptiveTradingBot 中提取的交易决策逻辑

增强功能：
- 风险收益比(R/R)门禁 - 按投资类型差异化
- 市场结构判断
- 交易员级仓位管理建议
- safe_mode减半开仓辅助条件

R/R 门禁阈值定义在 alpha_trading_bot.config.thresholds:
- RR_CONSERVATIVE_MIN (0.8)
- RR_MODERATE_MIN (1.0)
- RR_AGGRESSIVE_MIN (0.6)
- RR_GOOD_RATIO (2.0)
"""

import logging
import os
from typing import Any, Dict

from alpha_trading_bot.config.thresholds import (
    RR_CONSERVATIVE_MIN,
    RR_MODERATE_MIN,
    RR_AGGRESSIVE_MIN,
    RR_GOOD_RATIO,
)

logger = logging.getLogger(__name__)

# R/R比门禁阈值 - 按投资类型差异化
# 加密货币市场R/R<1.5很常见，原1.5过于严格
INVESTMENT_RR_THRESHOLDS = {
    "conservative": RR_CONSERVATIVE_MIN,
    "moderate": RR_MODERATE_MIN,
    "aggressive": RR_AGGRESSIVE_MIN,
}
DEFAULT_RR_THRESHOLD = RR_MODERATE_MIN
GOOD_RR_RATIO = RR_GOOD_RATIO


class DecisionEngine:
    """交易决策引擎"""

    def __init__(self, config: Any):
        self._config = config
        # 从配置中获取投资类型，决定R/R门禁阈值
        self._investment_type = self._detect_investment_type()
        self._min_rr = INVESTMENT_RR_THRESHOLDS.get(
            self._investment_type, DEFAULT_RR_THRESHOLD
        )
        logger.info(
            f"[决策引擎] 投资类型={self._investment_type}, "
            f"R/R最低阈值={self._min_rr}"
        )

    def _detect_investment_type(self) -> str:
        """检测投资类型（从环境变量读取）"""
        return os.getenv("INVESTMENT_TYPE", "moderate").lower()

    def _get_min_rr(self) -> float:
        """获取当前投资类型的最低R/R阈值"""
        return self._min_rr

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
            rr_ratio = market_data.get("risk_reward_ratio", 0)

            if is_downtrend and signal == "SHORT":
                logger.info("[安全] 下跌趋势中，安全模式允许 SHORT 信号")
            elif not has_position:
                # safe_mode + 上升趋势 + AI=BUY + 辅助条件: 允许减半仓位开仓
                # 辅助条件: R/R>=1.0 且 ATR<40%，确保收益覆盖风险且波动可控
                if (
                    trend_direction == "up"
                    and signal == "BUY"
                    and rr_ratio >= 1.0
                    and atr_percent < 0.40
                ):
                    logger.info(
                        "[安全] 安全模式+上升趋势+AI=BUY+R/R≥1.0+ATR<40%，"
                        "允许减半仓位开仓"
                    )
                    return {
                        "action": "open",
                        "reason": "安全模式减半开仓: 上升趋势+AI=BUY+R/R≥1.0+ATR<40%",
                        "confidence": selected.confidence * 0.5,
                        "strategy": "safe_mode_reduced",
                        "position_advice": "安全模式，建议半仓",
                    }
                elif trend_direction == "up" and signal == "BUY":
                    logger.info(
                        f"[安全] 安全模式+上升趋势+AI=BUY，但辅助条件不满足 "
                        f"(R/R={rr_ratio:.2f}, ATR={atr_percent * 100:.1f}%)，跳过"
                    )
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
            # BTC波动率40%在加密货币市场属于常见水平，不应做绝对禁止条件
            # 原0.40→0.55，避免在常见波动环境下过度保守
            if atr_percent > 0.55:
                logger.warning(
                    f"[高波动] ATR%={atr_percent * 100:.1f}% > 55%，高波动市场禁止开仓"
                )
                return {"action": "skip", "reason": "高波动市场禁止开仓",
                        "confidence": selected.confidence, "strategy": selected.strategy_type}

            # R/R比门禁：从integrator结果中获取
            rr_ratio = market_data.get("risk_reward_ratio", 0)
            market_structure = market_data.get("market_structure", "sideways")

            if rr_ratio > 0 and rr_ratio < self._get_min_rr():
                logger.warning(
                    f"[R/R门禁] R/R={rr_ratio:.2f} < {self._get_min_rr()}，风险收益比不足，禁止开仓"
                )
                return {"action": "skip",
                        "reason": f"R/R={rr_ratio:.2f}不足(最低{self._get_min_rr()})",
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
            elif rr_ratio >= self._get_min_rr():
                position_advice = f"R/R={rr_ratio:.2f}勉强，建议减仓"

            result = {"action": "open", "reason": "AI信号买入",
                      "confidence": selected.confidence, "strategy": selected.strategy_type}
            if position_advice:
                result["position_advice"] = position_advice
            return result

        # SHORT 信号处理
        if signal == "SHORT":
            if atr_percent > 0.55:
                logger.warning(
                    f"[高波动] ATR%={atr_percent * 100:.1f}% > 55%，高波动市场禁止做空"
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
            if atr_percent > 0.55:
                logger.warning(
                    f"[高波动] ATR%={atr_percent * 100:.1f}% > 55%，HOLD信号下完全停仓"
                )
                return {"action": "skip",
                        "reason": f"AI-HOLD+高波动停仓(ATR={atr_percent * 100:.1f}%)",
                        "confidence": selected.confidence, "strategy": selected.strategy_type}
            if selected.signal.upper() == "HOLD":
                # 检查市场结构做空方向 - 结构方向为short且R/R优秀时，允许覆盖AI-HOLD做空
                market_structure_direction = market_data.get("market_structure_direction", "none")
                rr_ratio = market_data.get("risk_reward_ratio", 0)
                if (
                    market_structure_direction == "short"
                    and rr_ratio >= GOOD_RR_RATIO
                    and atr_percent < 0.55
                    and rsi > 40
                    and not has_position
                    and self._config.trading.allow_short_selling
                ):
                    logger.info(
                        f"[决策] 市场结构SHORT(R/R={rr_ratio:.2f})覆盖AI-HOLD"
                    )
                    return {"action": "sell", "reason": f"市场结构做空(R/R={rr_ratio:.2f})覆盖AI-HOLD",
                            "confidence": 0.75, "strategy": "market_structure_short",
                            "position_advice": f"R/R={rr_ratio:.2f}优秀，市场结构做空"}
                return {"action": "skip", "reason": "AI和策略都是HOLD",
                        "confidence": selected.confidence, "strategy": selected.strategy_type}
            # 策略信号与AI-HOLD冲突：高置信度策略BUY可覆盖AI-HOLD
            market_structure = market_data.get("market_structure", "sideways")
            if (
                selected.signal.upper() == "BUY"
                and selected.confidence >= 0.80
                and market_structure != "bearish"
            ):
                logger.info(
                    f"[决策] 策略BUY(置信度{selected.confidence:.0%})覆盖AI-HOLD"
                )
                result = {
                    "action": "open",
                    "reason": f"策略BUY覆盖AI-HOLD(置信度{selected.confidence:.0%})",
                    "confidence": selected.confidence * 0.8,  # 降权20%作为保守处理
                    "strategy": selected.strategy_type,
                }
                rr_ratio = market_data.get("risk_reward_ratio", 0)
                if rr_ratio >= GOOD_RR_RATIO:
                    result["position_advice"] = f"R/R={rr_ratio:.2f}良好，正常仓位"
                elif rr_ratio >= self._get_min_rr():
                    result["position_advice"] = f"R/R={rr_ratio:.2f}勉强，建议减仓"
                return result
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
