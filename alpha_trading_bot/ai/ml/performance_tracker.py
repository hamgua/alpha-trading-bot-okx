"""
Performance Tracker - 追踪 AI 信号表现
"""

import json
import os
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
from collections import defaultdict
import logging

from alpha_trading_bot.ai.provider_utils import get_runtime_fusion_providers

logger = logging.getLogger(__name__)


@dataclass
class SignalRecord:
    timestamp: str
    provider: str
    signal: str
    confidence: int
    regime: str
    price_at_signal: float
    outcome: Optional[str] = None
    price_at_outcome: Optional[float] = None
    return_pct: Optional[float] = None


class PerformanceTracker:
    """AI 信号表现追踪器"""

    def __init__(self, data_dir: str = "data/performance"):
        self.data_dir = data_dir
        self.records: List[SignalRecord] = []
        self._ensure_data_dir()

    def _ensure_data_dir(self):
        os.makedirs(self.data_dir, exist_ok=True)
        try:
            os.chmod(self.data_dir, 0o700)
        except OSError:
            pass

    def record_signal(
        self,
        provider: str,
        signal: str,
        confidence: int,
        regime: str,
        price: float,
        timestamp: Optional[str] = None,
    ) -> str:
        """记录信号，返回时间戳供后续更新结果使用"""
        if timestamp is None:
            timestamp = datetime.now().isoformat()

        record = SignalRecord(
            timestamp=timestamp,
            provider=provider,
            signal=signal,
            confidence=confidence,
            regime=regime,
            price_at_signal=price,
        )
        self.records.append(record)
        return timestamp

    def update_outcome(self, provider: str, timestamp: str, outcome: str, price: float):
        for record in reversed(self.records):
            if (
                record.provider == provider
                and record.timestamp == timestamp
                and record.outcome is None
            ):
                record.outcome = outcome
                record.price_at_outcome = price
                record.return_pct = (
                    (price - record.price_at_signal) / record.price_at_signal * 100
                )
                break

    def get_provider_stats(self, provider: str) -> Dict:
        provider_records = [r for r in self.records if r.provider == provider]

        if not provider_records:
            return {"signals": 0}

        correct = [r for r in provider_records if r.outcome == "correct"]
        partial = [r for r in provider_records if r.outcome == "partial"]
        wrong = [r for r in provider_records if r.outcome == "wrong"]

        returns = [r.return_pct for r in provider_records if r.return_pct is not None]

        return {
            "signals": len(provider_records),
            "correct": len(correct),
            "partial": len(partial),
            "wrong": len(wrong),
            "win_rate": (
                (len(correct) + len(partial) * 0.5) / len(provider_records)
                if provider_records
                else 0
            ),
            "avg_return": sum(returns) / len(returns) if returns else 0,
            "best_return": max(returns) if returns else 0,
            "worst_return": min(returns) if returns else 0,
        }

    def get_regime_stats(self, regime: str) -> Dict:
        regime_records = [r for r in self.records if r.regime == regime]

        if not regime_records:
            return {"signals": 0}

        signal_stats = defaultdict(lambda: {"total": 0, "correct": 0})
        for r in regime_records:
            signal_stats[r.signal]["total"] += 1
            if r.outcome == "correct":
                signal_stats[r.signal]["correct"] += 1

        return {"signals": len(regime_records), "signal_breakdown": dict(signal_stats)}

    def get_confidence_accuracy(self) -> Dict[int, Dict]:
        buckets = defaultdict(lambda: {"total": 0, "correct": 0})

        for r in self.records:
            if r.confidence and r.outcome:
                bucket = (r.confidence // 10) * 10
                buckets[bucket]["total"] += 1
                if r.outcome == "correct":
                    buckets[bucket]["correct"] += 1

        return {
            f"{k}-{k + 9}": {
                "total": v["total"],
                "correct": v["correct"],
                "accuracy": v["correct"] / v["total"] if v["total"] > 0 else 0,
            }
            for k, v in buckets.items()
        }

    def save(self):
        filepath = os.path.join(self.data_dir, "performance_history.json")
        with open(filepath, "w") as f:
            json.dump(
                [
                    {
                        "timestamp": r.timestamp,
                        "provider": r.provider,
                        "signal": r.signal,
                        "confidence": r.confidence,
                        "regime": r.regime,
                        "price_at_signal": r.price_at_signal,
                        "outcome": r.outcome,
                        "price_at_outcome": r.price_at_outcome,
                        "return_pct": r.return_pct,
                    }
                    for r in self.records
                ],
                f,
                indent=2,
            )
        try:
            os.chmod(filepath, 0o600)
        except OSError:
            pass
        logger.info(f"性能数据已保存: {filepath}")


def get_performance_summary() -> Dict[str, Any]:
    tracker = PerformanceTracker()
    providers = sorted({record.provider for record in tracker.records})
    if not providers:
        providers = get_runtime_fusion_providers()
    return {
        "total_signals": len(tracker.records),
        "provider_stats": {
            provider: tracker.get_provider_stats(provider) for provider in providers
        },
    }
