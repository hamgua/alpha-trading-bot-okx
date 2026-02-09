"""
Adaptive Fusion Strategy - 自适应融合策略
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class FusionMode(Enum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


@dataclass
class FusionConfig:
    mode: FusionMode = FusionMode.MODERATE
    base_threshold: float = 0.50
    strong_trend_threshold: float = 0.40
    weak_trend_threshold: float = 0.45
    momentum_boost: float = 0.05


class AdaptiveFusionStrategy:
    """自适应融合策略"""

    def __init__(self, config: Optional[FusionConfig] = None):
        self.config = config or FusionConfig()
        self.weight_map = {
            "strong_uptrend": {"kimi": 0.55, "deepseek": 0.45},
            "weak_uptrend": {"kimi": 0.50, "deepseek": 0.50},
            "sideways": {"kimi": 0.50, "deepseek": 0.50},
            "weak_downtrend": {"kimi": 0.40, "deepseek": 0.60},
            "strong_downtrend": {"kimi": 0.30, "deepseek": 0.70},
        }

    def fuse(
        self,
        signals: List[Dict[str, Any]],
        trend_context: Dict[str, Any],
        momentum: float = 0.0,
    ) -> Dict[str, Any]:
        if not signals:
            return {"signal": "hold", "confidence": 0.0, "threshold": 0.5}

        regime = self._determine_regime(trend_context, momentum)
        weights = self.weight_map.get(regime, self.weight_map["sideways"])
        threshold = self._calculate_threshold(regime, momentum)

        scores = {"buy": 0.0, "hold": 0.0, "sell": 0.0}

        for signal_data in signals:
            provider = signal_data.get("provider", "unknown")
            action = signal_data.get("signal", "hold")
            confidence = signal_data.get("confidence", 50)

            weight = weights.get(provider, 0.5)
            weighted_score = confidence / 100.0 * weight

            scores[action] += weighted_score

        total = sum(scores.values())
        if total > 0:
            for s in scores:
                scores[s] = scores[s] / total

        buy_ratio = scores["buy"]

        if buy_ratio >= threshold:
            result_signal = "buy"
            result_confidence = buy_ratio * 100
        elif scores["sell"] >= threshold:
            result_signal = "sell"
            result_confidence = scores["sell"] * 100
        else:
            result_signal = "hold"
            result_confidence = max(scores.values()) * 100

        return {
            "signal": result_signal,
            "confidence": result_confidence,
            "threshold": threshold,
            "regime": regime,
            "scores": scores,
            "weights": weights,
        }

    def _determine_regime(self, trend_context: Dict[str, Any], momentum: float) -> str:
        direction = trend_context.get("trend_direction", "neutral")
        strength = trend_context.get("trend_strength", 0.0)

        if direction == "up":
            return "strong_uptrend" if strength > 0.6 else "weak_uptrend"
        elif direction == "down":
            return "strong_downtrend" if strength > 0.6 else "weak_downtrend"
        else:
            return "sideways"

    def _calculate_threshold(self, regime: str, momentum: float) -> float:
        if "uptrend" in regime:
            if momentum > 0.005:
                return self.config.strong_trend_threshold
            elif momentum > 0.002:
                return self.config.weak_trend_threshold
            return self.config.base_threshold
        elif "downtrend" in regime:
            return self.config.base_threshold
        else:
            return self.config.base_threshold

    def update_weights(self, regime: str, new_weights: Dict[str, float]):
        if regime in self.weight_map:
            self.weight_map[regime] = new_weights


def adaptive_fuse(
    signals: List[Dict[str, Any]], trend_context: Dict[str, Any], momentum: float = 0.0
) -> Dict[str, Any]:
    strategy = AdaptiveFusionStrategy()
    return strategy.fuse(signals, trend_context, momentum)
