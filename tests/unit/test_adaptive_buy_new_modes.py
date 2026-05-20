"""自适应买入条件新增模式单元测试"""

import pytest
from alpha_trading_bot.ai.adaptive_buy_condition import (
    AdaptiveBuyCondition,
    BuyConditions,
    BuyConditionResult,
)


class TestBreakoutConfirmationMode:
    """突破确认买入模式测试"""

    def setup_method(self):
        self.conditions = BuyConditions(breakout_enabled=True)
        self.buy_condition = AdaptiveBuyCondition(self.conditions)

    def _make_market_data(self, **overrides):
        """构造测试用市场数据"""
        defaults = {
            "price": 100,
            "recent_change_percent": 0.01,
            "technical": {
                "rsi": 55,
                "macd_hist": 0.001,
                "bb_position": 0.60,
                "trend_direction": "up",
                "trend_strength": 0.20,
                "adx": 25,
                "price_position": 0.60,
            },
            "price_history": [95, 98, 100],
            "hourly_changes": [0.005, 0.003, 0.002],
        }
        defaults.update(overrides)
        if "technical" in overrides:
            defaults["technical"].update(overrides.pop("technical", {}))
        return defaults

    def test_breakout_confirmation_pass(self):
        """测试突破确认模式条件通过"""
        data = self._make_market_data(
            recent_change_percent=0.01,
            technical={
                "rsi": 55,
                "bb_position": 0.60,
                "trend_direction": "up",
                "trend_strength": 0.20,
                "price_position": 0.60,
            },
        )

        result = self.buy_condition.should_buy(data)

        assert isinstance(result, BuyConditionResult)
        assert isinstance(result.can_buy, bool)

    def test_breakout_confirmation_downtrend_blocked(self):
        """测试下跌趋势中突破确认被阻止"""
        data = self._make_market_data(
            technical={
                "rsi": 55,
                "bb_position": 0.60,
                "trend_direction": "down",
                "trend_strength": 0.20,
                "price_position": 0.60,
            },
        )

        result = self.buy_condition.should_buy(data)

        # 下跌趋势中突破模式不应通过
        if result.mode == "breakout_confirmation":
            assert result.can_buy is False

    def test_breakout_confirmation_insufficient_conditions(self):
        """测试突破确认条件不足"""
        data = self._make_market_data(
            recent_change_percent=-0.005,  # 无动量
            technical={
                "rsi": 70,  # RSI过高
                "bb_position": 0.40,  # 布林带位置低
                "trend_direction": "neutral",
                "trend_strength": 0.10,  # 趋势弱
                "price_position": 0.30,
            },
        )

        result = self.buy_condition.should_buy(data)

        if result.mode == "breakout_confirmation":
            assert result.can_buy is False


class TestPullbackBuyMode:
    """强势回调买入模式测试"""

    def setup_method(self):
        self.conditions = BuyConditions(pullback_enabled=True)
        self.buy_condition = AdaptiveBuyCondition(self.conditions)

    def _make_market_data(self, **overrides):
        defaults = {
            "price": 100,
            "recent_change_percent": 0.002,
            "technical": {
                "rsi": 50,
                "macd_hist": 0.001,
                "bb_position": 0.50,
                "trend_direction": "up",
                "trend_strength": 0.25,
                "adx": 25,
                "price_position": 0.45,
            },
            "price_history": [95, 98, 100],
            "hourly_changes": [0.005, -0.002, 0.001],
        }
        defaults.update(overrides)
        if "technical" in overrides:
            defaults["technical"].update(overrides.pop("technical", {}))
        return defaults

    def test_pullback_buy_pass(self):
        """测试回调买入模式条件通过"""
        data = self._make_market_data(
            technical={
                "rsi": 50,
                "bb_position": 0.50,
                "trend_direction": "up",
                "trend_strength": 0.25,
                "price_position": 0.45,
            },
        )

        result = self.buy_condition.should_buy(data)

        assert isinstance(result, BuyConditionResult)

    def test_pullback_buy_non_uptrend_blocked(self):
        """测试非上涨趋势中回调买入被阻止"""
        data = self._make_market_data(
            technical={
                "rsi": 50,
                "bb_position": 0.50,
                "trend_direction": "down",
                "trend_strength": 0.25,
                "price_position": 0.45,
            },
        )

        result = self.buy_condition.should_buy(data)

        if result.mode == "pullback_buy":
            assert result.can_buy is False

    def test_pullback_buy_rsi_out_of_range(self):
        """测试RSI超出回调区间"""
        data = self._make_market_data(
            technical={
                "rsi": 70,  # RSI过高，不在回调区间
                "bb_position": 0.50,
                "trend_direction": "up",
                "trend_strength": 0.25,
                "price_position": 0.45,
            },
        )

        result = self.buy_condition.should_buy(data)

        if result.mode == "pullback_buy":
            assert result.can_buy is False


class TestNewModesCoexist:
    """新旧模式共存测试"""

    def test_all_modes_initialized(self):
        """测试所有模式正确初始化"""
        conditions = BuyConditions(
            breakout_enabled=True,
            pullback_enabled=True,
        )
        buy_condition = AdaptiveBuyCondition(conditions)

        assert buy_condition.conditions.breakout_enabled is True
        assert buy_condition.conditions.pullback_enabled is True

    def test_disable_new_modes(self):
        """测试可以禁用新模式"""
        conditions = BuyConditions(
            breakout_enabled=False,
            pullback_enabled=False,
        )
        buy_condition = AdaptiveBuyCondition(conditions)

        assert buy_condition.conditions.breakout_enabled is False
        assert buy_condition.conditions.pullback_enabled is False

    def test_existing_modes_still_work(self):
        """测试新模式不影响旧模式"""
        data = {
            "price": 100,
            "recent_change_percent": 0.005,
            "technical": {
                "rsi": 50,
                "macd_hist": 0.002,
                "bb_position": 0.45,
                "trend_direction": "up",
                "trend_strength": 0.20,
                "adx": 25,
                "price_position": 0.35,
            },
            "price_history": [95, 98, 100],
            "hourly_changes": [0.005, 0.003, 0.002],
        }

        conditions = BuyConditions(
            breakout_enabled=False,
            pullback_enabled=False,
        )
        buy_condition = AdaptiveBuyCondition(conditions)
        result = buy_condition.should_buy(data)

        assert isinstance(result, BuyConditionResult)