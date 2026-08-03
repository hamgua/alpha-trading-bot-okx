"""PositionManager 动态止损百分比锁定测试。

修复 P0 bug：开仓时规则引擎给的动态止损百分比（0.8%）在持仓期
不应被全局 stop_loss_percent（默认 0.0005）立即收紧。
"""

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
            min_net_profit_to_close_percent=0.0,
        )
        defaults.update(overrides)
        for k, v in defaults.items():
            setattr(self, k, v)


class _StubConfig:
    def __init__(self, **stop_overrides: Any):
        self.stop_loss = _StubStopLoss(**stop_overrides)


def _make_manager(tmp_path: Any = None, **stop_overrides: Any) -> PositionManager:
    return PositionManager(config=_StubConfig(**stop_overrides), data_dir=tmp_path)


def _force_position(manager: PositionManager, entry: float = 63000.0) -> None:
    manager._position = type(
        "P",
        (),
        {
            "symbol": "BTC/USDT:USDT",
            "side": "long",
            "amount": 0.01,
            "entry_price": entry,
        },
    )()
    manager._entry_price = entry
    manager._highest_price_since_entry = entry


# T1: 默认无锁定时回退到全局默认
def test_default_no_dynamic_lock_uses_global_default(tmp_path: Any) -> None:
    """未调用 setter 时（dyn_pct=None），calculate 走全局 stop_loss_percent。"""
    m = _make_manager(tmp_path)  # 默认 stop_loss_percent=0.0005
    _force_position(m, entry=63000.0)
    price = 63000.0 * 0.99  # 亏损分支
    stop = m._calculate_entry_based_stop_loss(price)
    expected = 63000.0 * (1 - 0.0005)
    assert stop == expected


# T2: 锁定后应优先使用锁定值
def test_dynamic_lock_overrides_global(tmp_path: Any) -> None:
    """开仓时锁定 dyn_pct=0.008，持仓期（亏损分支）应用 0.008，而非 0.0005。"""
    m = _make_manager(tmp_path)
    _force_position(m, entry=63000.0)
    m.set_entry_dynamic_stop_loss_percent(0.008)
    price = 63000.0 * 0.99  # 亏损分支
    stop = m._calculate_entry_based_stop_loss(price)
    expected = 63000.0 * (1 - 0.008)
    assert abs(stop - expected) < 1e-6


# T3: update_position 重置
def test_update_position_resets_lock(tmp_path: Any) -> None:
    m = _make_manager(tmp_path)
    m.set_entry_dynamic_stop_loss_percent(0.008)
    assert m.entry_dynamic_stop_loss_percent == 0.008
    m.update_position(amount=0.01, entry_price=63000.0, symbol="BTC/USDT:USDT")
    assert m.entry_dynamic_stop_loss_percent is None


# T4: clear_position 重置
def test_clear_position_resets_lock(tmp_path: Any) -> None:
    m = _make_manager(tmp_path)
    _force_position(m, entry=63000.0)
    m.set_entry_dynamic_stop_loss_percent(0.008)
    assert m.entry_dynamic_stop_loss_percent == 0.008
    m.clear_position()
    assert m.entry_dynamic_stop_loss_percent is None


# T5: setter 拒绝越界值
def test_setter_rejects_out_of_range(tmp_path: Any) -> None:
    m = _make_manager(tmp_path)
    m.set_entry_dynamic_stop_loss_percent(0.0001)  # 太小
    assert m.entry_dynamic_stop_loss_percent is None

    m.set_entry_dynamic_stop_loss_percent(0.5)  # 太大
    assert m.entry_dynamic_stop_loss_percent is None

    m.set_entry_dynamic_stop_loss_percent(None)
    assert m.entry_dynamic_stop_loss_percent is None


# T6: setter 接受合法范围
def test_setter_accepts_valid_range(tmp_path: Any) -> None:
    m = _make_manager(tmp_path)
    for pct in (0.0005, 0.005, 0.008, 0.05):
        m.set_entry_dynamic_stop_loss_percent(pct)
        assert m.entry_dynamic_stop_loss_percent == pct


# T7: 盈利但价差<容错 分支也使用锁定值
def test_entry_based_else_branch_uses_lock(tmp_path: Any) -> None:
    """盈利但价差 < tolerance (默认 0.001) 时，else 分支应使用 dyn_pct。"""
    m = _make_manager(
        tmp_path,
        price_vs_entry_tolerance_percent=0.001,
    )
    entry = 63000.0
    _force_position(m, entry=entry)
    m.set_entry_dynamic_stop_loss_percent(0.008)
    # 盈利 0.0005 (在 tolerance 0.001 之内)
    price = entry * 1.0005
    stop = m._calculate_entry_based_stop_loss(price)
    expected = entry * (1 - 0.008)
    assert abs(stop - expected) < 1e-6


# T8: min_net fallback 分支使用锁定值
def test_min_net_fallback_uses_lock(tmp_path: Any) -> None:
    """启用 min_net 后，浮盈不足时 fallback 应使用 dyn_pct。"""
    m = _make_manager(
        tmp_path,
        min_net_profit_to_close_percent=0.003,
        stop_loss_profit_percent=0.0002,
        min_profit_to_tighten_stop_percent=0.001,
    )
    entry = 63000.0
    _force_position(m, entry=entry)
    m.set_entry_dynamic_stop_loss_percent(0.008)
    m._highest_price_since_entry = entry * 1.001  # 0.1% 浮盈
    price = entry * 1.001
    stop = m._calculate_entry_based_stop_loss(price)
    expected = entry * (1 - 0.008)
    assert abs(stop - expected) < 1e-6
