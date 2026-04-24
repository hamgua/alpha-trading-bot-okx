"""
多数表决融合策略
"""

import logging
from typing import Dict, List, Optional, Any

from .base import FusionStrategy
from .consensus_boosted import FusionResult

logger = logging.getLogger(__name__)


class MajorityFusion(FusionStrategy):
    """多数表决融合"""

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
                strategy_used="majority",
                details={"reason": "no_signals", "market_data": market_data or {}},
            )

        signal_counts = {}
        for s in signals:
            sig = s["signal"]
            signal_counts[sig] = signal_counts.get(sig, 0) + 1

        total = len(signals)
        normalized_scores = {
            "buy": signal_counts.get("buy", 0) / total,
            "hold": signal_counts.get("hold", 0) / total,
            "sell": signal_counts.get("sell", 0) / total,
            "short": signal_counts.get("short", 0) / total,
        }
        consensus_ratio = max(signal_counts.values()) / total

        for sig, count in signal_counts.items():
            if count / total >= threshold:
                self._log_result("多数表决", sig, f"{count}/{total} >= {threshold}")
                return FusionResult(
                    signal=sig,
                    confidence=count / total,
                    scores=normalized_scores,
                    threshold=threshold,
                    is_valid=True,
                    consensus_ratio=consensus_ratio,
                    strategy_used="majority",
                    details={"market_data": market_data or {}},
                )

        # 未达阈值，取最多的
        max_sig: str = max(signal_counts, key=lambda signal: signal_counts[signal])
        self._log_result("多数表决-降级", max_sig, "max count")
        return FusionResult(
            signal=max_sig,
            confidence=signal_counts[max_sig] / total,
            scores=normalized_scores,
            threshold=threshold,
            is_valid=False,
            consensus_ratio=consensus_ratio,
            strategy_used="majority",
            details={"fallback": True, "market_data": market_data or {}},
        )
