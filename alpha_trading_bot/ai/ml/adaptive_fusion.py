"""
Adaptive Fusion Strategy - 自适应融合策略
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum
import logging

from alpha_trading_bot.ai.provider_utils import get_runtime_fusion_providers

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
        self.providers = get_runtime_fusion_providers()
        self.weight_map = self._build_default_weight_map(self.providers)

    @staticmethod
    def _normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
        total = sum(weights.values())
        if total <= 0:
            equal = 1.0 / len(weights)
            return {provider: equal for provider in weights}
        return {provider: value / total for provider, value in weights.items()}

    @classmethod
    def _build_default_weight_map(
        cls, providers: List[str]
    ) -> Dict[str, Dict[str, float]]:
        """按 provider 集合动态构建各市场状态默认权重。"""
        if not providers:
            providers = get_runtime_fusion_providers()

        equal = 1.0 / len(providers)
        map_template = {
            "strong_uptrend": {provider: equal for provider in providers},
            "weak_uptrend": {provider: equal for provider in providers},
            "sideways": {provider: equal for provider in providers},
            "weak_downtrend": {provider: equal for provider in providers},
            "strong_downtrend": {provider: equal for provider in providers},
        }

        if "kimi" in providers and "deepseek" in providers:
            map_template["strong_uptrend"]["kimi"] += 0.10
            map_template["strong_uptrend"]["deepseek"] -= 0.10
            map_template["weak_downtrend"]["kimi"] -= 0.10
            map_template["weak_downtrend"]["deepseek"] += 0.10
            map_template["strong_downtrend"]["kimi"] -= 0.20
            map_template["strong_downtrend"]["deepseek"] += 0.20

        return {
            regime: cls._normalize_weights(weights)
            for regime, weights in map_template.items()
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

        scores = {"buy": 0.0, "hold": 0.0, "sell": 0.0, "short": 0.0}

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
        short_ratio = scores.get("short", 0.0)

        if buy_ratio >= threshold:
            result_signal = "buy"
            result_confidence = buy_ratio * 100
        elif scores["sell"] >= threshold:
            result_signal = "sell"
            result_confidence = scores["sell"] * 100
        elif short_ratio >= threshold:
            result_signal = "short"
            result_confidence = short_ratio * 100
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
            self.weight_map[regime] = self._normalize_weights(new_weights)


def adaptive_fuse(
    signals: List[Dict[str, Any]], trend_context: Dict[str, Any], momentum: float = 0.0
) -> Dict[str, Any]:
    strategy = AdaptiveFusionStrategy()
    return strategy.fuse(signals, trend_context, momentum)
