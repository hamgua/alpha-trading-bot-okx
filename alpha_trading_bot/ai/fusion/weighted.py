"""
加权平均融合策略 - 支持置信度加权
"""

import logging
from typing import Dict, List, Optional, Any

from .base import FusionStrategy
from .consensus_boosted import FusionResult

logger = logging.getLogger(__name__)


class WeightedFusion(FusionStrategy):
    """加权平均融合 - 支持置信度加权"""

    def fuse(
        self,
        signals: List[Dict[str, str]],
        weights: Dict[str, float],
        threshold: float,
        *,
        confidences: Optional[Dict[str, float]] = None,
        market_data: Optional[Dict[str, Any]] = None,
    ) -> FusionResult:
        """
        融合信号（带置信度加权）

        Args:
            signals: [{"provider": "deepseek", "signal": "buy"}, ...]
            weights: {"deepseek": 0.5, "kimi": 0.5, ...}
            threshold: 融合阈值
            confidences: {"deepseek": 0.7, "kimi": 0.75, ...} 置信度（可选）
        """
        if not signals:
            logger.warning("无有效信号，默认hold")
            return FusionResult(
                signal="hold",
                confidence=0.0,
                scores={"buy": 0.0, "hold": 1.0, "sell": 0.0, "short": 0.0},
                threshold=threshold,
                is_valid=False,
                consensus_ratio=0.0,
                strategy_used="weighted",
                details={"reason": "no_signals", "market_data": market_data or {}},
            )

        weighted_scores: Dict[str, float] = {
            "buy": 0.0,
            "hold": 0.0,
            "sell": 0.0,
            "short": 0.0,
        }
        total_weight = 0.0

        for s in signals:
            provider = s["provider"]
            sig = s["signal"]
            weight = weights.get(provider, 1.0)

            # 置信度统一为 0-1，若未提供使用默认0.7
            confidence_factor = confidences.get(provider, 0.7) if confidences else 0.7
            confidence_factor = max(0.0, min(1.0, confidence_factor))

            # 置信度加权：score = weight * confidence_factor
            adjusted_weight = weight * confidence_factor

            if sig == "buy":
                weighted_scores["buy"] += adjusted_weight
            elif sig == "sell":
                weighted_scores["sell"] += adjusted_weight
            elif sig == "short":
                weighted_scores["short"] += adjusted_weight
            else:
                weighted_scores["hold"] += adjusted_weight

            total_weight += adjusted_weight

        for sig in weighted_scores:
            weighted_scores[sig] /= total_weight if total_weight > 0 else 1

        max_sig = max(weighted_scores, key=lambda signal: weighted_scores[signal])
        max_score = weighted_scores[max_sig]

        # 信号有效性判断
        is_valid = max_score >= threshold

        self._log_result(
            "加权平均(置信度加权)",
            max_sig,
            f"buy:{weighted_scores['buy']:.2f}, hold:{weighted_scores['hold']:.2f}, sell:{weighted_scores['sell']:.2f}, short:{weighted_scores['short']:.2f}, threshold:{threshold}, valid:{is_valid}",
        )
        consensus_ratio = 0.0
        total_signals = len(signals)
        if total_signals > 0:
            signal_counts: Dict[str, int] = {}
            for item in signals:
                signal = item["signal"]
                signal_counts[signal] = signal_counts.get(signal, 0) + 1
            consensus_ratio = max(signal_counts.values()) / total_signals

        return FusionResult(
            signal=max_sig,
            confidence=float(max_score),
            scores=weighted_scores,
            threshold=threshold,
            is_valid=is_valid,
            consensus_ratio=consensus_ratio,
            strategy_used="weighted",
            details={"market_data": market_data or {}},
        )
