"""
ML Weight Optimizer - 基于历史数据自动优化 AI 权重
"""

import json
import os
from typing import Dict, List
from dataclasses import dataclass
from datetime import datetime
import logging

from alpha_trading_bot.ai.provider_utils import get_runtime_fusion_providers

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
        self.providers: List[str] = get_runtime_fusion_providers()
        self.current_weights: Dict[str, Dict[str, float]] = self._default_weight_map(
            self.providers
        )
        self._ensure_data_dir()

    @staticmethod
    def _normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
        total = sum(weights.values())
        if total <= 0:
            equal = 1.0 / len(weights)
            return {provider: equal for provider in weights}
        return {provider: value / total for provider, value in weights.items()}

    @classmethod
    def _default_weight_map(cls, providers: List[str]) -> Dict[str, Dict[str, float]]:
        if not providers:
            providers = get_runtime_fusion_providers()
        equal = 1.0 / len(providers)
        template = {
            "strong_uptrend": {provider: equal for provider in providers},
            "weak_uptrend": {provider: equal for provider in providers},
            "sideways": {provider: equal for provider in providers},
            "weak_downtrend": {provider: equal for provider in providers},
            "strong_downtrend": {provider: equal for provider in providers},
        }
        if "kimi" in providers and "deepseek" in providers:
            template["strong_uptrend"]["kimi"] += 0.10
            template["strong_uptrend"]["deepseek"] -= 0.10
            template["weak_downtrend"]["kimi"] -= 0.10
            template["weak_downtrend"]["deepseek"] += 0.10
            template["strong_downtrend"]["kimi"] -= 0.20
            template["strong_downtrend"]["deepseek"] += 0.20

        return {
            regime: cls._normalize_weights(weights)
            for regime, weights in template.items()
        }

    def _ensure_data_dir(self):
        os.makedirs(self.data_dir, exist_ok=True)
        try:
            os.chmod(self.data_dir, 0o700)
        except OSError:
            pass

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
        default = self._normalize_weights(
            {provider: 1.0 for provider in self.providers}
        )
        return self.current_weights.get(regime, default)

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
        try:
            os.chmod(filepath, 0o600)
        except OSError:
            pass
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
