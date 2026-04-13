"""
Core Managers - 职责分离后的专门管理器

将 AdaptiveTradingBot 的职责拆分到专门的 Manager 类中：
- MarketRegimeManager: 市场状态管理
- StrategyExecutionManager: 策略执行管理
- RiskControlManager: 风险管理
- ParameterManager: 参数管理
- LearningManager: 学习模块管理
"""

from .market_regime_manager import MarketRegimeManager
from .strategy_manager import StrategyExecutionManager
from .risk_manager import RiskControlManager
from .parameter_manager import ParameterManager
from .learning_manager import LearningManager

__all__ = [
    "MarketRegimeManager",
    "StrategyExecutionManager",
    "RiskControlManager",
    "ParameterManager",
    "LearningManager",
]
