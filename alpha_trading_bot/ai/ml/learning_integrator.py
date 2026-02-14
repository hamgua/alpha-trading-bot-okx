"""
ML 学习集成器

功能：
- 连接 ML 模块到主交易流程
- 实现真正的机器学习闭环
- 自动学习 → 优化 → 应用

作者：AI Trading System
日期：2026-02-14
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from dataclasses import dataclass

from .ml_data_manager import MLDataManager, get_ml_data_manager
from .adaptive_weight_optimizer import (
    AdaptiveWeightOptimizer,
    EnsembleWeightOptimizer,
    get_weight_optimizer,
)

logger = logging.getLogger(__name__)


@dataclass
class LearningResult:
    """学习结果"""

    success: bool
    weights: Dict[str, float]
    confidence: float
    method: str  # "performance" / "optuna" / "ml" / "ensemble"
    training_samples: int
    elapsed_seconds: float
    timestamp: str
    message: str = ""


class MLLearningIntegrator:
    """
    ML 学习集成器

    负责：
    1. 从交易记录中学习
    2. 运行优化算法
    3. 将优化结果应用到配置
    """

    def __init__(
        self,
        db_path: str = "data_json/trading_data.db",
        auto_optimize_interval_hours: int = 6,
    ):
        """
        初始化学习集成器

        Args:
            db_path: 数据库路径
            auto_optimize_interval_hours: 自动优化间隔（小时）
        """
        self.db_path = db_path
        self.auto_interval = auto_optimize_interval_hours * 3600

        # 组件
        self.data_manager = get_ml_data_manager(db_path)
        self.weight_optimizer = get_weight_optimizer(db_path)
        self.ensemble_optimizer = EnsembleWeightOptimizer(db_path)

        # 状态
        self._last_optimize_time: Optional[datetime] = None
        self._is_running = False

    async def run_learning_cycle(self) -> LearningResult:
        """
        运行一次完整的学习循环

        Returns:
            LearningResult: 学习结果
        """
        start_time = datetime.now()

        try:
            logger.info("[ML学习] 开始学习循环...")

            # 1. 收集交易数据
            signals = self.data_manager.get_ai_signals_with_outcomes(days=30)

            if len(signals) < 10:
                logger.warning(f"[ML学习] 数据不足: {len(signals)} 条信号")
                return LearningResult(
                    success=False,
                    weights={"deepseek": 0.5, "kimi": 0.5},
                    confidence=0.0,
                    method="none",
                    training_samples=len(signals),
                    elapsed_seconds=0,
                    timestamp=datetime.now().isoformat(),
                    message="数据不足，无法学习",
                )

            # 2. 获取优化权重
            weights, confidence = self.ensemble_optimizer.get_ensemble_weights()

            # 3. 训练 ML 模型（如有足够数据）
            features, labels, info = self.data_manager.get_training_data(
                min_trades=50, days=60
            )

            ml_trained = False
            if len(features) > 0:
                try:
                    self.weight_optimizer.train_ml_model(features.values, labels.values)
                    ml_trained = True
                    logger.info("[ML学习] ML模型训练完成")
                except Exception as e:
                    logger.error(f"[ML学习] ML模型训练失败: {e}")

            # 4. 保存权重
            self.data_manager.save_model_weights(weights, source="learning_cycle")

            elapsed = (datetime.now() - start_time).total_seconds()

            logger.info(
                f"[ML学习] 完成: 权重={weights}, 置信度={confidence:.2f}, "
                f"训练样本={len(features)}, 耗时={elapsed:.2f}秒"
            )

            return LearningResult(
                success=True,
                weights=weights,
                confidence=confidence,
                method="ensemble",
                training_samples=len(features),
                elapsed_seconds=elapsed,
                timestamp=datetime.now().isoformat(),
                message="学习成功",
            )

        except Exception as e:
            logger.error(f"[ML学习] 学习失败: {e}")
            return LearningResult(
                success=False,
                weights={"deepseek": 0.5, "kimi": 0.5},
                confidence=0.0,
                method="error",
                training_samples=0,
                elapsed_seconds=0,
                timestamp=datetime.now().isoformat(),
                message=str(e),
            )

    async def run_continuous_learning(
        self, stop_event: asyncio.Event, optimize_callback: Optional[callable] = None
    ) -> None:
        """
        运行持续学习任务

        Args:
            stop_event: 停止事件
            optimize_callback: 优化完成后的回调函数
        """
        self._is_running = True
        logger.info("[ML学习] 持续学习任务启动")

        try:
            while not stop_event.is_set():
                try:
                    # 检查是否到达优化时间
                    now = datetime.now()

                    if (
                        self._last_optimize_time is None
                        or (now - self._last_optimize_time).total_seconds()
                        >= self.auto_interval
                    ):
                        # 运行学习循环
                        result = await self.run_learning_cycle()

                        if result.success:
                            self._last_optimize_time = now

                            # 调用回调（应用新权重）
                            if optimize_callback:
                                try:
                                    optimize_callback(result.weights)
                                except Exception as e:
                                    logger.error(f"[ML学习] 回调失败: {e}")

                    # 等待
                    await asyncio.sleep(300)  # 每5分钟检查一次

                except Exception as e:
                    logger.error(f"[ML学习] 持续学习出错: {e}")
                    await asyncio.sleep(60)  # 错误后等待1分钟

        finally:
            self._is_running = False
            logger.info("[ML学习] 持续学习任务停止")

    def apply_optimized_weights(self, weights: Dict[str, float]) -> bool:
        """
        应用优化后的权重到配置

        Args:
            weights: 新的权重

        Returns:
            bool: 是否成功
        """
        try:
            # 更新融合权重配置
            self.data_manager.save_model_weights(weights, source="auto_optimize")

            logger.info(f"[ML学习] 已应用新权重: {weights}")
            return True

        except Exception as e:
            logger.error(f"[ML学习] 应用权重失败: {e}")
            return False

    def get_learning_status(self) -> Dict[str, Any]:
        """
        获取学习状态

        Returns:
            Dict: 状态信息
        """
        return {
            "is_running": self._is_running,
            "last_optimize_time": self._last_optimize_time.isoformat()
            if self._last_optimize_time
            else None,
            "auto_interval_hours": self.auto_interval / 3600,
            "performance_report": self.weight_optimizer.get_performance_report(),
        }


class SimpleLearningLoop:
    """
    简化版学习循环

    用于快速集成的轻量级版本
    """

    def __init__(self, db_path: str = "data_json/trading_data.db"):
        self.db_path = db_path
        self.data_manager = get_ml_data_manager(db_path)
        self.optimizer = get_weight_optimizer(db_path)

    def learn_from_trades(self) -> Dict[str, float]:
        """
        从交易记录学习

        Returns:
            Dict: 新的权重
        """
        # 基于历史表现计算权重
        weights = self.optimizer.calculate_performance_based_weights()

        # 保存到数据库
        self.data_manager.save_model_weights(weights, source="simple_learn")

        logger.info(f"[简单学习] 新权重: {weights}")
        return weights

    def online_update(
        self, provider: str, confidence: float, outcome: str, pnl_percent: float
    ) -> None:
        """
        在线更新：收到新交易结果后调用

        Args:
            provider: AI 提供商
            confidence: 信号置信度
            outcome: 交易结果 (win/loss)
            pnl_percent: 盈亏百分比
        """
        self.optimizer.online_update(
            provider=provider,
            signal_confidence=confidence,
            trade_result=outcome,
            pnl_percent=pnl_percent,
        )


# 便捷函数
def get_learning_integrator(
    db_path: str = "data_json/trading_data.db",
) -> MLLearningIntegrator:
    """获取 ML 学习集成器"""
    return MLLearningIntegrator(db_path)


def get_simple_learning(
    db_path: str = "data_json/trading_data.db",
) -> SimpleLearningLoop:
    """获取简化版学习循环"""
    return SimpleLearningLoop(db_path)
