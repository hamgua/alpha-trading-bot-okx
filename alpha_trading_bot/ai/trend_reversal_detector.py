"""
趋势反转检测器

功能：
- 检测动量反转信号
- 检测RSI反弹信号
- 检测价格形态反转
- 综合判断趋势是否可能反转

作者：AI Trading System
日期：2026-02-04
"""

import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class TrendReversalSignal:
    """趋势反转信号"""

    reversal_detected: bool
    reversal_type: str  # momentum | rsi | pattern | multi
    confidence: float  # 0-1
    suggested_signal: str  # buy | hold | sell
    details: Dict[str, Any]
    timestamp: str


@dataclass
class TrendMetrics:
    """趋势指标"""

    trend_direction: str  # up | down | sideways
    trend_strength: float  # 0-1
    momentum: float  # 正=上涨动量, 负=下跌动量
    rsi: float
    rsi_trend: float  # RSI变化趋势
    price_position: float  # 0-100，价格位置


class TrendReversalDetector:
    """
    趋势反转检测器

    通过多维度指标检测趋势是否可能反转：
    1. 动量反转：价格短期变化率由负转正
    2. RSI反弹：RSI从低位回升
    3. 形态反转：价格形成支撑/阻力位
    """

    def __init__(
        self,
        momentum_window: int = 3,
        rsi_window: int = 5,
        momentum_threshold: float = 0.008,
        rsi_oversold: float = 30,
        rsi_rebound_threshold: float = 3,
        price_position_low: float = 25,
    ):
        """
        初始化趋势反转检测器

        Args:
            momentum_window: 动量计算窗口（周期数）
            rsi_window: RSI趋势计算窗口
            momentum_threshold: 动量反转阈值（0.8%）
            rsi_oversold: RSI超卖阈值
            rsi_rebound_threshold: RSI反弹阈值
            price_position_low: 低价位阈值（25%）
        """
        self.momentum_window = momentum_window
        self.rsi_window = rsi_window
        self.momentum_threshold = momentum_threshold
        self.rsi_oversold = rsi_oversold
        self.rsi_rebound_threshold = rsi_rebound_threshold
        self.price_position_low = price_position_low

        logger.info(
            f"[趋势反转检测器] 初始化完成: "
            f"动量窗口={momentum_window}, 动量阈值={momentum_threshold * 100}%, "
            f"RSI超卖={rsi_oversold}"
        )

    def detect(
        self,
        current_price: float,
        price_history: List[float],
        rsi_history: List[float],
        hourly_changes: List[float],
        current_rsi: float,
        trend_direction: str,
        trend_strength: float,
        price_position: float,
    ) -> TrendReversalSignal:
        """
        检测趋势反转信号

        Args:
            current_price: 当前价格
            price_history: 历史价格列表（最近到最远）
            rsi_history: 历史RSI列表
            hourly_changes: 小时级别变化率列表
            current_rsi: 当前RSI
            trend_direction: 趋势方向
            trend_strength: 趋势强度 (0-1)
            price_position: 价格位置 (0-100)

        Returns:
            TrendReversalSignal: 趋势反转信号
        """
        reversal_signals: List[str] = []
        confidence_bonus: float = 0.0
        details: Dict[str, Any] = {}

        # 1. 动量反转检测
        momentum_signal = self._detect_momentum_reversal(
            hourly_changes, current_price, price_history
        )
        if momentum_signal["detected"]:
            reversal_signals.append("momentum")
            confidence_bonus += momentum_signal["confidence"]
            details["momentum"] = momentum_signal

        # 2. RSI反弹检测
        rsi_signal = self._detect_rsi_rebound(rsi_history, current_rsi)
        if rsi_signal["detected"]:
            reversal_signals.append("rsi_rebound")
            confidence_bonus += rsi_signal["confidence"]
            details["rsi"] = rsi_signal

        # 3. 形态反转检测
        pattern_signal = self._detect_pattern_reversal(
            price_history, current_price, price_position
        )
        if pattern_signal["detected"]:
            reversal_signals.append("pattern")
            confidence_bonus += pattern_signal["confidence"]
            details["pattern"] = pattern_signal

        # 4. 趋势强度衰减检测
        strength_signal = self._detect_strength_decay(trend_strength)
        if strength_signal["detected"]:
            reversal_signals.append("strength_decay")
            confidence_bonus += strength_signal["confidence"]
            details["strength"] = strength_signal

        # 综合判断
        if len(reversal_signals) >= 2:
            # 多个信号同时出现，反转可能性高
            reversal_type = "multi"
            base_confidence = 0.55
            suggested_signal = "buy"
        elif len(reversal_signals) == 1:
            reversal_type = reversal_signals[0]
            base_confidence = 0.45
            suggested_signal = "buy"
        else:
            reversal_type = "none"
            base_confidence = 0.0
            suggested_signal = "hold"

        # 计算最终置信度
        final_confidence = min(
            base_confidence + confidence_bonus + (len(reversal_signals) * 0.1), 0.92
        )

        # 如果原趋势是强势下跌，反弹信号更可信
        if trend_direction == "down" and trend_strength > 0.4:
            final_confidence = min(final_confidence + 0.1, 0.95)

        result = TrendReversalSignal(
            reversal_detected=len(reversal_signals) >= 1,
            reversal_type=reversal_type,
            confidence=final_confidence,
            suggested_signal=suggested_signal,
            details={
                "reversal_signals": reversal_signals,
                "signal_count": len(reversal_signals),
                "confidence_bonus": confidence_bonus,
                "trend_context": {
                    "direction": trend_direction,
                    "strength": trend_strength,
                },
                **details,
            },
            timestamp=datetime.now().isoformat(),
        )

        logger.info(
            f"[趋势反转检测] 结果: 检测到{len(reversal_signals)}个信号, "
            f"类型={reversal_type}, 置信度={final_confidence:.2%}, "
            f"建议={suggested_signal}"
        )

        return result

    def _detect_momentum_reversal(
        self,
        hourly_changes: List[float],
        current_price: float,
        price_history: List[float],
    ) -> Dict[str, Any]:
        """
        检测动量反转

        逻辑：
        - 计算近期平均动量
        - 判断动量是否由负转正
        """
        if not hourly_changes:
            return {"detected": False, "confidence": 0.0, "reason": "无历史数据"}

        # 使用最近N个周期计算平均动量
        recent_changes = hourly_changes[: self.momentum_window]
        avg_momentum = sum(recent_changes) / len(recent_changes)

        # 判断动量状态
        if avg_momentum > self.momentum_threshold:
            momentum_status = "positive"
            confidence = 0.25
        elif avg_momentum > 0:
            momentum_status = "weak_positive"
            confidence = 0.15
        elif avg_momentum > -self.momentum_threshold:
            momentum_status = "weak_negative"
            confidence = 0.0
        else:
            momentum_status = "negative"
            confidence = 0.0

        # 检测动量反转：近期动量比早期更正向
        reversal_detected = False
        if len(hourly_changes) >= 6:
            early_momentum = sum(hourly_changes[-3:]) / 3
            if avg_momentum > early_momentum + self.momentum_threshold:
                reversal_detected = True
                confidence += 0.15
                momentum_status = "reversal"

        # 价格位置辅助判断
        if len(price_history) >= 7:
            recent_low = min(price_history[:7])
            price_range = max(price_history[:7]) - recent_low
            if price_range > 0:
                position_from_low = (current_price - recent_low) / price_range * 100
            else:
                position_from_low = 50
        else:
            position_from_low = 50

        return {
            "detected": reversal_detected
            or momentum_status in ["positive", "weak_positive"],
            "confidence": min(confidence, 0.35),
            "avg_momentum": avg_momentum,
            "momentum_status": momentum_status,
            "position_from_low": position_from_low,
            "reason": f"动量{'反转' if reversal_detected else '状态=' + momentum_status}",
        }

    def _detect_rsi_rebound(
        self, rsi_history: List[float], current_rsi: float
    ) -> Dict[str, Any]:
        """
        检测RSI反弹

        逻辑：
        - RSI处于超卖区域
        - RSI开始回升
        """
        if current_rsi >= self.rsi_oversold:
            return {
                "detected": False,
                "confidence": 0.0,
                "current_rsi": current_rsi,
                "rsi_trend": 0,
                "reason": f"RSI={current_rsi:.1f}未超卖",
            }

        # 计算RSI趋势
        if len(rsi_history) >= 3:
            rsi_change = current_rsi - rsi_history[-1]
            rsi_trend = rsi_change
        else:
            rsi_change = 0
            rsi_trend = 0

        # RSI反弹检测
        if rsi_trend > self.rsi_rebound_threshold:
            # RSI明显回升
            detected = True
            confidence = 0.30
            reason = f"RSI反弹({rsi_trend:+.1f})"
        elif rsi_trend > 0 and current_rsi < 25:
            # 轻微回升 + 严重超卖
            detected = True
            confidence = 0.20
            reason = "RSI轻微回升+严重超卖"
        else:
            detected = False
            confidence = 0.0
            reason = f"RSI趋势={rsi_trend:+.1f}"

        return {
            "detected": detected,
            "confidence": min(confidence, 0.35),
            "current_rsi": current_rsi,
            "rsi_trend": rsi_trend,
            "oversold_level": (
                self.rsi_oversold - current_rsi
                if current_rsi < self.rsi_oversold
                else 0
            ),
            "reason": reason,
        }

    def _detect_pattern_reversal(
        self, price_history: List[float], current_price: float, price_position: float
    ) -> Dict[str, Any]:
        """
        检测价格形态反转

        逻辑：
        - 价格处于近期低位
        - 形成支撑位
        - 出现十字星等反转形态
        """
        if len(price_history) < 5:
            return {
                "detected": False,
                "confidence": 0.0,
                "pattern": "insufficient_data",
                "reason": "数据不足",
            }

        recent_prices = price_history[:5]
        recent_low = min(recent_prices)
        recent_high = max(recent_prices)

        # 计算价格位置
        price_range = recent_high - recent_low
        if price_range > 0:
            current_position = (current_price - recent_low) / price_range * 100
        else:
            current_position = 50

        # 检测双底形态
        if len(price_history) >= 10:
            early_low = min(price_history[5:10])
            if abs(recent_low - early_low) / early_low < 0.02:  # 2%以内
                pattern = "double_bottom"
                detected = True
                confidence = 0.30
                reason = "双底形态"
            elif recent_low > early_low and current_position > 60:
                pattern = "higher_low"
                detected = True
                confidence = 0.25
                reason = "低点抬高"
            else:
                pattern = "none"
                detected = False
                confidence = 0.0
                reason = "未形成形态"
        else:
            # 简化检测
            if current_position < self.price_position_low:
                pattern = "low_position"
                detected = True
                confidence = 0.20
                reason = f"价格位置={current_position:.1f}%"
            elif current_position < 35:
                pattern = "low_position"
                detected = True
                confidence = 0.15
                reason = f"价格位置={current_position:.1f}%"
            else:
                pattern = "none"
                detected = False
                confidence = 0.0
                reason = "价格位置正常"

        return {
            "detected": detected,
            "confidence": min(confidence, 0.35),
            "pattern": pattern,
            "current_position": current_position,
            "price_position_given": price_position,
            "reason": reason,
        }

    def _detect_strength_decay(self, trend_strength: float) -> Dict[str, Any]:
        """
        检测趋势强度衰减

        逻辑：
        - 趋势强度正在减弱
        - 可能预示趋势反转
        """
        if trend_strength < 0.2:
            return {
                "detected": False,
                "confidence": 0.0,
                "trend_strength": trend_strength,
                "reason": "趋势已弱，无需检测衰减",
            }

        # 趋势强度衰减本身不直接导致反转信号
        # 但可以作为辅助判断
        return {
            "detected": False,
            "confidence": 0.0,
            "trend_strength": trend_strength,
            "reason": "衰减检测需要历史趋势强度数据",
        }

    def calculate_trend_metrics(
        self,
        current_price: float,
        price_history: List[float],
        rsi_history: List[float],
        hourly_changes: List[float],
        current_rsi: float,
    ) -> TrendMetrics:
        """
        计算趋势指标

        用于给其他模块提供趋势相关指标
        """
        # 趋势方向和强度
        if len(price_history) >= 10:
            short_ma = sum(price_history[:3]) / 3
            long_ma = sum(price_history[7:10]) / 3
            if short_ma > long_ma * 1.01:
                trend_direction = "up"
                trend_strength = min((short_ma / long_ma - 1) * 10, 1.0)
            elif short_ma < long_ma * 0.99:
                trend_direction = "down"
                trend_strength = min((long_ma / short_ma - 1) * 10, 1.0)
            else:
                trend_direction = "sideways"
                trend_strength = 0.2
        else:
            trend_direction = "sideways"
            trend_strength = 0.2

        # 动量
        if hourly_changes:
            momentum = sum(hourly_changes[:3]) / 3
        else:
            momentum = 0.0

        # RSI趋势
        if len(rsi_history) >= 2:
            rsi_trend = current_rsi - rsi_history[-1]
        else:
            rsi_trend = 0.0

        # 价格位置
        if len(price_history) >= 7:
            low = min(price_history[:7])
            high = max(price_history[:7])
            if high > low:
                price_position = (current_price - low) / (high - low) * 100
            else:
                price_position = 50
        else:
            price_position = 50

        return TrendMetrics(
            trend_direction=trend_direction,
            trend_strength=trend_strength,
            momentum=momentum,
            rsi=current_rsi,
            rsi_trend=rsi_trend,
            price_position=price_position,
        )
