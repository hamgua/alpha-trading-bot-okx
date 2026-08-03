"""position_manager 噪声过滤分支测试：默认不启用，启用后拦截低于手续费的浮盈触发。"""

from typing import Any

from alpha_trading_bot.core.position_manager import PositionManager


class _StubStopLoss:
    def __init__(self, **overrides: Any):
        defaults = dict(
            stop_loss_percent=0.0005,
            stop_loss_profit_percent=0.0002,
            min_profit_to_tighten_stop_percent=0.001,
            price_vs_entry_tolerance_percent=0.001,
            take_profit_percent=0.008,
        )
        defaults.update(overrides)
        for k, v in defaults.items():
            setattr(self, k, v)


class _StubConfig:
    def __init__(self, **stop_overrides: Any):
        self.stop_loss = _StubStopLoss(**stop_overrides)


def _make_manager(
    tmp_path: Any = None, **stop_overrides: Any
) -> PositionManager:
    cfg = _StubConfig(**stop_overrides)
    manager = PositionManager(config=cfg, data_dir=tmp_path)
    return manager


def _force_position(manager: PositionManager, entry: float = 63000.0) -> None:
    manager._position = type(
        "P", (), {"symbol": "BTC/USDT:USDT", "side": "long", "amount": 0.01, "entry_price": entry}
    )()
    manager._entry_price = entry
    manager._highest_price_since_entry = entry


def test_default_min_net_disables_noise_filter(tmp_path: Any) -> None:
    """默认 min_net_profit_to_close_percent=0，分支不进入，行为与改动前等价。"""
    m = _make_manager(tmp_path, min_net_profit_to_close_percent=0.0)
    _force_position(m, entry=63000.0)
    m._highest_price_since_entry = 63000.0 + 63000.0 * 0.005  # 0.5% 上行
    price = 63000.0 * 1.005
    stop = m._calculate_entry_based_stop_loss(price)
    assert stop > 63000.0 * 0.999  # 旧行为：能进入 99.98% 追踪


def test_min_net_blocks_tightening_when_implied_profit_too_low(tmp_path: Any) -> None:
    """启用 min_net=0.003 时，浮盈 0.1% 计算的追踪止损约 0.08% < 0.3%，退回基础止损。"""
    m = _make_manager(
        tmp_path,
        min_net_profit_to_close_percent=0.003,
        stop_loss_profit_percent=0.0002,
        min_profit_to_tighten_stop_percent=0.0005,
    )
    _force_position(m, entry=63000.0)
    m._highest_price_since_entry = 63000.0 + 63000.0 * 0.001  # 仅 0.1% 上行
    price = 63000.0 * 1.001
    stop = m._calculate_entry_based_stop_loss(price)
    expected_fallback = 63000.0 * (1 - 0.0005)
    assert stop == expected_fallback


def test_min_net_allows_tightening_when_implied_profit_sufficient(
    tmp_path: Any,
) -> None:
    """启用 min_net=0.003 且浮盈充足时（>0.3%），允许追踪。"""
    m = _make_manager(
        tmp_path,
        min_net_profit_to_close_percent=0.003,
        stop_loss_profit_percent=0.0002,
        min_profit_to_tighten_stop_percent=0.001,
    )
    _force_position(m, entry=63000.0)
    m._highest_price_since_entry = 63000.0 * 1.005  # 0.5% 上行
    price = 63000.0 * 1.005
    stop = m._calculate_entry_based_stop_loss(price)
    assert stop > 63000.0 * 1.002  # 至少锁到 0.2%


def test_min_net_no_effect_when_stop_below_entry(tmp_path: Any) -> None:
    """计算所得止损已低于 entry 时，不触发 min_net 检查（保持向下防御）。"""
    m = _make_manager(
        tmp_path,
        min_net_profit_to_close_percent=0.003,
        stop_loss_profit_percent=0.0002,
        min_profit_to_tighten_stop_percent=0.001,
    )
    _force_position(m, entry=63000.0)
    price = 63000.0 * 0.99  # 浮亏
    stop = m._calculate_entry_based_stop_loss(price)
    expected = 63000.0 * (1 - 0.0005)  # 基础止损
    assert stop == expected
