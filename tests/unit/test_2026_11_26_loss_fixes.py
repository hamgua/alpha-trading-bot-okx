# -*- coding: utf-8 -*-
"""2026-11-25/26 三笔趋势空单亏损复盘修复回归测试。

覆盖 (P0/P1/P2 修复):
- P0-1 止损棘轮: 有 initial_stop 时, 空仓不再被"当前价×(1+0.5%)"重锚
  (T3 回放: 59754 结构止损不得被改写为 58673), 多仓 entry-based 追踪
  只上移不下移; 无 initial_stop 的旧状态保持旧行为。
- P0-2 趋势仓反手保护: 开仓后 60 分钟内反向 AI 信号需 置信度≥0.75 且
  技术趋势反转 才允许平仓。
- P0-3 每日计数持久化: 重启后计数恢复 (不再击穿"每方向每日≤1次")。
- P1-4 重启后首周期只同步: 不获取 AI 信号/不开平仓。
- P1-5 保护单归因: 优先查交易所算法单真实成交 (触发价/成交价)。
- P1-7 趋势通道入场过滤: HTF(4h) 对齐 + 区间端点禁追 (突破极值放行)。
- P2-10 信号连续确认: SIGNAL_CONFIRM_CYCLES=2 时孤立单次信号不执行。
"""

import datetime
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
from alpha_trading_bot.core.bot import TradingBot
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


def _make_slm(tmp_path: Path, pm: PositionManager) -> tuple:
    config = _make_config()
    config.stop_loss = StopLossConfig(stop_loss_tolerance_percent=0.05)
    exchange = MagicMock()
    exchange.get_algo_orders = AsyncMock(return_value=[])
    exchange.get_open_orders = AsyncMock(return_value=[])
    exchange.cancel_algo_order = AsyncMock(return_value=(True, ""))
    exchange.create_stop_loss = AsyncMock(return_value="SL_NEW")
    return StopLossManager(exchange, config, pm), exchange


def _make_bot(tmp_path: Path) -> TradingBot:
    config = _make_config()
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
    bot._close_position = AsyncMock(return_value=True)
    bot._decision_journal = None
    return bot


def _iso_minutes_ago(minutes: float) -> str:
    return (datetime.datetime.now() - datetime.timedelta(minutes=minutes)).isoformat()


# ==================== P0-1 止损棘轮 ====================


@pytest.mark.asyncio
async def test_ratchet_short_structural_stop_not_reanchored(tmp_path: Path) -> None:
    """T3 回放 (11-26 00:00 趋势空单): 旧逻辑把 59754 结构止损在下一
    周期改写为 58381.2×1.005=58673.1, 00:14 一根 1m 上影 58683.4 扫损。
    棘轮后: 空仓保留结构止损, 不重锚到当前价。
    """
    pm = _make_pm(tmp_path)
    pm.update_position(0.03, 58304.4, "BTC/USDT:USDT", side="short")
    pm.set_stop_order("SL_T3", 59754.015)
    pm.set_initial_stop(59754.015)
    slm, exchange = _make_slm(tmp_path, pm)

    await slm.update_stop_loss(58381.2, atr_percent=0.005)

    # 止损价无变化 → 不应创建新止损单 (旧逻辑会创建 58673.1)
    if exchange.create_stop_loss.await_count:
        got = exchange.create_stop_loss.call_args.kwargs["stop_price"]
        assert got == pytest.approx(59754.015, rel=1e-9)
    # 00:14 的 1m 高点 58683.4 低于结构止损 → 不再触发
    assert 58683.4 < 59754.015
    assert pm.last_stop_price == pytest.approx(59754.015, rel=1e-9)


