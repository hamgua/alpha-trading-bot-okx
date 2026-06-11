"""参数应用模块

从 AdaptiveTradingBot 中提取的自适应参数应用逻辑
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class ParamApplier:
    """参数应用管理器"""

    def __init__(self, config: Any, ai_client: Any):
        self._config = config
        self._ai_client = ai_client

    def apply_adaptive_params(self, current_params: Dict[str, Any]) -> None:
        """应用调整后的参数到主配置"""
        if current_params.get("fusion_threshold"):
            self._config.ai.fusion_threshold = current_params["fusion_threshold"]
        if current_params.get("stop_loss_percent"):
            self._config.ai.stop_loss_percent = current_params["stop_loss_percent"]
        if current_params.get("position_multiplier"):
            self._config.ai.position_multiplier = current_params["position_multiplier"]
        if self._ai_client:
            self._ai_client.update_integrator_config(current_params)

        logger.info(
            f"[自适应] 参数已调整: "
            f"阈值={current_params.get('fusion_threshold', 0):.2f}, "
            f"止损={current_params.get('stop_loss_percent', 0):.2%}, "
            f"仓位乘数={current_params.get('position_multiplier', 1):.2f}"
        )
