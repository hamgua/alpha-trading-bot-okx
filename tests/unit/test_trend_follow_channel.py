# -*- coding: utf-8 -*-
"""趋势跟踪独立通道测试 (Task 3)。

口径与 docs/superpowers/specs/2026-11-25-trend-follow-channel-design.md
模块 0 (变体 E) 一致: SMA10/20 1h 趋势方向 + 24h 涨跌幅 ±2% + RSI 排除;
摆动止损 (24h 高低 + 0.5×ATR, 上限 2.5%) + 10R 安全止盈; 半仓, 每方向每日 1 次。
"""

import datetime
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest

from alpha_trading_bot.config.models import (
    Config,
    ExchangeConfig,
    TradingConfig,
)
from alpha_trading_bot.core.bot import TradingBot
from alpha_trading_bot.core.position_manager import PositionManager


def _make_bot(
    tmp_path: Path,
    allow_short: bool = True,
    daily_limit: int = 2,
) -> TradingBot:
    config = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(
            test_mode=True,
            real_trading_confirmed=True,
            runtime_environment="dev",
            daily_open_limit=daily_limit,
            allow_short_selling=allow_short,
        ),
    )
    bot = TradingBot(config)
    bot.position_manager = PositionManager(config, data_dir=tmp_path)
    bot._exchange = MagicMock()
    bot._exchange.get_balance = AsyncMock(return_value=1000.0)
    bot._exchange.create_order = AsyncMock(return_value="ORD_123456")
    bot._exchange.calculate_max_contracts = AsyncMock(return_value=0.03)
    bot._exchange.normalize_order_size = MagicMock(side_effect=lambda a: a)
    bot._exchange.create_stop_loss = AsyncMock(return_value="SL_ID")
    bot._exchange.create_take_profit = AsyncMock(return_value="TP_ID")
    bot._exchange.calculate_notional_usdt = MagicMock(
        side_effect=lambda amount, price: amount * price
    )
    bot._stop_loss_manager = None
    bot._open_position = AsyncMock(return_value=True)
    return bot


def _md_down(
    rsi: float = 35.0,
    highs: float = 61000.0,
    lows: float = 59500.0,
    price: float = 59000.0,
    change: float = -2.5,
    atr_percent: float = 0.005,
) -> Dict[str, Any]:
    return {
        "price": price,
        "change_percent": change,
        "technical": {
            "trend_direction": "down",
            "rsi": rsi,
            "atr_percent": atr_percent,
        },
        "high_history": [highs] * 24,
        "low_history": [lows] * 24,
    }


def _md_up(
    rsi: float = 55.0,
    highs: float = 59500.0,
    lows: float = 58000.0,
    price: float = 59000.0,
    change: float = 2.5,
    atr_percent: float = 0.005,
) -> Dict[str, Any]:
    return {
        "price": price,
        "change_percent": change,
        "technical": {
            "trend_direction": "up",
            "rsi": rsi,
            "atr_percent": atr_percent,
        },
        "high_history": [highs] * 24,
        "low_history": [lows] * 24,
    }


def _today() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d")


# ==================== 触发路径 ====================


@pytest.mark.asyncio
async def test_trend_follow_opens_short_on_downtrend(tmp_path: Path) -> None:
    bot = _make_bot(tmp_path)
    md = _md_down()
    # atr_abs = 0.005*59000 = 295 (atr_percent 为 0~1 比率, 见 technical/volatility.py)
    # stop = min(61000 + 0.5*295, 59000*1.025) = min(61147.5, 60475) = 60475
    # tp = 59000 - 10*(60475-59000) = 44250
    res = await bot._maybe_trend_follow(md, 59000.0)
    assert res is not None
    assert res.action == "open_trend_follow"
    kwargs = bot._open_position.call_args.kwargs
    assert kwargs["side"] == "short"
    assert kwargs["size_factor"] == 0.5
    assert kwargs["atr_percent"] == pytest.approx(0.005)
    assert kwargs["stop_price_override"] == pytest.approx(60475.0)
    assert kwargs["tp_price_override"] == pytest.approx(44250.0)
    assert bot._daily_open_counts[_today()] == 1
    assert bot._trend_follow_counts[_today()] == 1


