"""规则引擎参数修改验证测试

验证 RSIRule 超卖时 position_multiplier=0.8 和
VolatilityRule 低波动时 stop_loss_percent=0.008 的修改。
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

    def test_low_volatility_stop_loss_is_0_008(self):
        rule = VolatilityRule()
        market_state = self._make_market_state(atr_percent=0.01)
        perf = self._make_perf()

        result = rule.evaluate(market_state, perf)

        assert result.triggered is True
        assert result.adjustment["stop_loss_percent"] == 0.008

    def test_low_volatility_position_multiplier_1_2(self):
        rule = VolatilityRule()
        market_state = self._make_market_state(atr_percent=0.01)
        perf = self._make_perf()

        result = rule.evaluate(market_state, perf)

        assert result.adjustment["position_multiplier"] == 1.2

    def test_medium_volatility_stop_loss_0_007(self):
        rule = VolatilityRule()
        market_state = self._make_market_state(atr_percent=0.25)
        perf = self._make_perf()

        result = rule.evaluate(market_state, perf)

        assert result.triggered is True
        assert result.adjustment["stop_loss_percent"] == 0.007


class TestRulesEngineIntegration:
    def _make_market_state(self, rsi=15.0, atr=0.01):
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
        engine = AdaptiveRulesEngine()
        market_state = self._make_market_state(rsi=15.0, atr=0.01)
        perf = self._make_perf()

        result = engine.evaluate_all(market_state, perf)

        adjustments = result["adjustments"]
        assert adjustments["position_multiplier"] == 0.8
        assert adjustments["stop_loss_percent"] == 0.008
