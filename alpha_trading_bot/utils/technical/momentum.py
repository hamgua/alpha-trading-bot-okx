"""
动量指标 - RSI、MACD、EMA
"""

from typing import Dict, List, Any


def calculate_ema(data: List[float], period: int) -> List[float]:
    """计算指数移动平均"""
    if len(data) < period:
        return data

    multiplier = 2 / (period + 1)
    ema = [sum(data[:period]) / period]

    for i in range(period, len(data)):
        ema.append((data[i] - ema[-1]) * multiplier + ema[-1])

    return ema


def calculate_rsi(prices: List[float], period: int = 14) -> float:
    """计算RSI"""
    if len(prices) < period + 1:
        return 50.0

    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    # 使用指数移动平均
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return max(0, min(100, rsi))


def calculate_macd(
    prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> Dict[str, float]:
    """计算MACD"""
    if len(prices) < slow + signal:
        return {"macd": 0, "signal": 0, "histogram": 0}

    fast_ema = calculate_ema(prices, fast)
    slow_ema = calculate_ema(prices, slow)

    # 对齐长度
    slow_start = len(slow_ema) - len(fast_ema)
    macd_line = [fast_ema[i] - slow_ema[slow_start + i] for i in range(len(fast_ema))]

    # 信号线
    signal_ema = calculate_ema(macd_line, signal)

    histogram = macd_line[-1] - signal_ema[-1]

    return {
        "macd": macd_line[-1] if macd_line else 0,
        "signal": signal_ema[-1] if signal_ema else 0,
        "histogram": histogram,
    }
