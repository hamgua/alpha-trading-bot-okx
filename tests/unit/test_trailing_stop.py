# -*- coding: utf-8 -*-
"""追踪止损 / 保本测试 (Task 4)。

口径 (spec 模块 1): 浮盈 ≥ 1R → 保本 (entry±0.1%); 浮盈 ≥ 2R → 从
2R 后极值 3×ATR(1h) 追踪; 只收紧不放松; initial_stop 持久化跨重启;
tolerance 窗口内强制更新; 方向错误侧安全钳位 (OKX 51280/51278 防护)。
"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from alpha_trading_bot.config.models import (
    Config,
    ExchangeConfig,
    StopLossConfig,
    TradingConfig,
)
from alpha_trading_bot.core.position_manager import PositionManager
from alpha_trading_bot.core.stop_loss_manager import StopLossManager


def _make_config(**trading_kwargs: Any) -> Config:
    return Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(
            test_mode=True,
            real_trading_confirmed=True,
            runtime_environment="dev",
            **trading_kwargs,
        ),
    )


def _make_pm(tmp_path: Path, **trading_kwargs: Any) -> PositionManager:
    return PositionManager(_make_config(**trading_kwargs), data_dir=tmp_path)


# ==================== calculate_trailing_stop 纯计算 ====================


def test_trailing_long_breakeven_at_1r(tmp_path: Path) -> None:
    pm = _make_pm(tmp_path)
    pm.update_position(0.01, 100.0, "BTC-USDT-SWAP", side="long")
    pm.set_stop_order("SL0", 98.0)
    pm.set_initial_stop(98.0)  # R = 2
    pm.update_price_tracking(102.0, "long")  # 最高价 102
    # 恰 1R → 保本候选 100*1.001 = 100.1 > last_stop 98 → 收紧
    assert pm.calculate_trailing_stop(102.0, 0.005) == pytest.approx(100.1)


def test_trailing_long_trail_at_2r_uses_extreme(tmp_path: Path) -> None:
    pm = _make_pm(tmp_path)
    pm.update_position(0.01, 100.0, "BTC-USDT-SWAP", side="long")
    pm.set_stop_order("SL0", 98.0)
    pm.set_initial_stop(98.0)
    pm.update_price_tracking(104.0, "long")
    # 2R → 追踪候选 = max(100.1, 104 - 3*ATR_abs); ATR_abs = 0.5/104*104 = 0.5
    # 候选 = max(100.1, 102.5) = 102.5 > last_stop 98
    assert pm.calculate_trailing_stop(104.0, 0.5 / 104.0) == pytest.approx(102.5)


def test_trailing_never_relaxes(tmp_path: Path) -> None:
    pm = _make_pm(tmp_path)
    pm.update_position(0.01, 100.0, "BTC-USDT-SWAP", side="long")
    pm.set_stop_order("SL0", 98.0)
    pm.set_initial_stop(98.0)
    pm.update_price_tracking(104.0, "long")
    pm.set_stop_order("SL1", 103.0)  # 止损已被推高到 103
    # 候选 102.5 < 103 → 不放松
    assert pm.calculate_trailing_stop(104.0, 0.5 / 104.0) is None


def test_trailing_short_mirror(tmp_path: Path) -> None:
    pm = _make_pm(tmp_path)
    pm.update_position(0.01, 100.0, "BTC-USDT-SWAP", side="short")
    pm.set_stop_order("SL0", 102.0)
    pm.set_initial_stop(102.0)  # R = 2
    pm.update_price_tracking(98.0, "short")  # 最低价 98, 恰 1R
    # 保本候选 = 100*0.999 = 99.9 < last_stop 102 → 收紧 (空=更低价)
    assert pm.calculate_trailing_stop(98.0, 0.005) == pytest.approx(99.9)

    pm.update_price_tracking(96.0, "short")  # 2R
    # 追踪候选 = min(99.9, 96 + 3*0.5) = 97.5 < 102 → 97.5
    assert pm.calculate_trailing_stop(96.0, 0.5 / 96.0) == pytest.approx(97.5)


def test_trailing_degrades_without_initial_stop(tmp_path: Path) -> None:
    # 旧 JSON 无 initial_stop_price → 0 → 优雅降级 None, 不抛异常
    pm = _make_pm(tmp_path)
    pm.update_position(0.01, 100.0, "BTC-USDT-SWAP", side="long")
    pm.set_stop_order("SL0", 98.0)
    assert pm.initial_stop_price == 0.0
    pm.update_price_tracking(110.0, "long")
    assert pm.calculate_trailing_stop(110.0, 0.005) is None


def test_trailing_disabled_config(tmp_path: Path) -> None:
    pm = _make_pm(tmp_path, trailing_stop_enabled=False)
    pm.update_position(0.01, 100.0, "BTC-USDT-SWAP", side="long")
    pm.set_stop_order("SL0", 98.0)
    pm.set_initial_stop(98.0)
    pm.update_price_tracking(110.0, "long")
    assert pm.calculate_trailing_stop(110.0, 0.005) is None


def test_trailing_set_initial_stop_idempotent(tmp_path: Path) -> None:
    pm = _make_pm(tmp_path)
    pm.update_position(0.01, 100.0, "BTC-USDT-SWAP", side="long")
    pm.set_initial_stop(98.0)
    pm.set_initial_stop(90.0)  # 已设过 → 忽略 (开仓锁定的 R 不可变)
    assert pm.initial_stop_price == pytest.approx(98.0)


def test_initial_stop_persistence_across_restart(tmp_path: Path) -> None:
    pm1 = _make_pm(tmp_path)
    pm1.update_position(0.01, 100.0, "BTC-USDT-SWAP", side="long")
    pm1.set_initial_stop(98.0)
    # 模拟重启: 新实例从持久化恢复
    pm2 = _make_pm(tmp_path)
    assert pm2.initial_stop_price == pytest.approx(98.0)
    # 恢复后追踪仍可用
    pm2.update_price_tracking(102.0, "long")
    assert pm2.calculate_trailing_stop(102.0, 0.005) == pytest.approx(100.1)


# ==================== update_stop_loss 集成 (force update + 钳位) ====================


def _make_slm(tmp_path: Path, pm: PositionManager) -> tuple:
    """构造 StopLossManager + exchange mock, 返回 (slm, exchange_mock)。

    stop_loss_tolerance_percent 提到 0.05 (5%), 用于验证 trailing 的
    force_update 不被容错窗口吞掉 (Review Focus 5)。
    """
    config = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(
            test_mode=True,
            real_trading_confirmed=True,
            runtime_environment="dev",
        ),
        stop_loss=StopLossConfig(stop_loss_tolerance_percent=0.05),
    )
    exchange = MagicMock()
    exchange.get_algo_orders = AsyncMock(return_value=[])
    exchange.get_open_orders = AsyncMock(return_value=[])
    exchange.cancel_algo_order = AsyncMock(return_value=(True, ""))
    exchange.create_stop_loss = AsyncMock(return_value="SL_NEW")
    return StopLossManager(exchange, config, pm), exchange


@pytest.mark.asyncio
async def test_trailing_forces_update_within_tolerance(tmp_path: Path) -> None:
    # long, entry=100, initial_stop=98 (R=2), current=102 (恰 1R)。
    # 现有 entry-based 紧密追踪 (highest×0.9998=101.9796) 比我的保本 (100.1) 更紧,
    # merge 取更紧者 → 最终 101.9796。old=100.0 → 变化 1.98% < tolerance 5%:
    # 无 force_update 时会被容错窗口吞掉; trailing_active 时必须强制更新。
    pm = _make_pm(tmp_path)
    pm.update_position(0.01, 100.0, "BTC-USDT-SWAP", side="long")
    pm.set_stop_order("SL_EXIST", 100.0)
    pm.set_initial_stop(98.0)
    pm.update_price_tracking(102.0, "long")
    expected = max(
        pm.calculate_stop_price_unified(102.0),
        pm.calculate_trailing_stop(102.0, 0.005),
    )
    slm, exchange = _make_slm(tmp_path, pm)
    await slm.update_stop_loss(102.0, atr_percent=0.005)
    assert exchange.create_stop_loss.await_count == 1
    assert exchange.create_stop_loss.call_args.kwargs["stop_price"] == pytest.approx(
        expected
    )
    # 关键: 证明强制更新生效 (1.98% < 5% 容错, 非 trailing 则被跳过)
    assert abs(expected - 100.0) / 100.0 < 0.05


@pytest.mark.asyncio
async def test_trailing_stop_wrong_side_clamped(tmp_path: Path) -> None:
    # 空: 追踪候选 96.0 == current_price (ATR=0 边界) → 方向错误侧,
    # 必须钳位到 current + max(current*0.001, 1.0) = 97.0, 避免 OKX 51280
    pm = _make_pm(tmp_path)
    pm.update_position(0.01, 100.0, "BTC-USDT-SWAP", side="short")
    pm.set_stop_order("SL_EXIST", 102.0)
    pm.set_initial_stop(102.0)
    pm.update_price_tracking(96.0, "short")
    slm, exchange = _make_slm(tmp_path, pm)
    await slm.update_stop_loss(96.0, atr_percent=0.0)
    assert exchange.create_stop_loss.await_count == 1
    assert exchange.create_stop_loss.call_args.kwargs["stop_price"] == pytest.approx(
        97.0
    )


@pytest.mark.asyncio
async def test_update_stop_loss_backward_compatible_no_trailing(
    tmp_path: Path,
) -> None:
    # 旧调用签名 (不传 atr_percent) 且无 initial_stop → 行为零回归
    pm = _make_pm(tmp_path)
    pm.update_position(0.01, 100.0, "BTC-USDT-SWAP", side="long")
    pm.set_stop_order("SL_EXIST", 98.0)
    slm, exchange = _make_slm(tmp_path, pm)
    await slm.update_stop_loss(100.5)
    # 无 trailing (initial_stop=0); 统一止损在 entry 附近, 变化率 < 5% → 不更新
    exchange.create_stop_loss.assert_not_called()