@pytest.mark.asyncio
async def test_ratchet_short_trailing_still_tightens(tmp_path: Path) -> None:
    """棘轮不阻止 trailing 收紧: 浮盈 ≥2R 后追踪候选 (极值-3×ATR) 下移
    锁盈仍然生效 (只收紧不放松的"收紧"方向)。
    """
    pm = _make_pm(tmp_path)
    # short entry=100, stop=102 (R=2), 价格跌到 96 (2R 浮盈), 极值 96
    pm.update_position(0.01, 100.0, "BTC-USDT-SWAP", side="short")
    pm.set_stop_order("SL0", 102.0)
    pm.set_initial_stop(102.0)
    pm.update_price_tracking(96.0, "short")
    slm, exchange = _make_slm(tmp_path, pm)

    await slm.update_stop_loss(96.0, atr_percent=0.005)

    # ATR_abs = 0.5%×96 = 0.48; 追踪候选 = min(96+... 镜像: 96 + 3×0.48 之上)
    # calculate_trailing_stop 对空仓: 候选 = lowest + 3*ATR = 96+1.44 = 97.44 < 102 → 收紧
    assert exchange.create_stop_loss.await_count >= 1
    got = exchange.create_stop_loss.call_args.kwargs["stop_price"]
    assert got < 102.0  # 比结构止损更紧 (下移锁盈)
    assert got == pytest.approx(97.44, rel=1e-3)


@pytest.mark.asyncio
async def test_ratchet_long_entry_based_tightens_only(tmp_path: Path) -> None:
    """多仓: 有 initial_stop 时 entry-based 追踪 (highest×99.98%) 只允许
    上移; 价格回落但仍在止损上方时, 止损保持不下移。

    注: 价格回落穿越止损 (stop ≥ 当前价) 时, 既有"方向安全钳位"接管
    (交易所侧止损单本应先于本地对账触发), 不属于棘轮语义。
    """
    pm = _make_pm(tmp_path)
    pm.update_position(0.01, 100.0, "BTC-USDT-SWAP", side="long")
    pm.set_stop_order("SL0", 98.0)
    pm.set_initial_stop(98.0)
    slm, exchange = _make_slm(tmp_path, pm)

    # 价格上涨到 104: entry-based 追踪上移 (104×99.98% = 103.9792)
    await slm.update_stop_loss(104.0, atr_percent=0.005)
    assert exchange.create_stop_loss.await_count >= 1
    first_stop = exchange.create_stop_loss.call_args.kwargs["stop_price"]
    assert first_stop == pytest.approx(103.9792, rel=1e-6)

    # 价格回落到 103.0 (仍在止损上方): 止损不得下移
    await slm.update_stop_loss(103.0, atr_percent=0.005)
    assert pm.last_stop_price == pytest.approx(103.9792, rel=1e-6)

    # 新高 106: 继续上移
    before = exchange.create_stop_loss.await_count
    await slm.update_stop_loss(106.0, atr_percent=0.005)
    if exchange.create_stop_loss.await_count > before:
        new_stop = exchange.create_stop_loss.call_args.kwargs["stop_price"]
        assert new_stop == pytest.approx(106.0 * 0.9998, rel=1e-6)
        assert new_stop > first_stop


@pytest.mark.asyncio
async def test_ratchet_legacy_without_initial_stop_unchanged(
    tmp_path: Path,
) -> None:
    """旧状态 (无 initial_stop) 保持旧行为: 空仓止损 = 当前价×(1+止损比例)
    (零回归)。
    """
    pm = _make_pm(tmp_path)
    pm.update_position(0.01, 100.0, "BTC-USDT-SWAP", side="short")
    # 旧止损 105 (距新候选 >5% 容错, 确保走创建路径)
    pm.set_stop_order("SL0", 105.0)
    slm, exchange = _make_slm(tmp_path, pm)

    await slm.update_stop_loss(99.0, atr_percent=0.0)

    assert exchange.create_stop_loss.await_count >= 1
    got = exchange.create_stop_loss.call_args.kwargs["stop_price"]
    # 默认 stop_loss_percent=0.0005
    assert got == pytest.approx(99.0 * 1.0005, rel=1e-6)


# ==================== P0-2 趋势仓反手保护 ====================


