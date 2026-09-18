"""低波动规则参数验证测试 (dream 2026-09-16-loss-root-cause 修复后)

原测试固化了单位混淆的错误行为 (atr_percent=0.01 当作"低波动", 即 1% ATR,
高波动阈值 0.60/0.35/0.20 永远不触发)。修复后:
- 阈值单位统一为小数, 与 atr_percent 一致 (0.0014 = 0.14%)
- 低波动带 (ATR < 0.20%): SL = clamp(3×ATR, 0.3%, 0.5%), 仓位 1.0x,
  门禁收紧到 0.55 (不再放松到 0.40), 仅深度超卖可买 (RSI<35)
- 高波动分支 (ATR > 0.20%/0.35%/0.60%) 可正常触发
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
    def test_low_volatility_tightens_fusion_threshold(self):
        """低波动 (ATR 0.10%): 门禁收紧到 0.55 (原 0.40 放松门禁是亏损根因之一)。"""
        rule = VolatilityRule()
        state = _make_market_state(0.0010)
        perf = _make_perf()

        result = rule.evaluate(state, perf)

        assert result.triggered is True
        assert result.adjustment["fusion_threshold"] == 0.55

    def test_low_volatility_adds_buy_rsi_threshold_35(self):
        rule = VolatilityRule()
        state = _make_market_state(0.0010)
        perf = _make_perf()

        result = rule.evaluate(state, perf)

        assert result.triggered is True
        assert result.adjustment["buy_rsi_threshold"] == 35

    def test_low_volatility_position_not_boosted(self):
        """低波动仓位 1.0x (原 1.2x 放大风险敞口, 已移除)。"""
        rule = VolatilityRule()
        state = _make_market_state(0.0010)
        perf = _make_perf()

        result = rule.evaluate(state, perf)

        assert result.triggered is True
        assert result.adjustment["position_multiplier"] == 1.0

    def test_low_volatility_stop_is_atr_proportional(self):
        """低波动止损 = clamp(3×ATR, 0.3%, 0.5%)。ATR 0.10% → 0.30%。"""
        rule = VolatilityRule()
        state = _make_market_state(0.0010)
        perf = _make_perf()

        result = rule.evaluate(state, perf)

        assert result.triggered is True
        assert abs(result.adjustment["stop_loss_percent"] - 0.003) < 1e-9


class TestVolatilityRuleHighVolatility:
    """修复单位后, 高波动分支可正常触发 (原 0.60/0.35/0.20 永远不触发)。"""

    def test_very_high_volatility(self):
        rule = VolatilityRule()
        state = _make_market_state(0.007)  # ATR 0.7%
        perf = _make_perf()

        result = rule.evaluate(state, perf)

        assert result.triggered is True
        assert result.adjustment["stop_loss_percent"] == 0.015
        assert result.adjustment["position_multiplier"] == 0.5

    def test_high_volatility(self):
        rule = VolatilityRule()
        state = _make_market_state(0.005)  # ATR 0.5%
        perf = _make_perf()

        result = rule.evaluate(state, perf)

        assert result.triggered is True
        assert result.adjustment["stop_loss_percent"] == 0.01
        assert result.adjustment["position_multiplier"] == 0.7

    def test_medium_volatility(self):
        rule = VolatilityRule()
        state = _make_market_state(0.003)  # ATR 0.3%
        perf = _make_perf()

        result = rule.evaluate(state, perf)

        assert result.triggered is True
        assert result.adjustment["stop_loss_percent"] == 0.007
        assert result.adjustment["position_multiplier"] == 0.85
