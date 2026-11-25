# -*- coding: utf-8 -*-
"""趋势跟踪回放工具单测 (Task 1)。

测试口径与 docs/superpowers/specs/2026-11-25-trend-follow-channel-design.md
"模块 0" 节一致: SMA10/20 1h 趋势方向 + 24h 涨跌幅 ±2% + RSI 排除,
1R 保本 / 2R 起 3×ATR 追踪 (只收紧) / 10R 安全止盈, 每方向每日 1 次。
"""

import datetime
from typing import Dict, List

import pytest

from alpha_trading_bot.utils.trend_replay import (
    Candle,
    ReplayConfig,
    simulate_trades,
    trigger_at,
)

TS0 = 1765000000000  # 任意起点, 单位 ms
H = 3600 * 1000
M15 = 900 * 1000


def _mk_hour(ts: int, o: float, c: float) -> Candle:
    return {"ts": ts, "o": o, "h": max(o, c) + 10.0, "l": min(o, c) - 10.0, "c": c}


def _sawtooth_decline(n_decline: int = 50, base: float = 62000.0) -> List[Candle]:
    """前 30 根平盘, 之后锯齿下跌 (偶数小时 -200 / 奇数小时 +90)。"""
    bars: List[Candle] = []
    price = base
    for i in range(30 + n_decline):
        ts = TS0 + i * H
        if i >= 30:
            step = -200.0 if (i - 30) % 2 == 0 else 90.0
            o = price
            price = price + step
        else:
            o = price
        bars.append(_mk_hour(ts, o, price))
    return bars


def _sawtooth_rally(n_rally: int = 50, base: float = 58000.0) -> List[Candle]:
    bars: List[Candle] = []
    price = base
    for i in range(30 + n_rally):
        ts = TS0 + i * H
        if i >= 30:
            step = 200.0 if (i - 30) % 2 == 0 else -90.0
            o = price
            price = price + step
        else:
            o = price
        bars.append(_mk_hour(ts, o, price))
    return bars


def _chop(n: int = 60, base: float = 60000.0) -> List[Candle]:
    bars: List[Candle] = []
    price = base
    for i in range(n):
        ts = TS0 + i * H
        step = 30.0 if i % 2 == 0 else -30.0
        o = price
        price = price + step
        bars.append(_mk_hour(ts, o, price))
    return bars


def _to_m15(h1: List[Candle]) -> List[Candle]:
    """每根 1h 拆 4 根 15m (ts = 小时起点 + k*15m, OKX 口径为 bar 开始时间)。"""
    out: List[Candle] = []
    for b in h1:
        prev_c = b["o"]
        for k in range(4):
            ts = b["ts"] + k * M15
            frac = (k + 1) / 4.0
            c = b["o"] + (b["c"] - b["o"]) * frac
            o = prev_c
            out.append(
                {
                    "ts": ts,
                    "o": o,
                    "h": max(o, c) + 5.0,
                    "l": min(o, c) - 5.0,
                    "c": c,
                }
            )
            prev_c = c
    return out


def test_trigger_short_on_sawtooth_decline():
    bars = _sawtooth_decline()
    closes = [b["c"] for b in bars]
    highs = [b["h"] for b in bars]
    lows = [b["l"] for b in bars]
    assert trigger_at(closes, highs, lows, 59, ReplayConfig()) == "short"


def test_trigger_long_on_sawtooth_rally():
    bars = _sawtooth_rally()
    closes = [b["c"] for b in bars]
    highs = [b["h"] for b in bars]
    lows = [b["l"] for b in bars]
    assert trigger_at(closes, highs, lows, 59, ReplayConfig()) == "long"


def test_no_trigger_in_chop():
    bars = _chop()
    closes = [b["c"] for b in bars]
    highs = [b["h"] for b in bars]
    lows = [b["l"] for b in bars]
    assert trigger_at(closes, highs, lows, 59, ReplayConfig()) is None


def test_rsi_exclusion_blocks_short():
    # 锯齿下跌 + 末 5 根急跌 (使 RSI(1h) < 20), 24h 跌幅与趋势方向仍满足
    bars = _sawtooth_decline()
    for i in range(5):
        b = bars[59 - i]  # t=59 窗口内的末 5 根 (窗口 = bars[0..59])
        b["c"] = b["c"] - 1200.0
        b["l"] = b["c"] - 10.0
        b["h"] = max(b["h"], b["o"])
    closes = [b["c"] for b in bars]
    highs = [b["h"] for b in bars]
    lows = [b["l"] for b in bars]
    assert trigger_at(closes, highs, lows, 59, ReplayConfig()) is None


def test_simulate_captures_decline_with_trail():
    h1 = _sawtooth_decline(n_decline=50)
    m15 = _to_m15(h1)
    trades = simulate_trades(h1, m15, ReplayConfig())
    assert len(trades) >= 1
    first = trades[0]
    assert first["side"] == "short"
    assert first["pnl_r"] > 0
    assert first["exit"] < first["entry"]


def test_simulate_respects_daily_limit():
    # 连续两天都满足触发条件时, 同一天只允许 1 笔
    h1 = _sawtooth_decline(n_decline=80)
    m15 = _to_m15(h1)
    cfg = ReplayConfig(daily_limit=1, cooldown_minutes=0)
    trades = simulate_trades(h1, m15, cfg)
    days = {
        datetime.datetime.fromtimestamp(t["entry_ts"] / 1000).strftime("%Y-%m-%d")
        for t in trades
    }
    # 同一 (日, 方向) 至多 1 笔
    by_key: Dict[tuple, int] = {}
    for t in trades:
        key = (
            datetime.datetime.fromtimestamp(t["entry_ts"] / 1000).strftime("%Y-%m-%d"),
            t["side"],
        )
        by_key[key] = by_key.get(key, 0) + 1
    assert all(v <= 1 for v in by_key.values())
    assert len(days) >= 1


def test_simulate_no_trades_without_15m_data():
    h1 = _sawtooth_decline()
    assert simulate_trades(h1, [], ReplayConfig()) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
