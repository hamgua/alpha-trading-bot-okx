"""
参数管理器 - 整合自适应参数和配置更新

职责：
- 自适应参数调整
- 配置热更新
- 参数版本管理
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ParameterSnapshot:
    """参数快照"""

    version: int
    parameters: Dict[str, float]
    timestamp: str


class ParameterManager:
    """参数管理器

    整合 AdaptiveParameterManager 和 ConfigUpdater，
    提供参数查询和更新接口。
    """

    def __init__(self) -> None:
        from alpha_trading_bot.ai.adaptive import AdaptiveParameterManager

        self._param_manager = AdaptiveParameterManager()
        self._config_updater: Optional[Any] = None
        self._current_snapshot: Optional[ParameterSnapshot] = None
        logger.info("[ParameterManager] 初始化完成")

    def set_config_updater(self, updater: Any) -> None:
        """设置配置更新器

        Args:
            updater: ConfigUpdater 实例
        """
        self._config_updater = updater

    def get_parameters(self) -> Dict[str, float]:
        """获取当前参数

        Returns:
            参数字典
        """
        return self._param_manager.get_current_params()

    def update_parameters(self, params: Dict[str, float], reason: str = "") -> bool:
        """更新参数

        Args:
            params: 新参数
            reason: 更新原因

        Returns:
            是否成功
        """
        success = self._param_manager.update_params(params)
        if success and self._config_updater:
            self._config_updater.apply_optimized_params(params, reason)
        return success

    def reset_parameters(self) -> None:
        """重置参数到默认值"""
        self._param_manager.reset()

    def create_snapshot(self) -> ParameterSnapshot:
        """创建参数快照"""
        params = self.get_parameters()
        from datetime import datetime

        snapshot = ParameterSnapshot(
            version=len(params),
            parameters=params.copy(),
            timestamp=datetime.now().isoformat(),
        )
        self._current_snapshot = snapshot
        return snapshot

    def restore_snapshot(self, snapshot: ParameterSnapshot) -> bool:
        """恢复参数快照

        Args:
            snapshot: 参数快照

        Returns:
            是否成功
        """
        return self.update_parameters(snapshot.parameters, "restore snapshot")

    def get_param_history(self) -> list:
        """获取参数变更历史"""
        return self._param_manager.get_change_history()
