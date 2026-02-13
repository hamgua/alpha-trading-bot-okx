"""
高位BUY信号优化器 - BTC友好版

针对高波动资产（如BTC）的价格水平检测
使用基于24小时高低价百分比的阈值检测
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class BTCPriceLevelConfig:
    """BTC价格水平检测配置

    针对BTC等高波动资产的百分比阈值配置

    核心参数说明（重要！）：
    - high_threshold: 高位阈值百分比
      例如：0.97 表示"24小时最高价的97%"
      意味着：如果当前价格 >= 24小时最高价 × 0.97，则为高位
      实际上这个阈值太宽了！应该用更高的值

    - low_threshold: 低位阈值百分比
      例如：1.03 表示"24小时最低价的103%"
      意味着：如果当前价格 <= 24小时最低价 × 1.03，则为低位
      这个理解是错误的！

    正确的理解方式：
    - high_threshold 应该是 "距离高点的百分比"
    - low_threshold 应该是 "距离低点的百分比"

    例如：
    - high_threshold = 0.97 表示"距离高点3%以内"
    - low_threshold = 0.03 表示"距离低点3%以内"
    """

    # 高位阈值：距离24小时高点的百分比
    # 0.97 表示"距离高点3%以内"（高价 × 0.97）
    # 这个值越大，高位范围越宽
    high_threshold: float = 0.97

    # 低位阈值：距离24小时低点的百分比
    # 0.03 表示"距离低点3%以内"（低价 + 区间 × 0.03）
    # 这个值越小，低位范围越窄
    low_threshold: float = 0.03

    # 相对价格位置阈值 (基于近期50个周期)
    relative_mid_threshold: float = 0.70
    relative_high_threshold: float = 0.85

    # 近期高点检测
    recent_high_periods: int = 10
    high_proximity_threshold: float = 0.03

    # 多重确认
    require_multi_confirmation: bool = True


@dataclass
class PriceLevelResult:
    """价格水平检测结果"""

    level: str  # high | mid | low
    confidence: float
    is_high_risk: bool
    is_low_opportunity: bool
    recent_high: float
    recent_low: float
    high_threshold: float
    low_threshold: float
    distance_to_high: float
    distance_to_low: float


class BTCPriceLevelDetector:
    """
    BTC价格水平检测器

    专门针对BTC等高波动资产设计

    检测方法：
    1. 高位检测：价格在24小时高价的一定范围内
    2. 低位检测：价格在24小时低价的一定范围内
    3. 相对位置：价格在近期范围中的位置
    4. 多重确认：至少2种方法确认

    配置建议（针对BTC高波动特性）：
    - 高位阈值：0.97-0.99（距离高点1-3%）
    - 低位阈值：0.01-0.03（距离低点1-3%）
    """

    def __init__(self, config: Optional[BTCPriceLevelConfig] = None):
        self.config = config or BTCPriceLevelConfig()
        self.price_history: list = []

        logger.info(
            f"[BTC价格检测器] 初始化: "
            f"高位阈值={self.config.high_threshold:.0%}, "
            f"低位阈值={self.config.low_threshold:.0%}"
        )

    def detect_level(self, price: float) -> PriceLevelResult:
        """
        检测当前价格水平

        Args:
            price: 当前价格

        Returns:
            PriceLevelResult: 检测结果
        """
        # 更新价格历史
        self.price_history.append(price)
        if len(self.price_history) > 100:
            self.price_history = self.price_history[-100:]

        if len(self.price_history) < 2:
            return self._default_result(price)

        # 获取24小时范围
        recent_prices = self.price_history[-50:]
        recent_high = max(recent_prices)
        recent_low = min(recent_prices)

        if recent_high == recent_low:
            return self._default_result(price)

        price_range = recent_high - recent_low

        # 计算阈值 - 基于价格区间的百分比位置
        high_threshold_price = recent_high - price_range * (
            1 - self.config.high_threshold
        )
        low_threshold_price = recent_low + price_range * self.config.low_threshold

        # 确保阈值合理（high > low）
        if high_threshold_price <= low_threshold_price:
            high_threshold_price = recent_high

        # 计算距离
        distance_to_high = (recent_high - price) / recent_high
        distance_to_low = (price - recent_low) / price_range

        # 判断高位
        is_high = price >= high_threshold_price
        is_low = price <= low_threshold_price

        # 多重确认
        high_confirmations = 0
        if is_high:
            high_confirmations += 1
        if distance_to_high < self.config.high_proximity_threshold:
            high_confirmations += 1
        if self._is_relative_high(price):
            high_confirmations += 1

        low_confirmations = 0
        if is_low:
            low_confirmations += 1
        if self._is_relative_low(price):
            low_confirmations += 1

        # 综合判断
        if self.config.require_multi_confirmation:
            if high_confirmations >= 2:
                level = "high"
                confidence = high_confirmations / 3
            elif low_confirmations >= 2:
                level = "low"
                confidence = low_confirmations / 2
            else:
                level = "mid"
                confidence = 0.5
        else:
            if is_high:
                level = "high"
                confidence = 0.8
            elif is_low:
                level = "low"
                confidence = 0.8
            else:
                level = "mid"
                confidence = 0.5

        # 高风险/低机会判断
        is_high_risk = level == "high" and distance_to_high < 0.01  # 距离高点1%以内
        is_low_opportunity = level == "low" and distance_to_low < 0.01  # 距离低点1%以内

        result = PriceLevelResult(
            level=level,
            confidence=confidence,
            is_high_risk=is_high_risk,
            is_low_opportunity=is_low_opportunity,
            recent_high=recent_high,
            recent_low=recent_low,
            high_threshold=high_threshold_price,
            low_threshold=low_threshold_price,
            distance_to_high=distance_to_high,
            distance_to_low=distance_to_low,
        )

        logger.info(
            f"[BTC价格检测] 价格=${price:,.0f}, "
            f"水平={level}, 高位阈值=${high_threshold_price:,.0f}, "
            f"低位阈值=${low_threshold_price:,.0f}"
        )

        return result

    def _is_relative_high(self, price: float) -> bool:
        """判断是否相对高位"""
        if len(self.price_history) < 10:
            return False
        recent = self.price_history[-50:]
        min_p, max_p = min(recent), max(recent)
        if max_p == min_p:
            return False
        return (price - min_p) / (max_p - min_p) >= self.config.relative_high_threshold

    def _is_relative_low(self, price: float) -> bool:
        """判断是否相对低位"""
        if len(self.price_history) < 10:
            return False
        recent = self.price_history[-50:]
        min_p, max_p = min(recent), max(recent)
        if max_p == min_p:
            return False
        return (max_p - price) / (max_p - min_p) >= (
            1 - self.config.relative_mid_threshold
        )

    def _default_result(self, price: float) -> PriceLevelResult:
        """默认结果（数据不足时）"""
        return PriceLevelResult(
            level="mid",
            confidence=0.5,
            is_high_risk=False,
            is_low_opportunity=False,
            recent_high=price,
            recent_low=price,
            high_threshold=price,
            low_threshold=price,
            distance_to_high=0,
            distance_to_low=0,
        )

    def get_info(self) -> Dict[str, Any]:
        """获取检测器信息"""
        if not self.price_history:
            return {"status": "no_data"}

        current = self.price_history[-1]
        recent_high = max(self.price_history[-50:])
        recent_low = min(self.price_history[-50:])
        range_val = recent_high - recent_low

        return {
            "current_price": current,
            "24h_high": recent_high,
            "24h_low": recent_low,
            "24h_range": range_val,
            "high_threshold": recent_high * self.config.high_threshold,
            "low_threshold": recent_low + range_val * self.config.low_threshold,
            "config": {
                "high_threshold": self.config.high_threshold,
                "low_threshold": self.config.low_threshold,
            },
        }


@dataclass
class EnhancedBuyConfig:
    """增强版买入配置"""

    price_detector = BTCPriceLevelConfig()

    # 高价位买入条件（更严格）
    high_position_threshold: float = 0.10
    high_rsi_threshold: float = 30
    high_trend_threshold: float = 0.40

    # 中价位买入条件
    mid_position_threshold: float = 0.20
    mid_rsi_threshold: float = 35
    mid_trend_threshold: float = 0.30

    # 低价位买入条件（更宽松）
    low_position_threshold: float = 0.30
    low_rsi_threshold: float = 40
    low_trend_threshold: float = 0.15

    # 惩罚/奖励
    high_risk_penalty: float = 0.20
    low_opportunity_bonus: float = 0.10


class EnhancedBuyOptimizer:
    """增强版买入优化器"""

    def __init__(self, config: Optional[EnhancedBuyConfig] = None):
        self.config = config or EnhancedBuyConfig()
        self.detector = BTCPriceLevelDetector(self.config.price_detector)

        logger.info("[增强版买入优化器] 初始化完成")

    def should_buy(
        self,
        price: float,
        rsi: float,
        price_position: float,
        trend_strength: float,
        recent_change: float,
    ) -> Dict[str, Any]:
        """
        增强版买入判断

        Args:
            price: 当前价格
            rsi: RSI值
            price_position: 价格位置 (0-100)
            trend_strength: 趋势强度
            recent_change: 近期变化

        Returns:
            Dict: 决策结果
        """
        # 检测价格水平
        level_result = self.detector.detect_level(price)

        # 选择阈值
        if level_result.level == "high":
            pos_thresh = self.config.high_position_threshold
            rsi_thresh = self.config.high_rsi_threshold
            trend_thresh = self.config.high_trend_threshold
            base_conf = 0.60
        elif level_result.level == "low":
            pos_thresh = self.config.low_position_threshold
            rsi_thresh = self.config.low_rsi_threshold
            trend_thresh = self.config.low_trend_threshold
            base_conf = 0.70
        else:
            pos_thresh = self.config.mid_position_threshold
            rsi_thresh = self.config.mid_rsi_threshold
            trend_thresh = self.config.mid_trend_threshold
            base_conf = 0.65

        # 检查条件
        checks = {
            "position": price_position < pos_thresh * 100,
            "rsi": rsi < rsi_thresh,
            "trend": trend_strength > trend_thresh,
            "momentum": recent_change > 0.003,
        }

        passed = sum(1 for v in checks.values() if v)

        # 计算置信度
        confidence = base_conf + passed * 0.10

        # 惩罚/奖励
        if level_result.is_high_risk:
            confidence -= self.config.high_risk_penalty
            reason = "高风险：距离高点<1%"
        elif level_result.is_low_opportunity:
            confidence += self.config.low_opportunity_bonus
            reason = "低机会：距离低点<1%"
        else:
            reason = f"价格{level_result.level}，{passed}/4条件通过"

        can_buy = confidence >= 0.50 and passed >= 3

        return {
            "can_buy": can_buy,
            "confidence": confidence,
            "price_level": level_result.level,
            "checks": checks,
            "passed": passed,
            "distance_to_high": level_result.distance_to_high,
            "distance_to_low": level_result.distance_to_low,
            "reason": reason,
        }
