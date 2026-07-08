"""
RiskManager P3 & Boundaries 全覆盖测试

测试:
1. calculate_trade_params P3 全部 side 分支 (buy/open/long/sell/short/空字符串/未知)
2. HardStopLossBoundary check/apply 全分支
3. DynamicPositionBoundary check/calculate_position/apply 全分支
4. CircuitBreakerBoundary check/trigger/record_loss/record_win/check_drawdown 全分支
5. RiskControlManager assess_risk/can_open_position/record_trade_result 全分支
"""
import pytest
from unittest.mock import MagicMock
from alpha_trading_bot.ai.adaptive.risk_manager import (
    RiskControlManager,
    RiskConfig,
    RiskLevel,
    HardStopLossBoundary,
    DynamicPositionBoundary,
    CircuitBreakerBoundary,
)


# ============================================================
# RiskConfig / RiskState
# ============================================================

class TestRiskConfig:
    def test_default_values(self):
        c = RiskConfig()
        assert c.hard_stop_loss_percent == 0.05
        assert c.stop_loss_percent == 0.005
        assert c.max_position_percent == 0.1
        assert c.circuit_breaker_threshold == 0.03
        assert c.circuit_breaker_cooldown_hours == 4


# ============================================================
# HardStopLossBoundary
# ============================================================

class TestHardStopLossBoundary:
    def _make(self):
        return HardStopLossBoundary(RiskConfig())

    # --- check() paths ---

    def test_check_no_price_returns_true(self):
        b = self._make()
        ok, _ = b.check({"price": 0}, {"entry_price": 0})
        assert ok

    def test_check_long_loss_under_threshold_ok(self):
        b = self._make()
        # 做多: 亏损 -4% < 硬止损 5%, 不触发
        ok, _ = b.check({"price": 96000}, {"entry_price": 100000, "side": "buy"})
        assert ok

    def test_check_long_loss_exceeds_threshold(self):
        b = self._make()
        # 做多: 亏损 -6% > 硬止损 5%, 触发
        ok, reason = b.check({"price": 94000}, {"entry_price": 100000, "side": "buy"})
        assert not ok
        assert "硬止损" in reason

    def test_check_long_side_loss_exceeds_threshold(self):
        """交易所返回 side='long' 时也必须按多单计算硬止损。"""
        b = self._make()
        ok, reason = b.check(
            {"price": 94000}, {"entry_price": 100000, "side": "long"}
        )
        assert not ok
        assert "硬止损" in reason

    def test_check_short_loss_exceeds_threshold(self):
        b = self._make()
        # 做空: entry=100000, price=106000, 亏损=-6% > 5%
        ok, reason = b.check({"price": 106000}, {"entry_price": 100000, "side": "sell"})
        assert not ok
        assert "硬止损" in reason

    def test_check_long_profit_retracement(self):
        b = self._make()
        # 做多盈利但回吐至 < 1.5% (hard_stop_loss_profit_percent=3%, 50%=1.5%)
        ok, reason = b.check({"price": 100500}, {"entry_price": 100000, "side": "buy"})
        assert not ok
        assert "盈利硬保护" in reason

    def test_check_long_profit_safe(self):
        b = self._make()
        # 做多盈利 4% > 3%硬止损盈利阈值, 安全
        ok, _ = b.check({"price": 104000}, {"entry_price": 100000, "side": "buy"})
        assert ok

    # --- apply() paths ---

    def test_apply_with_existing_stop_keeps_it(self):
        b = self._make()
        signal = {"stop_loss_price": 99000, "entry_price": 100000, "side": "buy"}
        result = b.apply(signal)
        assert result["stop_loss_price"] == 99000

    def test_apply_long_no_stop(self):
        b = self._make()
        signal = {"entry_price": 100000, "side": "buy"}
        result = b.apply(signal)
        assert result["stop_loss_price"] < 100000

    def test_apply_long_open_no_stop(self):
        """side='open' 也应正确识别为做多"""
        b = self._make()
        signal = {"entry_price": 100000, "side": "open"}
        result = b.apply(signal)
        assert result["stop_loss_price"] < 100000

    def test_apply_long_long_side(self):
        """side='long' 也应正确识别"""
        b = self._make()
        signal = {"entry_price": 100000, "side": "long"}
        result = b.apply(signal)
        assert result["stop_loss_price"] < 100000

    def test_apply_sell_short_uses_short_formula(self):
        """做空: 止损价应高于入场价"""
        b = self._make()
        signal = {"entry_price": 100000, "side": "sell"}
        result = b.apply(signal)
        assert result["stop_loss_price"] > 100000

    def test_apply_short_side_short(self):
        b = self._make()
        signal = {"entry_price": 100000, "side": "short"}
        result = b.apply(signal)
        assert result["stop_loss_price"] > 100000

    def test_apply_unknown_side_defaults_short(self):
        """未知 side 值走 else 分支 -> 做空公式"""
        b = self._make()
        signal = {"entry_price": 100000, "side": "unknown"}
        result = b.apply(signal)
        assert result["stop_loss_price"] > 100000

    def test_apply_no_entry_price_no_stop(self):
        """无入场价时 stop_loss_price 不设置 (entry_price=0为falsy, 不进入任何分支)"""
        b = self._make()
        signal = {"side": "buy"}
        result = b.apply(signal)
        assert "stop_loss_price" not in result


