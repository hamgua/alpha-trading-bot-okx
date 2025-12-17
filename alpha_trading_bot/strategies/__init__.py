"""
策略模块 - 交易策略的实现和管理
"""

from .manager import (
    StrategyManager,
    create_strategy_manager,
    # MarketAnalyzer,  # 暂时注释掉
    # StrategySelector,
    # StrategyBacktestEngine,
    # StrategyOptimizer,
    # StrategyMonitor,
    # StrategyExecutor,
    # StrategyBehaviorHandler,
    generate_enhanced_fallback_signal,
    get_strategy_manager
)

__all__ = [
    # 策略管理器
    'StrategyManager',
    'create_strategy_manager',
    'get_strategy_manager',

    # 向后兼容的别名
    # 'MarketAnalyzer',
    # 'StrategySelector',
    # 'StrategyBacktestEngine',
    # 'StrategyOptimizer',
    # 'StrategyMonitor',
    # 'StrategyExecutor',
    # 'StrategyBehaviorHandler',
    'generate_enhanced_fallback_signal'
]