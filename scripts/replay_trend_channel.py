#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""趋势跟踪通道回放 CLI (仅供回放/回归, 不参与实盘)。

用法:
    python scripts/replay_trend_channel.py --fetch --days 14
    python scripts/replay_trend_channel.py --data-dir scripts/.replay_data

--fetch: 拉 OKX 公共 K 线 (1H candles + 15m history-candles 分页) 存 data-dir;
无 --fetch: 直接读 data-dir 下 okx_1H.json / okx_15m_full.json
(OKX 原始 JSON 行数组: [ts, o, h, l, c, ...])。

阈值/参数以 ReplayConfig 默认值为准 (spec 模块 0 回放验证值)。
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alpha_trading_bot.utils.trend_replay import (  # noqa: E402
    Candle,
    ReplayConfig,
    simulate_trades,
)


def _fetch_url(url: str) -> Any:
    """curl 拉取 (公共接口, 无需鉴权; urllib 默认 UA 会被 403)。"""
    out = subprocess.run(["curl", "-s", url], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"curl 失败: {out.stderr}")
    return json.loads(out.stdout)


def fetch_candles(inst: str, days: int, data_dir: Path) -> None:
    """拉 1H (limit=300) + 15m 分页 (history-candles, 100/次)。"""
    data_dir.mkdir(parents=True, exist_ok=True)
    one_h = _fetch_url(
        f"https://www.okx.com/api/v5/market/candles" f"?instId={inst}&bar=1H&limit=300"
    )
    rows = one_h.get("data") or []
    if not rows:
        raise RuntimeError(f"1H 拉取失败: {one_h.get('msg')}")
    (data_dir / "okx_1H.json").write_text(json.dumps(rows))

    cutoff = int(time.time() * 1000) - days * 24 * 3600 * 1000
    all_15m: Dict[int, List[str]] = {}
    ts = int(time.time() * 1000)
    for _ in range(500):
        data = (
            _fetch_url(
                f"https://www.okx.com/api/v5/market/history-candles"
                f"?instId={inst}&bar=15m&after={ts}&limit=100"
            ).get("data")
            or []
        )
        if not data:
            break
        for row in data:
            all_15m[int(row[0])] = row
        oldest = int(data[-1][0])
        if oldest <= cutoff:
            break
        ts = oldest - 1
        time.sleep(0.2)
    rows15 = sorted(all_15m.values(), key=lambda r: int(r[0]))
    (data_dir / "okx_15m_full.json").write_text(json.dumps(rows15))
    print(
        f"已拉取: 1H {len(rows)} 根, 15m {len(rows15)} 根 "
        f"({datetime.fromtimestamp(int(rows15[0][0]) / 1000)} -> "
        f"{datetime.fromtimestamp(int(rows15[-1][0]) / 1000)})"
    )


def _load_rows(path: Path) -> List[List[Any]]:
    """兼容两种保存格式: 纯行数组 / OKX 完整响应对象 (取 data)。"""
    parsed = json.loads(path.read_text())
    if isinstance(parsed, dict):
        parsed = parsed.get("data") or []
    return parsed


def _to_candles(rows: List[List[Any]]) -> List[Candle]:
    out = [
        {
            "ts": int(r[0]),
            "o": float(r[1]),
            "h": float(r[2]),
            "l": float(r[3]),
            "c": float(r[4]),
        }
        for r in rows
    ]
    out.sort(key=lambda x: x["ts"])
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="趋势跟踪通道回放 (回归基线)")
    parser.add_argument("--inst", default="BTC-USDT-SWAP")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument(
        "--data-dir", default=str(Path(__file__).parent / ".replay_data")
    )
    parser.add_argument("--fetch", action="store_true", help="拉取最新 K 线数据")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if args.fetch:
        fetch_candles(args.inst, args.days, data_dir)

    h1_path = data_dir / "okx_1H.json"
    m15_path = data_dir / "okx_15m_full.json"
    if not h1_path.exists() or not m15_path.exists():
        print(f"数据不存在: {h1_path} / {m15_path} (用 --fetch 拉取)")
        return 1

    h1 = _to_candles(_load_rows(h1_path))
    m15 = _to_candles(_load_rows(m15_path))
    trades = simulate_trades(h1, m15, ReplayConfig())

    def fmt(ts: int) -> str:
        return datetime.fromtimestamp(ts / 1000).strftime("%m-%d %H:%M")

    print(f"\n===== 趋势跟踪回放 ({args.inst}, 变体E 默认参数) =====")
    for x in trades:
        line = (
            f"  {fmt(x['entry_ts'])} {x['side']:5s} 入={x['entry']:7.0f} "
            f"R={x['risk'] / x['entry'] * 100:4.2f}% -> "
            f"{fmt(x['exit_ts'])} {x['exit']:7.0f} {x['reason']:12s} "
            f"{x['pnl_r']:+6.2f}R"
        )
        print(line)
    if trades:
        total = sum(t["pnl_r"] for t in trades)
        wins = len([t for t in trades if t["pnl_r"] > 0])
        print(
            f"  >>> 共 {len(trades)} 笔, 总 {total:+.2f}R, 胜率 {wins}/{len(trades)}, "
            f"最差 {min(t['pnl_r'] for t in trades):+.2f}R"
        )
    else:
        print("  >>> 无触发 (窗口内无满足条件的趋势段)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