# ============================================================
# DynamicPositionBoundary
# ============================================================

class TestDynamicPositionBoundary:
    def _make(self):
        return DynamicPositionBoundary(RiskConfig())

    def test_check_normal(self):
        b = self._make()
        ok, _ = b.check({}, {"position_percent": 0.05})
        assert ok

    def test_check_exceeds_max(self):
        b = self._make()
        ok, reason = b.check({}, {"position_percent": 0.15})
        assert not ok

    def test_calculate_position_low_volatility(self):
        b = self._make()
        pos = b.calculate_position({"technical": {"atr_percent": 0.01}}, 0)
        assert pos > 0

    def test_calculate_position_high_volatility(self):
        b = self._make()
        pos = b.calculate_position({"technical": {"atr_percent": 0.06}}, 0)
        assert pos < 0.1  # 高波动降低仓位

    def test_calculate_position_high_risk(self):
        b = self._make()
        pos = b.calculate_position({"technical": {"atr_percent": 0.02}}, 1.0)
        assert pos > 0
        assert pos <= 0.1

    def test_apply_adds_suggested_position(self):
        b = self._make()
        result = b.apply({"market_data": {"technical": {"atr_percent": 0.02}}})
        assert "suggested_position" in result
        assert result["suggested_position"] > 0


# ============================================================
# CircuitBreakerBoundary
# ============================================================

class TestCircuitBreakerBoundary:
    def _make(self):
        return CircuitBreakerBoundary(RiskConfig())

    def test_check_not_triggered(self):
        b = self._make()
        ok, _ = b.check({}, {})
        assert ok

    def test_trigger_and_check_during_cooldown(self):
        b = self._make()
        b.trigger_breaker("test_trigger")
        ok, reason = b.check({}, {})
        assert not ok
        assert "熔断中" in reason

    def test_record_loss_triggers_breaker(self):
        b = self._make()
        b.record_loss(-0.04)  # -4% > 3% 阈值
        assert b._breaker_triggered

    def test_record_loss_below_threshold_no_trigger(self):
        b = self._make()
        b.record_loss(-0.02)  # -2% < 3% 阈值
        assert not b._breaker_triggered

    def test_record_win_resets_consecutive_losses(self):
        b = self._make()
        b.record_loss(-0.02)
        b.record_loss(-0.02)
        b.record_win()
        assert b._consecutive_losses == 0

    def test_check_drawdown_triggers_breaker(self):
        b = self._make()
        b.update_high_water_mark(10000)
        ok, reason = b.check_drawdown(9600)  # -4% > 3%
        assert not ok
        assert "回撤超限" in reason

    def test_check_drawdown_safe(self):
        b = self._make()
        b.update_high_water_mark(10000)
        ok, _ = b.check_drawdown(9800)  # -2% < 3%
        assert ok

    def test_apply_adds_breaker_state(self):
        b = self._make()
        result = b.apply({})
        assert "circuit_breaker_active" in result


# ============================================================
# RiskControlManager - calculate_trade_params (P3 all sides)
# ============================================================