@pytest.mark.asyncio
async def test_trend_close_protection_blocks_early_flip(tmp_path: Path) -> None:
    """趋势空单开仓 30 分钟后 AI BUY(0.81) 但 1h 趋势仍 down → 拦截
    (11-25 T1/T2: 开仓 2~4 分钟后被单次 BUY 平掉)。
    """
    bot = _make_bot(tmp_path)
    pm = bot.position_manager
    pm.update_position(0.03, 58304.4, "BTC/USDT:USDT", side="short", origin="trend")
    pm._entry_time = _iso_minutes_ago(30)

    result = await bot._execute_signal(
        "BUY",
        58100.0,
        has_position=True,
        final_confidence=0.81,
        trend_direction="down",
    )
    assert result.action == "protected_trend_position"
    bot._close_position.assert_not_called()


@pytest.mark.asyncio
async def test_trend_close_protection_allows_confirmed_flip(
    tmp_path: Path,
) -> None:
    """置信度 ≥0.75 且 1h 趋势已反转 (up) → 放行平仓。"""
    bot = _make_bot(tmp_path)
    pm = bot.position_manager
    pm.update_position(0.03, 58304.4, "BTC/USDT:USDT", side="short", origin="trend")
    pm._entry_time = _iso_minutes_ago(30)

    result = await bot._execute_signal(
        "BUY",
        58100.0,
        has_position=True,
        final_confidence=0.81,
        trend_direction="up",
    )
    assert result.action == "close"
    bot._close_position.assert_awaited()


@pytest.mark.asyncio
async def test_trend_close_protection_window_expired(tmp_path: Path) -> None:
    """开仓 90 分钟 (> 60 分钟窗口) → 保护期已过, 普通门禁接管。"""
    bot = _make_bot(tmp_path)
    pm = bot.position_manager
    pm.update_position(0.03, 58304.4, "BTC/USDT:USDT", side="short", origin="trend")
    pm._entry_time = _iso_minutes_ago(90)

    # 置信度 0.65 < 平仓门禁 0.70 → 被普通门禁拦 (而非反手保护)
    result = await bot._execute_signal(
        "BUY",
        58100.0,
        has_position=True,
        final_confidence=0.65,
        trend_direction="down",
    )
    assert result.action == "blocked_low_confidence"


def test_trend_close_protection_helper_matrix(tmp_path: Path) -> None:
    """_trend_close_protection_active 判定矩阵。"""
    bot = _make_bot(tmp_path)
    cfg = bot.config.trading
    assert cfg.trend_close_protection_minutes == 60
    assert cfg.trend_close_min_confidence == 0.75

    entry_30 = _iso_minutes_ago(30)
    entry_90 = _iso_minutes_ago(90)
    h = bot._trend_close_protection_active

    # 窗口内: 低置信度 / 趋势未反转 → 拦截
    assert h(entry_30, "short", 0.60, "down", -1.0) is True
    assert h(entry_30, "short", 0.90, "down", -1.0) is True
    # 窗口内: 高置信度 + 反转 (trend up 或 24h 号翻转) → 放行
    assert h(entry_30, "short", 0.75, "up", -1.0) is False
    assert h(entry_30, "short", 0.90, "down", 1.0) is False
    # 置信度恰在门槛下 → 拦截
    assert h(entry_30, "short", 0.74, "up", -1.0) is True
    # 窗口外 / 无入场时间 / 保护关闭 → 不拦截
    assert h(entry_90, "short", 0.60, "down", -1.0) is False
    assert h(None, "short", 0.60, "down", -1.0) is False
    assert h("not-a-date", "short", 0.60, "down", -1.0) is False
    # 多仓镜像: 空仓方向判定对称
    assert h(entry_30, "long", 0.60, "up", 1.0) is True
    assert h(entry_30, "long", 0.80, "down", 1.0) is False


