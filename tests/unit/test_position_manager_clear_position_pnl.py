"""clear_position manual_close pnl 估算符号测试 (梦 2026-09-09-okx-trading-loss-analysis)。

背景: commit 07096ad (OC-NEW-4) 在 clear_position 兜底路径上估算平仓 pnl,
但公式 `side_sign * abs(entry - last_stop) / entry` 使符号与实际结果无关:
  - 空头止损亏损 (last_stop > entry) 被记为正 pnl
  - 多头利润锁定 (last_stop > entry) 被记为负 pnl
修复口径: 视为按 last_stop 退出, 与 position_close_audit.calculate_close_pnl_percent 一致:
  - long:  (last_stop - entry) / entry
  - short: (entry - last_stop) / entry
金额 = pnl% * entry * amount (无杠杆倍数, 与现状一致)。
本测试仅验证数据质量修复, 不涉及开平仓行为变化。
"""

from typing import Any, Dict, List

from alpha_trading_bot.core.position_manager import PositionManager


class _StubStopLoss:
    def __init__(self, **overrides: Any) -> None:
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
    def __init__(self, **stop_overrides: Any) -> None:
        self.stop_loss = _StubStopLoss(**stop_overrides)


class _StubPosition:
    def __init__(self, side: str, amount: float = 0.01) -> None:
        self.symbol = "BTC/USDT:USDT"
        self.side = side
        self.amount = amount
        self.entry_price = 0.0
        self.unrealized_pnl = 0.0


class _RecordingPersistence:
    """捕获 record_trade 调用参数的替身 (不触碰真实持久化)。"""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def record_trade(self, **kwargs: Any) -> bool:
        self.calls.append(kwargs)
        return True

    def clear_position(self) -> None:  # pragma: no cover - 替身空实现
        return None


def _make_manager(side: str, entry: float, last_stop: float) -> PositionManager:
    m = PositionManager(config=_StubConfig(), data_dir=None)
    m._position = _StubPosition(side=side, amount=0.01)
    m._position.entry_price = entry
    m._entry_price = entry
    m._last_stop_price = last_stop
    m._persistence = _RecordingPersistence()  # type: ignore[assignment]
    return m


def _close_pnl(m: PositionManager) -> float:
    entry = m._entry_price  # clear_position 会重置 _entry_price, 先捕获
    m.clear_position()
    assert (
        len(m._persistence.calls) == 1
    ), f"record_trade 应恰好调用 1 次: {m._persistence.calls}"
    call = m._persistence.calls[0]
    assert call["trade_type"] == "close"
    assert call["reason"] == "manual_close"
    # 锁定"不改变调用契约": price 仍为 entry, amount 不变
    assert call["price"] == entry
    assert call["amount"] == 0.01
    return float(call["pnl"])


# T1: long 亏损 (止损价 < 建仓价) → pnl 为负
def test_long_stop_loss_negative_pnl() -> None:
    m = _make_manager(side="long", entry=100.0, last_stop=99.2)
    pnl = _close_pnl(m)
    assert pnl < 0
    assert abs(pnl - (-0.008 * 100.0 * 0.01)) < 1e-12


# T2: long 利润锁定 (止损价 > 建仓价) → pnl 应为正 (修复前为负)
def test_long_profit_lock_positive_pnl() -> None:
    m = _make_manager(side="long", entry=100.0, last_stop=100.3)
    pnl = _close_pnl(m)
    assert pnl > 0
    assert abs(pnl - (0.003 * 100.0 * 0.01)) < 1e-12


# T3: short 亏损 (止损价 > 建仓价) → pnl 应为负 (修复前为正)
def test_short_stop_loss_negative_pnl() -> None:
    m = _make_manager(side="short", entry=100.0, last_stop=100.8)
    pnl = _close_pnl(m)
    assert pnl < 0
    assert abs(pnl - (-0.008 * 100.0 * 0.01)) < 1e-12


# T4: short 利润锁定 (止损价 < 建仓价) → pnl 为正
def test_short_profit_lock_positive_pnl() -> None:
    m = _make_manager(side="short", entry=100.0, last_stop=99.5)
    pnl = _close_pnl(m)
    assert pnl > 0
    assert abs(pnl - (0.005 * 100.0 * 0.01)) < 1e-12


# T5: 无止损价 → 不抛异常, pnl == 0.0 (保持现有兜底)
def test_no_stop_price_fallback_zero() -> None:
    m = _make_manager(side="long", entry=100.0, last_stop=0.0)
    pnl = _close_pnl(m)
    assert pnl == 0.0
