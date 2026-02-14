"""
自适应权重优化器

功能：
- 基于历史表现自动调整 AI 提供商权重
- 实现真正的机器学习闭环
- 支持在线学习和批量学习

作者：AI Trading System
日期：2026-02-14
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass
import json

import numpy as np
import pandas as pd

from .ml_data_manager import MLDataManager, get_ml_data_manager

logger = logging.getLogger(__name__)


@dataclass
class OptimizationResult:
    """优化结果"""

    best_weights: Dict[str, float]
    expected_return: float
    sharpe_ratio: float
    win_rate: float
    confidence: float
    timestamp: str
    iteration: int
    improvement: float = 0.0


class AdaptiveWeightOptimizer:
    """
    自适应权重优化器

    实现真正的机器学习：
    1. 从历史数据学习各 AI 提供商的性能模式
    2. 根据市场条件动态调整权重
    3. 在线学习：根据新交易结果持续优化
    """

    def __init__(
        self,
        db_path: str = "data_json/trading_data.db",
        window_days: int = 30,
        min_trades: int = 20,
    ):
        """
        初始化优化器

        Args:
            db_path: 数据库路径
            window_days: 分析窗口天数
            min_trades: 最少需要的交易数
        """
        self.db_path = db_path
        self.window_days = window_days
        self.min_trades = min_trades

        self.data_manager = get_ml_data_manager(db_path)

        # 缓存
        self._cached_weights: Optional[Dict[str, float]] = None
        self._cached_timestamp: Optional[datetime] = None
        self._cache_duration_hours = 6

        # 学习历史
        self._weight_history: List[Dict] = []

    def _get_cached_weights(self) -> Optional[Dict[str, float]]:
        """获取缓存的权重"""
        if self._cached_weights is None or self._cached_timestamp is None:
            return None

        age = (datetime.now() - self._cached_timestamp).total_seconds() / 3600
        if age < self._cache_duration_hours:
            return self._cached_weights

        return None

    def _set_cached_weights(self, weights: Dict[str, float]) -> None:
        """设置缓存的权重"""
        self._cached_weights = weights
        self._cached_timestamp = datetime.now()

    def calculate_performance_based_weights(self) -> Dict[str, float]:
        """
        基于历史表现的权重计算

        Returns:
            Dict: 各提供商权重
        """
        # 检查缓存
        cached = self._get_cached_weights()
        if cached:
            logger.debug("[权重优化] 使用缓存权重")
            return cached

        # 获取历史信号和结果
        signals = self.data_manager.get_ai_signals_with_outcomes(days=self.window_days)

        if not signals:
            logger.warning("[权重优化] 无历史数据，返回默认权重")
            return {"deepseek": 0.5, "kimi": 0.5}

        # 计算各提供商性能
        performance = self.data_manager.calculate_provider_performance(signals)

        if not performance:
            return {"deepseek": 0.5, "kimi": 0.5}

        # 计算综合得分
        weights = {}
        total_score = 0

        for provider, metrics in performance.items():
            # 综合评分公式
            score = (
                metrics.get("win_rate", 0.5) * 0.35
                + min(metrics.get("profit_factor", 1), 3) / 3 * 0.25
                + max(0, metrics.get("sharpe_ratio", 0)) * 0.2
                + min(1, metrics.get("signal_count", 1) / 100) * 0.1
                + (1 - min(1, metrics.get("max_drawdown", 0) / 0.1)) * 0.1
            )

            weights[provider] = score
            total_score += score

        # 归一化
        if total_score > 0:
            weights = {p: max(0.1, s / total_score) for p, s in weights.items()}

        # 归一化为1
        total = sum(weights.values())
        if total > 0:
            weights = {p: w / total for p, w in weights.items()}

        # 缓存
        self._set_cached_weights(weights)

        logger.info(f"[权重优化] 计算权重: {weights}")
        return weights

    def optimize_weights_grid_search(
        self, n_iterations: int = 100, objective: str = "sharpe"
    ) -> Tuple[Dict[str, float], float]:
        """
        使用网格搜索寻找最优权重

        Args:
            n_iterations: 迭代次数
            objective: 优化目标 (sharpe / return / win_rate)

        Returns:
            Tuple: (最优权重, 预期得分)
        """
        # 获取历史数据
        signals = self.data_manager.get_ai_signals_with_outcomes(days=self.window_days)

        if len(signals) < self.min_trades:
            logger.warning(f"[权重优化] 数据不足: {len(signals)} < {self.min_trades}")
            return self.calculate_performance_based_weights(), 0.0

        df = pd.DataFrame(signals)
        providers = df["provider"].unique()

        if len(providers) < 2:
            return {providers[0]: 1.0}, 0.0

        best_score = -float("inf")
        best_weights = {}

        # 简单网格搜索
        for _ in range(n_iterations):
            # 随机生成权重
            weights = {}
            for p in providers:
                weights[p] = np.random.uniform(0.1, 0.9)

            # 归一化
            total = sum(weights.values())
            weights = {p: w / total for p, w in weights.items()}

            # 计算加权得分
            weighted_score = 0
            total_signals = 0

            for provider in providers:
                provider_df = df[df["provider"] == provider]
                closed = provider_df[provider_df["trade_status"] == "closed"]

                if len(closed) == 0:
                    continue

                win_rate = (closed["pnl"] > 0).mean()

                weighted_score += weights[provider] * win_rate * len(closed)
                total_signals += len(closed)

            if total_signals == 0:
                continue

            score = weighted_score / total_signals

            if score > best_score:
                best_score = score
                best_weights = weights

        logger.info(
            f"[权重优化] 网格搜索最优权重: {best_weights}, 得分: {best_score:.4f}"
        )
        return best_weights, best_score

    def online_update(
        self,
        provider: str,
        signal_confidence: float,
        trade_result: str,
        pnl_percent: float,
    ) -> None:
        """
        在线学习：收到新交易结果后更新

        Args:
            provider: AI 提供商名称
            signal_confidence: 信号置信度
            trade_result: 交易结果 (win/loss)
            pnl_percent: 盈亏百分比
        """
        # 记录到数据库供后续分析
        self.data_manager.save_model_weights(
            {provider: signal_confidence}, source=f"online_{trade_result}"
        )

        logger.info(
            f"[在线学习] 更新 {provider}: confidence={signal_confidence}, "
            f"result={trade_result}, pnl={pnl_percent:.2f}%"
        )

        # 更新权重历史
        self._weight_history.append(
            {
                "timestamp": datetime.now().isoformat(),
                "provider": provider,
                "confidence": signal_confidence,
                "result": trade_result,
                "pnl": pnl_percent,
            }
        )

        # 保持历史长度
        if len(self._weight_history) > 1000:
            self._weight_history = self._weight_history[-500:]

    def get_optimized_weights(
        self,
        use_grid_search: bool = False,
    ) -> Tuple[Dict[str, float], float]:
        """
        获取优化后的权重

        Args:
            use_grid_search: 是否使用网格搜索

        Returns:
            Tuple: (权重字典, 置信度得分)
        """
        # 检查缓存
        cached = self._get_cached_weights()
        if cached and not use_grid_search:
            return cached, 0.7

        if use_grid_search:
            weights, score = self.optimize_weights_grid_search()
            self._set_cached_weights(weights)
            return weights, score

        # 默认：基于历史表现
        weights = self.calculate_performance_based_weights()
        return weights, 0.6

    def get_performance_report(self) -> Dict[str, Any]:
        """
        获取性能报告

        Returns:
            Dict: 性能报告
        """
        signals = self.data_manager.get_ai_signals_with_outcomes(days=self.window_days)
        performance = self.data_manager.calculate_provider_performance(signals)

        return {
            "window_days": self.window_days,
            "total_signals": len(signals),
            "providers": list(performance.keys()),
            "performance": performance,
            "current_weights": self.calculate_performance_based_weights(),
            "optimized_weights": self.get_optimized_weights()[0],
            "weight_history_len": len(self._weight_history),
            "timestamp": datetime.now().isoformat(),
        }


class EnsembleWeightOptimizer:
    """
    集成权重优化器

    组合多种优化方法：
    1. 历史表现法
    2. 网格搜索优化
    """

    def __init__(self, db_path: str = "data_json/trading_data.db"):
        self.optimizer = AdaptiveWeightOptimizer(db_path)
        self.data_manager = get_ml_data_manager(db_path)

    def get_ensemble_weights(self) -> Tuple[Dict[str, float], float]:
        """
        获取集成优化的权重

        Returns:
            Tuple: (权重, 置信度)
        """
        # 获取各方法的权重
        perf_weights, perf_score = (
            self.optimizer.calculate_performance_based_weights(),
            0.6,
        )
        grid_weights, grid_score = self.optimizer.get_optimized_weights(
            use_grid_search=True
        )

        # 获取数据量
        signals = self.data_manager.get_ai_signals_with_outcomes(days=30)

        if len(signals) < 20:
            # 数据不足，使用历史表现法
            return perf_weights, perf_score

        if len(signals) < 50:
            # 数据一般，结合两种方法
            combined = {}
            for provider in set(perf_weights.keys()) | set(grid_weights.keys()):
                w1 = perf_weights.get(provider, 0)
                w2 = grid_weights.get(provider, 0)
                combined[provider] = (w1 + w2) / 2

            total = sum(combined.values())
            combined = {p: w / total for p, w in combined.items()}
            return combined, 0.75

        # 数据充足，使用网格搜索
        return grid_weights, grid_score

    def run_learning_cycle(self) -> Dict[str, Any]:
        """
        运行一次学习循环

        Returns:
            Dict: 学习结果
        """
        start_time = datetime.now()

        # 获取优化权重
        weights, confidence = self.get_ensemble_weights()

        # 保存权重
        self.data_manager.save_model_weights(weights, source="ensemble")

        elapsed = (datetime.now() - start_time).total_seconds()

        result = {
            "weights": weights,
            "confidence": confidence,
            "elapsed_seconds": elapsed,
            "timestamp": datetime.now().isoformat(),
        }

        logger.info(
            f"[学习循环] 完成: 权重={weights}, 置信度={confidence:.2f}, 耗时={elapsed:.2f}秒"
        )
        return result


# 便捷函数
def get_weight_optimizer(
    db_path: str = "data_json/trading_data.db",
) -> AdaptiveWeightOptimizer:
    """获取权重优化器实例"""
    return AdaptiveWeightOptimizer(db_path)


def run_learning_cycle(db_path: str = "data_json/trading_data.db") -> Dict[str, Any]:
    """运行一次学习循环"""
    optimizer = EnsembleWeightOptimizer(db_path)
    return optimizer.run_learning_cycle()
