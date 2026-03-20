"""
ML Module - 机器学习优化模块
"""

from .weight_optimizer import WeightOptimizer, get_optimized_weights
from .performance_tracker import PerformanceTracker, get_performance_summary
from .ab_test_framework import ABTestFramework, run_ab_test, ABTestVariant
from .trend_detector import (
    EnhancedTrendDetector,
    TrendDirection,
    TrendState,
    detect_market_trend,
)
from .adaptive_fusion import (
    AdaptiveFusionStrategy,
    FusionConfig,
    FusionMode,
    adaptive_fuse,
)
from .monitoring_dashboard import (
    MonitoringDashboard,
    AlertManager,
    get_dashboard_status,
)
from ..prompt_optimizer import (
    OptimizedPromptBuilder,
    build_optimized_prompt,
)
from ..prompt_context import (
    TrendRegime,
    MomentumStrength,
    MarketContext,
)

__all__ = [
    "WeightOptimizer",
    "get_optimized_weights",
    "PerformanceTracker",
    "get_performance_summary",
    "ABTestFramework",
    "run_ab_test",
    "ABTestVariant",
    "EnhancedTrendDetector",
    "TrendDirection",
    "TrendState",
    "detect_market_trend",
    "AdaptiveFusionStrategy",
    "FusionConfig",
    "FusionMode",
    "adaptive_fuse",
    "MonitoringDashboard",
    "AlertManager",
    "get_dashboard_status",
    "OptimizedPromptBuilder",
    "TrendRegime",
    "MomentumStrength",
    "MarketContext",
    "build_optimized_prompt",
]
