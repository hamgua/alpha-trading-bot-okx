"""
增强版高位BUY信号优化器

改进点：
1. 绝对价格阈值检测
2. 相对价格位置检测
3. 近期高点检测
4. 多重确认机制
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class PriceLevelDetectorConfig:
    """价格水平检测配置"""

    # 基于24小时高低的百分比阈值
    high_threshold_percent: float = 0.97  # 价格在24小时高价的97%以上 = 高位
    low_threshold_percent: float = 1.03  # 价格在24小时低价的103%以上 = 低位

    # 相对价格位置阈值 (基于近期价格范围)
    relative_price_mid_threshold: float = 0.70
    relative_price_high_threshold: float = 0.85

    # 近期高点检测
    recent_high_periods: int = 10
    high_proximity_threshold: float = 0.03  # 价格在近期高点3%以内

    # 多重确认要求
    require_multi_confirmation: bool = True
    confirmation_methods_required: int = 2


@dataclass
class PriceLevelResult:
    """价格水平检测结果"""

    level: str  # absolute_high | relative_high | mid | low | absolute_low
    confidence: float
    detection_methods: Dict[str, bool]
    is_high_risk: bool
    is_low_opportunity: bool
    recent_high_price: float
    distance_to_high: float


class PriceLevelDetector:
    """
    价格水平检测器

    检测方法：
    1. 绝对价格检测 - 基于固定阈值（如 > $69,000 为高价）
    2. 相对价格位置检测 - 基于近期价格范围的位置
    3. 近期高点检测 - 是否接近近期最高点
    4. 价格趋势检测 - 判断价格运动方向

    判断逻辑：
    - 至少2种方法确认才算有效
    - 高风险信号：绝对高价 + 接近近期高点
    - 低机会信号：绝对低价 + 处于近期低点
    """

    def __init__(self, config: Optional[PriceLevelDetectorConfig] = None):
        self.config = config or PriceLevelDetectorConfig()
        self.price_history: list = []

        logger.info(
            f"[价格水平检测器] 初始化完成: "
            f"24小时高价阈值={self.config.high_threshold_percent:.0%}, "
            f"相对高位阈值={self.config.relative_price_high_threshold:.0%}"
        )

    def detect_price_level(self, price: float) -> PriceLevelResult:
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

        # 1. 绝对价格检测
        absolute_detection = self._detect_absolute_level(price)

        # 2. 相对价格位置检测
        relative_detection = self._detect_relative_level(price)

        # 3. 近期高点检测
        recent_high = self._get_recent_high()
        distance_to_high = (recent_high - price) / recent_high if recent_high > 0 else 0
        near_high = distance_to_high < self.config.high_proximity_threshold

        # 4. 构建检测结果
        detection_methods = {
            "absolute_high": absolute_detection == "high",
            "absolute_low": absolute_detection == "low",
            "relative_high": relative_detection == "relative_high",
            "relative_low": relative_detection == "relative_low",
            "near_recent_high": near_high,
        }

        # 计算确认数量
        high_confirmations = sum(
            [
                detection_methods["absolute_high"],
                detection_methods["relative_high"],
                detection_methods["near_recent_high"],
            ]
        )

        low_confirmations = sum(
            [
                detection_methods["absolute_low"],
                detection_methods["relative_low"],
            ]
        )

        # 综合判断
        if self.config.require_multi_confirmation:
            # 需要至少2种方法确认
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
            # 使用绝对价格为主
            if absolute_detection == "absolute_high":
                level = "high"
                confidence = 0.8
            elif absolute_detection == "absolute_low":
                level = "low"
                confidence = 0.8
            else:
                level = relative_detection
                confidence = 0.6

        # 判断高风险和低机会
        is_high_risk = level == "high" and detection_methods["near_recent_high"]
        is_low_opportunity = (
            level == "low" and not detection_methods["near_recent_high"]
        )

        result = PriceLevelResult(
            level=level,
            confidence=confidence,
            detection_methods=detection_methods,
            is_high_risk=is_high_risk,
            is_low_opportunity=is_low_opportunity,
            recent_high_price=recent_high,
            distance_to_high=distance_to_high,
        )

        logger.info(
            f"[价格水平检测] 价格=${price:,.0f}, 水平={level}, "
            f"高风险={is_high_risk}, 近期高点=${recent_high:,.0f}"
        )

        return result

    def _detect_absolute_level(self, price: float) -> str:
        """
        基于24小时高低的百分比检测

        计算当前价格在区间24小时高低中的位置：
        - 高位：价格在24小时高价的97%以上
        - 低位：价格在24小时低价的103%以上
        - 中位：其他情况

        Returns:
            str: high | mid | low
        """
        if len(self.price_history) < 2:
            return "mid"

        # 获取24小时最高价和最低价
        recent_24h = self.price_history[-50:]  # 约24小时的数据
        high_24h = max(recent_24h)
        low_24h = min(recent_24h)

        if high_24h == low_24h:
            return "mid"

        # 计算价格区间
        price_range = high_24h - low_24h

        # 计算当前价格相对于高低价的位置
        high_threshold = high_24h - (
            price_range * (1 - self.config.high_threshold_percent)
        )
        low_threshold = low_24h + (
            price_range * (self.config.low_threshold_percent - 1)
        )

        if price >= high_threshold:
            return "high"
        elif price <= low_threshold:
            return "low"
        else:
            return "mid"

    def _detect_relative_level(self, price: float) -> str:
        """
        相对价格位置检测

        基于近期价格范围判断当前位置

        Returns:
            str: relative_high | mid | relative_low
        """
        if len(self.price_history) < 10:
            return "mid"

        # 计算近期价格范围
        recent_prices = self.price_history[-50:]  # 近期50个价格
        min_price = min(recent_prices)
        max_price = max(recent_prices)
        price_range = max_price - min_price

        if price_range == 0:
            return "mid"

        # 计算相对位置
        relative_position = (price - min_price) / price_range

        if relative_position >= self.config.relative_price_high_threshold:
            return "relative_high"
        elif relative_position <= (1 - self.config.relative_price_high_threshold):
            return "relative_low"
        else:
            return "mid"

    def _get_recent_high(self) -> float:
        """获取近期最高价"""
        if len(self.price_history) < self.config.recent_high_periods:
            return max(self.price_history) if self.price_history else 0
        return max(self.price_history[-self.config.recent_high_periods :])

    def get_price_level_info(self) -> Dict[str, Any]:
        """获取价格水平信息"""
        if not self.price_history:
            return {"status": "no_data"}

        current = self.price_history[-1]
        recent_high = self._get_recent_high()
        recent_low = (
            min(self.price_history[-10:])
            if len(self.price_history) >= 10
            else min(self.price_history)
        )

        return {
            "current_price": current,
            "recent_high": recent_high,
            "recent_low": recent_low,
            "price_range": recent_high - recent_low,
            "relative_position": (current - recent_low) / (recent_high - recent_low)
            if recent_high != recent_low
            else 0.5,
            "absolute_level": self._detect_absolute_level(current),
            "relative_level": self._detect_relative_level(current),
        }


# ============================================
# 以下是整合了价格检测的增强版买入优化器
# ============================================


@dataclass
class EnhancedBuyConfig:
    """增强版买入配置"""

    # 价格水平检测配置
    price_detector = PriceLevelDetectorConfig()

    # 高价位买入阈值 (更严格)
    high_price_position_threshold: float = 0.10  # 低于近期10%
    high_rsi_threshold: float = 30  # RSI < 30
    high_trend_strength_threshold: float = 0.40  # 趋势强度 > 0.40

    # 中价位买入阈值
    mid_price_position_threshold: float = 0.20
    mid_rsi_threshold: float = 35
    mid_trend_strength_threshold: float = 0.30

    # 低价位买入阈值 (更宽松)
    low_price_position_threshold: float = 0.30
    low_rsi_threshold: float = 40
    low_trend_strength_threshold: float = 0.15

    # 惩罚机制
    high_risk_penalty: float = 0.20  # 高风险时惩罚20%
    low_opportunity_bonus: float = 0.10  # 低机会时奖励10%


class EnhancedBuyOptimizer:
    """
    增强版买入优化器

    特点：
    1. 精确的价格水平检测（绝对 + 相对）
    2. 多重确认机制
    3. 高风险预警
    4. 低机会识别
    """

    def __init__(self, config: Optional[EnhancedBuyConfig] = None):
        self.config = config or EnhancedBuyConfig()
        self.price_detector = PriceLevelDetector(self.config.price_detector)

        logger.info("[增强版买入优化器] 初始化完成")

    def should_buy_enhanced(
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
        # 1. 检测价格水平
        level_result = self.price_detector.detect_price_level(price)

        # 2. 根据价格水平选择阈值
        if level_result.level == "high":
            position_threshold = self.config.high_price_position_threshold
            rsi_threshold = self.config.high_rsi_threshold
            trend_threshold = self.config.high_trend_strength_threshold
            base_confidence = 0.60
        elif level_result.level == "low":
            position_threshold = self.config.low_price_position_threshold
            rsi_threshold = self.config.low_rsi_threshold
            trend_threshold = self.config.low_trend_strength_threshold
            base_confidence = 0.70
        else:
            position_threshold = self.config.mid_price_position_threshold
            rsi_threshold = self.config.mid_rsi_threshold
            trend_threshold = self.config.mid_trend_strength_threshold
            base_confidence = 0.65

        # 3. 检查各项条件
        checks = {
            "price_position": price_position < (position_threshold * 100),
            "rsi": rsi < rsi_threshold,
            "trend": trend_strength > trend_threshold,
            "momentum": recent_change > 0.003,
        }

        passed = sum(1 for v in checks.values() if v)

        # 4. 计算置信度
        confidence = base_confidence + (passed * 0.10)

        # 5. 应用惩罚/奖励
        if level_result.is_high_risk:
            confidence -= self.config.high_risk_penalty
            reason = "高风险：绝对高价 + 接近近期高点"
        elif level_result.is_low_opportunity:
            confidence += self.config.low_opportunity_bonus
            reason = "低机会：绝对低价 + 处于支撑位"
        else:
            reason = f"价格水平{level_result.level}，{passed}/4条件通过"

        # 6. 最终判断
        can_buy = confidence >= 0.50 and passed >= 3

        result = {
            "can_buy": can_buy,
            "confidence": confidence,
            "price_level": level_result.level,
            "checks": checks,
            "passed_count": passed,
            "is_high_risk": level_result.is_high_risk,
            "is_low_opportunity": level_result.is_low_opportunity,
            "recent_high": level_result.recent_high_price,
            "distance_to_high": level_result.distance_to_high,
            "reason": reason,
        }

        logger.info(
            f"[增强版买入优化] can_buy={can_buy}, confidence={confidence:.0%}, "
            f"level={level_result.level}, checks={passed}/4"
        )

        return result
