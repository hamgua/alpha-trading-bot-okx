"""规则引擎参数修改验证测试

验证 RSIRule 超卖时 position_multiplier=0.8 和
VolatilityRule 低波动时 ATR 比例止损 (dream 2026-09-16-loss-root-cause 修复后:
原固定 0.008 为单位混淆产物, 改为 clamp(3×ATR, 0.3%, 0.5%); 合并顺序修复为
高优先级规则覆盖低优先级)。
"""

from unittest.mock import MagicMock

from alpha_trading_bot.ai.adaptive.rules_engine import (
    AdaptiveRulesEngine,
    RSIRule,
    VolatilityRule,
)
from alpha_trading_bot.ai.adaptive.market_regime import MarketRegimeState
from alpha_trading_bot.ai.adaptive.performance_tracker import PerformanceMetrics


class TestRSIRuleOversoldPosition:
    def _make_market_state(self, rsi):
        state = MagicMock(spec=MarketRegimeState)
        state.rsi_level = rsi
        state.atr_percent = 0.01
        state.trend_strength = 0.1
        state.regime = MagicMock()
        state.regime.value = "low_volatility"
        return state

    def _make_perf(self):
        return MagicMock(spec=PerformanceMetrics)

    def test_rsi_oversold_position_multiplier_is_0_8(self):
        rule = RSIRule()
        market_state = self._make_market_state(rsi=15.0)
        perf = self._make_perf()

        result = rule.evaluate(market_state, perf)

        assert result.triggered is True
        assert result.adjustment["position_multiplier"] == 0.8

    def test_rsi_oversold_buy_rsi_threshold_25(self):
        rule = RSIRule()
        market_state = self._make_market_state(rsi=15.0)
        perf = self._make_perf()

        result = rule.evaluate(market_state, perf)

        assert result.adjustment["buy_rsi_threshold"] == 25

    def test_rsi_normal_not_triggered(self):
        rule = RSIRule()
        market_state = self._make_market_state(rsi=50.0)
        perf = self._make_perf()

        result = rule.evaluate(market_state, perf)

        assert result.triggered is False


class TestVolatilityRuleLowVolStopLoss:
    def _make_market_state(self, atr_percent):
        state = MagicMock(spec=MarketRegimeState)
        state.atr_percent = atr_percent
        state.rsi_level = 50.0
        state.trend_strength = 0.1
        state.regime = MagicMock()
        state.regime.value = "low_volatility"
        return state

    def _make_perf(self):
        return MagicMock(spec=PerformanceMetrics)

    def test_low_volatility_stop_loss_is_atr_proportional(self):
        """ATR 0.14% (2026-09-13 实盘值): SL = 3×ATR = 0.42% (原固定 0.8%)。"""
        rule = VolatilityRule()
        market_state = self._make_market_state(atr_percent=0.0014)
        perf = self._make_perf()

        result = rule.evaluate(market_state, perf)

        assert result.triggered is True
        assert abs(result.adjustment["stop_loss_percent"] - 0.0042) < 1e-6

    def test_low_volatility_position_multiplier_is_one(self):
        """低波动仓位 1.0x (原 1.2x 放大风险敞口, 已移除)。"""
        rule = VolatilityRule()
        market_state = self._make_market_state(atr_percent=0.0014)
        perf = self._make_perf()

        result = rule.evaluate(market_state, perf)

        assert result.adjustment["position_multiplier"] == 1.0

    def test_medium_volatility_stop_loss_0_007(self):
        """ATR 0.3% 落入中等波动带 (0.20% < atr <= 0.35%), SL 0.7%。"""
        rule = VolatilityRule()
        market_state = self._make_market_state(atr_percent=0.003)
        perf = self._make_perf()

        result = rule.evaluate(market_state, perf)

        assert result.triggered is True
        assert result.adjustment["stop_loss_percent"] == 0.007


class TestRulesEngineIntegration:
    def _make_market_state(self, rsi=15.0, atr=0.0014):
        state = MagicMock(spec=MarketRegimeState)
        state.rsi_level = rsi
        state.atr_percent = atr
        state.trend_strength = 0.1
        state.regime = MagicMock()
        state.regime.value = "low_volatility"
        return state

    def _make_perf(self):
        perf = MagicMock(spec=PerformanceMetrics)
        perf.consecutive_losses = 0
        return perf

    def test_oversold_plus_low_vol_combined_adjustments(self):
        """合并顺序修复: VolatilityRule(优先级10) 覆盖 RSIRule(优先级5)。

        ATR 0.14% (低波动带): SL=0.42%, pos=1.0x, 门禁=0.55
        RSI 15 (超卖, 低优先级): pos=0.8, 门禁=0.45, buy_rsi=25
        合并后: SL 取波动率规则 (RSI 规则不设 SL); pos/门禁 取高优先级 (波动率)。
        """
        engine = AdaptiveRulesEngine()
        market_state = self._make_market_state(rsi=15.0, atr=0.0014)
        perf = self._make_perf()

        result = engine.evaluate_all(market_state, perf)

        adjustments = result["adjustments"]
        assert abs(adjustments["stop_loss_percent"] - 0.0042) < 1e-6
        assert adjustments["position_multiplier"] == 1.0
        assert adjustments["fusion_threshold"] == 0.55
        # buy_rsi_threshold: 两规则都设置, 高优先级 VolatilityRule(35) 胜出
        assert adjustments["buy_rsi_threshold"] == 35
