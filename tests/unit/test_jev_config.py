"""
Jev 快车道配置单元测试
"""

import pytest

from alpha_trading_bot.ai.jev.config import JevFastLaneConfig


def test_defaults_are_safe() -> None:
    """默认配置：off 模式、默认阈值、无 Key → 合入即零行为变化。"""
    config = JevFastLaneConfig()
    assert config.mode == "off"
    assert config.api_key == ""
    assert config.model == "jev-1.13.0"
    assert config.base_url == "https://api.typesafe.ai"
    assert config.timeout_seconds == 5.0
    assert config.conf_buy == 0.75
    assert config.conf_sell == 0.75
    assert config.conf_hold == 0.50
    assert config.risk_noul_gate == 0.70
    assert config.failure_threshold == 3
    assert config.cooldown_seconds == 600
    assert config.auth_cooldown_seconds == 21600
    assert config.validate() == []


def test_from_env_reads_all_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """from_env 读取各环境变量并归一化（mode 小写、Key 去空白、base_url 去尾部斜杠）。"""
    monkeypatch.setenv("AI_FAST_LANE", " SHADOW ")
    monkeypatch.setenv("TYPESAFE_API_KEY", " ts_key_123 ")
    monkeypatch.setenv("TYPESAFE_MODEL", "jev-latest")
    monkeypatch.setenv("TYPESAFE_BASE_URL", "https://api.typesafe.ai/")
    monkeypatch.setenv("JEV_TIMEOUT", "8.5")
    monkeypatch.setenv("JEV_CONF_BUY", "0.8")
    monkeypatch.setenv("JEV_CONF_SELL", "0.8")
    monkeypatch.setenv("JEV_CONF_HOLD", "0.6")
    monkeypatch.setenv("JEV_RISK_NOUL_GATE", "0.75")
    monkeypatch.setenv("JEV_CB_FAILURES", "5")
    monkeypatch.setenv("JEV_CB_COOLDOWN", "120")
    monkeypatch.setenv("JEV_CB_AUTH_COOLDOWN", "3600")

    config = JevFastLaneConfig.from_env()
    assert config.mode == "shadow"
    assert config.api_key == "ts_key_123"
    assert config.model == "jev-latest"
    assert config.base_url == "https://api.typesafe.ai"
    assert config.timeout_seconds == 8.5
    assert config.conf_buy == 0.8
    assert config.conf_sell == 0.8
    assert config.conf_hold == 0.6
    assert config.risk_noul_gate == 0.75
    assert config.failure_threshold == 5
    assert config.cooldown_seconds == 120
    assert config.auth_cooldown_seconds == 3600
    assert config.validate() == []


def test_from_env_invalid_values_produce_validation_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非法环境变量不被吞掉：validate 返回对应错误。"""
    monkeypatch.setenv("AI_FAST_LANE", "turbo")
    monkeypatch.setenv("JEV_CONF_BUY", "1.5")
    monkeypatch.setenv("JEV_TIMEOUT", "-1")
    monkeypatch.setenv("JEV_CB_FAILURES", "0")

    config = JevFastLaneConfig.from_env()
    errors = config.validate()
    assert any(
        "模式" in e for e in errors
    )  # 项目惯例：错误消息用中文（对齐 AIConfig.validate）
    assert any("conf_buy" in e for e in errors)
    assert any("JEV_TIMEOUT" in e for e in errors)
    assert any("failure_threshold" in e for e in errors)
