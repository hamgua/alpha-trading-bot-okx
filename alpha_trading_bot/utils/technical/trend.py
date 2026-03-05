"""
趋势指标 - ADX、趋势方向和强度
"""

from typing import Dict, List, Any


def calculate_adx(
    high: List[float], low: List[float], close: List[float], period: int = 14
) -> float:
    """计算ADX"""
    if len(high) < period * 2:
        return 0.0

    # 计算+DI和-DI
    plus_dm = []
    minus_dm = []

    for i in range(1, len(high)):
        high_diff = high[i] - high[i - 1]
        low_diff = low[i - 1] - low[i]

        if high_diff > low_diff and high_diff > 0:
            plus_dm.append(high_diff)
        else:
            plus_dm.append(0)

        if low_diff > high_diff and low_diff > 0:
            minus_dm.append(low_diff)
        else:
            minus_dm.append(0)

    # 计算ATR
    from .volatility import calculate_atr

    atr_val, _ = calculate_atr(high, low, close, period)

    if atr_val == 0:
        return 0.0

    plus_di = (sum(plus_dm[-period:]) / period) / atr_val * 100
    minus_di = (sum(minus_dm[-period:]) / period) / atr_val * 100

    dx = (
        abs(plus_di - minus_di) / (plus_di + minus_di) * 100
        if (plus_di + minus_di) > 0
        else 0
    )

    # 平滑ADX
    adx_values = [dx]
    for i in range(1, len(dx) if isinstance(dx, list) else 1):
        adx_values.append(
            (adx_values[-1] * (period - 1) + dx if isinstance(dx, (int, float)) else dx)
            / period
        )

    return adx_values[-1] if adx_values else 0.0


def calculate_trend(
    prices: List[float], short_period: int = 10, long_period: int = 20
) -> Dict[str, Any]:
    """计算趋势方向和强度"""
    if len(prices) < long_period + 1:
        return {"direction": "neutral", "strength": 0.0}

    short_ma = sum(prices[-short_period:]) / short_period
    long_ma = sum(prices[-long_period:]) / long_period

    # 方向
    if prices[-1] > short_ma > long_ma:
        direction = "up"
    elif prices[-1] < short_ma < long_ma:
        direction = "down"
    else:
        direction = "neutral"

    # 强度 (基于价格与均线的距离)
    price_change = (prices[-1] - prices[0]) / prices[0] if prices[0] > 0 else 0
    strength = min(1.0, abs(price_change) * 10)

    return {"direction": direction, "strength": strength}
