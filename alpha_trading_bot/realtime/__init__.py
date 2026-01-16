"""
实时监控模块 - 渐进式实时化系统
"""

from .quick_signal_analyzer import (
    QuickSignalAnalyzer,
    QuickSignalRecord,
    SignalQualityMetrics,
    quick_signal_analyzer,
)
from .conservative_trader import (
    ConservativeTrader,
    ConservativeTraderConfig,
    TradeDecision,
    TradingStats,
    TradingMode,
    ConservativeTrader as ConservativeTraderClass,
)

# 创建全局实例
conservative_trader = ConservativeTraderClass()

__all__ = [
    "QuickSignalAnalyzer",
    "QuickSignalRecord",
    "SignalQualityMetrics",
    "quick_signal_analyzer",
    "ConservativeTrader",
    "ConservativeTraderConfig",
    "TradeDecision",
    "TradingStats",
    "TradingMode",
    "conservative_trader",
]
