"""
市场上下文数据模型

包含市场状态分类、动量强度和市场上下文信息
"""

from enum import Enum
from dataclasses import dataclass


class TrendRegime(Enum):
    STRONG_UPTREND = "strong_uptrend"
    WEAK_UPTREND = "weak_uptrend"
    SIDEWAYS = "sideways"
    WEAK_DOWNTREND = "weak_downtrend"
    STRONG_DOWNTREND = "strong_downtrend"


class MomentumStrength(Enum):
    STRONG_POSITIVE = "strong_positive"
    WEAK_POSITIVE = "weak_positive"
    NEUTRAL = "neutral"
    WEAK_NEGATIVE = "weak_negative"
    STRONG_NEGATIVE = "strong_negative"


@dataclass
class MarketContext:
    regime: TrendRegime = TrendRegime.SIDEWAYS
    momentum: MomentumStrength = MomentumStrength.NEUTRAL
    momentum_percent: float = 0.0
    trend_strength: float = 0.0
    confidence: float = 0.5
    consecutive_direction: int = 0
    volatility_level: str = "normal"
    recent_high: float = 0.0
    recent_low: float = 0.0
    price_position: float = 0.5
