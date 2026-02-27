"""
技术指标库
纯Python实现，不依赖外部库
"""

from typing import Any, Dict, List

from .momentum import calculate_ema, calculate_macd, calculate_rsi
from .trend import calculate_adx, calculate_trend
from .volatility import calculate_atr, calculate_bollinger_bands, calculate_true_range

__version__ = "1.0.0"

__all__ = [
    # 动量指标
    "calculate_rsi",
    "calculate_macd",
    "calculate_ema",
    # 趋势指标
    "calculate_adx",
    "calculate_trend",
    # 波动率指标
    "calculate_atr",
    "calculate_bollinger_bands",
    "calculate_true_range",
]


def calculate_all_indicators(
    prices: List[float], highs: List[float], lows: List[float], closes: List[float]
) -> Dict[str, Any]:
    """计算所有技术指标"""
    result: Dict[str, Any] = {}

    # RSI
    result["rsi"] = calculate_rsi(closes, 14)

    # MACD
    macd_data = calculate_macd(closes)
    result["macd"] = macd_data["macd"]
    result["macd_signal"] = macd_data["signal"]
    result["macd_histogram"] = macd_data["histogram"]

    # ADX
    result["adx"] = calculate_adx(highs, lows, closes, 14)

    # ATR
    atr_val, atr_percent = calculate_atr(highs, lows, closes, 14)
    result["atr"] = atr_val
    result["atr_percent"] = atr_percent

    # 布林带
    bb = calculate_bollinger_bands(closes)
    result["bb_upper"] = bb["upper"]
    result["bb_lower"] = bb["lower"]
    result["bb_middle"] = bb["middle"]
    result["bb_position"] = bb["position"]

    # 趋势
    trend = calculate_trend(closes)
    result["trend_direction"] = trend["direction"]
    result["trend_strength"] = trend["strength"]

    # 添加状态描述
    if result["rsi"] < 30:
        result["rsi_state"] = "oversold"
    elif result["rsi"] > 70:
        result["rsi_state"] = "overbought"
    else:
        result["rsi_state"] = "normal"

    if result["macd_histogram"] > 0:
        result["macd_state"] = "bullish"
    elif result["macd_histogram"] < 0:
        result["macd_state"] = "bearish"
    else:
        result["macd_state"] = "neutral"

    if result["adx"] < 25:
        result["adx_state"] = "weak"
    elif result["adx"] < 50:
        result["adx_state"] = "moderate"
    else:
        result["adx_state"] = "strong"

    if result["atr_percent"] < 1.0:
        result["volatility_state"] = "low"
    elif result["atr_percent"] < 3.0:
        result["volatility_state"] = "normal"
    else:
        result["volatility_state"] = "high"

    return result
