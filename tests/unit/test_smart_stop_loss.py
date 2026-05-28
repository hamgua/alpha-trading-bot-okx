"""智能止损管理测试 - 基于建仓价的止损计算"""

import tempfile
import pytest

from alpha_trading_bot.config.models import (
    Config,
    ExchangeConfig,
    StopLossConfig,
    TradingConfig,
)
from alpha_trading_bot.core.position_manager import PositionManager


def _make_config(
    stop_loss_percent: float = 0.0005,
    stop_loss_profit_percent: float = 0.0002,
    stop_loss_entry_based: bool = True,
    price_vs_entry_tolerance_percent: float = 0.001,
) -> Config:
    """创建测试配置"""
    return Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(test_mode=True),
        stop_loss=StopLossConfig(
            stop_loss_percent=stop_loss_percent,
            stop_loss_profit_percent=stop_loss_profit_percent,
            stop_loss_entry_based=stop_loss_entry_based,
            price_vs_entry_tolerance_percent=price_vs_entry_tolerance_percent,
        ),
    )


def _make_position_manager(
    entry_price: float = 100000.0,
    side: str = "long",
    config: Config = None,
) -> PositionManager:
    """创建测试用仓位管理器"""
    if config is None:
        config = _make_config()
    pm = PositionManager(config, data_dir=tempfile.mkdtemp())
    pm.update_position(0.01, entry_price, "BTC/USDT:USDT", side=side)
    return pm


# === 1. 正常路径测试 ===


class TestEntryBasedStopLossNormal:
    """基于建仓价的智能止损 - 正常路径"""

    def test_loss_state_stop_loss(self):
        """做多亏损时: 止损 = 建仓价 × 99.95%"""
        pm = _make_position_manager(entry_price=100000.0, side="long")
        current_price = 99000.0
        stop_price = pm.calculate_stop_price(current_price)
        expected = 100000.0 * 0.9995
        assert stop_price == pytest.approx(expected, rel=1e-6)

    def test_profit_state_above_tolerance(self):
        """做多盈利且价差 >= 0.1%: 止损 = 建仓价 × 99.98%"""
        pm = _make_position_manager(entry_price=100000.0, side="long")
        current_price = 100200.0
        stop_price = pm.calculate_stop_price(current_price)
        expected = 100000.0 * 0.9998
        assert stop_price == pytest.approx(expected, rel=1e-6)

    def test_profit_state_below_tolerance(self):
        """做多盈利但价差 < 0.1%: 止损 = 建仓价 × 99.95%"""
        pm = _make_position_manager(entry_price=100000.0, side="long")
        current_price = 100050.0
        stop_price = pm.calculate_stop_price(current_price)
        expected = 100000.0 * 0.9995
        assert stop_price == pytest.approx(expected, rel=1e-6)

    def test_first_position_stop_loss(self):
        """首次建仓: 止损 = 建仓价 × 99.95%"""
        pm = _make_position_manager(entry_price=100000.0, side="long")
        stop_price = pm.calculate_stop_price(100000.0)
        expected = 100000.0 * 0.9995
        assert stop_price == pytest.approx(expected, rel=1e-6)


# === 2. 异常路径测试 ===


class TestEntryBasedStopLossAbnormal:
    """基于建仓价的智能止损 - 异常路径"""

    def test_no_position_returns_zero(self):
        """无持仓时计算止损返回 0.0"""
        config = _make_config()
        pm = PositionManager(config, data_dir=tempfile.mkdtemp())
        assert pm.calculate_stop_price(100000.0) == 0.0

    def test_zero_entry_price_returns_zero(self):
        """入场价为0返回 0.0（通过清仓后计算）"""
        config = _make_config()
        pm = PositionManager(config, data_dir=tempfile.mkdtemp())
        assert not pm.has_position()
        assert pm.calculate_stop_price(100000.0) == 0.0

    def test_short_position_uses_short_logic(self):
        """做空仓位使用做空止损逻辑，不受智能止损影响"""
        pm = _make_position_manager(entry_price=100000.0, side="short")
        stop_price = pm.calculate_short_stop_price(99000.0)
        expected = 99000.0 * (1 + 0.0005)
        assert stop_price == pytest.approx(expected, rel=1e-6)


# === 3. 配置切换测试 ===


class TestConfigSwitching:
    """配置切换测试"""

    def test_entry_based_disabled_uses_current_price(self):
        """stop_loss_entry_based=False 时使用当前价计算"""
        config = _make_config(stop_loss_entry_based=False)
        pm = _make_position_manager(entry_price=100000.0, side="long", config=config)
        current_price = 99000.0
        stop_price = pm.calculate_stop_price(current_price)
        expected = 99000.0 * (1 - 0.0005)
        assert stop_price == pytest.approx(expected, rel=1e-6)

    def test_entry_based_enabled_uses_entry_price(self):
        """stop_loss_entry_based=True 时使用建仓价计算"""
        config = _make_config(stop_loss_entry_based=True)
        pm = _make_position_manager(entry_price=100000.0, side="long", config=config)
        current_price = 99000.0
        stop_price = pm.calculate_stop_price(current_price)
        expected = 100000.0 * 0.9995
        assert stop_price == pytest.approx(expected, rel=1e-6)

    def test_config_default_entry_based_true(self):
        """默认配置 stop_loss_entry_based 为 True"""
        config = StopLossConfig()
        assert config.stop_loss_entry_based is True


# === 4. 边界条件测试 ===


