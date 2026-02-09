"""
Enhanced Trend Detector with ML - 市场趋势检测模块
"""

from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum
from collections import deque
import logging

logger = logging.getLogger(__name__)


class TrendDirection(Enum):
    UP = "up"
    DOWN = "down"
    NEUTRAL = "neutral"


@dataclass
class TrendState:
    direction: TrendDirection
    strength: float
    confidence: float
    momentum: float
    volatility: str


class EnhancedTrendDetector:
    """增强版趋势检测器"""

    def __init__(
        self,
        sma_short: int = 5,
        sma_long: int = 20,
        momentum_periods: int = 12,
        price_history_size: int = 100,
    ):
        self.sma_short = sma_short
        self.sma_long = sma_long
        self.momentum_periods = momentum_periods
        self.price_history = deque(maxlen=price_history_size)

    def add_price(self, price: float):
        self.price_history.append(price)

    def calculate_sma(self, period: int) -> Optional[float]:
        if len(self.price_history) < period:
            return None
        return sum(list(self.price_history)[-period:]) / period

    def detect_trend(self) -> TrendState:
        if len(self.price_history) < self.sma_long:
            return TrendState(
                direction=TrendDirection.NEUTRAL,
                strength=0.0,
                confidence=0.0,
                momentum=0.0,
                volatility="normal",
            )

        sma5 = self.calculate_sma(self.sma_short)
        sma20 = self.calculate_sma(self.sma_long)
        price = self.price_history[-1]

        if sma5 is None or sma20 is None:
            return TrendState(
                direction=TrendDirection.NEUTRAL,
                strength=0.0,
                confidence=0.0,
                momentum=0.0,
                volatility="normal",
            )

        if price > sma5 > sma20:
            direction = TrendDirection.UP
        elif price < sma5 < sma20:
            direction = TrendDirection.DOWN
        else:
            direction = TrendDirection.NEUTRAL

        strength = abs(price - sma20) / sma20 if sma20 > 0 else 0
        strength = min(1.0, strength * 10)

        momentum = self._calculate_momentum()
        volatility = self._calculate_volatility()

        confidence = min(0.95, 0.5 + strength * 0.3 + abs(momentum) * 20)

        return TrendState(
            direction=direction,
            strength=strength,
            confidence=confidence,
            momentum=momentum,
            volatility=volatility,
        )

    def _calculate_momentum(self) -> float:
        if len(self.price_history) < self.momentum_periods + 1:
            return 0.0

        current = self.price_history[-1]
        past = self.price_history[-self.momentum_periods - 1]

        return (current - past) / past if past > 0 else 0.0

    def _calculate_volatility(self) -> str:
        if len(self.price_history) < 20:
            return "normal"

        prices = list(self.price_history)[-20:]
        returns = [
            (prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, len(prices))
        ]

        avg_return = sum(returns) / len(returns)
        variance = sum((r - avg_return) ** 2 for r in returns) / len(returns)
        std_return = variance**0.5

        if std_return > 0.04:
            return "high"
        elif std_return < 0.01:
            return "low"
        return "normal"

    def get_market_context(self) -> Dict[str, Any]:
        trend = self.detect_trend()

        sma5 = self.calculate_sma(self.sma_short)
        sma20 = self.calculate_sma(self.sma_long)

        return {
            "trend_direction": trend.direction.value,
            "trend_strength": trend.strength,
            "trend_confidence": trend.confidence,
            "momentum": trend.momentum,
            "momentum_percent": trend.momentum * 100,
            "volatility": trend.volatility,
            "sma_short": sma5,
            "sma_long": sma20,
            "sma_bullish": sma5 > sma20 if sma5 and sma20 else False,
            "price_vs_sma5": (self.price_history[-1] - sma5) / sma5 if sma5 else 0,
            "price_vs_sma20": (self.price_history[-1] - sma20) / sma20 if sma20 else 0,
        }


def detect_market_trend(market_data: Dict[str, Any]) -> Dict[str, Any]:
    detector = EnhancedTrendDetector()

    if "price" in market_data:
        detector.add_price(market_data["price"])

    return detector.get_market_context()
