# -*- coding: utf-8 -*-
"""趋势跟踪通道回放 (纯函数核心)。

口径与 docs/superpowers/specs/2026-11-25-trend-follow-channel-design.md
"模块 0" 节一致 (变体 E, 11-13 → 11-25 真实 OKX 数据回放 +10.34R):

- 触发: 生产 calculate_trend (SMA10/20, 1h) 方向 + 24h 涨跌幅 ±change_pct
  + RSI(1h) 排除 (RSI < short_rsi_floor 禁空 / RSI > long_rsi_ceil 禁多)
- 入场: 触发 1h 收盘后的下一根 15m K 线开盘 (bot 下一周期市价口径;
  1h 序列含未收盘 K 线, 与实盘 market_data 一致)
- 止损: 24h 摆动点 ± stop_atr_buffer×ATR(1h), 距离上限 max_stop_pct
- 出场: 浮盈 ≥ be_at_r → 保本 (entry×1.001 / ×0.999); 浮盈 ≥ trail_at_r →
  入场后极值 ∓ trail_atr_mult×ATR(1h) 追踪 (只收紧); safety_tp_r 安全止盈
- 约束: 每 (日, 方向) daily_limit 笔, 平仓后 cooldown_minutes 冷却, 单仓位

本模块仅供回放/回归, 不参与实盘。
"""

import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .technical import calculate_atr, calculate_rsi, calculate_trend

Candle = Dict[str, float]

_HOUR_MS = 3600 * 1000
_RSI_PERIOD = 14
_ATR_PERIOD = 14


@dataclass
class ReplayConfig:
    """回放参数 (默认值 = spec 模块 0 的 12 天回放验证值)。"""

    be_at_r: float = 1.0
    trail_at_r: float = 2.0
    trail_atr_mult: float = 3.0
    safety_tp_r: float = 10.0
    daily_limit: int = 1
    cooldown_minutes: int = 30
    change_pct: float = 2.0
    short_rsi_floor: float = 20.0
    long_rsi_ceil: float = 80.0
    stop_atr_buffer: float = 0.5
    max_stop_pct: float = 0.025


def trigger_at(
    closes: List[float],
    highs: List[float],
    lows: List[float],
    t: int,
    cfg: ReplayConfig,
) -> Optional[str]:
    """判断 t (0-based, 最旧起) 是否触发趋势跟踪。

    Returns:
        "short" / "long" / None
    """
    if t < 24 or t >= len(closes):
        return None
    trend = calculate_trend(closes[: t + 1])
    direction = trend.get("direction", "neutral")
    change_24h = (closes[t] - closes[t - 24]) / closes[t - 24] * 100
    rsi = calculate_rsi(closes[: t + 1], _RSI_PERIOD)
    if (
        direction == "down"
        and change_24h <= -cfg.change_pct
        and rsi >= cfg.short_rsi_floor
    ):
        return "short"
    if direction == "up" and change_24h >= cfg.change_pct and rsi <= cfg.long_rsi_ceil:
        return "long"
    return None


def _atr_at(h1: List[Candle], t: int) -> float:
    highs = [b["h"] for b in h1[: t + 1]]
    lows = [b["l"] for b in h1[: t + 1]]
    closes = [b["c"] for b in h1[: t + 1]]
    if len(closes) < _ATR_PERIOD + 1:  # calculate_atr 自身的最小数据要求
        return 0.0
    value, _ = calculate_atr(highs, lows, closes, _ATR_PERIOD)
    return float(value)


def _initial_stop(
    h1: List[Candle], t: int, side: str, entry: float, cfg: ReplayConfig
) -> Optional[float]:
    """24h 摆动点 ± buffer×ATR(1h), 距离上限 max_stop_pct。"""
    if t < 24:
        return None
    atr = _atr_at(h1, t)
    if side == "short":
        swing = max(b["h"] for b in h1[max(0, t - 24) : t])
        stop = min(swing + cfg.stop_atr_buffer * atr, entry * (1 + cfg.max_stop_pct))
        if stop <= entry:
            stop = entry * (1 + cfg.max_stop_pct)
    else:
        swing = min(b["l"] for b in h1[max(0, t - 24) : t])
        stop = max(swing - cfg.stop_atr_buffer * atr, entry * (1 - cfg.max_stop_pct))
        if stop >= entry:
            stop = entry * (1 - cfg.max_stop_pct)
    return stop


