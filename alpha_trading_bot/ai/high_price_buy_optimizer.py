"""
高位BUY信号优化器

专门解决高价位的买入信号准确率问题：
1. 价格位置动态调整
2. 高位趋势强度要求
3. RSI动态阈值
4. 价格位置上升惩罚
5. 高位综合过滤器

作者：AI Trading System
日期：2026-02-12
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime


logger = logging.getLogger(__name__)


@dataclass
class HighPriceBuyConfig:
    """高位买入优化配置"""

    # 价格位置阈值（根据价格水平调整）
    price_position_threshold_low: float = 35  # 低价位时：30→35（放宽）
    price_position_threshold_mid: float = 40  # 中价位时：35→40（放宽）
    price_position_threshold_high: float = 45  # 高价位时：40→45（放宽）

    # 价格水平划分（基于近期价格范围的百分比）
    price_level_mid_threshold: float = 0.65  # 价格>近期65%为中高位：60→65（放宽）
    price_level_high_threshold: float = 0.82  # 价格>近期82%为高位：80→82（放宽）

    # RSI阈值（根据价格水平调整）
    rsi_threshold_low: float = 50  # 低价位RSI上限（从35提高）
    rsi_threshold_mid: float = 55  # 中价位RSI上限（从30提高）
    rsi_threshold_high: float = 60  # 高价位RSI上限（从25提高）

    # 趋势强度要求（高位时需要更强趋势）
    trend_strength_threshold_low: float = 0.10  # 低价位趋势强度（从0.20降低）
    trend_strength_threshold_mid: float = 0.20  # 中价位趋势强度（从0.30降低）
    trend_strength_threshold_high: float = 0.30  # 高价位趋势强度（从0.45降低）

    # 价格位置上升惩罚
    price_position_rise_threshold: float = (
        0.30  # 价格上涨位置>30%时惩罚：25%→30%（放宽）
    )
    price_position_rise_penalty: float = 0.08  # 惩罚幅度：10%→8%（减轻）

    # 近期高点检测
    recent_high_periods: int = 10  # 近期高点周期数
    high_proximity_threshold: float = (
        0.08  # 价格>近期高点8%以内为接近高点：5%→8%（放宽）
    )


@dataclass
class HighPriceBuyResult:
    """高位买入优化结果"""

    adjusted_confidence: float
    price_level: str  # low | mid | high
    adjustment_reason: str
    should_buy: bool
    penalty_applied: bool
    details: Dict[str, Any]


class HighPriceBuyOptimizer:
    """
    高位BUY信号优化器

    问题分析：
    - 低价位BUY信号准确率高（68,400-68,800）
    - 高价位BUY信号容易追高（69,000+）

    解决方案：
    1. 根据价格水平动态调整阈值
    2. 增加高位时的趋势强度要求
    3. 惩罚价格位置快速上升的情况
    4. 检测是否接近近期高点
    """

    def __init__(self, config: Optional[HighPriceBuyConfig] = None):
        """
        初始化高位买入优化器

        Args:
            config: 优化配置，如果为None则使用默认配置
        """
        self.config = config or HighPriceBuyConfig()
        self.price_history: list = []

        logger.info(
            f"[高位买入优化器] 初始化完成: "
            f"价格位置阈值={self.config.price_position_threshold_low}/"
            f"{self.config.price_position_threshold_mid}/"
            f"{self.config.price_position_threshold_high}%"
        )

    def optimize_high_price_buy(
        self,
        market_data: Dict[str, Any],
        original_confidence: float,
        original_can_buy: bool,
        buy_mode: str,
        original_signal: str = "HOLD",
    ) -> HighPriceBuyResult:
        """
        优化高位BUY信号

        Args:
            market_data: 市场数据
            original_confidence: 原始置信度
            original_can_buy: 原始买入判断
            buy_mode: 买入模式
            original_signal: 原始信号类型 (BUY/HOLD/SELL)

        Returns:
            HighPriceBuyResult: 优化后的结果
        """
        technical = market_data.get("technical", {})
        price = market_data.get("price", 0)

        # 1. 更新价格历史
        self.price_history.append(price)
        if len(self.price_history) > 50:
            self.price_history = self.price_history[-50:]

        # 2. 判断价格水平 - 优先使用传入的 buy_mode，确保与 BTC 检测器一致
        price_level = (
            buy_mode
            if buy_mode in ["low", "mid", "high"]
            else self._get_price_level(price)
        )

        # 3. 获取当前阈值
        thresholds = self._get_thresholds(price_level)

        # 4. 获取当前指标
        price_position = technical.get("price_position", 50)
        rsi = technical.get("rsi", 50)
        trend_strength = technical.get("trend_strength", 0.3)
        trend_direction = technical.get("trend_direction", "sideways")

        # 5. 检查各项条件
        conditions_met = {
            "price_position": price_position < thresholds["price_position_threshold"],
            "rsi": rsi < thresholds["rsi_threshold"],
            "trend": trend_strength >= thresholds["trend_strength_threshold"],
        }

        passed_count = sum(1 for v in conditions_met.values() if v)

        # 6. 调整置信度
        adjusted_confidence = original_confidence
        adjustment_reason = ""
        penalty_applied = False

        # 判断是否为原始 BUY 信号（对 BUY 信号减少惩罚）
        is_original_buy = original_signal.upper() == "BUY"

        # BUY 信号惩罚系数（不减少惩罚，统一标准）
        penalty_factor = 1.0

        # 6.1 价格水平调整
        if price_level == "high":
            # 高位时需要更高的置信度
            if original_confidence < 0.75:
                adjusted_confidence = max(
                    adjusted_confidence - (0.10 * penalty_factor), 0.35
                )
                adjustment_reason += f"高位警告: 置信度降低{10 * penalty_factor:.0f}%; "

        # 6.2 价格位置检查
        if price_position >= thresholds["price_position_threshold"]:
            adjusted_confidence = max(
                adjusted_confidence - (0.15 * penalty_factor), 0.35
            )
            adjustment_reason += f"价格位置过高({price_position:.1f}%>{thresholds['price_position_threshold']}%): 置信度降低{15 * penalty_factor:.0f}%; "
            penalty_applied = True

        # 6.3 RSI检查
        if rsi >= thresholds["rsi_threshold"]:
            adjusted_confidence = max(
                adjusted_confidence - (0.12 * penalty_factor), 0.35
            )
            adjustment_reason += f"RSI过高({rsi:.1f}>{thresholds['rsi_threshold']}): 置信度降低{12 * penalty_factor:.0f}%; "
            penalty_applied = True

        # 6.4 趋势强度检查
        if trend_strength < thresholds["trend_strength_threshold"]:
            adjusted_confidence = max(
                adjusted_confidence - (0.10 * penalty_factor), 0.35
            )
            adjustment_reason += f"趋势强度不足({trend_strength:.2f}<{thresholds['trend_strength_threshold']:.2f}): 置信度降低{10 * penalty_factor:.0f}%; "
            penalty_applied = True

        # 6.5 价格位置上升惩罚
        if len(self.price_history) >= 5:
            position_change = self._calculate_price_position_change()
            if position_change > self.config.price_position_rise_threshold:
                penalty = self.config.price_position_rise_penalty * penalty_factor
                adjusted_confidence = max(adjusted_confidence - penalty, 0.35)
                adjustment_reason += f"价格位置快速上升({position_change:.1f}%): 置信度降低{penalty * 100:.0f}%; "
                penalty_applied = True

        # 6.6 近期高点检测
        near_high = self._is_near_recent_high(price)
        if near_high:
            adjusted_confidence = max(
                adjusted_confidence - (0.08 * penalty_factor), 0.35
            )
            adjustment_reason += f"接近近期高点: 置信度降低{8 * penalty_factor:.0f}%; "
            penalty_applied = True

        # 6.7 低位/超卖奖励机制（只有奖励，没有惩罚上限）
        reward_applied = False
        reward_reason = ""

        # 6.7.1 极低价位奖励
        if price_position < 20:
            reward = 0.15
            adjusted_confidence += reward
            reward_reason += (
                f"极低位(位置{price_position:.1f}%<20%): 置信度+{reward * 100:.0f}%; "
            )
            reward_applied = True
        # 6.7.2 超卖奖励
        elif rsi < 30:
            reward = 0.10
            adjusted_confidence += reward
            reward_reason += f"超卖(RSI={rsi:.1f}<30): 置信度+{reward * 100:.0f}%; "
            reward_applied = True

        # 6.7.3 强趋势奖励
        if trend_strength > 0.6:
            reward = 0.10
            adjusted_confidence += reward
            reward_reason += (
                f"强趋势(强度={trend_strength:.2f}>0.6): 置信度+{reward * 100:.0f}%; "
            )
            reward_applied = True

        if reward_applied:
            adjustment_reason += reward_reason

        # 7. 综合判断
        # 原始可以买入，且优化后置信度仍然足够
        should_buy = original_can_buy and adjusted_confidence >= 0.50

        # 如果是 BUY 信号，有惩罚时降低买入门槛（不要过于严格）
        if penalty_applied:
            if is_original_buy and adjusted_confidence >= 0.40:
                should_buy = True  # BUY 信号放宽门槛
            elif not is_original_buy and adjusted_confidence >= 0.45:
                should_buy = False  # 非 BUY 信号保持严格

        result = HighPriceBuyResult(
            adjusted_confidence=adjusted_confidence,
            price_level=price_level,
            adjustment_reason=adjustment_reason.strip("; ") or "无调整",
            should_buy=should_buy,
            penalty_applied=penalty_applied,
            details={
                "original_confidence": original_confidence,
                "price": price,
                "price_position": price_position,
                "rsi": rsi,
                "trend_strength": trend_strength,
                "trend_direction": trend_direction,
                "price_level": price_level,
                "thresholds": thresholds,
                "conditions_met": conditions_met,
                "passed_count": passed_count,
            },
        )

        logger.info(
            f"[高位买入优化] 结果: can_buy={should_buy}, "
            f"confidence={adjusted_confidence:.2%}, "
            f"level={price_level}, "
            f"penalty={penalty_applied}, "
            f"reason={result.adjustment_reason}"
        )

        return result

    def _get_price_level(self, price: float) -> str:
        """
        判断价格水平

        Args:
            price: 当前价格

        Returns:
            str: low | mid | high
        """
        if len(self.price_history) < 10:
            return "low"  # 历史数据不足，默认为低价位

        price_range = max(self.price_history) - min(self.price_history)
        if price_range == 0:
            return "low"

        # 计算价格相对位置
        relative_position = (price - min(self.price_history)) / price_range

        if relative_position < self.config.price_level_mid_threshold:
            return "low"
        elif relative_position < self.config.price_level_high_threshold:
            return "mid"
        else:
            return "high"

    def _get_thresholds(self, price_level: str) -> Dict[str, float]:
        """
        获取当前价格水平对应的阈值

        Args:
            price_level: 价格水平

        Returns:
            Dict: 阈值配置
        """
        if price_level == "low":
            return {
                "price_position_threshold": self.config.price_position_threshold_low,
                "rsi_threshold": self.config.rsi_threshold_low,
                "trend_strength_threshold": self.config.trend_strength_threshold_low,
            }
        elif price_level == "mid":
            return {
                "price_position_threshold": self.config.price_position_threshold_mid,
                "rsi_threshold": self.config.rsi_threshold_mid,
                "trend_strength_threshold": self.config.trend_strength_threshold_mid,
            }
        else:  # high
            return {
                "price_position_threshold": self.config.price_position_threshold_high,
                "rsi_threshold": self.config.rsi_threshold_high,
                "trend_strength_threshold": self.config.trend_strength_threshold_high,
            }

    def _calculate_price_position_change(self) -> float:
        """计算价格位置变化"""
        if len(self.price_history) < 5:
            return 0

        # 计算最近5个价格的位置变化
        recent_prices = self.price_history[-5:]
        price_range = max(recent_prices) - min(recent_prices)
        if price_range == 0:
            return 0

        position_change = (recent_prices[-1] - recent_prices[0]) / price_range
        return position_change

    def _is_near_recent_high(self, price: float) -> bool:
        """
        检测是否接近近期高点

        Args:
            price: 当前价格

        Returns:
            bool: 是否接近近期高点
        """
        if len(self.price_history) < self.config.recent_high_periods:
            return False

        recent_high = max(self.price_history[-self.config.recent_high_periods :])
        if recent_high == 0:
            return False

        # 价格在近期高点3%以内
        proximity = (recent_high - price) / recent_high
        return proximity < self.config.high_proximity_threshold

    def get_price_level_info(self) -> Dict[str, Any]:
        """获取价格水平信息"""
        if len(self.price_history) < 10:
            return {"status": "insufficient_data"}

        price_range = max(self.price_history) - min(self.price_history)
        current_price = self.price_history[-1]

        relative_position = (
            (current_price - min(self.price_history)) / price_range
            if price_range > 0
            else 0
        )

        return {
            "current_price": current_price,
            "price_range": price_range,
            "relative_position": relative_position,
            "price_level": self._get_price_level(current_price),
            "recent_high": max(self.price_history[-10:]),
            "recent_low": min(self.price_history[-10:]),
        }
