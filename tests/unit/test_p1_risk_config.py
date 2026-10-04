"""P1 风控与决策日志配置测试（2026-10-04 双向交易 spec P1）"""

from alpha_trading_bot.config.models import Config, TradingConfig


def test_p1_defaults() -> None:
    tc = TradingConfig()
    assert tc.decision_journal_enabled is True
    assert tc.risk_drawdown_halt == 0.30
    assert tc.risk_per_trade_max == 0.10
    assert tc.risk_resume is False
    assert tc.validate() == []


def test_from_env_overrides(monkeypatch) -> None:
    # from_env 末尾 validate_or_raise 需要 OKX 凭据，按既有测试模式补齐
    monkeypatch.setenv("OKX_API_KEY", "t")
    monkeypatch.setenv("OKX_SECRET", "t")
    monkeypatch.setenv("OKX_PASSWORD", "t")
    monkeypatch.setenv("DECISION_JOURNAL", "false")
    monkeypatch.setenv("RISK_DRAWDOWN_HALT", "0.25")
    monkeypatch.setenv("RISK_PER_TRADE_MAX", "0.05")
    monkeypatch.setenv("RISK_RESUME", "true")
    cfg = Config.from_env()
    assert cfg.trading.decision_journal_enabled is False
    assert cfg.trading.risk_drawdown_halt == 0.25
    assert cfg.trading.risk_per_trade_max == 0.05
    assert cfg.trading.risk_resume is True


def test_validate_rejects_bad_values() -> None:
    assert any(
        "risk_drawdown_halt" in e
        for e in TradingConfig(risk_drawdown_halt=1.5).validate()
    )
    assert any(
        "risk_drawdown_halt" in e
        for e in TradingConfig(risk_drawdown_halt=0.0).validate()
    )
    assert any(
        "risk_per_trade_max" in e
        for e in TradingConfig(risk_per_trade_max=0.0).validate()
    )