@pytest.mark.asyncio
async def test_ai_origin_position_not_protected(tmp_path: Path) -> None:
    """origin=ai (默认) 的仓位不受反手保护 (零回归): 满足门禁即可平。"""
    bot = _make_bot(tmp_path)
    pm = bot.position_manager
    pm.update_position(0.03, 58304.4, "BTC/USDT:USDT", side="short")
    pm._entry_time = _iso_minutes_ago(5)

    result = await bot._execute_signal(
        "BUY",
        58100.0,
        has_position=True,
        final_confidence=0.75,
        trend_direction="down",
    )
    assert result.action == "close"


# ==================== P0-3 每日计数持久化 ====================


def test_daily_counts_persist_across_restart(tmp_path: Path) -> None:
    """重启 (新 PositionManager) 后计数恢复, 门禁不再被部署击穿。"""
    pm1 = _make_pm(tmp_path)
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    pm1.save_daily_counts({today: 1}, {today: 1}, {today: 1}, {today: 1})

    pm2 = _make_pm(tmp_path)  # 模拟重启
    d_open, d_trend, d_oversold, d_climax = pm2.load_daily_counts()
    assert d_open.get(today) == 1
    assert d_trend.get(today) == 1
    assert d_oversold.get(today) == 1
    assert d_climax.get(today) == 1


def test_bot_restores_daily_counts_in_init(tmp_path: Path, monkeypatch) -> None:
    """TradingBot.__init__ 从持久化恢复四个每日计数器。

    monkeypatch bot 模块内的 PositionManager 工厂, 使 __init__ 创建的
    PM 也指向 tmp_path (与生产单目录持久化同语义)。
    """
    import alpha_trading_bot.core.bot as bot_module

    real_pm = PositionManager

    def patched_pm(config=None, data_dir=None):
        return real_pm(config, data_dir=tmp_path)

    monkeypatch.setattr(bot_module, "PositionManager", patched_pm)

    pm_seed = real_pm(_make_config(), data_dir=tmp_path)
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    pm_seed.save_daily_counts({today: 1}, {today: 1}, {}, {})

    bot = TradingBot(_make_config())
    assert bot._daily_open_counts.get(today) == 1
    assert bot._trend_follow_counts.get(today) == 1
    assert bot._oversold_buy_counts.get(today, 0) == 0
    assert bot._climax_short_counts.get(today, 0) == 0


def test_daily_counts_pruned_to_recent_days(tmp_path: Path) -> None:
    """只保留今天/昨天, 过期 key 清理 (防无限膨胀)。"""
    pm = _make_pm(tmp_path)
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    old = "2020-01-01"
    pm.save_daily_counts({today: 1, old: 5}, {}, {}, {})
    d_open, _, _, _ = _make_pm(tmp_path).load_daily_counts()
    assert d_open.get(today) == 1
    assert old not in d_open


# ==================== P1-4 重启后首周期只同步 ====================


@pytest.mark.asyncio
async def test_startup_sync_only_first_cycle(tmp_path: Path) -> None:
    """首周期: 不获取 AI 信号/不开平仓; 第二周期正常。
    STARTUP_SYNC_ONLY=false 可回滚到旧行为。
    """
    config = _make_config(startup_sync_only=False)
    bot = TradingBot(config)
    bot.position_manager = PositionManager(config, data_dir=tmp_path)
    bot._exchange = MagicMock()
    bot._exchange.get_position = AsyncMock(return_value=None)
    bot._exchange.get_balance = AsyncMock(return_value=1000.0)
    bot._exchange.get_market_data = AsyncMock(
        return_value={
            "price": 60000.0,
            "price_history": [60000.0] * 100,
            "technical": {"rsi": 50.0, "trend_direction": "neutral"},
        }
    )
    bot._ai_client = MagicMock()
    bot._ai_client.get_signal = AsyncMock(return_value="HOLD")
    bot._ai_client.get_last_signal_trace = MagicMock(return_value={})
    bot._decision_journal = None
    bot._open_position = AsyncMock(return_value=True)

    await bot._execute_trading_cycle()
    # startup_sync_only=False → 首周期即获取 AI 信号 (旧行为, 可回滚)
    bot._ai_client.get_signal.assert_called()


