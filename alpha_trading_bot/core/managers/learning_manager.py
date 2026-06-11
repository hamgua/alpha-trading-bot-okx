"""
学习管理器 - 整合ML学习模块

职责：
- ML数据管理
- 权重优化
- 回测学习
- 学习循环控制
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class LearningManager:
    """学习管理器

    整合 MLDataManager, AdaptiveWeightOptimizer, BacktestLearner,
    提供统一的学习和优化接口。
    """

    def __init__(self) -> None:
        from alpha_trading_bot.ai.ml.ml_data_manager import get_ml_data_manager
        from alpha_trading_bot.ai.ml.adaptive_weight_optimizer import (
            get_weight_optimizer,
        )
        from alpha_trading_bot.ai.ml.signal_backtest import get_backtest_learner
        from alpha_trading_bot.ai.ml.learning_integrator import SimpleLearningLoop

        self._ml_data_manager = get_ml_data_manager()
        self._weight_optimizer = get_weight_optimizer()
        self._backtest_learner = get_backtest_learner()
        self._learning_loop = SimpleLearningLoop()
        logger.info("[LearningManager] 初始化完成")

    def record_trade(self, trade_data: Dict[str, Any]) -> None:
        """记录交易数据用于学习

        Args:
            trade_data: 交易数据字典
        """
        self._ml_data_manager.record_trade(trade_data)
        self._weight_optimizer.record_trade(trade_data)

    def optimize_weights(self) -> Dict[str, float]:
        """优化权重

        Returns:
            优化后的权重字典
        """
        return self._weight_optimizer.optimize()

    def run_backtest(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """运行回测

        Args:
            market_data: 历史市场数据

        Returns:
            回测结果
        """
        return self._backtest_learner.learn(market_data)

    def get_learning_status(self) -> Dict[str, Any]:
        """获取学习状态

        Returns:
            学习状态字典
        """
        return {
            "ml_data_count": self._ml_data_manager.get_data_count(),
            "optimizer_status": self._weight_optimizer.get_status(),
            "learning_loop_active": self._learning_loop.is_active(),
        }

    def trigger_optimization(self) -> bool:
        """触发优化任务

        Returns:
            是否成功触发
        """
        try:
            self._learning_loop.trigger_optimization()
            return True
        except Exception as e:
            logger.error(f"[LearningManager] 优化触发失败: {e}")
            return False

    def get_optimized_parameters(self) -> Dict[str, float]:
        """获取优化后的参数

        Returns:
            参数字典
        """
        return self._weight_optimizer.get_best_params()
