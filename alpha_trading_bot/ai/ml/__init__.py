"""
ML Module - 机器学习优化模块
"""

from .weight_optimizer import WeightOptimizer, get_optimized_weights
from .performance_tracker import PerformanceTracker, get_performance_summary
from .ab_test_framework import ABTestFramework, run_ab_test, StrategyType
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
    MarketRegime,
    MomentumStrength,
    MarketContext,
    build_optimized_prompt,
)

__all__ = [
    "WeightOptimizer",
    "get_optimized_weights",
    "PerformanceTracker",
    "get_performance_summary",
    "ABTestFramework",
    "run_ab_test",
    "StrategyType",
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
    "MarketRegime",
    "MomentumStrength",
    "MarketContext",
    "build_optimized_prompt",
]