class TestRiskControlManagerP3:
    """P3 规则引擎 side 参数全分支测试"""

    @pytest.fixture
    def manager(self):
        return RiskControlManager()

    def test_p3_side_buy(self, manager):
        """action='buy' -> is_long=True -> stop低于入场价"""
        params = manager.calculate_trade_params(
            {"side": "buy", "price": 100000, "entry_price": 100000},
            {"technical": {"atr_percent": 0.02}},
            risk_score=0,
            rule_adjustments={"stop_loss_percent": 0.02},
        )
        assert params["stop_loss_price"] < 100000

    def test_p3_side_open(self, manager):
        """action='open' -> is_long=True (我们修复的)"""
        params = manager.calculate_trade_params(
            {"side": "open", "price": 100000, "entry_price": 100000},
            {"technical": {"atr_percent": 0.02}},
            risk_score=0,
            rule_adjustments={"stop_loss_percent": 0.02},
        )
        assert params["stop_loss_price"] < 100000

    def test_p3_side_long(self, manager):
        """side='long' -> is_long=True"""
        params = manager.calculate_trade_params(
            {"side": "long", "price": 100000, "entry_price": 100000},
            {"technical": {"atr_percent": 0.02}},
            risk_score=0,
            rule_adjustments={"stop_loss_percent": 0.02},
        )
        assert params["stop_loss_price"] < 100000

    def test_p3_side_sell(self, manager):
        """action='sell' -> is_long=False -> stop高于入场价"""
        params = manager.calculate_trade_params(
            {"side": "sell", "price": 100000, "entry_price": 100000},
            {"technical": {"atr_percent": 0.02}},
            risk_score=0,
            rule_adjustments={"stop_loss_percent": 0.02},
        )
        assert params["stop_loss_price"] > 100000

    def test_p3_side_short(self, manager):
        """side='short' -> is_long=False"""
        params = manager.calculate_trade_params(
            {"side": "short", "price": 100000, "entry_price": 100000},
            {"technical": {"atr_percent": 0.02}},
            risk_score=0,
            rule_adjustments={"stop_loss_percent": 0.02},
        )
        assert params["stop_loss_price"] > 100000

    def test_p3_no_rule_adjustments(self, manager):
        """无 rule_adjustments 时不影响"""
        params = manager.calculate_trade_params(
            {"side": "buy", "price": 100000, "entry_price": 100000},
            {"technical": {"atr_percent": 0.02}},
            risk_score=0,
        )
        assert "stop_loss_price" in params

    def test_p3_position_multiplier(self, manager):
        params = manager.calculate_trade_params(
            {"side": "buy", "price": 100000},
            {"technical": {"atr_percent": 0.02}},
            risk_score=0,
            rule_adjustments={"position_multiplier": 0.8},
        )
        assert params["position_adjustment"] == 0.8

    def test_p3_fusion_threshold(self, manager):
        params = manager.calculate_trade_params(
            {"side": "buy", "price": 100000},
            {"technical": {"atr_percent": 0.02}},
            risk_score=0,
            rule_adjustments={"fusion_threshold": 0.6},
        )
        assert params["fusion_threshold"] == 0.6


# ============================================================
# RiskControlManager - assess_risk / can_open_position
# ============================================================

class TestRiskControlManager:
    def test_assess_risk_no_position(self):
        manager = RiskControlManager()
        state = manager.assess_risk(
            {"price": 100000, "technical": {"atr_percent": 0.02}},
        )
        assert state.risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM)

    def test_assess_risk_high_atr(self):
        manager = RiskControlManager()
        state = manager.assess_risk(
            {"price": 100000, "technical": {"atr_percent": 0.08}},
            {"entry_price": 100000, "position_percent": 0.1},
        )
        assert state.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    def test_assess_risk_high_drawdown(self):
        manager = RiskControlManager()
        state = manager.assess_risk(
            {"price": 100000, "technical": {"atr_percent": 0.02}},
            {"daily_pnl_percent": -0.06},
        )
        assert state.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    def test_can_open_position_all_clear(self):
        manager = RiskControlManager()
        ok, _ = manager.can_open_position(
            {"price": 100000, "technical": {"atr_percent": 0.02}},
            {"entry_price": 100000, "side": "buy", "position_percent": 0.03},
        )
        assert ok

    def test_can_open_position_during_breaker(self):
        manager = RiskControlManager()
        manager.circuit_breaker_boundary.trigger_breaker("test")
        ok, reason = manager.can_open_position({}, {})
        assert not ok

    def test_can_open_position_excessive_position(self):
        manager = RiskControlManager()
        ok, reason = manager.can_open_position(
            {},
            {"position_percent": 0.15},
        )
        assert not ok

    def test_record_trade_result_loss(self):
        manager = RiskControlManager()
        manager.record_trade_result({"pnl_percent": -0.05, "outcome": "loss"})
        assert manager.circuit_breaker_boundary._consecutive_losses == 1

    def test_record_trade_result_win(self):
        manager = RiskControlManager()
        manager.record_trade_result({"pnl_percent": 0.02, "outcome": "win"})
        assert manager.circuit_breaker_boundary._consecutive_losses == 0

    def test_get_risk_summary(self):
        manager = RiskControlManager()
        summary = manager.get_risk_summary()
        assert "current_risk_level" in summary
        assert "circuit_breaker_active" in summary
