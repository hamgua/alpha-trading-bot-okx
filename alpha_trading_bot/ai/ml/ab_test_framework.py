"""
A/B Testing Framework - 对比不同策略效果
"""

import hashlib
import json
import os
import random
from typing import Dict, Optional, Callable, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class StrategyType(Enum):
    CONSENSUS_BOOSTED = "consensus_boosted"
    ADAPTIVE = "adaptive"
    WEIGHTED = "weighted"


@dataclass
class ABTestResult:
    strategy: str
    signals: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    avg_return: float = 0.0
    total_return: float = 0.0


class ABTestFramework:
    """A/B 测试框架"""

    def __init__(self, data_dir: str = "data/ab_tests"):
        self.data_dir = data_dir
        self.control_strategy = StrategyType.CONSENSUS_BOOSTED
        self.test_strategy = StrategyType.ADAPTIVE
        self.traffic_split = 0.2
        self._ensure_data_dir()

    def _ensure_data_dir(self):
        os.makedirs(self.data_dir, exist_ok=True)

    def assign_variant(self, user_id: str) -> StrategyType:
        """分配测试变体"""
        hash_input = f"{user_id}_{datetime.now().date()}"
        hash_value = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)
        variant = hash_value % 100

        if variant < self.traffic_split * 100:
            return self.test_strategy
        return self.control_strategy

    def record_result(
        self,
        user_id: str,
        strategy: StrategyType,
        signal: str,
        outcome: str,
        return_pct: float,
    ):
        """记录测试结果"""
        test_id = f"ab_{datetime.now().strftime('%Y%m%d')}"
        filepath = os.path.join(self.data_dir, f"{test_id}.json")

        result = {
            "user_id": user_id,
            "strategy": strategy.value,
            "signal": signal,
            "outcome": outcome,
            "return_pct": return_pct,
            "timestamp": datetime.now().isoformat(),
        }

        with open(filepath, "a") as f:
            f.write(json.dumps(result) + "\n")

    def analyze_results(self, test_id: str) -> Dict[str, ABTestResult]:
        """分析测试结果"""
        filepath = os.path.join(self.data_dir, f"{test_id}.json")
        if not os.path.exists(filepath):
            return {}

        results = {
            StrategyType.CONSENSUS_BOOSTED: ABTestResult(strategy="consensus_boosted"),
            StrategyType.ADAPTIVE: ABTestResult(strategy="adaptive"),
        }

        with open(filepath, "r") as f:
            for line in f:
                data = json.loads(line)
                strategy = StrategyType(data["strategy"])
                r = results[strategy]
                r.signals += 1

                if data["outcome"] == "correct":
                    r.wins += 1
                elif data["outcome"] == "wrong":
                    r.losses += 1

                if data.get("return_pct") is not None:
                    r.total_return += data["return_pct"]

        for r in results.values():
            if r.signals > 0:
                r.win_rate = r.wins / r.signals
                r.avg_return = r.total_return / r.signals

        return results

    def get_recommendation(self, test_id: str) -> Optional[str]:
        """获取优化建议"""
        results = self.analyze_results(test_id)

        if not results:
            return None

        control = results.get(StrategyType.CONSENSUS_BOOSTED)
        test = results.get(StrategyType.ADAPTIVE)

        if not control or not test:
            return None

        if test.signals < 10:
            return "等待更多样本"

        if test.avg_return > control.avg_return + 0.5:
            return "推荐切换到自适应策略"
        elif test.avg_return < control.avg_return - 0.5:
            return "保持当前共识策略"
        else:
            return "两种策略表现相近，维持现状"


def run_ab_test(
    user_id: str,
    market_data: Dict[str, Any],
    adaptive_func: Callable,
    consensus_func: Callable,
) -> tuple:
    """运行 A/B 测试"""
    framework = ABTestFramework()
    variant = framework.assign_variant(user_id)

    if variant == StrategyType.ADAPTIVE:
        result = adaptive_func(market_data)
        strategy = "adaptive"
    else:
        result = consensus_func(market_data)
        strategy = "consensus"

    return result, strategy
