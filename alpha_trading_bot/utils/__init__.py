"""
工具模块
"""

from .technical import (
    calculate_rsi,
    calculate_macd,
    calculate_ema,
    calculate_adx,
    calculate_trend,
    calculate_atr,
    calculate_bollinger_bands,
    calculate_true_range,
    calculate_all_indicators,
)
from .formatters import format_indicators_for_ai
from .observability import (
    get_runtime_metrics,
    get_runtime_slo_snapshot,
    record_fallback_invocation,
    record_gemini_request,
    record_live_guard_block,
)

__version__ = "1.0.0"

__all__ = [
    # 技术指标
    "calculate_rsi",
    "calculate_macd",
    "calculate_ema",
    "calculate_adx",
    "calculate_trend",
    "calculate_atr",
    "calculate_bollinger_bands",
    "calculate_true_range",
    "calculate_all_indicators",
    # 格式化工具
    "format_indicators_for_ai",
    # 观测指标
    "record_gemini_request",
    "record_fallback_invocation",
    "record_live_guard_block",
    "get_runtime_metrics",
    "get_runtime_slo_snapshot",
]
