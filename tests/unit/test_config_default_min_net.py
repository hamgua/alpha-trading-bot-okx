"""配置加载与新增 min_net_profit_to_close_percent 校验测试。"""

import os
from typing import Any

from alpha_trading_bot.config.models import StopLossConfig


def test_default_min_net_is_zero() -> None:
    cfg = StopLossConfig()
    assert cfg.min_net_profit_to_close_percent == 0.0


def test_min_net_zero_passes_validation() -> None:
    cfg = StopLossConfig(min_net_profit_to_close_percent=0.0)
    assert cfg.validate() == []


def test_min_net_positive_passes_validation() -> None:
    cfg = StopLossConfig(min_net_profit_to_close_percent=0.003)
    assert cfg.validate() == []


def test_min_net_negative_fails_validation() -> None:
    cfg = StopLossConfig(min_net_profit_to_close_percent=-0.001)
    errors = cfg.validate()
    assert any("min_net_profit_to_close_percent" in e for e in errors)


def test_min_net_loads_from_env(monkeypatch: Any) -> None:
    """环境变量 MIN_NET_PROFIT_TO_CLOSE_PERCENT 应正确加载，缺省为 0。"""
    from alpha_trading_bot.config import models as config_models

    # 隔离其它环境变量对 from_env 的影响
    monkeypatch.setenv("MIN_NET_PROFIT_TO_CLOSE_PERCENT", "0.004")

    captured_kwargs: dict = {}
    original_stop_loss_ctor = config_models.StopLossConfig

    def _capturing_ctor(**kwargs: Any) -> Any:
        captured_kwargs.update(kwargs)
        return original_stop_loss_ctor(**kwargs)

    monkeypatch.setattr(config_models, "StopLossConfig", _capturing_ctor)

    # 调用 from_env；不实际校验，仅观察构造参数
    try:
        config_models.Config.from_env()
    except Exception:
        pass  # from_env 完整路径可能因缺 OKX 凭证失败，但能跑到 stop_loss ctor 即可

    assert captured_kwargs.get("min_net_profit_to_close_percent") == 0.004