class TestBoundaryConditions:
    """边界条件测试"""

    def test_exact_tolerance_boundary(self):
        """价差恰好等于 0.1%: 止损 = 建仓价 × 99.98%"""
        pm = _make_position_manager(entry_price=100000.0, side="long")
        current_price = 100100.0
        stop_price = pm.calculate_stop_price(current_price)
        expected = 100000.0 * 0.9998
        assert stop_price == pytest.approx(expected, rel=1e-6)

    def test_price_equals_entry_price(self):
        """当前价等于建仓价: 止损 = 建仓价 × 99.95%"""
        pm = _make_position_manager(entry_price=100000.0, side="long")
        stop_price = pm.calculate_stop_price(100000.0)
        expected = 100000.0 * 0.9995
        assert stop_price == pytest.approx(expected, rel=1e-6)

    def test_very_small_price_difference_below_tolerance(self):
        """价差 0.05% < 0.1%容错: 止损 = 建仓价 × 99.95%"""
        pm = _make_position_manager(entry_price=100000.0, side="long")
        current_price = 100050.0
        stop_price = pm.calculate_stop_price(current_price)
        expected = 100000.0 * 0.9995
        assert stop_price == pytest.approx(expected, rel=1e-6)

    def test_very_large_price_difference(self):
        """当前价远高于建仓价: 止损 = 建仓价 × 99.98%"""
        pm = _make_position_manager(entry_price=100000.0, side="long")
        current_price = 110000.0
        stop_price = pm.calculate_stop_price(current_price)
        expected = 100000.0 * 0.9998
        assert stop_price == pytest.approx(expected, rel=1e-6)

    def test_slightly_above_tolerance(self):
        """价差刚超过 0.1%: 止损 = 建仓价 × 99.98%"""
        pm = _make_position_manager(entry_price=100000.0, side="long")
        current_price = 100101.0
        stop_price = pm.calculate_stop_price(current_price)
        expected = 100000.0 * 0.9998
        assert stop_price == pytest.approx(expected, rel=1e-6)


# === 5. 回归测试 ===


class TestRegression:
    """回归测试"""

    def test_calculate_stop_price_unified_long(self):
        """统一止损入口做多正确路由到新逻辑"""
        pm = _make_position_manager(entry_price=100000.0, side="long")
        current_price = 99000.0
        stop_price = pm.calculate_stop_price_unified(current_price)
        expected = 100000.0 * 0.9995
        assert stop_price == pytest.approx(expected, rel=1e-6)

    def test_calculate_stop_price_unified_short(self):
        """统一止损入口做空使用做空止损逻辑（不变）"""
        pm = _make_position_manager(entry_price=100000.0, side="short")
        current_price = 99000.0
        stop_price = pm.calculate_stop_price_unified(current_price)
        expected = 99000.0 * (1 + 0.0005)
        assert stop_price == pytest.approx(expected, rel=1e-6)

    def test_stop_loss_manager_tolerance_check(self):
        """StopLossManager 容错判断: 差值 < 0.1% 不更新"""
        config = _make_config()
        pm = _make_position_manager(entry_price=100000.0, side="long", config=config)
        pm.set_stop_order("test-stop-1", 99950.0)
        entry_price = pm.entry_price
        price_vs_entry_tolerance = config.stop_loss.price_vs_entry_tolerance_percent
        current_price = 100050.0
        price_vs_entry_percent = (current_price - entry_price) / entry_price
        assert abs(price_vs_entry_percent) < price_vs_entry_tolerance


# === 6. StopLossConfig 验证测试 ===


class TestStopLossConfigValidation:
    """StopLossConfig 验证测试"""

    def test_valid_config_no_errors(self):
        """有效配置验证无错误"""
        config = StopLossConfig()
        errors = config.validate()
        assert len(errors) == 0

    def test_negative_price_vs_entry_tolerance(self):
        """负数建仓价容错验证返回错误"""
        config = StopLossConfig(price_vs_entry_tolerance_percent=-0.001)
        errors = config.validate()
        assert any("建仓价容错比例" in e for e in errors)

    def test_default_values(self):
        """默认值正确"""
        config = StopLossConfig()
        assert config.stop_loss_percent == 0.02
        assert config.stop_loss_profit_percent == 0.01
        assert config.stop_loss_tolerance_percent == 0.001
        assert config.stop_loss_entry_based is True
        assert config.price_vs_entry_tolerance_percent == 0.001


# === 7. 传统模式回归测试 ===


class TestTraditionalMode:
    """传统模式（stop_loss_entry_based=False）回归测试"""

    def test_loss_state_uses_current_price(self):
        """亏损时止损 = 当前价 × (1 - stop_loss_percent)"""
        config = _make_config(stop_loss_entry_based=False)
        pm = _make_position_manager(entry_price=100000.0, side="long", config=config)
        current_price = 99000.0
        stop_price = pm.calculate_stop_price(current_price)
        expected = 99000.0 * (1 - 0.0005)
        assert stop_price == pytest.approx(expected, rel=1e-6)

    def test_profit_state_uses_current_price(self):
        """盈利时止损 = 当前价 × (1 - stop_loss_profit_percent)"""
        config = _make_config(stop_loss_entry_based=False)
        pm = _make_position_manager(entry_price=100000.0, side="long", config=config)
        current_price = 101000.0
        stop_price = pm.calculate_stop_price(current_price)
        expected = 101000.0 * (1 - 0.0002)
        assert stop_price == pytest.approx(expected, rel=1e-6)