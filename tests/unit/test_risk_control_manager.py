"""RiskControlManager 委托方法测试 - 验证 assess_risk 等方法的正确性"""

import pytest
from alpha_trading_bot.core.managers.risk_manager import RiskControlManager
from alpha_trading_bot.ai.adaptive.risk_manager import RiskLevel, RiskState


@pytest.fixture
def risk_manager():
    """创建 RiskControlManager 实例"""
    return RiskControlManager()


@pytest.fixture
def sample_market_data():
    """示例市场数据"""
    return {
        "price": 100000.0,
        "change_percent": 1.5,
        "technical": {
            "rsi": 55.0,
            "atr_percent": 0.025,
        },
    }


@pytest.fixture
def sample_position_data():
    """示例持仓数据"""
    return {
        "entry_price": 99000.0,
        "amount": 0.01,
        "side": "long",
        "position_percent": 0.05,
        "daily_pnl_percent": 0.01,
    }


# === T1: assess_risk 返回 RiskState 对象 ===


def test_assess_risk_returns_risk_state(risk_manager, sample_market_data, sample_position_data):
    """assess_risk 应返回 AI 底层的 RiskState 对象"""
    result = risk_manager.assess_risk(sample_market_data, sample_position_data)
    assert isinstance(result, RiskState)


def test_assess_risk_has_correct_attributes(risk_manager, sample_market_data, sample_position_data):
    """assess_risk 返回的 RiskState 应包含 adaptive_bot 使用的属性"""
    result = risk_manager.assess_risk(sample_market_data, sample_position_data)
    assert hasattr(result, "risk_level")
    assert hasattr(result, "current_drawdown")
    assert hasattr(result, "circuit_breaker_active")
    assert hasattr(result, "circuit_breaker_reason")


def test_assess_risk_risk_level_is_enum(risk_manager, sample_market_data, sample_position_data):
    """assess_risk 返回的 risk_level 应为 RiskLevel 枚举"""
    result = risk_manager.assess_risk(sample_market_data, sample_position_data)
    assert isinstance(result.risk_level, RiskLevel)
    assert result.risk_level.value in ("low", "medium", "high", "critical")


# === T2: 无持仓时 assess_risk 正常处理 ===


def test_assess_risk_with_no_position(risk_manager, sample_market_data):
    """无持仓时 assess_risk 应正常处理（position_data 为 None）"""
    result = risk_manager.assess_risk(sample_market_data, None)
    assert isinstance(result, RiskState)
    assert result.position_percent == 0


# === T8: 空市场数据 ===


def test_assess_risk_with_empty_market_data(risk_manager):
    """空市场数据时 assess_risk 不应崩溃"""
    result = risk_manager.assess_risk({}, {})
    assert isinstance(result, RiskState)


# === T3: calculate_trade_params 返回字典 ===


def test_calculate_trade_params_returns_dict(risk_manager, sample_market_data):
    """calculate_trade_params 应返回字典"""
    signal = {"side": "buy", "price": 100000.0, "entry_price": 100000.0}
    result = risk_manager.calculate_trade_params(signal, sample_market_data, risk_score=0.5)
    assert isinstance(result, dict)
    assert "stop_loss_price" in result or "risk_score" in result


# === T4: 带规则调整的 calculate_trade_params ===


def test_calculate_trade_params_with_rule_adjustments(risk_manager, sample_market_data):
    """带规则调整时 calculate_trade_params 应正常处理"""
    signal = {"side": "buy", "price": 100000.0, "entry_price": 100000.0}
    rule_adjustments = {"stop_loss_percent": 0.01, "position_multiplier": 0.8}
    result = risk_manager.calculate_trade_params(
        signal, sample_market_data, risk_score=0.3, rule_adjustments=rule_adjustments
    )
    assert isinstance(result, dict)


# === T9: 空信号 ===


def test_calculate_trade_params_with_minimal_signal(risk_manager, sample_market_data):
    """最小信号时 calculate_trade_params 不应崩溃"""
    result = risk_manager.calculate_trade_params({}, sample_market_data, risk_score=0.5)
    assert isinstance(result, dict)


# === T5: get_risk_summary ===


def test_get_risk_summary_returns_dict(risk_manager):
    """get_risk_summary 应返回包含关键字的字典"""
    result = risk_manager.get_risk_summary()
    assert isinstance(result, dict)
    assert "current_risk_level" in result
    assert "circuit_breaker_active" in result


# === T6: record_trade_result 委托 ===


def test_record_trade_result_delegates(risk_manager):
    """record_trade_result 应正确委托给底层实现"""
    risk_manager.record_trade_result({"pnl_percent": -0.02, "outcome": "loss"})
    summary = risk_manager.get_risk_summary()
    assert isinstance(summary, dict)


# === T7: can_open_position 返回元组 ===


def test_can_open_position_returns_tuple(risk_manager, sample_market_data):
    """can_open_position 应返回 (bool, str) 元组"""
    result = risk_manager.can_open_position(sample_market_data, {})
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], bool)
    assert isinstance(result[1], str)


# === T11: 原有方法不受影响 ===


def test_get_risk_config_still_works(risk_manager):
    """get_risk_config 原有方法应仍正常工作"""
    config = risk_manager.get_risk_config()
    assert isinstance(config, dict)
    assert "hard_stop_loss_percent" in config
    assert "max_position_percent" in config
    assert "circuit_breaker_threshold" in config


def test_calculate_position_size_still_works(risk_manager):
    """calculate_position_size 原有方法应仍正常工作"""
    result = risk_manager.calculate_position_size(balance=10000.0, price=100000.0)
    assert isinstance(result, float)
    assert result > 0


def test_should_trigger_circuit_breaker_still_works(risk_manager):
    """should_trigger_circuit_breaker 原有方法应仍正常工作"""
    assert risk_manager.should_trigger_circuit_breaker(-0.05) is True
    assert risk_manager.should_trigger_circuit_breaker(-0.01) is False