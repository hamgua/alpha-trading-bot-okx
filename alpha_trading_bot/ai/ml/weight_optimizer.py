"""
ML Weight Optimizer - 基于历史数据自动优化 AI 权重
"""

import json
import os
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class WeightMetrics:
    """权重性能指标"""

    regime: str
    provider: str
    total_signals: int = 0
    correct_signals: int = 0
    avg_confidence: float = 0.0
    avg_return: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0


class WeightOptimizer:
    """ML 权重优化器"""

    def __init__(self, data_dir: str = "data/weight_history"):
        self.data_dir = data_dir
        self.metrics: Dict[str, WeightMetrics] = {}
        self.current_weights: Dict[str, Dict[str, float]] = {
            "strong_uptrend": {"kimi": 0.55, "deepseek": 0.45},
            "weak_uptrend": {"kimi": 0.50, "deepseek": 0.50},
            "sideways": {"kimi": 0.50, "deepseek": 0.50},
            "weak_downtrend": {"kimi": 0.40, "deepseek": 0.60},
            "strong_downtrend": {"kimi": 0.30, "deepseek": 0.70},
        }
        self._ensure_data_dir()

    def _ensure_data_dir(self):
        os.makedirs(self.data_dir, exist_ok=True)

    def record_signal_outcome(
        self,
        regime: str,
        provider: str,
        signal: str,
        confidence: int,
        market_outcome: str,
        price_return: float,
    ):
        """记录信号结果"""
        key = f"{regime}_{provider}"

        if key not in self.metrics:
            self.metrics[key] = WeightMetrics(regime=regime, provider=provider)

        m = self.metrics[key]
        m.total_signals += 1
        m.avg_confidence = (
            m.avg_confidence * (m.total_signals - 1) + confidence
        ) / m.total_signals
        m.avg_return = (
            m.avg_return * (m.total_signals - 1) + price_return
        ) / m.total_signals

        if market_outcome in ["correct", "partial"]:
            m.correct_signals += 1

        m.win_rate = m.correct_signals / m.total_signals if m.total_signals > 0 else 0

    def optimize_weights(self) -> Dict[str, Dict[str, float]]:
        """基于历史表现优化权重"""
        if len(self.metrics) < 10:
            logger.warning("样本不足，保持当前权重")
            return self.current_weights

        optimized = {}

        for regime in self.current_weights.keys():
            regime_metrics = [m for m in self.metrics.values() if m.regime == regime]

            if not regime_metrics:
                optimized[regime] = self.current_weights[regime]
                continue

            total_wr = sum(m.win_rate for m in regime_metrics)
            count = len(regime_metrics)

            new_weights = {}
            for m in regime_metrics:
                provider = m.provider
                normalized_wr = m.win_rate / total_wr if total_wr > 0 else 0.5
                new_weights[provider] = min(0.8, max(0.2, normalized_wr))

            total = sum(new_weights.values()) if new_weights else 1.0
            if total > 0:
                for p in new_weights:
                    new_weights[p] = round(new_weights[p] / total, 2)

            optimized[regime] = new_weights

        self.current_weights = optimized
        logger.info(f"权重优化完成: {optimized}")
        return optimized

    def get_weights(self, regime: str) -> Dict[str, float]:
        return self.current_weights.get(regime, {"kimi": 0.5, "deepseek": 0.5})

    def save_weights(self):
        """保存权重到文件"""
        filepath = os.path.join(self.data_dir, "optimized_weights.json")
        with open(filepath, "w") as f:
            json.dump(
                {
                    "timestamp": datetime.now().isoformat(),
                    "weights": self.current_weights,
                    "metrics": {
                        k: {
                            "regime": v.regime,
                            "provider": v.provider,
                            "total_signals": v.total_signals,
                            "win_rate": v.win_rate,
                            "avg_return": v.avg_return,
                        }
                        for k, v in self.metrics.items()
                    },
                },
                f,
                indent=2,
            )
        logger.info(f"权重已保存: {filepath}")

    def load_weights(self) -> bool:
        """从文件加载权重"""
        filepath = os.path.join(self.data_dir, "optimized_weights.json")
        if not os.path.exists(filepath):
            return False

        try:
            with open(filepath, "r") as f:
                data = json.load(f)
                self.current_weights = data.get("weights", self.current_weights)
            logger.info("权重已加载")
            return True
        except Exception as e:
            logger.error(f"加载权重失败: {e}")
            return False


def get_optimized_weights() -> Dict[str, Dict[str, float]]:
    optimizer = WeightOptimizer()
    optimizer.load_weights()
    return optimizer.current_weights