@pytest.mark.asyncio
async def test_trend_follow_opens_long_on_uptrend(tmp_path: Path) -> None:
    bot = _make_bot(tmp_path)
    md = _md_up()
    # stop = max(58000 - 0.5*295, 59000*0.975) = max(57852.5, 57525) = 57852.5
    # tp = 59000 + 10*(59000-57852.5) = 70475
    res = await bot._maybe_trend_follow(md, 59000.0)
    assert res is not None
    assert res.action == "open_trend_follow"
    kwargs = bot._open_position.call_args.kwargs
    assert kwargs["side"] == "long"
    assert kwargs["size_factor"] == 0.5
    assert kwargs["stop_price_override"] == pytest.approx(57852.5)
    assert kwargs["tp_price_override"] == pytest.approx(70475.0)


# ==================== 门禁 ====================


@pytest.mark.asyncio
async def test_trend_follow_rsi_floor_blocks_short(tmp_path: Path) -> None:
    bot = _make_bot(tmp_path)
    md = _md_down(rsi=18.0)  # < short_rsi_floor=20
    res = await bot._maybe_trend_follow(md, 59000.0)
    assert res is None
    bot._open_position.assert_not_called()


@pytest.mark.asyncio
async def test_trend_follow_rsi_ceil_blocks_long(tmp_path: Path) -> None:
    bot = _make_bot(tmp_path)
    md = _md_up(rsi=85.0)  # > long_rsi_ceil=80
    res = await bot._maybe_trend_follow(md, 59000.0)
    assert res is None
    bot._open_position.assert_not_called()


@pytest.mark.asyncio
async def test_trend_follow_requires_24_bars(tmp_path: Path) -> None:
    bot = _make_bot(tmp_path)
    md = _md_down()
    md["high_history"] = [61000.0] * 20
    md["low_history"] = [59500.0] * 20
    res = await bot._maybe_trend_follow(md, 59000.0)
    assert res is None
    bot._open_position.assert_not_called()


@pytest.mark.asyncio
async def test_trend_follow_24h_change_gate(tmp_path: Path) -> None:
    bot = _make_bot(tmp_path)
    md = _md_down(change=-1.5)  # 未达 -2% 门槛
    res = await bot._maybe_trend_follow(md, 59000.0)
    assert res is None
    bot._open_position.assert_not_called()


@pytest.mark.asyncio
async def test_trend_follow_neutral_trend_skips(tmp_path: Path) -> None:
    bot = _make_bot(tmp_path)
    md = _md_down()
    md["technical"]["trend_direction"] = "neutral"
    res = await bot._maybe_trend_follow(md, 59000.0)
    assert res is None
    bot._open_position.assert_not_called()


@pytest.mark.asyncio
async def test_trend_follow_daily_cap(tmp_path: Path) -> None:
    bot = _make_bot(tmp_path)
    md = _md_down()
    assert (await bot._maybe_trend_follow(md, 59000.0)) is not None
    res2 = await bot._maybe_trend_follow(md, 59000.0)
    assert res2 is None
    assert bot._open_position.await_count == 1
    assert bot._trend_follow_counts[_today()] == 1


@pytest.mark.asyncio
async def test_trend_follow_blocked_by_shared_daily_limit(tmp_path: Path) -> None:
    # 共享 daily_open_limit: AI 路径已开满当日上限时, 本通道必须被拦
    bot = _make_bot(tmp_path, daily_limit=2)
    bot._daily_open_counts[_today()] = 2
    res = await bot._maybe_trend_follow(_md_down(), 59000.0)
    assert res is None
    bot._open_position.assert_not_called()


@pytest.mark.asyncio
async def test_trend_follow_disabled_config(tmp_path: Path) -> None:
    bot = _make_bot(tmp_path)
    bot.config.trading.trend_follow_enabled = False
    res = await bot._maybe_trend_follow(_md_down(), 59000.0)
    assert res is None


@pytest.mark.asyncio
async def test_trend_follow_short_requires_allow_short_selling(tmp_path: Path) -> None:
    bot = _make_bot(tmp_path, allow_short=False)
    res = await bot._maybe_trend_follow(_md_down(), 59000.0)
    assert res is None
    bot._open_position.assert_not_called()


@pytest.mark.asyncio
async def test_trend_follow_skips_when_has_position(tmp_path: Path) -> None:
    bot = _make_bot(tmp_path)
    bot.position_manager.has_position = MagicMock(return_value=True)
    res = await bot._maybe_trend_follow(_md_down(), 59000.0)
    assert res is None
    bot._open_position.assert_not_called()


