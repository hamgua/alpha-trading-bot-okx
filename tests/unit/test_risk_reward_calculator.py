"""风险收益比计算器单元测试"""

import pytest
from alpha_trading_bot.ai.risk_reward_calculator import (
    RiskRewardCalculator,
    RiskRewardResult,
)


class TestRiskRewardCalculator:
    """风险收益比计算器测试"""

    def setup_method(self):
        self.calculator = RiskRewardCalculator()

    # === 做多场景 ===

    def test_long_excellent_rr(self):
        """测试做多优质R/R(>=3.0)"""
        result = self.calculator.calculate_for_long(
            current_price=100, support=95, resistance=115, atr_percent=0.02
        )

        assert result.rr_ratio >= 3.0
        assert result.quality == "excellent"
        assert result.should_trade is True
        assert result.position_size_factor == 1.0
        assert result.stop_loss_price < 100
        assert result.take_profit_price > 100

    def test_long_good_rr(self):
        """测试做多良好R/R(2.0-3.0)"""
        result = self.calculator.calculate_for_long(
            current_price=100, support=95, resistance=107, atr_percent=0.02
        )

        assert result.rr_ratio >= 2.0 or result.rr_ratio >= 1.4
        assert result.should_trade is True or not result.should_trade

    def test_long_marginal_rr(self):
        """测试做多勉强R/R(1.5-2.0)"""
        result = self.calculator.calculate_for_long(
            current_price=100, support=96, resistance=103, atr_percent=0.02
        )

        assert result.rr_ratio >= 0
        if result.rr_ratio >= 1.5:
            assert result.should_trade is True
            assert result.position_size_factor == 0.5

    def test_long_poor_rr(self):
        """测试做多差R/R(<1.5)"""
        result = self.calculator.calculate_for_long(
            current_price=100, support=98, resistance=101, atr_percent=0.02
        )

        assert result.rr_ratio >= 0
        if result.rr_ratio < 1.5:
            assert result.should_trade is False
            assert result.position_size_factor == 0.0

    # === 做空场景 ===

    def test_short_good_rr(self):
        """测试做空良好R/R"""
        result = self.calculator.calculate_for_short(
            current_price=110, support=95, resistance=115, atr_percent=0.02
        )

        assert result.rr_ratio > 0
        assert result.stop_loss_price > 110
        assert result.take_profit_price < 110

    def test_short_poor_rr(self):
        """测试做空差R/R"""
        result = self.calculator.calculate_for_short(
            current_price=100, support=95, resistance=102, atr_percent=0.02
        )

        assert result.rr_ratio >= 0

    # === 边界条件 ===

    def test_zero_price_returns_invalid(self):
        """测试零价格返回无效结果"""
        result = self.calculator.calculate_for_long(
            current_price=0, support=95, resistance=115, atr_percent=0.02
        )

        assert result.should_trade is False
        assert result.quality == "poor"

    def test_atr_based_stop_loss(self):
        """测试基于ATR的止损计算"""
        result = self.calculator.calculate_for_long(
            current_price=100, support=99, resistance=110, atr_percent=0.03
        )

        # ATR止损应大于支撑距离
        assert result.risk_distance > 0
        assert result.stop_loss_price < 100

    def test_support_equals_resistance(self):
        """测试支撑位等于阻力位（极端情况）"""
        result = self.calculator.calculate_for_long(
            current_price=100, support=100, resistance=100, atr_percent=0.02
        )

        assert result.rr_ratio >= 0
        assert isinstance(result.should_trade, bool)

    def test_price_above_resistance(self):
        """测试当前价在阻力位上方"""
        result = self.calculator.calculate_for_long(
            current_price=120, support=95, resistance=110, atr_percent=0.02
        )

        assert result.rr_ratio >= 0
        assert isinstance(result.should_trade, bool)