def _simulate_one(
    h1: List[Candle],
    m15: List[Candle],
    side: str,
    t: int,
    cfg: ReplayConfig,
) -> Optional[Dict[str, Any]]:
    """单笔模拟: 入场 = 触发 1h 后的下一根 15m 开盘, 15m 路径出场。"""
    bar = h1[t]
    # 入场 = 触发 1h 收盘后的下一根 15m (ts 为 bar 开始时间, OKX 口径)
    entry_bar = next((b for b in m15 if b["ts"] >= bar["ts"] + _HOUR_MS), None)
    if entry_bar is None:
        return None
    entry = entry_bar["o"]
    if entry <= 0:
        return None
    stop0 = _initial_stop(h1, t, side, entry, cfg)
    if stop0 is None:
        return None
    if side == "short":
        risk = stop0 - entry
    else:
        risk = entry - stop0
    if risk <= 0:
        return None
    atr = _atr_at(h1, t)
    tp = (
        entry - cfg.safety_tp_r * risk
        if side == "short"
        else entry + cfg.safety_tp_r * risk
    )
    bars = [b for b in m15 if b["ts"] > entry_bar["ts"]]
    if not bars:
        return None
    extreme = entry
    stop = float(stop0)
    exit_price: Optional[float] = None
    exit_ts: float = 0.0
    reason = ""
    for b in bars:
        if side == "short":
            extreme = min(extreme, b["l"])
            upl_r = (entry - b["c"]) / risk
            if upl_r >= cfg.be_at_r and stop > entry * 1.001:
                stop = entry * 1.001
            # 空头追踪 = 最低价上方 k×ATR (买入触发, 锁利); min = 只收紧(下移)
            if upl_r >= cfg.trail_at_r and atr > 0:
                stop = min(stop, extreme + cfg.trail_atr_mult * atr)
            if b["h"] >= stop:
                exit_price, exit_ts, reason = stop, b["ts"], "trail/be/stop"
                break
            if b["l"] <= tp:
                exit_price, exit_ts, reason = tp, b["ts"], "tp"
                break
        else:
            extreme = max(extreme, b["h"])
            upl_r = (b["c"] - entry) / risk
            if upl_r >= cfg.be_at_r and stop < entry * 0.999:
                stop = entry * 0.999
            if upl_r >= cfg.trail_at_r and atr > 0:
                stop = max(stop, extreme - cfg.trail_atr_mult * atr)
            if b["l"] <= stop:
                exit_price, exit_ts, reason = stop, b["ts"], "trail/be/stop"
                break
            if b["h"] >= tp:
                exit_price, exit_ts, reason = tp, b["ts"], "tp"
                break
    if exit_price is None:
        last = bars[-1]
        exit_price, exit_ts, reason = last["c"], last["ts"], "open@eod"
    pnl_r = (
        (entry - exit_price) / risk if side == "short" else (exit_price - entry) / risk
    )
    return {
        "side": side,
        "entry_ts": entry_bar["ts"],
        "entry": entry,
        "stop0": stop0,
        "risk": risk,
        "exit_ts": exit_ts,
        "exit": exit_price,
        "reason": reason,
        "pnl_r": pnl_r,
    }


def simulate_trades(
    h1: List[Candle], m15: List[Candle], cfg: ReplayConfig
) -> List[Dict[str, Any]]:
    """回放趋势通道: 返回按入场时间排序的交易列表。

    Args:
        h1: 1h K 线 (最旧起, 键 ts/o/h/l/c, ts 单位 ms)
        m15: 15m K 线 (同上; 为空时返回 [])
        cfg: 回放参数
    """
    if not m15:
        return []
    closes = [b["c"] for b in h1]
    highs = [b["h"] for b in h1]
    lows = [b["l"] for b in h1]
    daily_counts: Dict[tuple, int] = {}
    trades: List[Dict[str, Any]] = []
    last_exit_ts = 0
    cooldown_ms = cfg.cooldown_minutes * 60 * 1000
    for t in range(24, len(h1)):
        side = trigger_at(closes, highs, lows, t, cfg)
        if side is None:
            continue
        day = datetime.datetime.fromtimestamp(h1[t]["ts"] / 1000).strftime("%Y-%m-%d")
        key = (day, side)
        if daily_counts.get(key, 0) >= cfg.daily_limit:
            continue
        trade = _simulate_one(h1, m15, side, t, cfg)
        if trade is None:
            continue
        if trade["entry_ts"] - last_exit_ts < cooldown_ms:
            continue
        daily_counts[key] = daily_counts.get(key, 0) + 1
        last_exit_ts = trade["exit_ts"]
        trades.append(trade)
    trades.sort(key=lambda x: x["entry_ts"])
    return trades
