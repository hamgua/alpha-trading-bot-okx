"""R7/R10: 仓位乘数与波动率因子失效修复 (全场景波动矩阵测试发现)

场景矩阵 F1/F2 (连亏 3/5 次) 与 A5/A6 (高/极高波动) 暴露:
规则引擎计算的 position_multiplier (0.5x/0.2x/0.7x/0.5x)
被写入 signal["position_adjustment"] 后从未被消费 ——
下单仓位只读 suggested_position (RiskControlManager.calculate_trade_params
→ PositionBoundary.apply → calculate_position), 规则乘数对实际下单零作用。

同时 calculate_position 的 ATR 波动率因子阈值 (0.05/0.03/0.02 = 5%/3%/2%
ATR) 与小数 atr_percent (实盘 ~0.15%) 比较, 永远落在 else 分支,
波动率减仓因子恒为 1.0; 且 signal 字典无 market_data 键,
ATR 根本传不进去。

修复:
- R10: 规则 position_multiplier 乘入 suggested_position (实际下单仓位)
- R7: calculate_position ATR 阈值改为与 VolatilityRule 一致的波动带
  (>0.6% → 0.3x, >0.35% → 0.6x, >0.20% → 0.8x, 否则 1.0x),
  并将 market_data 注入 signal 供仓位计算使用。
"""

import pytest

from alpha_trading_bot.ai.adaptive.risk_manager import (
    DynamicPositionBoundary,
    RiskConfig,
    RiskControlManager,
)


def _md(atr: float) -> dict:
    return {"price": 77000.0, "technical": {"atr_percent": atr}}


def _base_position(
    rm: RiskControlManager, atr: float, risk_score: float = 0.5
) -> float:
    """无规则调整时的基准仓位。"""
    params = rm.calculate_trade_params(
        {"side": "buy", "price": 77000.0, "entry_price": 77000.0},
        _md(atr),
        risk_score,
        rule_adjustments=None,
    )
    return float(params["suggested_position"])


class TestPositionMultiplierApplied:
    """R10: 规则仓位乘数必须作用于实际下单仓位。"""

    def test_consecutive_loss_multiplier_applied(self):
        """连亏 3 次规则 (0.5x) → suggested_position 减半。"""
        rm = RiskControlManager(RiskConfig())
        base = _base_position(rm, 0.0014)
        params = rm.calculate_trade_params(
            {"side": "buy", "price": 77000.0, "entry_price": 77000.0},
            _md(0.0014),
            0.5,
            rule_adjustments={"position_multiplier": 0.5},
        )
        assert params["position_adjustment"] == 0.5
        assert params["suggested_position"] == pytest.approx(base * 0.5)

    def test_extreme_loss_multiplier_applied(self):
        """连亏 5 次规则 (0.2x) → suggested_position 降至 20%。"""
        rm = RiskControlManager(RiskConfig())
        base = _base_position(rm, 0.0014)
        params = rm.calculate_trade_params(
            {"side": "buy", "price": 77000.0, "entry_price": 77000.0},
            _md(0.0014),
            0.5,
            rule_adjustments={"position_multiplier": 0.2},
        )
        assert params["suggested_position"] == pytest.approx(base * 0.2)

    def test_no_multiplier_keeps_position(self):
        """无规则调整 → 仓位不变。"""
        rm = RiskControlManager(RiskConfig())
        base = _base_position(rm, 0.0014)
        params = rm.calculate_trade_params(
            {"side": "buy", "price": 77000.0, "entry_price": 77000.0},
            _md(0.0014),
            0.5,
            rule_adjustments=None,
        )
        assert params["suggested_position"] == pytest.approx(base)


class TestVolatilityPositionFactor:
    """R7: 波动率减仓因子随 ATR 生效 (原阈值单位错误恒为 1.0)。"""

    def test_high_volatility_reduces_position(self):
        """ATR 0.5% (高波动带) → 仓位 < 低波动仓位。"""
        rm = RiskControlManager(RiskConfig())
        low = _base_position(rm, 0.0014)
        high = _base_position(rm, 0.005)
        assert high < low, f"高波动仓位 {high} 应低于低波动仓位 {low}"

    def test_extreme_volatility_reduces_more(self):
        """ATR 1.2% (极端) → 仓位比高波动更激进地降低。"""
        rm = RiskControlManager(RiskConfig())
        high = _base_position(rm, 0.005)
        extreme = _base_position(rm, 0.012)
        assert extreme <= high

    def test_low_volatility_unchanged(self):
        """ATR 0.15% (低波动) → 因子 1.0, 仓位 = 基准×风险因子。"""
        boundary = DynamicPositionBoundary(RiskConfig())
        pos = boundary.calculate_position(_md(0.0014), 0.0)
        # risk_score=0 → risk_factor 1.0, 因子 1.0 → 基准仓位 10%
        assert pos == pytest.approx(0.1)

    def test_factor_bands(self):
        """波动带与 VolatilityRule 一致: >0.6%→0.3, >0.35%→0.6, >0.2%→0.8。"""
        boundary = DynamicPositionBoundary(RiskConfig())
        # risk_score=0 → 仓位 = 10% × 波动因子
        assert boundary.calculate_position(_md(0.0014), 0.0) == pytest.approx(0.10)
        assert boundary.calculate_position(_md(0.003), 0.0) == pytest.approx(0.08)
        assert boundary.calculate_position(_md(0.005), 0.0) == pytest.approx(0.06)
        assert boundary.calculate_position(_md(0.012), 0.0) == pytest.approx(0.03)
