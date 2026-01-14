"""
高位预警保护模块
在价格高峰期自动增强保护机制，防止追高买入
"""

import logging
from typing import Dict, Any, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class HighPriceLevel(Enum):
    """高位级别"""

    NORMAL = "normal"  # 正常 (< 70%)
    ELEVATED = "elevated"  # 偏高 (70-85%)
    HIGH = "high"  # 高位 (85-95%)
    EXTREME = "extreme"  # 极高 (> 95%)


@dataclass
class HighPriceProtectionConfig:
    """高位保护配置"""

    # 各级别的价格位置阈值
    elevated_threshold: float = 0.70  # 70%
    high_threshold: float = 0.85  # 85%
    extreme_threshold: float = 0.95  # 95%

    # 高位时的信心度要求提升
    elevated_confidence_boost: float = 0.05  # 偏高时+5%
    high_confidence_boost: float = 0.10  # 高位时+10%
    extreme_confidence_boost: float = 0.15  # 极高时+15%

    # 回调买入参数
    pullback_ma_periods: list = None  # 均线周期列表
    pullback_max_distance: float = 0.10  # 最大回调距离10%

    # 缓存时间调整
    normal_cache_duration: int = 900  # 15分钟
    high_cache_duration: int = 300  # 5分钟
    extreme_cache_duration: int = 60  # 1分钟

    def __post_init__(self):
        if self.pullback_ma_periods is None:
            self.pullback_ma_periods = [20, 50, 200]  # 20日/50日/200日均线


