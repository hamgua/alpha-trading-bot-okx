"""
风险收益比计算器

专业交易员的核心原则：每笔交易必须评估风险收益比(Risk/Reward Ratio)。
只有当潜在收益至少是风险的2倍时，才值得入场。

功能:
1. 根据支撑阻力位计算R/R比
2. 基于ATR动态计算止损距离
3. 给出仓位建议
4. 判断交易是否值得执行

作者: AI Trading System
日期: 2026-05-20
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RiskRewardResult:
    """风险收益比计算结果"""

    rr_ratio: float  # R/R比
    risk_distance: float  # 风险距离（止损距离）
    reward_distance: float  # 收益距离（止盈距离）
    stop_loss_price: float  # 建议止损价
    take_profit_price: float  # 建议止盈价
    should_trade: bool  # 是否应该交易
    position_size_factor: float  # 仓位系数 0.0-1.0
    quality: str  # excellent | good | marginal | poor
    reason: str  # 判断原因


class RiskRewardCalculator:
    """
    风险收益比计算器

    专业交易员的R/R评估规则：
    - R/R >= 3.0: 优质交易，全额仓位 (1.0)
    - R/R >= 2.0: 良好交易，正常仓位 (0.8)
    - R/R >= 1.5: 勉强交易，减半仓位 (0.5)
    - R/R < 1.5: 不交易 (0.0)

    止损价计算：
    - 做多止损 = 支撑位 - ATR * 0.5 (留出缓冲)
    - 止损距离 = max(ATR * 1.5, 当前价 - 支撑位)

    止盈价计算：
    - 做多止盈 = 阻力位
    - 保守止盈 = 阻力位 * 0.98 (阻力位前提前止盈)
    """

    EXCELLENT_RR = 3.0
    GOOD_RR = 2.0
    MARGINAL_RR = 1.5
    ATR_STOP_MULTIPLIER = 1.5
    SUPPORT_BUFFER_ATR_RATIO = 0.5

    def calculate_for_long(
        self,
        current_price: float,
        support: float,
        resistance: float,
        atr_percent: float = 0.0,
        atr_value: float = 0.0,
    ) -> RiskRewardResult:
        """
        计算做多场景的风险收益比

        Args:
            current_price: 当前价格
            support: 支撑位
            resistance: 阻力位
            atr_percent: ATR百分比
            atr_value: ATR绝对值

        Returns:
            RiskRewardResult: 风险收益比计算结果
        """
        if current_price <= 0:
            return self._create_invalid_result("当前价格无效")

        # 计算止损距离
        support_distance = current_price - support
        atr_stop = current_price * atr_percent * self.ATR_STOP_MULTIPLIER

        risk_distance = max(support_distance, atr_stop)
        if risk_distance <= 0:
            risk_distance = current_price * 0.02  # 默认2%止损

        # 计算止损价
        stop_loss_price = current_price - risk_distance

        # 计算止盈距离和止盈价
        reward_distance = resistance - current_price
        if reward_distance <= 0:
            # 当前价已在阻力位上方，使用保守目标
            reward_distance = current_price * atr_percent * 2.0
            if reward_distance <= 0:
                reward_distance = current_price * 0.04  # 默认4%止盈

        take_profit_price = current_price + reward_distance

        # 计算R/R比
        rr_ratio = reward_distance / risk_distance if risk_distance > 0 else 0.0

        # 评估质量
        quality, should_trade, position_factor, reason = self._evaluate_rr(rr_ratio)

        result = RiskRewardResult(
            rr_ratio=rr_ratio,
            risk_distance=risk_distance,
            reward_distance=reward_distance,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            should_trade=should_trade,
            position_size_factor=position_factor,
            quality=quality,
            reason=reason,
        )

        logger.info(
            f"[R/R计算] 做多: R/R={rr_ratio:.2f}({quality}), "
            f"止损={stop_loss_price:.2f}, 止盈={take_profit_price:.2f}, "
            f"仓位系数={position_factor:.2f}, 建议={'交易' if should_trade else '跳过'}"
        )

        return result

    def calculate_for_short(
        self,
        current_price: float,
        support: float,
        resistance: float,
        atr_percent: float = 0.0,
    ) -> RiskRewardResult:
        """
        计算做空场景的风险收益比

        Args:
            current_price: 当前价格
            support: 支撑位
            resistance: 阻力位
            atr_percent: ATR百分比

        Returns:
            RiskRewardResult: 风险收益比计算结果
        """
        if current_price <= 0:
            return self._create_invalid_result("当前价格无效")

        # 做空：风险在上方，收益在下方
        resistance_distance = resistance - current_price
        atr_stop = current_price * atr_percent * self.ATR_STOP_MULTIPLIER

        risk_distance = max(resistance_distance, atr_stop)
        if risk_distance <= 0:
            risk_distance = current_price * 0.02

        stop_loss_price = current_price + risk_distance

        reward_distance = current_price - support
        if reward_distance <= 0:
            reward_distance = current_price * atr_percent * 2.0
            if reward_distance <= 0:
                reward_distance = current_price * 0.04

        take_profit_price = current_price - reward_distance

        rr_ratio = reward_distance / risk_distance if risk_distance > 0 else 0.0

        quality, should_trade, position_factor, reason = self._evaluate_rr(rr_ratio)

        result = RiskRewardResult(
            rr_ratio=rr_ratio,
            risk_distance=risk_distance,
            reward_distance=reward_distance,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            should_trade=should_trade,
            position_size_factor=position_factor,
            quality=quality,
            reason=reason,
        )

        logger.info(
            f"[R/R计算] 做空: R/R={rr_ratio:.2f}({quality}), "
            f"止损={stop_loss_price:.2f}, 止盈={take_profit_price:.2f}, "
            f"仓位系数={position_factor:.2f}, 建议={'交易' if should_trade else '跳过'}"
        )

        return result

    def _evaluate_rr(
        self, rr_ratio: float
    ) -> tuple:
        """评估R/R比并给出交易建议"""
        if rr_ratio >= self.EXCELLENT_RR:
            return (
                "excellent",
                True,
                1.0,
                f"R/R={rr_ratio:.2f}>=3.0，优质交易机会",
            )
        elif rr_ratio >= self.GOOD_RR:
            return (
                "good",
                True,
                0.8,
                f"R/R={rr_ratio:.2f}>=2.0，良好交易机会",
            )
        elif rr_ratio >= self.MARGINAL_RR:
            return (
                "marginal",
                True,
                0.5,
                f"R/R={rr_ratio:.2f}>=1.5，勉强可交易，减仓",
            )
        else:
            return (
                "poor",
                False,
                0.0,
                f"R/R={rr_ratio:.2f}<1.5，风险过高，不交易",
            )

    def _create_invalid_result(self, reason: str) -> RiskRewardResult:
        """创建无效计算结果"""
        return RiskRewardResult(
            rr_ratio=0.0,
            risk_distance=0.0,
            reward_distance=0.0,
            stop_loss_price=0.0,
            take_profit_price=0.0,
            should_trade=False,
            position_size_factor=0.0,
            quality="poor",
            reason=reason,
        )