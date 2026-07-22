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
from numbers import Number
from typing import Any, Dict

from alpha_trading_bot.config.thresholds import (
    RR_CONSERVATIVE_MIN,
    RR_MODERATE_MIN,
    RR_AGGRESSIVE_MIN,
    RR_GOOD_RATIO,
    RR_SHORT_CONSERVATIVE_MIN,
    RR_SHORT_MODERATE_MIN,
    RR_SHORT_AGGRESSIVE_MIN,
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
MAX_TRADE_ATR_PERCENT = 0.55
SHORT_RSI_OVERSOLD_BLOCK = 40
SAFE_MODE_REDUCED_MIN_RR = 1.0
SAFE_MODE_REDUCED_MAX_ATR = 0.40
HOLD_STRATEGY_BUY_MIN_CONFIDENCE = 0.80
HOLD_STRATEGY_SHORT_MIN_CONFIDENCE = 0.75
# SELL覆盖AI-HOLD最低置信度（均值回归超买信号）
HOLD_STRATEGY_SELL_MIN_CONFIDENCE = 0.75
MARKET_STRUCTURE_LONG_MIN_CONFIDENCE = 0.72
MARKET_STRUCTURE_LONG_MIN_RR = 2.0
MARKET_STRUCTURE_LONG_MIN_TREND = 0.70
MARKET_STRUCTURE_LONG_MAX_RSI = 68
MARKET_STRUCTURE_SHORT_MIN_RR = 3.0
MARKET_STRUCTURE_SHORT_MIN_TREND = 0.25
BEARISH_STRUCTURE_SHORT_MIN_RR = 3.0
BEARISH_STRUCTURE_SHORT_MIN_TREND = 0.25
BEARISH_STRUCTURE_SHORT_MIN_CONFIDENCE = 0.60
MEAN_REVERSION_SHORT_MIN_RR = 3.0
MEAN_REVERSION_SHORT_MIN_RSI = 78

OVERSOLD_BUY_RSI_THRESHOLD = 30
OVERSOLD_BUY_MIN_RR = 1.0
STRATEGY_BUY_OVERRIDE_MIN_RR = 1.0

# 做空专用 R/R 门禁阈值 - 加密货币做空R/R天然偏低
SHORT_RR_THRESHOLDS = {
    "conservative": RR_SHORT_CONSERVATIVE_MIN,
    "moderate": RR_SHORT_MODERATE_MIN,
    "aggressive": RR_SHORT_AGGRESSIVE_MIN,
}
DEFAULT_SHORT_RR_THRESHOLD = RR_SHORT_MODERATE_MIN


class DecisionEngine:
    """交易决策引擎"""

    def __init__(self, config: Any):
        self._config = config
        # 从配置中获取投资类型，决定R/R门禁阈值
        self._investment_type = self._detect_investment_type()
        self._min_rr = INVESTMENT_RR_THRESHOLDS.get(
            self._investment_type, DEFAULT_RR_THRESHOLD
        )
        self._conflict_metrics: Dict[str, int] = {
            "ai_hold_strategy_buy_conservative_skip": 0,
            "ai_hold_oversold_buy_executed": 0,
            "ai_hold_strategy_buy_executed": 0,
            "market_structure_long_executed": 0,
            "market_structure_short_executed": 0,
        }
        self._oversold_metrics: Dict[str, int] = {
            "oversold_signal_total": 0,
            "oversold_signal_executed": 0,
            "oversold_signal_blocked_position": 0,
            "oversold_signal_blocked_rr": 0,
            "oversold_signal_blocked_atr": 0,
            "oversold_signal_blocked_confidence": 0,
        }
        logger.info(
            f"[决策引擎] 投资类型={self._investment_type}, "
            f"R/R最低阈值={self._min_rr}"
        )

    def get_conflict_metrics(self) -> Dict[str, int]:
        """返回 AI/策略冲突相关的决策指标快照。"""
        return dict(self._conflict_metrics)

    def get_oversold_metrics(self) -> Dict[str, int]:
        """返回均值回归超卖信号相关的指标快照。"""
        return dict(self._oversold_metrics)

    def _detect_investment_type(self) -> str:
        """检测投资类型（从环境变量读取）"""
        return os.getenv("INVESTMENT_TYPE", "moderate").lower()

    def _get_min_rr(self) -> float:
        """获取当前投资类型的最低R/R阈值"""
        return self._min_rr

    def _get_short_min_rr(self) -> float:
        """获取当前投资类型的最低做空R/R阈值（比做多更宽松）"""
        return SHORT_RR_THRESHOLDS.get(
            self._investment_type, DEFAULT_SHORT_RR_THRESHOLD
        )

    def _confidence_gate(
        self, side: str, selected: Any, market_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """最终执行前置信度门禁。"""
        configured_threshold = getattr(
            getattr(self._config, "ai", None), "fusion_threshold", 0.5
        )
        if not isinstance(configured_threshold, Number):
            configured_threshold = 0.5
        min_confidence = market_data.get("min_trade_confidence", configured_threshold)
        final_confidence = market_data.get(
            "ai_final_confidence",
            market_data.get("final_confidence", selected.confidence),
        )
        if (
            side == "short"
            and self._is_confirmed_mean_reversion_short(selected, market_data)
        ):
            final_confidence = max(final_confidence, selected.confidence)
        if (
            side == "long"
            and market_data.get("is_high_risk", False)
            and final_confidence < max(min_confidence, 0.55)
        ):
            return {
                "action": "skip",
                "reason": (
                    f"BTC高位风险且置信度不足({final_confidence:.0%})，禁止开多"
                ),
                "confidence": final_confidence,
                "strategy": selected.strategy_type,
            }

        if final_confidence < min_confidence:
            return {
                "action": "skip",
                "reason": (
                    f"最终置信度{final_confidence:.0%}低于阈值{min_confidence:.0%}"
                ),
                "confidence": final_confidence,
                "strategy": selected.strategy_type,
            }

        return {}

    def _is_confirmed_mean_reversion_short(
        self, selected: Any, market_data: Dict[str, Any]
    ) -> bool:
        """确认后的均值回归空头可使用策略置信度穿过门禁。"""
        technical = market_data.get("technical", {})
        return (
            selected.strategy_type == "mean_reversion"
            and selected.signal.upper() == "SELL"
            and selected.confidence >= HOLD_STRATEGY_SELL_MIN_CONFIDENCE
            and self._get_short_rr(market_data) >= MEAN_REVERSION_SHORT_MIN_RR
            and technical.get("atr_percent", 0) < MAX_TRADE_ATR_PERCENT
            and technical.get("rsi", 50) >= MEAN_REVERSION_SHORT_MIN_RSI
            and self._has_mean_reversion_confirmation(
                "short", market_data, technical
            )
        )

    def _get_short_rr(self, market_data: Dict[str, Any]) -> float:
        """获取做空专用 R/R，避免复用做多方向的风险收益比。"""
        short_rr = market_data.get("short_risk_reward_ratio")
        if isinstance(short_rr, Number) and short_rr > 0:
            return float(short_rr)

        structure_direction = market_data.get("market_structure_direction")
        market_structure = market_data.get("market_structure")
        if structure_direction == "short" or market_structure == "bearish":
            rr_ratio = market_data.get("risk_reward_ratio", 0)
            if isinstance(rr_ratio, Number) and rr_ratio > 0:
                return float(rr_ratio)
        return 0.0

    @staticmethod
    def _position_side(market_data: Dict[str, Any]) -> str:
        """返回标准化持仓方向。"""
        side = str(market_data.get("position_side", "") or "").lower()
        if side in {"long", "short"}:
            return side
        return ""

    def _position_aware_signal_decision(
        self, signal: str, selected: Any, market_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """已有持仓时按持仓方向解释交易信号。"""
        if not market_data.get("has_position", False):
            return {}

        position_side = self._position_side(market_data)
        if not position_side:
            return {}

        normalized_signal = signal.upper()
        if normalized_signal == "BUY":
            if position_side == "short":
                return {
                    "action": "close",
                    "reason": "BUY信号与空仓反向，平空",
                    "confidence": selected.confidence,
                    "strategy": selected.strategy_type,
                }
            return {
                "action": "skip",
                "reason": "多仓同向BUY，继续持有",
                "confidence": selected.confidence,
                "strategy": selected.strategy_type,
            }

        if normalized_signal in {"SELL", "SHORT"}:
            if position_side == "long":
                return {
                    "action": "close",
                    "reason": f"{normalized_signal}信号与多仓反向，平多",
                    "confidence": selected.confidence,
                    "strategy": selected.strategy_type,
                }
            return {
                "action": "skip",
                "reason": f"空仓同向{normalized_signal}，继续持有",
                "confidence": selected.confidence,
                "strategy": selected.strategy_type,
            }

        return {}

    def _has_mean_reversion_confirmation(
        self, side: str, market_data: Dict[str, Any], technical: Dict[str, Any]
    ) -> bool:
        """均值回归只在出现反转/拒绝确认后覆盖 AI-HOLD。"""
        if market_data.get("mean_reversion_confirmed") is True:
            return True
        if technical.get("reversal_confirmed") is True:
            return True

        macd_hist = technical.get("macd_hist", 0)
        if side == "long":
            has_rebound = bool(technical.get("rsi_rebounding"))
            has_price_reclaim = bool(
                technical.get("price_above_short_ma")
                or technical.get("price_above_vwap")
                or technical.get("bullish_reversal_candle")
            )
            return has_rebound and (has_price_reclaim or macd_hist > 0)

        has_rejection = bool(technical.get("rsi_falling"))
        has_price_reject = bool(
            technical.get("price_below_short_ma")
            or technical.get("price_below_vwap")
            or technical.get("bearish_reversal_candle")
        )
        return has_rejection and (has_price_reject or macd_hist < 0)

    def _has_short_pullback_confirmation(
        self, market_data: Dict[str, Any], technical: Dict[str, Any]
    ) -> bool:
        """确认空头方向，避免在高位震荡上行中仅凭 R/R 开空。"""
        if market_data.get("market_structure_direction") == "short":
            return True
        return self._has_mean_reversion_confirmation("short", market_data, technical)

    def _make_safe_mode_decision(
        self,
        signal: str,
        selected: Any,
        technical: Dict[str, Any],
        has_position: bool,
        atr_percent: float,
    ) -> Dict[str, Any]:
        """处理 safe_mode 策略，保持原有分支顺序。"""
        trend_direction = technical.get("trend_direction", "neutral")
        is_downtrend = trend_direction == "down"
        rr_ratio = technical.get("risk_reward_ratio", 0)

        if is_downtrend and signal == "SHORT":
            if has_position:
                logger.warning("[安全] 下跌趋势SHORT+有持仓，降低仓位")
                return {
                    "action": "reduce",
                    "reason": "安全模式+下跌趋势+SHORT: 降低仓位",
                    "confidence": selected.confidence * 0.5,
                    "strategy": "safe_mode",
                }
            logger.info("[安全] 下跌趋势中，安全模式允许 SHORT 信号")
            return {}
        if not has_position:
            if (
                trend_direction == "up"
                and signal == "BUY"
                and rr_ratio >= SAFE_MODE_REDUCED_MIN_RR
                and atr_percent < SAFE_MODE_REDUCED_MAX_ATR
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

        logger.warning(f"[安全] 安全模式触发，降低仓位: {selected.reasons}")
        return {
            "action": "reduce",
            "reason": f"安全模式降低仓位: {selected.reasons}",
            "confidence": selected.confidence * 0.5,
            "strategy": "safe_mode",
        }

    def _make_buy_decision(
        self,
        selected: Any,
        market_data: Dict[str, Any],
        atr_percent: float,
    ) -> Dict[str, Any]:
        """处理 BUY 信号分支。"""
        confidence_block = self._confidence_gate("long", selected, market_data)
        if confidence_block:
            return confidence_block

        if atr_percent > MAX_TRADE_ATR_PERCENT:
            logger.warning(
                f"[高波动] ATR%={atr_percent * 100:.1f}% > 55%，高波动市场禁止开仓"
            )
            return {
                "action": "skip",
                "reason": "高波动市场禁止开仓",
                "confidence": selected.confidence,
                "strategy": selected.strategy_type,
            }

        rr_ratio = market_data.get("risk_reward_ratio", 0)
        market_structure = market_data.get("market_structure", "sideways")

        if rr_ratio > 0 and rr_ratio < self._get_min_rr():
            logger.warning(
                f"[R/R门禁] R/R={rr_ratio:.2f} < {self._get_min_rr()}，风险收益比不足，禁止开仓"
            )
            return {
                "action": "skip",
                "reason": f"R/R={rr_ratio:.2f}不足(最低{self._get_min_rr()})",
                "confidence": selected.confidence,
                "strategy": selected.strategy_type,
            }

        if market_structure == "bearish":
            logger.warning(f"[市场结构] 下跌结构中禁止做多")
            return {
                "action": "skip",
                "reason": "市场结构为下跌，禁止做多",
                "confidence": selected.confidence,
                "strategy": selected.strategy_type,
            }

        position_advice = ""
        if rr_ratio >= GOOD_RR_RATIO:
            position_advice = f"R/R={rr_ratio:.2f}良好，正常仓位"
        elif rr_ratio >= self._get_min_rr():
            position_advice = f"R/R={rr_ratio:.2f}勉强，建议减仓"

        result = {
            "action": "open",
            "reason": "AI信号买入",
            "confidence": selected.confidence,
            "strategy": selected.strategy_type,
        }
        if position_advice:
            result["position_advice"] = position_advice
        return result

    def _make_low_confidence_buy_counter_short_decision(
        self, selected: Any, market_data: Dict[str, Any], has_position: bool
    ) -> Dict[str, Any]:
        """AI BUY 被风险降权时，让已确认的超买做空策略接管。"""
        if has_position or not self._config.trading.allow_short_selling:
            return {}
        if not self._is_confirmed_mean_reversion_short(selected, market_data):
            return {}

        configured_threshold = getattr(
            getattr(self._config, "ai", None), "fusion_threshold", 0.5
        )
        if not isinstance(configured_threshold, Number):
            configured_threshold = 0.5
        min_confidence = market_data.get("min_trade_confidence", configured_threshold)
        final_confidence = market_data.get(
            "ai_final_confidence", market_data.get("final_confidence", 0)
        )
        long_rr = market_data.get("risk_reward_ratio", 0)
        if (
            final_confidence >= min_confidence
            and long_rr >= self._get_min_rr()
            and not market_data.get("is_high_risk", False)
        ):
            return {}

        market_structure = market_data.get("market_structure", "sideways")
        market_direction = market_data.get("market_structure_direction", "none")
        if market_structure == "bullish" and market_direction != "short":
            return {}

        short_rr = self._get_short_rr(market_data)
        logger.info(
            "[决策] AI-BUY低置信度，策略SELL确认超买回落接管，"
            f"短R/R={short_rr:.2f}"
        )
        return {
            "action": "sell",
            "reason": (
                "AI-BUY低置信度，策略SELL确认超买回落做空"
                f"(置信度{selected.confidence:.0%}, 短R/R={short_rr:.2f})"
            ),
            "confidence": selected.confidence * 0.75,
            "strategy": "mean_reversion_short_rr_override",
            "position_advice": f"短R/R={short_rr:.2f}优秀，轻仓做空",
            "metadata": {
                "ai_low_confidence_buy_counter_short": True,
                "ai_hold_override_type": "mean_reversion_short_rr_override",
            },
        }

    def _make_short_decision(
        self,
        selected: Any,
        market_data: Dict[str, Any],
        atr_percent: float,
        rsi: float,
        has_position: bool,
    ) -> Dict[str, Any]:
        """处理 SHORT 信号分支。"""
        position_decision = self._position_aware_signal_decision(
            "SHORT", selected, market_data
        )
        if position_decision:
            return position_decision

        confidence_block = self._confidence_gate("short", selected, market_data)
        if confidence_block:
            return confidence_block

        if atr_percent > MAX_TRADE_ATR_PERCENT:
            logger.warning(
                f"[高波动] ATR%={atr_percent * 100:.1f}% > 55%，高波动市场禁止做空"
            )
            return {
                "action": "skip",
                "reason": "高波动市场禁止做空",
                "confidence": selected.confidence,
                "strategy": selected.strategy_type,
            }
        if rsi < SHORT_RSI_OVERSOLD_BLOCK:
            logger.warning(f"[RSI超卖] RSI={rsi:.1f} < 40，RSI超卖禁止做空")
            return {
                "action": "skip",
                "reason": "RSI超卖禁止做空",
                "confidence": selected.confidence,
                "strategy": selected.strategy_type,
            }

        short_min_rr = self._get_short_min_rr()
        rr_ratio = self._get_short_rr(market_data)
        if rr_ratio > 0 and rr_ratio < short_min_rr:
            logger.warning(
                f"[短R/R门禁] 做空R/R={rr_ratio:.2f} < {short_min_rr}，风险收益比不足"
            )
            return {
                "action": "skip",
                "reason": f"做空R/R={rr_ratio:.2f}不足(短R/R阈值{short_min_rr})",
                "confidence": selected.confidence,
                "strategy": selected.strategy_type,
            }
        if not has_position and self._config.trading.allow_short_selling:
            return {
                "action": "sell",
                "reason": "AI信号做空",
                "confidence": selected.confidence,
                "strategy": selected.strategy_type,
            }
        if has_position:
            return {
                "action": "close",
                "reason": "AI信号SHORT+有持仓，平仓",
                "confidence": selected.confidence,
                "strategy": selected.strategy_type,
            }
        return {
            "action": "skip",
            "reason": "禁止做空（未开启做空功能）",
            "confidence": selected.confidence,
            "strategy": selected.strategy_type,
        }

    def _make_hold_decision(
        self,
        selected: Any,
        market_data: Dict[str, Any],
        technical: Dict[str, Any],
        atr_percent: float,
        rsi: float,
        has_position: bool,
    ) -> Dict[str, Any]:
        """处理 HOLD 信号分支。"""
        if atr_percent > MAX_TRADE_ATR_PERCENT:
            logger.warning(
                f"[高波动] ATR%={atr_percent * 100:.1f}% > 55%，HOLD信号下完全停仓"
            )
            return {
                "action": "skip",
                "reason": f"AI-HOLD+高波动停仓(ATR={atr_percent * 100:.1f}%)",
                "confidence": selected.confidence,
                "strategy": selected.strategy_type,
            }
        if selected.signal.upper() == "HOLD":
            market_structure_direction = market_data.get(
                "market_structure_direction", "none"
            )
            market_structure = market_data.get("market_structure", "sideways")
            long_rr_ratio = market_data.get("risk_reward_ratio", 0)
            rr_ratio = self._get_short_rr(market_data)
            trend_strength = technical.get("trend_strength", 0)
            if (
                market_structure_direction == "long"
                and market_structure == "bullish"
                and selected.confidence >= MARKET_STRUCTURE_LONG_MIN_CONFIDENCE
                and long_rr_ratio >= MARKET_STRUCTURE_LONG_MIN_RR
                and trend_strength >= MARKET_STRUCTURE_LONG_MIN_TREND
                and atr_percent < MAX_TRADE_ATR_PERCENT
                and rsi < MARKET_STRUCTURE_LONG_MAX_RSI
                and not has_position
            ):
                confidence_block = self._confidence_gate("long", selected, market_data)
                if confidence_block:
                    return confidence_block
                logger.info(
                    f"[决策] 市场结构LONG(R/R={long_rr_ratio:.2f})覆盖AI-HOLD"
                )
                self._conflict_metrics["market_structure_long_executed"] += 1
                return {
                    "action": "open",
                    "reason": f"市场结构做多(R/R={long_rr_ratio:.2f})覆盖AI-HOLD",
                    "confidence": min(max(selected.confidence, 0.72), 0.78),
                    "strategy": "market_structure_long",
                    "position_advice": f"R/R={long_rr_ratio:.2f}优秀，市场结构做多",
                }
            if (
                market_structure_direction == "short"
                and rr_ratio >= MARKET_STRUCTURE_SHORT_MIN_RR
                and trend_strength >= MARKET_STRUCTURE_SHORT_MIN_TREND
                and atr_percent < MAX_TRADE_ATR_PERCENT
                and rsi > SHORT_RSI_OVERSOLD_BLOCK
                and not has_position
                and self._config.trading.allow_short_selling
            ):
                confidence_block = self._confidence_gate("short", selected, market_data)
                if confidence_block:
                    return confidence_block
                logger.info(f"[决策] 市场结构SHORT(R/R={rr_ratio:.2f})覆盖AI-HOLD")
                self._conflict_metrics["market_structure_short_executed"] += 1
                return {
                    "action": "sell",
                    "reason": f"市场结构做空(R/R={rr_ratio:.2f})覆盖AI-HOLD",
                    "confidence": 0.75,
                    "strategy": "market_structure_short",
                    "position_advice": f"R/R={rr_ratio:.2f}优秀，市场结构做空",
                }
            if (
                market_structure == "bearish"
                and rr_ratio >= BEARISH_STRUCTURE_SHORT_MIN_RR
                and trend_strength >= BEARISH_STRUCTURE_SHORT_MIN_TREND
                and selected.confidence >= BEARISH_STRUCTURE_SHORT_MIN_CONFIDENCE
                and self._has_short_pullback_confirmation(market_data, technical)
                and atr_percent < MAX_TRADE_ATR_PERCENT
                and rsi > SHORT_RSI_OVERSOLD_BLOCK
                and not has_position
                and self._config.trading.allow_short_selling
            ):
                confidence_block = self._confidence_gate("short", selected, market_data)
                if confidence_block:
                    return confidence_block
                logger.info(
                    f"[决策] 下跌结构SHORT(R/R={rr_ratio:.2f})覆盖AI-HOLD"
                )
                self._conflict_metrics["market_structure_short_executed"] += 1
                return {
                    "action": "sell",
                    "reason": f"下跌结构做空(R/R={rr_ratio:.2f})覆盖AI-HOLD",
                    "confidence": min(max(selected.confidence, 0.70), 0.75),
                    "strategy": "bearish_structure_short",
                    "position_advice": f"短R/R={rr_ratio:.2f}，下跌结构轻仓做空",
                }
            return {
                "action": "skip",
                "reason": "AI和策略都是HOLD",
                "confidence": selected.confidence,
                "strategy": selected.strategy_type,
            }

        position_decision = self._position_aware_signal_decision(
            selected.signal, selected, market_data
        )
        if position_decision:
            return position_decision

        market_structure = market_data.get("market_structure", "sideways")
        rr_ratio = market_data.get("risk_reward_ratio", 0)
        short_rr_ratio = self._get_short_rr(market_data)
        if (
            selected.strategy_type == "mean_reversion"
            and selected.signal.upper() == "BUY"
        ):
            self._oversold_metrics["oversold_signal_total"] += 1
            if has_position:
                self._oversold_metrics["oversold_signal_blocked_position"] += 1
            elif rsi >= OVERSOLD_BUY_RSI_THRESHOLD:
                pass
            elif rr_ratio < OVERSOLD_BUY_MIN_RR:
                self._oversold_metrics["oversold_signal_blocked_rr"] += 1
            elif atr_percent >= MAX_TRADE_ATR_PERCENT:
                self._oversold_metrics["oversold_signal_blocked_atr"] += 1
            elif not self._has_mean_reversion_confirmation(
                "long", market_data, technical
            ):
                self._oversold_metrics.setdefault(
                    "oversold_signal_blocked_confirmation", 0
                )
                self._oversold_metrics["oversold_signal_blocked_confirmation"] += 1
        if (
            selected.strategy_type == "mean_reversion"
            and selected.signal.upper() == "BUY"
            and rsi < OVERSOLD_BUY_RSI_THRESHOLD
            and not has_position
            and rr_ratio >= OVERSOLD_BUY_MIN_RR
            and atr_percent < MAX_TRADE_ATR_PERCENT
            and market_structure != "bearish"
        ):
            if not self._has_mean_reversion_confirmation(
                "long", market_data, technical
            ):
                return {
                    "action": "skip",
                    "reason": "均值回归BUY等待反转确认",
                    "confidence": selected.confidence,
                    "strategy": selected.strategy_type,
                }
            confidence_block = self._confidence_gate("long", selected, market_data)
            if confidence_block:
                self._oversold_metrics["oversold_signal_blocked_confidence"] += 1
                return confidence_block
            logger.info(
                f"[决策] 均值回归超卖反弹(BUY)覆盖AI-HOLD, "
                f"RSI={rsi:.1f}, R/R={rr_ratio:.2f}"
            )
            self._conflict_metrics["ai_hold_oversold_buy_executed"] += 1
            self._oversold_metrics["oversold_signal_executed"] += 1
            return {
                "action": "open",
                "reason": (
                    f"均值回归超卖反弹覆盖AI-HOLD"
                    f"(RSI={rsi:.1f}, R/R={rr_ratio:.2f})"
                ),
                "confidence": selected.confidence * 0.8,
                "strategy": "mean_reversion_oversold_override",
                "position_advice": "超卖反弹，建议轻仓",
            }
        relaxed_min_rr = max(STRATEGY_BUY_OVERRIDE_MIN_RR, self._get_min_rr())
        if (
            selected.signal.upper() == "BUY"
            and selected.strategy_type != "mean_reversion"
            and selected.confidence >= HOLD_STRATEGY_BUY_MIN_CONFIDENCE
            and market_structure != "bearish"
            and rr_ratio >= relaxed_min_rr
        ):
            confidence_block = self._confidence_gate("long", selected, market_data)
            if confidence_block:
                return confidence_block
            logger.info(
                f"[决策] 策略BUY(置信度{selected.confidence:.0%})覆盖AI-HOLD, "
                f"R/R={rr_ratio:.2f}, 阈值={relaxed_min_rr:.2f}"
            )
            self._conflict_metrics["ai_hold_strategy_buy_executed"] += 1
            result = {
                "action": "open",
                "reason": (
                    f"策略BUY覆盖AI-HOLD(置信度{selected.confidence:.0%}, "
                    f"R/R={rr_ratio:.2f})"
                ),
                "confidence": selected.confidence * 0.8,
                "strategy": selected.strategy_type,
            }
            if rr_ratio >= GOOD_RR_RATIO:
                result["position_advice"] = f"R/R={rr_ratio:.2f}良好，正常仓位"
            elif rr_ratio >= self._get_min_rr():
                result["position_advice"] = f"R/R={rr_ratio:.2f}勉强，建议减仓"
            return result
        relaxed_short_min_rr = self._get_short_min_rr()
        if (
            selected.signal.upper() == "SHORT"
            and selected.confidence >= HOLD_STRATEGY_SHORT_MIN_CONFIDENCE
            and not has_position
            and self._config.trading.allow_short_selling
            and short_rr_ratio >= relaxed_short_min_rr
            and atr_percent < MAX_TRADE_ATR_PERCENT
            and rsi > SHORT_RSI_OVERSOLD_BLOCK
        ):
            confidence_block = self._confidence_gate("short", selected, market_data)
            if confidence_block:
                return confidence_block
            logger.info(
                f"[决策] 策略SHORT(置信度{selected.confidence:.0%})"
                f"覆盖AI-HOLD, "
                f"短R/R={short_rr_ratio:.2f}, 阈值={relaxed_short_min_rr:.2f}"
            )
            return {
                "action": "sell",
                "reason": (
                    f"策略SHORT覆盖AI-HOLD(置信度{selected.confidence:.0%}, "
                    f"短R/R={short_rr_ratio:.2f})"
                ),
                "confidence": selected.confidence * 0.8,
                "strategy": selected.strategy_type,
                "position_advice": f"短R/R={short_rr_ratio:.2f}，做空开仓",
            }
        # 策略 SELL 覆盖 AI-HOLD：
        # mean_reversion SELL 置信度 >= 75% 时允许做空/平仓
        if (
            selected.signal.upper() == "SELL"
            and selected.confidence >= HOLD_STRATEGY_SELL_MIN_CONFIDENCE
        ):
            # 有持仓时执行平仓（平仓不受做空安全门禁限制）
            if has_position:
                confidence_block = self._confidence_gate(
                    "short", selected, market_data
                )
                if confidence_block:
                    return confidence_block
                logger.info(
                    f"[决策] 策略SELL(置信度{selected.confidence:.0%})"
                    f"覆盖AI-HOLD, "
                    f"平仓已有持仓"
                )
                return {
                    "action": "close",
                    "reason": (
                        f"策略SELL覆盖AI-HOLD(置信度{selected.confidence:.0%})"
                        f"，平仓"
                    ),
                    "confidence": selected.confidence * 0.8,
                    "strategy": selected.strategy_type,
                }
            # 无持仓时执行做空（需满足做空安全门禁）
            if (
                self._config.trading.allow_short_selling
                and self._is_confirmed_mean_reversion_short(selected, market_data)
            ):
                confidence_block = self._confidence_gate(
                    "short", selected, market_data
                )
                if confidence_block:
                    return confidence_block
                logger.info(
                    f"[决策] 策略SELL高质量短R/R({short_rr_ratio:.2f})"
                    "覆盖AI-HOLD, 做空开仓"
                )
                return {
                    "action": "sell",
                    "reason": (
                        f"策略SELL高质量短R/R覆盖AI-HOLD"
                        f"(置信度{selected.confidence:.0%}, 短R/R={short_rr_ratio:.2f})"
                    ),
                    "confidence": selected.confidence * 0.75,
                    "strategy": "mean_reversion_short_rr_override",
                    "position_advice": f"短R/R={short_rr_ratio:.2f}优秀，轻仓做空",
                }
            if (
                self._config.trading.allow_short_selling
                and self._is_confirmed_mean_reversion_short(selected, market_data)
            ):
                confidence_block = self._confidence_gate(
                    "short", selected, market_data
                )
                if confidence_block:
                    return confidence_block
                logger.info(
                    f"[决策] 策略SELL(置信度{selected.confidence:.0%})"
                    f"覆盖AI-HOLD, 做空开仓, "
                    f"短R/R={short_rr_ratio:.2f}, "
                    f"阈值={relaxed_short_min_rr:.2f}"
                )
                return {
                    "action": "sell",
                    "reason": (
                        f"策略SELL覆盖AI-HOLD(置信度{selected.confidence:.0%}, "
                        f"短R/R={short_rr_ratio:.2f})"
                    ),
                    "confidence": selected.confidence * 0.8,
                    "strategy": selected.strategy_type,
                    "position_advice": f"短R/R={short_rr_ratio:.2f}，做空开仓",
                }
        logger.warning(f"[决策] AI-HOLD但策略={selected.signal}，保守处理")
        self._conflict_metrics["ai_hold_strategy_buy_conservative_skip"] += 1
        return {
            "action": "skip",
            "reason": f"AI-HOLD覆盖策略({selected.signal})",
            "confidence": selected.confidence,
            "strategy": selected.strategy_type,
        }

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
            safe_mode_technical = dict(technical)
            safe_mode_technical["risk_reward_ratio"] = market_data.get(
                "risk_reward_ratio", 0
            )
            safe_mode_decision = self._make_safe_mode_decision(
                signal, selected, safe_mode_technical, has_position, atr_percent
            )
            if safe_mode_decision:
                return safe_mode_decision

        # BUY 信号处理
        if signal == "BUY":
            counter_short_decision = (
                self._make_low_confidence_buy_counter_short_decision(
                    selected, market_data, has_position
                )
            )
            if counter_short_decision:
                return counter_short_decision
            position_decision = self._position_aware_signal_decision(
                signal, selected, market_data
            )
            if position_decision:
                return position_decision
            return self._make_buy_decision(selected, market_data, atr_percent)

        # SHORT 信号处理
        if signal == "SHORT":
            return self._make_short_decision(
                selected, market_data, atr_percent, rsi, has_position
            )

        # SELL 信号处理
        if signal == "SELL":
            position_decision = self._position_aware_signal_decision(
                signal, selected, market_data
            )
            if position_decision:
                return position_decision
            if not has_position:
                return {
                    "action": "skip",
                    "reason": "SELL信号+无持仓，忽略",
                    "confidence": selected.confidence,
                    "strategy": selected.strategy_type,
                }
            if selected.signal.upper() == "SELL":
                return {
                    "action": "close",
                    "reason": "AI+策略共振卖出",
                    "confidence": selected.confidence,
                    "strategy": selected.strategy_type,
                }
            return {
                "action": "close",
                "reason": "AI信号卖出",
                "confidence": selected.confidence,
                "strategy": selected.strategy_type,
            }

        # HOLD 信号处理
        if signal == "HOLD":
            decision = self._make_hold_decision(
                selected, market_data, technical, atr_percent, rsi, has_position
            )
            return self._mark_ai_hold_override(decision)

        # 未知信号 - 使用策略信号
        if selected.signal.upper() != "HOLD":
            action = "open" if selected.signal.upper() == "BUY" else "close"
            return {
                "action": action,
                "reason": f"策略信号: {selected.signal}",
                "confidence": selected.confidence,
                "strategy": selected.strategy_type,
            }

        return {
            "action": "skip",
            "reason": "AI和策略都是HOLD",
            "confidence": selected.confidence,
            "strategy": selected.strategy_type,
        }

    @staticmethod
    def _mark_ai_hold_override(decision: Dict[str, Any]) -> Dict[str, Any]:
        """为 AI-HOLD 覆盖入场决策添加可统计 metadata。"""
        action = decision.get("action")
        reason = str(decision.get("reason", ""))
        if action not in ["open", "sell"] or "覆盖AI-HOLD" not in reason:
            return decision

        metadata = dict(decision.get("metadata", {}))
        metadata["ai_hold_override"] = True
        metadata["ai_hold_override_type"] = str(decision.get("strategy", "unknown"))
        decision["metadata"] = metadata
        return decision