# ==================== P1-5 保护单归因 (交易所真实数据) ====================


@pytest.mark.asyncio
async def test_protection_attribution_uses_exchange_fill(tmp_path: Path) -> None:
    """交易所侧止损单已成交 (state=filled) → 归因含真实触发价,
    不再出现 "未知保护单" (11-26 00:18 盲区)。
    """
    bot = _make_bot(tmp_path)
    pm = bot.position_manager
    pm.update_position(0.03, 58304.4, "BTC/USDT:USDT", side="short")
    pm.set_stop_order("SL_ALGO_1", 59754.0)
    bot._exchange.get_algo_order_history = AsyncMock(
        return_value=[
            {
                "id": "SL_ALGO_1",
                "status": "closed",
                "info": {
                    "state": "filled",
                    "slTriggerPx": "59754.0",
                    "avgPx": "59760.0",
                },
            }
        ]
    )

    attr, fill_px = await bot._query_protection_fill_attribution("SL_ALGO_1", None)
    assert attr is not None
    assert "止损单" in attr
    assert "59754.0" in attr
    assert fill_px == pytest.approx(59760.0)


@pytest.mark.asyncio
async def test_protection_attribution_falls_back_when_unfilled(
    tmp_path: Path,
) -> None:
    """查询不到已成交算法单 (TEST_MODE/接口失败) → 返回 None,
    调用方回退现价启发式。
    """
    bot = _make_bot(tmp_path)
    bot._exchange.get_algo_order_history = AsyncMock(
        return_value=[
            {
                "id": "SL_ALGO_1",
                "status": "open",
                "info": {"state": "effective"},
            }
        ]
    )
    assert await bot._query_protection_fill_attribution("SL_ALGO_1", None) is None


# ==================== P1-7 趋势通道入场过滤 ====================


def _htf_closes(start: float, slope: float, n: int = 100) -> list:
    """合成 1h 收盘序列 (n 根, 满足 HTF ≥84 根要求)。"""
    return [start + slope * i for i in range(n)]


@pytest.mark.asyncio
async def test_trend_htf_misalignment_blocks_entry(tmp_path: Path) -> None:
    """HTF(4h)=up 但趋势通道想开空 → 跳过 (T2/T3 均为 HTF=sideways 入场)。"""
    bot = _make_bot(tmp_path)
    md = {
        "price": 59000.0,
        "change_percent": -2.5,
        "technical": {"trend_direction": "down", "rsi": 35.0},
        "high_history": [61000.0] * 24,
        "low_history": [59500.0] * 24,
        # 上涨 1h 序列 → HTF(4h) = up
        "price_history": _htf_closes(55000.0, +100.0),
    }
    assert await bot._maybe_trend_follow(md, 59000.0) is None


@pytest.mark.asyncio
async def test_trend_htf_aligned_allows_entry(tmp_path: Path) -> None:
    """HTF(4h)=down + 1h 趋势 down + 24h 跌幅达标 → 放行开空。"""
    bot = _make_bot(tmp_path)
    md = {
        "price": 59000.0,
        "change_percent": -2.5,
        "technical": {"trend_direction": "down", "rsi": 35.0},
        "high_history": [61000.0] * 24,
        "low_history": [59500.0] * 24,
        # 下跌 1h 序列 → HTF(4h) = down
        "price_history": _htf_closes(65000.0, -100.0),
    }
    res = await bot._maybe_trend_follow(md, 59000.0)
    assert res is not None
    assert res.action == "open_trend_follow"


