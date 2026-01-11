"""
统一价格计算模块
集中管理所有价格相关的计算逻辑
"""

from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass


@dataclass
class PricePosition:
    """价格位置计算结果"""

    daily_position: float  # 日内价格位置 (0-100)
    position_24h: float  # 24小时价格位置 (0-100)
    position_7d: float  # 7日价格位置 (0-100)
    composite_position: float  # 综合价格位置 (0-100)


@dataclass
class StopLossCalculation:
    """止损价格计算结果"""

    stop_price: float
    stop_percentage: float
    calculation_method: str  # 'entry_price_based' 或 'current_price_based'
    reason: str


class PriceCalculator:
    """统一价格计算器"""

    @staticmethod
    def calculate_price_position(
        current_price: float,
        daily_high: float,
        daily_low: float,
        high_24h: Optional[float] = None,
        low_24h: Optional[float] = None,
        high_7d: Optional[float] = None,
        low_7d: Optional[float] = None,
    ) -> PricePosition:
        """
        统一的价格位置计算
        避免在多个文件中重复实现相同的计算逻辑

        Args:
            current_price: 当前价格
            daily_high: 日内最高价
            daily_low: 日内最低价
            high_24h: 24小时最高价 (可选)
            low_24h: 24小时最低价 (可选)
            high_7d: 7日最高价 (可选)
            low_7d: 7日最低价 (可选)

        Returns:
            PricePosition: 包含所有价格位置的计算结果
        """
        # 日内价格位置
        daily_position = 50.0
        if daily_high > daily_low and daily_high != daily_low:
            daily_position = (
                (current_price - daily_low) / (daily_high - daily_low)
            ) * 100

        # 24小时价格位置
        position_24h = 50.0
        if high_24h and low_24h and high_24h > low_24h:
            position_24h = ((current_price - low_24h) / (high_24h - low_24h)) * 100

        # 7日价格位置
        position_7d = 50.0
        if high_7d and low_7d and high_7d > low_7d:
            position_7d = ((current_price - low_7d) / (high_7d - low_7d)) * 100

        # 综合价格位置 (24h: 55%, 7d: 45%)
        composite_position = (position_24h * 0.55) + (position_7d * 0.45)

        return PricePosition(
            daily_position=daily_position,
            position_24h=position_24h,
            position_7d=position_7d,
            composite_position=composite_position,
        )

    @staticmethod
    def calculate_stop_loss_price(
        entry_price: float, current_price: float, position_side: str = "long"
    ) -> StopLossCalculation:
        """
        统一的止损价格计算
        遵循标准规则：
        - 多头：当前价格 > 入场价 → 当前价格 × 0.998 (99.8%)
        - 多头：当前价格 ≤ 入场价 → 入场价 × 0.995 (99.5%)
        - 空头：当前价格 < 入场价 → 当前价格 × 1.002 (100.2%)
        - 空头：当前价格 ≥ 入场价 → 入场价 × 1.005 (100.5%)
        """
        if position_side.lower() == "long":
            if current_price > entry_price:
                stop_price = current_price * 0.998
                stop_percentage = 0.002
                calculation_method = "current_price_based"
                reason = f"多头盈利：当前价格{current_price:.2f} > 入场价{entry_price:.2f}，使用当前价格×99.8%"
            else:
                stop_price = entry_price * 0.995
                stop_percentage = 0.005
                calculation_method = "entry_price_based"
                reason = f"多头亏损：当前价格{current_price:.2f} ≤ 入场价{entry_price:.2f}，使用入场价×99.5%"
        else:  # short
            if current_price < entry_price:
                stop_price = current_price * 1.002
                stop_percentage = 0.002
                calculation_method = "current_price_based"
                reason = f"空头盈利：当前价格{current_price:.2f} < 入场价{entry_price:.2f}，使用当前价格×100.2%"
            else:
                stop_price = entry_price * 1.005
                stop_percentage = 0.005
                calculation_method = "entry_price_based"
                reason = f"空头亏损：当前价格{current_price:.2f} ≥ 入场价{entry_price:.2f}，使用入场价×100.5%"

        return StopLossCalculation(
            stop_price=round(stop_price, 2),
            stop_percentage=stop_percentage,
            calculation_method=calculation_method,
            reason=reason,
        )

    @staticmethod
    def calculate_atr_percentage(atr_value: float, price: float) -> float:
        """
        统一的ATR百分比计算
        避免在多个文件中重复实现 (atr / price) * 100
        """
        if price <= 0 or atr_value < 0:
            return 0.0
        return (atr_value / price) * 100

    @staticmethod
    def calculate_profit_percentage(
        entry_price: float, current_price: float, position_side: str = "long"
    ) -> float:
        """
        统一的利润百分比计算
        """
        if position_side.lower() == "long":
            return ((current_price - entry_price) / entry_price) * 100
        else:  # short
            return ((entry_price - current_price) / entry_price) * 100

    @staticmethod
    def calculate_profit_amount(
        entry_price: float,
        current_price: float,
        position_amount: float,
        position_side: str = "long",
    ) -> float:
        """
        统一的利润金额计算
        """
        if position_side.lower() == "long":
            return (current_price - entry_price) * position_amount
        else:  # short
            return (entry_price - current_price) * position_amount

    @staticmethod
    def get_price_level_description(price_position: float) -> str:
        """
        统一的价格位置描述
        """
        if price_position >= 90:
            return "极高位"
        elif price_position >= 75:
            return "高位"
        elif price_position >= 60:
            return "中高位"
        elif price_position >= 40:
            return "中位"
        elif price_position >= 25:
            return "中低位"
        elif price_position >= 10:
            return "低位"
        else:
            return "极低位"

    @staticmethod
    def calculate_current_price_from_market_data(market_data: Dict[str, Any]) -> float:
        """
        从市场数据中统一提取当前价格
        避免在多个文件中重复实现价格获取逻辑
        """
        return float(market_data.get("price", market_data.get("last", 0)))

    @staticmethod
    def calculate_atr_score(atr_value: float, price: float) -> float:
        """
        统一的ATR评分计算
        避免在strategies/manager.py中重复实现
        """
        if price <= 0:
            return 0.0
        atr_ratio = atr_value / price if price > 0 else 0
        # 将ATR比例转换为0-100的分数
        return min(atr_ratio * 10000, 100)  # 放大并限制在100以内

    @staticmethod
    def calculate_volatility_score(
        price_history: List[float], window: int = 20
    ) -> float:
        """
        统一的价格波动率评分计算
        """
        if len(price_history) < window:
            return 0.0

        # 计算价格变化率的标准差
        changes = []
        for i in range(1, min(window + 1, len(price_history))):
            if price_history[i - 1] > 0:
                change = (price_history[i] - price_history[i - 1]) / price_history[
                    i - 1
                ]
                changes.append(change)

        if not changes:
            return 0.0

        # 计算标准差
        mean_change = sum(changes) / len(changes)
        variance = sum((x - mean_change) ** 2 for x in changes) / len(changes)
        std_dev = math.sqrt(variance)

        # 标准化为0-100的分数
        volatility_score = min(std_dev * 1000, 100)
        return volatility_score
