"""
波动率指标 - ATR、布林带、真实波幅
"""

from typing import Dict, List, Any


def calculate_true_range(
    high: List[float], low: List[float], close: List[float]
) -> List[float]:
    """计算真实波幅 (TR)"""
    tr = []
    for i in range(len(high)):
        if i == 0:
            tr.append(high[0] - low[0])
        else:
            hl = high[i] - low[i]
            hc = abs(high[i] - close[i - 1])
            lc = abs(low[i] - close[i - 1])
            tr.append(max(hl, max(hc, lc)))
    return tr


def calculate_atr(
    high: List[float], low: List[float], close: List[float], period: int = 14
) -> tuple:
    """计算ATR"""
    if len(high) < period + 1:
        return 0.0, 0.0

    tr = calculate_true_range(high, low, close)
    atr = sum(tr[-period:]) / period

    # 计算ATR百分比
    if close[-1] > 0:
        atr_percent = (atr / close[-1]) * 100
    else:
        atr_percent = 0.0

    return atr, atr_percent


def calculate_bollinger_bands(
    prices: List[float], period: int = 20, std_dev: float = 2.0
) -> Dict[str, float]:
    """计算布林带"""
    if len(prices) < period:
        return {"upper": 0, "middle": 0, "lower": 0, "position": 0.5}

    middle = sum(prices[-period:]) / period

    # 计算标准差
    variance = sum((p - middle) ** 2 for p in prices[-period:]) / period
    std = variance**0.5

    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)

    # 计算价格位置 (0-1)
    if upper != lower:
        position = (prices[-1] - lower) / (upper - lower)
    else:
        position = 0.5

    return {
        "upper": upper,
        "middle": middle,
        "lower": lower,
        "position": max(0, min(1, position)),
    }