class HighPriceProtection:
    """高位预警保护器"""

    def __init__(self, config: Optional[HighPriceProtectionConfig] = None):
        if config is None:
            config = HighPriceProtectionConfig()
        self.config = config

    def get_price_level(self, price_position: float) -> HighPriceLevel:
        """
        根据价格位置判断高位级别

        Args:
            price_position: 价格位置 (0-1)

        Returns:
            HighPriceLevel: 高位级别
        """
        if price_position >= self.config.extreme_threshold:
            return HighPriceLevel.EXTREME
        elif price_position >= self.config.high_threshold:
            return HighPriceLevel.HIGH
        elif price_position >= self.config.elevated_threshold:
            return HighPriceLevel.ELEVATED
        else:
            return HighPriceLevel.NORMAL

    def get_required_confidence_boost(
        self, price_position: float, trend_strength: float = 0.0
    ) -> float:
        """
        获取高位时需要的信心度提升

        Args:
            price_position: 价格位置 (0-1)
            trend_strength: 趋势强度 (-1到1)

        Returns:
            float: 需要的信心度提升
        """
        level = self.get_price_level(price_position)
        base_boost = {
            HighPriceLevel.NORMAL: 0.0,
            HighPriceLevel.ELEVATED: self.config.elevated_confidence_boost,
            HighPriceLevel.HIGH: self.config.high_confidence_boost,
            HighPriceLevel.EXTREME: self.config.extreme_confidence_boost,
        }[level]

        # 如果是上涨趋势且在高位，减少一些惩罚（允许顺势买入）
        if trend_strength > 0.3 and level in [
            HighPriceLevel.HIGH,
            HighPriceLevel.ELEVATED,
        ]:
            base_boost *= 0.5  # 减半惩罚

        # 如果是下跌趋势且在高位，增加惩罚
        if trend_strength < -0.1 and level in [
            HighPriceLevel.HIGH,
            HighPriceLevel.EXTREME,
        ]:
            base_boost *= 1.5  # 增加50%惩罚

        return base_boost

    def check_pullback_opportunity(
        self, current_price: float, close_prices: list, trend_direction: str = "up"
    ) -> Tuple[bool, float, str]:
        """
        检查是否处于回调买入机会

        Args:
            current_price: 当前价格
            close_prices: 收盘价历史
            trend_direction: 趋势方向

        Returns:
            (是否回调机会, 回调幅度, 说明)
        """
        if not close_prices or len(close_prices) < max(self.config.pullback_ma_periods):
            return False, 0.0, "数据不足"

        if trend_direction != "up":
            return False, 0.0, "非上涨趋势，不考虑回调买入"

        import numpy as np

        prices = np.array(close_prices)

        # 计算各均线
        ma_levels = {}
        for period in self.config.pullback_ma_periods:
            if len(prices) >= period:
                ma_levels[period] = np.mean(prices[-period:])

        if not ma_levels:
            return False, 0.0, "均线数据不足"

        # 获取短期均线（最近的一个）
        short_ma_period = min(ma_levels.keys())
        short_ma = ma_levels[short_ma_period]

        # 计算价格到均线的回调距离
        if current_price > short_ma:
            # 价格在均线上方，计算回调比例
            distance = (current_price - short_ma) / current_price
            pullback_pct = distance * 100

            # 判断是否在合理回调范围内
            max_distance = self.config.pullback_max_distance

            if distance <= max_distance:
                # 合理回调区间
                return (
                    True,
                    pullback_pct,
                    f"回调至{short_ma_period}日均线附近({pullback_pct:.1f}%)",
                )
            else:
                # 回调过深
                return (
                    False,
                    pullback_pct,
                    f"回调过深({pullback_pct:.1f}%)，超过{max_distance * 100:.0f}%",
                )
        else:
            # 价格在均线下方，可能处于下跌趋势
            distance = (short_ma - current_price) / current_price
            return False, -distance * 100, f"价格低于{short_ma_period}日均线"

    def get_cache_duration(
        self, price_position: float, market_volatility: float = 0.25
    ) -> int:
        """
        根据价格位置获取缓存时长

        Args:
            price_position: 价格位置 (0-1)
            market_volatility: 市场波动率

        Returns:
            int: 缓存时长（秒）
        """
        level = self.get_price_level(price_position)

        # 高波动市场缩短缓存
        volatility_factor = 1.0
        if market_volatility > 0.5:
            volatility_factor = 0.5
        elif market_volatility > 0.3:
            volatility_factor = 0.7

        cache_duration = {
            HighPriceLevel.NORMAL: self.config.normal_cache_duration,
            HighPriceLevel.ELEVATED: self.config.high_cache_duration,
            HighPriceLevel.HIGH: self.config.high_cache_duration,
            HighPriceLevel.EXTREME: self.config.extreme_cache_duration,
        }[level]

        return int(cache_duration * volatility_factor)

    def get_buy_conditions(
        self,
        price_position: float,
        trend_strength: float = 0.0,
        trend_direction: str = "neutral",
        rsi: float = 50.0,
        volume_ratio: float = 1.0,
    ) -> Tuple[bool, float, str]:
        """
        综合评估高位时的买入条件

        Args:
            price_position: 价格位置 (0-1)
            trend_strength: 趋势强度 (-1到1)
            trend_direction: 趋势方向
            rsi: RSI指标
            volume_ratio: 成交量比率

        Returns:
            (是否满足条件, 信心度要求, 说明)
        """
        level = self.get_price_level(price_position)

        # 基础信心度要求
        base_confidence = {
            HighPriceLevel.NORMAL: 0.50,
            HighPriceLevel.ELEVATED: 0.60,
            HighPriceLevel.HIGH: 0.70,
            HighPriceLevel.EXTREME: 0.80,
        }[level]

        # 趋势方向调整
        trend_bonus = 0.0
        trend_reason = ""

        if trend_direction == "up":
            if trend_strength > 0.5:
                trend_bonus = 0.05  # 强上涨趋势，可以稍低要求
                trend_reason = "强上涨趋势允许稍低信心度"
            elif trend_strength > 0.2:
                trend_bonus = 0.0  # 正常要求
                trend_reason = "正常上涨趋势"
        elif trend_direction == "down":
            trend_bonus = -0.15  # 下跌趋势需要更高信心度
            trend_reason = "下跌趋势需要更严格条件"
        else:
            trend_bonus = 0.0  # 中性

        # RSI调整
        rsi_adjustment = 0.0
        rsi_reason = ""

        if level != HighPriceLevel.NORMAL:
            if rsi < 50:
                rsi_adjustment = 0.08  # 低RSI是利好
                rsi_reason = f"RSI({rsi:.1f})偏低，支持买入"
            elif rsi < 60:
                rsi_adjustment = 0.0  # 正常
                rsi_reason = f"RSI({rsi:.1f})中性"
            elif rsi < 70:
                rsi_adjustment = -0.05  # RSI偏高是利空
                rsi_reason = f"RSI({rsi:.1f})偏高，需要更高信心度"
            else:
                rsi_adjustment = -0.10  # RSI过高是强烈利空
                rsi_reason = f"RSI({rsi:.1f})超买，强烈不建议买入"

        # 成交量调整
        volume_adjustment = 0.0
        volume_reason = ""

        if level != HighPriceLevel.NORMAL:
            if volume_ratio > 1.5:
                volume_adjustment = 0.05  # 放量是利好
                volume_reason = f"成交量放大({volume_ratio:.1f}倍)"
            elif volume_ratio < 0.8:
                volume_adjustment = -0.05  # 缩量是利空
                volume_reason = f"成交量萎缩({volume_ratio:.1f}倍)"
            else:
                volume_reason = "成交量正常"

        # 计算最终信心度要求
        required_confidence = (
            base_confidence - trend_bonus - rsi_adjustment - volume_adjustment
        )
        required_confidence = max(0.3, min(0.95, required_confidence))  # 限制范围

        # 合成说明
        reasons = []
        reasons.append(f"高位级别: {level.value}")
        reasons.append(f"基础要求: {base_confidence:.0%}")
        if trend_reason:
            reasons.append(trend_reason)
        if rsi_reason:
            reasons.append(rsi_reason)
        if volume_reason:
            reasons.append(volume_reason)

        # 判断是否满足条件
        # 基础条件：趋势不是下跌
        trend_ok = trend_direction != "down" or trend_strength > -0.3

        # RSI条件：不超过70（高位时）
        rsi_ok = True
        if level != HighPriceLevel.NORMAL and rsi >= 70:
            rsi_ok = False

        can_buy = trend_ok and rsi_ok

        return can_buy, required_confidence, " | ".join(reasons)

    def get_protection_summary(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        获取高位保护摘要

        Args:
            market_data: 市场数据

        Returns:
            Dict: 保护摘要
        """
        price_position = market_data.get("composite_price_position", 50.0) / 100.0
        trend_strength = market_data.get("trend_strength", 0.0)
        trend_direction = market_data.get("trend_direction", "neutral")
        rsi = market_data.get("technical_data", {}).get("rsi", 50.0)
        volume_ratio = market_data.get("volume_ratio", 1.0)

        level = self.get_price_level(price_position)
        cache_duration = self.get_cache_duration(price_position)
        can_buy, required_confidence, reason = self.get_buy_conditions(
            price_position, trend_strength, trend_direction, rsi, volume_ratio
        )

        return {
            "price_level": level.value,
            "price_position_pct": f"{price_position * 100:.1f}%",
            "trend_direction": trend_direction,
            "trend_strength": f"{trend_strength:.2f}",
            "rsi": f"{rsi:.1f}",
            "required_confidence": f"{required_confidence:.0%}",
            "cache_duration_seconds": cache_duration,
            "can_buy": can_buy,
            "protection_reason": reason,
        }


# 全局实例
high_price_protection = HighPriceProtection()


def check_high_price_protection(market_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    便捷的高位保护检查函数

    Args:
        market_data: 市场数据

    Returns:
        Dict: 保护检查结果
    """
    return high_price_protection.get_protection_summary(market_data)
