"""
持续下跌检测器

功能：
- 检测周期区间内的持续小幅下降趋势
- 根据检测结果调整买卖信号生成
- 降低下跌趋势中的BUY信号生成概率
- 增加下跌趋势中的SELL信号生成概率

应用场景：
如：3/5 03:00 到 3/7 01:00，BTC从74030跌到68405，跌幅7.6%
期间多次小幅反弹后继续下跌，系统不断产生BUY信号导致亏损

实现逻辑：
1. 检测累积跌幅是否超过阈值
2. 检测下跌持续时间
3. 检测是否连续下跌（不包含显著反弹）
4. 根据检测结果调整信号权重

author: AI Trading System
date: 2026-03-07
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class DeclineLevel(Enum):
    """下跌级别"""

    NONE = "none"  # 无下跌
    MILD = "mild"  # 轻度下跌 (3-5%)
    MODERATE = "moderate"  # 中度下跌 (5-8%)
    SEVERE = "severe"  # 严重下跌 (>8%)


@dataclass
class DeclineMetrics:
    """下跌指标"""

    # 累积跌幅
    cumulative_decline_percent: float  # 累积跌幅百分比

    # 下跌持续时间
    decline_duration_hours: float  # 下跌持续小时数

    # 连续性
    consecutive_down_periods: int  # 连续下跌周期数
    total_periods: int  # 总周期数
    down_ratio: float  # 下跌周期占比

    # 反弹情况
    max_rebound_percent: float  # 最大反弹幅度
    rebound_count: int  # 反弹次数

    # 综合评估
    decline_level: str  # 下跌级别
    is_sustained_decline: bool  # 是否为持续下跌
    trend_score: float  # 下跌趋势得分 (0-1)


@dataclass
class SustainedDeclineConfig:
    """持续下跌检测配置"""

    # 是否启用检测
    enabled: bool = True

    # 累积跌幅阈值
    mild_decline_threshold: float = 3.0  # 轻度下跌阈值 (%)
    moderate_decline_threshold: float = 5.0  # 中度下跌阈值 (%)
    severe_decline_threshold: float = 8.0  # 严重下跌阈值 (%)

    # 持续时间阈值
    min_decline_hours: float = 2.0  # 最小下跌持续小时

    # 连续性阈值
    min_consecutive_down: int = 3  # 最少连续下跌周期数
    min_down_ratio: float = 0.6  # 最小下跌周期占比

    # 反弹容忍度
    max_rebound_threshold: float = 1.5  # 最大允许反弹 (%)

    # 信号调整参数
    buy_confidence_penalty_mild: float = 0.15  # 轻度下跌时BUY置信度惩罚
    buy_confidence_penalty_moderate: float = 0.25  # 中度下跌时BUY置信度惩罚
    buy_confidence_penalty_severe: float = 0.40  # 严重下跌时BUY置信度惩罚

    sell_confidence_boost_mild: float = 0.10  # 轻度下跌时SELL置信度加成
    sell_confidence_boost_moderate: float = 0.20  # 中度下跌时SELL置信度加成
    sell_confidence_boost_severe: float = 0.35  # 严重下跌时SELL置信度加成

    # BUY信号阻断（完全不允许BUY的阈值）
    block_buy_at_severe: bool = True  # 严重下跌时完全阻断BUY信号
    block_buy_at_moderate: bool = False  # 中度下跌时是否阻断BUY信号


@dataclass
class DeclineDetectionResult:
    """下跌检测结果"""

    # 检测状态
    is_detected: bool  # 是否检测到持续下跌
    decline_level: str  # 下跌级别

    # 指标数据
    metrics: Optional[DeclineMetrics] = None

    # 信号调整建议
    buy_penalty: float = 0.0  # BUY置信度惩罚值
    sell_boost: float = 0.0  # SELL置信度加成值
    should_block_buy: bool = False  # 是否应该阻断BUY信号
    suggested_signal_adjustment: str = ""  # 建议的信号调整

    # 日志信息
    log_message: str = ""


class SustainedDeclineDetector:
    """
    持续下跌检测器

    用于检测周期区间内的持续小幅下降趋势，并根据检测结果
    调整交易信号的生成，降低BUY信号，增加SELL信号。

    检测维度：
    1. 累积跌幅：从周期高点到当前价格的跌幅
    2. 下跌持续时间：下跌持续了多少小时
    3. 下跌连续性：有多少个周期在下跌
    4. 反弹幅度：下跌过程中是否有显著反弹
    """

    def __init__(self, config: Optional[SustainedDeclineConfig] = None):
        """
        初始化持续下跌检测器

        Args:
            config: 配置参数，如果为None则使用默认配置
        """
        self.config = config or SustainedDeclineConfig()

        # 存储周期高点和时间（用于计算累积跌幅）
        self._cycle_high_price: Optional[float] = None
        self._cycle_high_time: Optional[datetime] = None

        logger.info(
            f"[持续下跌检测器] 初始化完成: "
            f"启用={self.config.enabled}, "
            f"轻度阈值={self.config.mild_decline_threshold}%, "
            f"中度阈值={self.config.moderate_decline_threshold}%, "
            f"严重阈值={self.config.severe_decline_threshold}%"
        )

    def detect(
        self,
        market_data: Dict[str, Any],
        cycle_start_price: Optional[float] = None,
        cycle_start_time: Optional[datetime] = None,
    ) -> DeclineDetectionResult:
        """
        检测持续下跌趋势

        Args:
            market_data: 市场数据字典，包含：
                - price: 当前价格
                - hourly_changes: 小时级别变化率列表 (正=上涨, 负=下跌)
                - price_history: 历史价格列表
                - recent_change_percent: 最近1小时涨跌幅
                - daily_change_percent: 24小时涨跌幅
                - cycle_start_price: 可选，周期开始价格
                - cycle_start_time: 可选，周期开始时间

            cycle_start_price: 周期开始价格（可选，如果market_data中没有）
            cycle_start_time: 周期开始时间（可选）

        Returns:
            DeclineDetectionResult: 检测结果
        """
        # 如果未启用，直接返回无下跌
        if not self.config.enabled:
            return DeclineDetectionResult(
                is_detected=False,
                decline_level=DeclineLevel.NONE.value,
                log_message="检测器未启用",
            )

        # 获取当前价格
        current_price = market_data.get("price", 0)
        if not current_price or current_price <= 0:
            return DeclineDetectionResult(
                is_detected=False,
                decline_level=DeclineLevel.NONE.value,
                log_message="无效的价格数据",
            )

        # 获取周期开始价格和时间
        start_price = (
            market_data.get("cycle_start_price")
            or cycle_start_price
            or self._cycle_high_price
            or current_price
        )
        start_time = (
            market_data.get("cycle_start_time")
            or cycle_start_time
            or self._cycle_high_time
        )

        # 获取小时变化数据
        hourly_changes = market_data.get("hourly_changes", [])

        # 如果没有小时变化数据，尝试从价格历史计算
        if not hourly_changes:
            price_history = market_data.get("price_history", [])
            if len(price_history) >= 2:
                hourly_changes = self._calculate_hourly_changes(price_history)

        # 计算下跌指标
        metrics = self._calculate_decline_metrics(
            current_price=current_price,
            start_price=start_price,
            start_time=start_time,
            hourly_changes=hourly_changes,
            recent_change=market_data.get("recent_change_percent", 0),
            daily_change=market_data.get("daily_change_percent", 0),
        )

        # 判断是否为持续下跌
        is_sustained = self._is_sustained_decline(metrics)

        # 计算信号调整
        buy_penalty = 0.0
        sell_boost = 0.0
        should_block_buy = False
        suggested_adjustment = ""

        if is_sustained:
            level = metrics.decline_level

            if level == DeclineLevel.SEVERE.value:
                buy_penalty = self.config.buy_confidence_penalty_severe
                sell_boost = self.config.sell_confidence_boost_severe
                should_block_buy = self.config.block_buy_at_severe
                suggested_adjustment = f"严重下跌趋势，BUY信号降低{buy_penalty:.0%}，SELL信号增强{sell_boost:.0%}"

            elif level == DeclineLevel.MODERATE.value:
                buy_penalty = self.config.buy_confidence_penalty_moderate
                sell_boost = self.config.sell_confidence_boost_moderate
                should_block_buy = self.config.block_buy_at_moderate
                suggested_adjustment = f"中度下跌趋势，BUY信号降低{buy_penalty:.0%}，SELL信号增强{sell_boost:.0%}"

            else:  # MILD
                buy_penalty = self.config.buy_confidence_penalty_mild
                sell_boost = self.config.sell_confidence_boost_mild
                suggested_adjustment = f"轻度下跌趋势，BUY信号降低{buy_penalty:.0%}，SELL信号增强{sell_boost:.0%}"

        # 记录日志
        log_msg = (
            f"[持续下跌检测] "
            f"级别={metrics.decline_level}, "
            f"累积跌幅={metrics.cumulative_decline_percent:.2f}%, "
            f"持续时间={metrics.decline_duration_hours:.1f}h, "
            f"下跌周期={metrics.consecutive_down_periods}/{metrics.total_periods}, "
            f"反弹幅度={metrics.max_rebound_percent:.2f}%, "
            f"是否持续={is_sustained}"
        )

        if is_sustained:
            logger.warning(log_msg)
            logger.warning(f"  → 信号调整: {suggested_adjustment}")
        else:
            logger.info(log_msg)

        return DeclineDetectionResult(
            is_detected=is_sustained,
            decline_level=metrics.decline_level,
            metrics=metrics,
            buy_penalty=buy_penalty,
            sell_boost=sell_boost,
            should_block_buy=should_block_buy,
            suggested_signal_adjustment=suggested_adjustment,
            log_message=log_msg,
        )

    def _calculate_hourly_changes(self, price_history: List[float]) -> List[float]:
        """
        从价格历史计算小时变化率

        Args:
            price_history: 价格历史列表（从旧到新）

        Returns:
            List[float]: 小时变化率列表
        """
        if len(price_history) < 2:
            return []

        changes = []
        for i in range(1, len(price_history)):
            if price_history[i - 1] > 0:
                change = (price_history[i] - price_history[i - 1]) / price_history[
                    i - 1
                ]
                changes.append(change)

        return changes

    def _calculate_decline_metrics(
        self,
        current_price: float,
        start_price: float,
        start_time: Optional[datetime],
        hourly_changes: List[float],
        recent_change: float,
        daily_change: float,
    ) -> DeclineMetrics:
        """
        计算下跌指标
        """
        # 1. 累积跌幅
        cumulative_decline = 0.0
        if start_price and start_price > 0:
            cumulative_decline = ((start_price - current_price) / start_price) * 100
            cumulative_decline = max(0, cumulative_decline)  # 只计算下跌，不计算上涨

        # 如果没有提供start_time，尝试从daily_change估算
        decline_duration = 0.0
        if start_time:
            try:
                now = datetime.now()
                if start_time.tzinfo:
                    now = now.replace(tzinfo=start_time.tzinfo)
                decline_duration = (now - start_time).total_seconds() / 3600
            except (AttributeError, TypeError):
                # 如果时间计算失败，使用daily_change估算
                if daily_change < 0:
                    decline_duration = abs(daily_change) / 0.5  # 假设每小时平均跌0.5%
                else:
                    decline_duration = 0
        else:
            # 没有start_time时，根据跌幅和变化估算
            if cumulative_decline > 0:
                avg_change = recent_change if recent_change != 0 else daily_change / 24
                if avg_change < 0:
                    decline_duration = cumulative_decline / abs(avg_change)

        # 2. 分析下跌连续性
        consecutive_down = 0
        total_periods = len(hourly_changes)
        down_periods = 0

        # 从最近到最旧遍历，计算连续下跌
        for change in hourly_changes[: min(12, len(hourly_changes))]:  # 最多取12个周期
            if change < -0.001:  # 下跌超过0.1%
                consecutive_down += 1
                down_periods += 1
            else:
                break  # 遇到非下跌，停止连续计数

        # 如果最近的不是下跌，从头开始计算连续下跌
        if not hourly_changes or hourly_changes[0] >= -0.001:
            consecutive_down = 0
            for change in hourly_changes:
                if change < -0.001:
                    consecutive_down += 1
                else:
                    break

        # 计算下跌周期占比
        down_ratio = down_periods / total_periods if total_periods > 0 else 0

        # 3. 反弹分析
        rebounds = [c for c in hourly_changes if c > 0.003]  # 超过0.3%视为反弹
        max_rebound = max([c * 100 for c in rebounds]) if rebounds else 0

        # 4. 确定下跌级别
        if cumulative_decline >= self.config.severe_decline_threshold:
            level = DeclineLevel.SEVERE.value
        elif cumulative_decline >= self.config.moderate_decline_threshold:
            level = DeclineLevel.MODERATE.value
        elif cumulative_decline >= self.config.mild_decline_threshold:
            level = DeclineLevel.MILD.value
        else:
            level = DeclineLevel.NONE.value

        # 5. 计算趋势得分 (0-1)
        # 基于跌幅、持续性、连续性加权
        score = 0.0
        if cumulative_decline > 0:
            score += min(cumulative_decline / 10, 0.3)  # 跌幅贡献最多0.3
        if decline_duration > 0:
            score += min(decline_duration / 24, 0.2)  # 持续时间贡献最多0.2
        if down_ratio > 0:
            score += down_ratio * 0.3  # 下跌占比贡献最多0.3
        if consecutive_down > 0:
            score += min(consecutive_down / 6, 0.2)  # 连续性贡献最多0.2

        # 如果有显著反弹，降低得分
        if max_rebound > self.config.max_rebound_threshold * 2:
            score *= 0.7

        score = min(score, 1.0)

        return DeclineMetrics(
            cumulative_decline_percent=cumulative_decline,
            decline_duration_hours=decline_duration,
            consecutive_down_periods=consecutive_down,
            total_periods=total_periods,
            down_ratio=down_ratio,
            max_rebound_percent=max_rebound,
            rebound_count=len(rebounds),
            decline_level=level,
            is_sustained_decline=False,  # 稍后重新计算
            trend_score=score,
        )

    def _is_sustained_decline(self, metrics: DeclineMetrics) -> bool:
        """
        判断是否为持续下跌

        需要同时满足：
        1. 累积跌幅达到轻度阈值
        2. 下跌持续时间足够
        3. 下跌周期占比足够或连续下跌周期足够
        """
        # 条件1: 累积跌幅达到轻度阈值
        if metrics.cumulative_decline_percent < self.config.mild_decline_threshold:
            return False

        # 条件2: 下跌持续时间足够
        if metrics.decline_duration_hours < self.config.min_decline_hours:
            # 如果跌幅足够大，可以忽略持续时间
            if (
                metrics.cumulative_decline_percent
                < self.config.moderate_decline_threshold
            ):
                return False

        # 条件3: 连续性检查
        has_consecutive = (
            metrics.consecutive_down_periods >= self.config.min_consecutive_down
        )
        has_enough_ratio = metrics.down_ratio >= self.config.min_down_ratio

        if not (has_consecutive or has_enough_ratio):
            return False

        # 条件4: 反弹不太大
        # 如果反弹幅度超过阈值，且反弹次数多，说明可能不是持续下跌
        if metrics.max_rebound_percent > self.config.max_rebound_threshold * 3:
            if metrics.rebound_count >= 3:
                return False

        return True

    def update_cycle_high(
        self, price: float, timestamp: Optional[datetime] = None
    ) -> None:
        """
        更新周期高点信息

        Args:
            price: 价格
            timestamp: 时间戳
        """
        if not self._cycle_high_price or price > self._cycle_high_price:
            self._cycle_high_price = price
            self._cycle_high_time = timestamp or datetime.now()
            logger.info(
                f"[持续下跌检测] 更新周期高点: {price}, 时间: {self._cycle_high_time}"
            )

    def reset_cycle(self) -> None:
        """
        重置周期数据
        """
        self._cycle_high_price = None
        self._cycle_high_time = None
        logger.info("[持续下跌检测] 周期数据已重置")

    def get_info(self) -> Dict[str, Any]:
        """
        获取检测器信息
        """
        return {
            "enabled": self.config.enabled,
            "mild_threshold": self.config.mild_decline_threshold,
            "moderate_threshold": self.config.moderate_decline_threshold,
            "severe_threshold": self.config.severe_decline_threshold,
            "current_cycle_high": self._cycle_high_price,
            "cycle_high_time": self._cycle_high_time.isoformat()
            if self._cycle_high_time
            else None,
        }