# ==================== 端到端冒烟 (Task 6 Step 3 本地替代) ====================


@pytest.mark.asyncio
async def test_trend_follow_end_to_end_cycle_smoke(tmp_path: Path) -> None:
    """完整 _execute_trading_cycle 冒烟 (本地 OKX 网络不可达, 全 mock 替代)。

    验证新链路端到端接线: 5.8 hook → 趋势通道 → _open_position(止损/止盈
    覆盖价) → set_initial_stop → 持久化 → 止损单方向, 全程无异常栈。
    用 live 前置条件 + mock exchange (不发出任何真实订单), 因为 TEST_MODE
    路径在 _open_position 实盘闸门即返回 (不建仓/不建止损单, 无法覆盖新链路)。
    """
    from alpha_trading_bot.core.stop_loss_manager import StopLossManager

    config = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(
            test_mode=False,
            real_trading_confirmed=True,
            runtime_environment="prod",
        ),
    )
    bot = TradingBot(config)
    bot.position_manager = PositionManager(config, data_dir=tmp_path)
    bot._exchange = MagicMock()
    bot._exchange.get_market_data = AsyncMock(
        return_value={
            "price": 60223.0,
            "change_percent": -2.8,
            "recent_drop_percent": -0.005,
            "technical": {
                "trend_direction": "down",
                "rsi": 35.0,
                "atr_percent": 0.005,
                "atr": 301.0,
            },
            "high_history": [61000.0] * 24,
            "low_history": [59500.0] * 24,
        }
    )
    bot._exchange.get_position = AsyncMock(return_value=None)
    bot._exchange.get_balance = AsyncMock(return_value=1000.0)
    bot._exchange.create_order = AsyncMock(return_value="ORD_123456")
    bot._exchange.calculate_max_contracts = AsyncMock(return_value=0.03)
    bot._exchange.normalize_order_size = MagicMock(side_effect=lambda a: a)
    bot._exchange.create_stop_loss = AsyncMock(return_value="SL_ID")
    bot._exchange.create_take_profit = AsyncMock(return_value="TP_ID")
    bot._exchange.calculate_notional_usdt = MagicMock(
        side_effect=lambda amount, price: amount * price
    )
    bot._stop_loss_manager = StopLossManager(
        bot._exchange, config, bot.position_manager
    )
    bot._ai_client = MagicMock()
    bot._ai_client.get_signal = AsyncMock(return_value="HOLD")
    bot._ai_client.get_last_signal_trace = MagicMock(return_value={})
    bot._decision_journal = None  # 避免磁盘写入 (与被测链路无关)

    # 2026-11-26 P1-4: 重启后首个周期只同步不交易 (STARTUP_SYNC_ONLY=true 默认),
    # 第二周期才走 AI 信号 + 独立技术通道。此处先跑一个同步周期消费掉。
    await bot._execute_trading_cycle()
    assert not bot.position_manager.has_position()

    # 第二周期: 5.8 hook → 趋势通道 → 开空 (AI HOLD 路径未开仓)
    await bot._execute_trading_cycle()
    assert bot.position_manager.has_position()
    assert bot.position_manager.position.side == "short"
    assert bot.position_manager.entry_price == pytest.approx(60223.0)

    # 止损 = min(61000 + 0.5*0.005*60223, 60223*1.025) = 61150.58 (ATR 侧)
    expected_stop = 61000.0 + 0.5 * 0.005 * 60223.0
    assert bot.position_manager.last_stop_price == pytest.approx(expected_stop)
    # initial_stop 已锁定并随持久化落盘
    assert bot.position_manager.initial_stop_price == pytest.approx(expected_stop)
    state_file = tmp_path / "trading_state.json"
    assert state_file.exists()
    import json as _json

    state = _json.loads(state_file.read_text(encoding="utf-8"))
    assert state["position"]["initial_stop_price"] == pytest.approx(expected_stop)

    # 止损单方向正确 (空仓止损 = buy)
    stop_kwargs = bot._exchange.create_stop_loss.call_args.kwargs
    assert stop_kwargs["side"] == "buy"
    assert stop_kwargs["stop_price"] == pytest.approx(expected_stop)

    # 计数
    assert bot._trend_follow_counts[_today()] == 1
    assert bot._daily_open_counts[_today()] == 1
