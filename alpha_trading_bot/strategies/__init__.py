"""
策略模块 - 交易策略的实现和管理
"""

from .manager import (
    StrategyManager,
    create_strategy_manager,
    MarketAnalyzer,
    StrategySelector,
    StrategyBacktestEngine,
    StrategyOptimizer,
    StrategyMonitor,
    StrategyExecutor,
    StrategyBehaviorHandler,
    generate_enhanced_fallback_signal
)

__all__ = [
    # 策略管理器
    'StrategyManager',
    'create_strategy_manager',

    # 向后兼容的别名
    'MarketAnalyzer',
    'StrategySelector',
    'StrategyBacktestEngine',
    'StrategyOptimizer',
    'StrategyMonitor',
    'StrategyExecutor',
    'StrategyBehaviorHandler',
    'generate_enhanced_fallback_signal'
]