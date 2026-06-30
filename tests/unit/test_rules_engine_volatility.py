"""低波动规则参数验证测试

验证 VolatilityRule 在低波动市场中调整 fusion_threshold 和 buy_rsi_threshold。
"""

from alpha_trading_bot.ai.adaptive.rules_engine import VolatilityRule
from alpha_trading_bot.ai.adaptive.market_regime import MarketRegimeState, MarketRegime
from alpha_trading_bot.ai.adaptive.performance_tracker import PerformanceMetrics


def _make_market_state(atr_percent: float) -> MarketRegimeState:
    return MarketRegimeState(
        regime=MarketRegime.NORMAL,
        confidence=0.5,
        trend_strength=0.0,
        volatility_level=0.0,
        rsi_level=50.0,
        atr_percent=atr_percent,
        trend_direction="sideways",
        regime_changes=0,
        timestamp="",
    )


def _make_perf() -> PerformanceMetrics:
    return PerformanceMetrics()


class TestVolatilityRuleLowVolatility:

    def test_low_volatility_adjusts_fusion_threshold_to_040(self):
        rule = VolatilityRule()
        state = _make_market_state(0.010)
        perf = _make_perf()

        result = rule.evaluate(state, perf)

        assert result.triggered is True
        assert result.adjustment["fusion_threshold"] == 0.40

    def test_low_volatility_adds_buy_rsi_threshold_35(self):
        rule = VolatilityRule()
        state = _make_market_state(0.010)
        perf = _make_perf()

        result = rule.evaluate(state, perf)

        assert result.triggered is True
        assert result.adjustment["buy_rsi_threshold"] == 35

    def test_low_volatility_keeps_position_multiplier(self):
        rule = VolatilityRule()
        state = _make_market_state(0.010)
        perf = _make_perf()

        result = rule.evaluate(state, perf)

        assert result.triggered is True
        assert result.adjustment["position_multiplier"] == 1.2

    def test_normal_volatility_not_triggered(self):
        rule = VolatilityRule()
        state = _make_market_state(0.025)
        perf = _make_perf()

        result = rule.evaluate(state, perf)

        assert result.triggered is False
        assert result.adjustment == {}
