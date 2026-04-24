"""
置信度优先融合策略
"""

import logging
from typing import Dict, List, Optional, Any

from .base import FusionStrategy
from .consensus_boosted import FusionResult

logger = logging.getLogger(__name__)


class ConfidenceFusion(FusionStrategy):
    """置信度优先融合"""

    def fuse(
        self,
        signals: List[Dict[str, str]],
        weights: Dict[str, float],
        threshold: float,
        *,
        confidences: Optional[Dict[str, float]] = None,
        market_data: Optional[Dict[str, Any]] = None,
    ) -> FusionResult:
        if not signals:
            logger.warning("无有效信号，默认hold")
            return FusionResult(
                signal="hold",
                confidence=0.0,
                scores={"buy": 0.0, "hold": 1.0, "sell": 0.0, "short": 0.0},
                threshold=threshold,
                is_valid=False,
                consensus_ratio=0.0,
                strategy_used="confidence",
                details={"reason": "no_signals", "market_data": market_data or {}},
            )

        signal_counts: Dict[str, int] = {}
        total = len(signals)

        for s in signals:
            sig = s["signal"]
            signal_counts[sig] = signal_counts.get(sig, 0) + 1

        buy_count = signal_counts.get("buy", 0)
        sell_count = signal_counts.get("sell", 0)
        normalized_scores = {
            "buy": signal_counts.get("buy", 0) / total,
            "hold": signal_counts.get("hold", 0) / total,
            "sell": signal_counts.get("sell", 0) / total,
            "short": signal_counts.get("short", 0) / total,
        }
        consensus_ratio = max(signal_counts.values()) / total

        if buy_count > sell_count and buy_count / total >= threshold:
            return FusionResult(
                signal="buy",
                confidence=buy_count / total,
                scores=normalized_scores,
                threshold=threshold,
                is_valid=True,
                consensus_ratio=consensus_ratio,
                strategy_used="confidence",
                details={"market_data": market_data or {}},
            )
        elif sell_count > buy_count and sell_count / total >= threshold:
            return FusionResult(
                signal="sell",
                confidence=sell_count / total,
                scores=normalized_scores,
                threshold=threshold,
                is_valid=True,
                consensus_ratio=consensus_ratio,
                strategy_used="confidence",
                details={"market_data": market_data or {}},
            )
        return FusionResult(
            signal="hold",
            confidence=max(normalized_scores.values()),
            scores=normalized_scores,
            threshold=threshold,
            is_valid=False,
            consensus_ratio=consensus_ratio,
            strategy_used="confidence",
            details={"market_data": market_data or {}},
        )
