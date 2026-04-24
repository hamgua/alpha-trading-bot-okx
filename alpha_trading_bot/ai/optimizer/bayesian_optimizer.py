"""
贝叶斯优化器

使用 Optuna 进行参数自动优化
每日收盘后运行，找出最优参数组合

功能增强：
- 详细的学习过程日志记录
- 优化结果可视化
- 学习历史追踪
"""

import logging
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass
from datetime import datetime
import json
import os

from alpha_trading_bot.ai.provider_utils import get_runtime_fusion_providers

logger = logging.getLogger(__name__)


# 学习历史记录（全局）
_learning_history: list[Dict[str, Any]] = []


@dataclass
class OptimizationResult:
    """优化结果"""

    best_params: Dict[str, float]
    best_value: float
    n_trials: int
    optimization_time_seconds: float
    study_name: str
    timestamp: str
    learning_details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        details = self.learning_details if self.learning_details is not None else {}
        return {
            "best_params": self.best_params,
            "best_value": self.best_value,
            "n_trials": self.n_trials,
            "optimization_time_seconds": self.optimization_time_seconds,
            "study_name": self.study_name,
            "timestamp": self.timestamp,
            "learning_details": details,
        }


class BayesianOptimizer:
    """
    贝叶斯参数优化器

    使用 Optuna 进行高效的参数搜索
    """

    def __init__(
        self,
        study_name: str = "trading_bot_optimization",
        storage_path: str = "data_json/optuna_study.db",
        n_trials: int = 100,
    ):
        """
        初始化优化器

        Args:
            study_name: 研究名称
            storage_path: SQLite 存储路径
            n_trials: 优化试验次数
        """
        self.study_name = study_name
        self.storage_path = storage_path
        self.n_trials = n_trials
        self._objective_func: Optional[Callable] = None
        self._search_space: Dict[str, Dict[str, Any]] = {}
        self.providers: list[str] = get_runtime_fusion_providers()

    def define_search_space(self) -> Dict[str, Dict[str, Any]]:
        """定义参数搜索空间"""
        search_space = {
            "fusion_threshold": {
                "type": "float",
                "low": 0.3,
                "high": 0.8,
                "log": False,
            },
            "stop_loss_percent": {
                "type": "float",
                "low": 0.002,
                "high": 0.015,
                "log": False,
            },
            "stop_loss_profit_percent": {
                "type": "float",
                "low": 0.001,
                "high": 0.01,
                "log": False,
            },
            "buy_rsi_threshold": {
                "type": "float",
                "low": 50,
                "high": 80,
                "log": False,
            },
        }

        for provider in self.providers:
            search_space[f"weight_{provider}"] = {
                "type": "float",
                "low": 0.1,
                "high": 0.8,
                "log": False,
            }

        self._search_space = search_space
        return search_space

    def set_objective(
        self,
        objective_func: Callable[[Dict[str, float]], float],
    ) -> None:
        """
        设置优化目标函数

        Args:
            objective_func: 目标函数，输入参数字典，返回优化目标值
        """
        self._objective_func = objective_func

    def _create_optuna_objective(self):
        """创建 Optuna 目标函数"""
        import optuna

        search_space = self._search_space

        def objective(trial):
            params = {}

            for name, config in search_space.items():
                if config["type"] == "float":
                    if config.get("log", False):
                        params[name] = trial.suggest_float(
                            name,
                            config["low"],
                            config["high"],
                            log=True,
                        )
                    else:
                        params[name] = trial.suggest_float(
                            name, config["low"], config["high"]
                        )
                elif config["type"] == "int":
                    params[name] = trial.suggest_int(
                        name, int(config["low"]), int(config["high"])
                    )
                elif config["type"] == "categorical":
                    params[name] = trial.suggest_categorical(name, config["choices"])

            obj_func = self._objective_func
            if obj_func is not None:
                return obj_func(params)
            return 0.0

        return objective

    def optimize(self) -> OptimizationResult:
        """
        运行优化

        Returns:
            OptimizationResult: 优化结果
        """
        import optuna
        import time

        start_time = time.time()

        try:
            # 创建或加载研究
            storage = f"sqlite:///{self.storage_path}"
            study = optuna.create_study(
                study_name=self.study_name,
                storage=storage,
                load_if_exists=True,
                direction="maximize",
            )

            # 运行优化
            study.optimize(
                self._create_optuna_objective(),
                n_trials=self.n_trials,
                show_progress_bar=False,
            )

            optimization_time = time.time() - start_time

            # 获取最优参数
            best_params = study.best_params
            best_value = study.best_value

            # 记录学习详情
            learning_details = {
                "search_space": self._search_space,
                "trials_completed": len(study.trials),
                "best_trial_number": study.best_trial.number,
            }

            # 详细的学习日志
            logger.info(
                f"[贝叶斯优化] 学习完成: "
                f"最优值={best_value:.4f}, "
                f"试验次数={len(study.trials)}, "
                f"耗时={optimization_time:.2f}秒"
            )
            logger.info(f"[贝叶斯优化] 最优参数: {best_params}")

            return OptimizationResult(
                best_params=best_params,
                best_value=best_value,
                n_trials=len(study.trials),
                optimization_time_seconds=optimization_time,
                study_name=self.study_name,
                timestamp=datetime.now().isoformat(),
                learning_details=learning_details,
            )

        except ImportError:
            logger.error("[贝叶斯优化] Optuna 未安装，请运行: pip install optuna")
            return OptimizationResult(
                best_params={},
                best_value=0,
                n_trials=0,
                optimization_time_seconds=0,
                study_name=self.study_name,
                timestamp=datetime.now().isoformat(),
                learning_details={"error": "optuna not installed"},
            )

    def get_best_params(self) -> Dict[str, float]:
        """获取当前最优参数"""
        try:
            import optuna

            storage = f"sqlite:///{self.storage_path}"
            study = optuna.load_study(study_name=self.study_name, storage=storage)
            return study.best_params
        except ImportError:
            return {}
        except Exception as e:
            logger.error(f"[贝叶斯优化] 获取最优参数失败: {e}")
            return {}

    def get_optimization_history(self, n_top: int = 10) -> list[Dict[str, Any]]:
        """获取优化历史"""
        try:
            import optuna

            storage = f"sqlite:///{self.storage_path}"
            study = optuna.load_study(study_name=self.study_name, storage=storage)

            trials = study.get_trials(deepcopy=False)[-n_top:][::-1]

            return [
                {
                    "number": t.number,
                    "value": t.value,
                    "params": t.params,
                    "state": t.state.name,
                    "duration": t.duration.total_seconds() if t.duration else 0,
                }
                for t in trials
            ]
        except ImportError:
            return []
        except Exception as e:
            logger.error(f"[贝叶斯优化] 获取历史失败: {e}")
            return []
