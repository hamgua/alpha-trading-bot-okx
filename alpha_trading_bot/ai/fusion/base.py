"""
融合策略基类
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .consensus_boosted import FusionResult

logger = logging.getLogger(__name__)


class FusionStrategy(ABC):
    """融合策略基类"""

    @abstractmethod
    def fuse(
        self,
        signals: List[Dict[str, str]],
        weights: Dict[str, float],
        threshold: float,
        *,
        confidences: Optional[Dict[str, float]] = None,
        market_data: Optional[Dict[str, Any]] = None,
    ) -> "FusionResult":
        """
        融合信号

        Args:
            signals: [{"provider": "deepseek", "signal": "buy"}, ...]
            weights: {"deepseek": 0.5, "kimi": 0.5, ...}
            threshold: 融合阈值
            confidences: {"deepseek": 0.7, "kimi": 0.75, ...} 置信度（可选）
            market_data: 市场数据字典，用于动态阈值计算（可选）

        Returns:
            融合结果对象（包含 signal/confidence/scores）
        """
        pass

    def _log_result(self, strategy_name: str, result: str, details: str) -> None:
        """记录融合结果"""
        logger.info(f"融合结果({strategy_name}): {result} ({details})")


# 策略缓存（延迟加载）
_strategy_cache: Optional[FusionStrategy] = None
_strategy_cache_name: Optional[str] = None


def get_fusion_strategy(name: str) -> FusionStrategy:
    """获取融合策略实例（延迟加载）"""
    global _strategy_cache, _strategy_cache_name

    if _strategy_cache_name == name and _strategy_cache is not None:
        return _strategy_cache

    # 延迟导入策略类
    if name == "weighted":
        from .weighted import WeightedFusion

        _strategy_cache = WeightedFusion()
    elif name == "majority":
        from .majority import MajorityFusion

        _strategy_cache = MajorityFusion()
    elif name == "consensus":
        from .consensus import ConsensusFusion

        _strategy_cache = ConsensusFusion()
    elif name == "confidence":
        from .confidence import ConfidenceFusion

        _strategy_cache = ConfidenceFusion()
    elif name == "consensus_boosted":
        from .consensus_boosted import ConsensusBoostedFusion

        _strategy_cache = ConsensusBoostedFusion()
    else:
        from .consensus_boosted import ConsensusBoostedFusion

        _strategy_cache = ConsensusBoostedFusion()

    _strategy_cache_name = name
    return _strategy_cache
