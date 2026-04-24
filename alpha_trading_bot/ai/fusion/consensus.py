"""
共识融合策略
"""

import logging
from typing import Dict, List, Optional, Any

from .base import FusionStrategy
from .consensus_boosted import FusionResult

logger = logging.getLogger(__name__)


class ConsensusFusion(FusionStrategy):
    """共识融合 - 所有AI必须一致"""

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
                strategy_used="consensus",
                details={"reason": "no_signals", "market_data": market_data or {}},
            )

        unique_signals = set(s["signal"] for s in signals)
        signal_counts = {"buy": 0, "hold": 0, "sell": 0, "short": 0}
        for item in signals:
            signal = item["signal"]
            if signal in signal_counts:
                signal_counts[signal] += 1
        total = len(signals)
        consensus_ratio = max(signal_counts.values()) / total if total > 0 else 0.0
        normalized_scores = {key: value / total for key, value in signal_counts.items()}

        if len(unique_signals) == 1:
            sig = list(unique_signals)[0]
            self._log_result("共识", sig, "all agreed")
            return FusionResult(
                signal=sig,
                confidence=1.0,
                scores=normalized_scores,
                threshold=threshold,
                is_valid=True,
                consensus_ratio=consensus_ratio,
                strategy_used="consensus",
                details={"reason": "all agreed", "market_data": market_data or {}},
            )
        else:
            logger.warning(f"未达成共识: {unique_signals}，默认hold")
            return FusionResult(
                signal="hold",
                confidence=0.6,
                scores=normalized_scores,
                threshold=threshold,
                is_valid=False,
                consensus_ratio=consensus_ratio,
                strategy_used="consensus",
                details={"reason": "no consensus", "market_data": market_data or {}},
            )