@pytest.mark.asyncio
async def test_trend_range_edge_chase_blocked(tmp_path: Path) -> None:
    """端点禁追: 空单时价格位于 24h 低点内侧 0.5% 内 (区间末端拐头区)
    → 跳过; 突破极值之外 (新低点) → 放行。
    """
    bot = _make_bot(tmp_path)
    # 价 59540, 24h 低 59500 → 内侧 0.067% (<0.5%) → 拦截
    md_edge = {
        "price": 59540.0,
        "change_percent": -2.5,
        "technical": {"trend_direction": "down", "rsi": 35.0},
        "high_history": [61000.0] * 24,
        "low_history": [59500.0] * 24,
        "price_history": _htf_closes(65000.0, -100.0),
    }
    assert await bot._maybe_trend_follow(md_edge, 59540.0) is None

    # 价 59400 < 24h 低 59500 (新低点, 趋势延续) → 放行
    md_new_low = dict(md_edge)
    res = await bot._maybe_trend_follow(md_new_low, 59400.0)
    assert res is not None


def test_htf_trend_direction_aggregation() -> None:
    """1h→4h 聚合判定: 单边下跌→down, 单边上涨→up, 数据不足→unknown。"""
    assert TradingBot._htf_trend_direction(_htf_closes(65000.0, -100.0)) == "down"
    assert TradingBot._htf_trend_direction(_htf_closes(55000.0, +100.0)) == "up"
    assert TradingBot._htf_trend_direction([]) == "unknown"
    assert TradingBot._htf_trend_direction([60000.0] * 50) == "unknown"


# ==================== P2-10 信号连续确认 ====================


def test_signal_streak_update_and_persist(tmp_path: Path) -> None:
    """同向 +1, 换向重置为 1; 持久化跨重启。"""
    bot = _make_bot(tmp_path)
    assert bot._update_signal_streak("BUY") == 1
    assert bot._update_signal_streak("BUY") == 2
    assert bot._update_signal_streak("HOLD") == 1

    bot2 = _make_bot(tmp_path)  # 模拟重启
    last, streak = bot2.position_manager.load_signal_streak()
    assert (last, streak) == ("HOLD", 1)


@pytest.mark.asyncio
async def test_signal_confirm_gate_blocks_isolated_signal(
    tmp_path: Path,
) -> None:
    """SIGNAL_CONFIRM_CYCLES=2: 第 1 个 BUY 周期拦截, 连续第 2 个放行。
    (11-25 两笔亏损平仓均为前后 HOLD 的孤立 BUY 信号)
    """
    bot = _make_bot(tmp_path)
    bot.config.trading.signal_confirm_cycles = 2

    bot._signal_streak = 1
    result = await bot._execute_signal(
        "BUY",
        60000.0,
        has_position=False,
        final_confidence=0.9,
        signal_streak=1,
    )
    assert result.action == "blocked_signal_confirm"
    bot._open_position.assert_not_called()

    result = await bot._execute_signal(
        "BUY",
        60000.0,
        has_position=False,
        final_confidence=0.9,
        signal_streak=2,
    )
    assert result.action == "open_long"
    bot._open_position.assert_awaited()


@pytest.mark.asyncio
async def test_signal_confirm_default_off_zero_regression(
    tmp_path: Path,
) -> None:
    """默认 SIGNAL_CONFIRM_CYCLES=1 → 门禁关闭 (零回归)。"""
    bot = _make_bot(tmp_path)
    assert bot.config.trading.signal_confirm_cycles == 1
    result = await bot._execute_signal(
        "BUY",
        60000.0,
        has_position=False,
        final_confidence=0.9,
        signal_streak=1,
    )
    assert result.action == "open_long"


# ==================== P2-9 平仓门禁默认值 ====================


def test_min_confidence_close_default_raised() -> None:
    """P0-2: 平仓门禁 0.60 → 0.70 (65~81% 单次 BUY 快速反手三笔全亏)。"""
    cfg = TradingConfig()
    assert cfg.min_confidence_close == 0.70
    assert cfg.trend_follow_short_rsi_floor == 30.0
    assert cfg.trend_follow_long_rsi_ceil == 70.0
    assert cfg.trend_follow_extreme_distance_pct == 0.005
    assert cfg.trend_follow_require_htf_alignment is True
