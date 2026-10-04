#!/usr/bin/env python3
"""决策日志周报（P1）：各层信号的分层胜率/收益统计。

用法:
  python scripts/decision_journal_report.py [--days 14] [--jev-conf 0.55] [--dir DIR]

输出四张表：Jev 分档 / LLM 信号 / 最终信号 / 翻转守卫拦截复盘。
数据源: data/trading_state/decision_journal-*.jsonl（Task 6 产出）。

error 周期过滤规则（execution.action == "error"）:
  异常可能发生在 integrator 写入 signal trace 之后，此时 cycle 的 final
  字段携带的是 integrator 残留的方向性信号、不可信。因此「最终信号」表与
  「翻转守卫拦截」表排除 error 周期；「Jev 分档」/「LLM 信号」两表保留
  error 周期（这两层是当轮真实判断，与异常无关）。
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

TS_FMT = "%Y-%m-%d %H:%M:%S"
DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data" / "trading_state"


def load_journal(
    days_dir: Path, since: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """读取 journal 文件，返回 (cycle 记录列表[已 join outcome], ts→outcome 映射)。

    两遍扫描：先收集全部 cycle 与 outcome（outcome 行总是晚于对应 cycle 行
    写入，可能落在更晚的文件），再按 ts join。坏行（JSON 解析失败 / 非对象）
    与坏文件（半写多字节的非法 UTF-8 / OSError）跳过，不中断统计。
    """
    cutoff = None
    if since:
        cutoff = datetime.strptime(since, TS_FMT)
    cycles: List[Dict[str, Any]] = []
    outcomes: Dict[str, Dict[str, Any]] = {}
    for f in sorted(days_dir.glob("decision_journal-*.jsonl")):
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as e:
            # 文件级损坏（半写多字节/权限）：跳过该文件，不影响整份周报
            # （与 DecisionJournal.backfill 的容错一致）
            print(f"[warn] 跳过 {f.name}: {e}", file=sys.stderr)
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue  # 合法 JSON 但非对象（数组/标量）跳过
            if rec.get("type") == "outcome":
                ts = rec.get("ts")
                if ts:
                    prev = outcomes.get(ts, {})
                    prev.update(rec)
                    outcomes[ts] = prev
            elif rec.get("type") == "cycle":
                cycles.append(rec)

    cutoff_str = cutoff.strftime(TS_FMT) if cutoff else None
    selected: List[Dict[str, Any]] = []
    for rec in cycles:
        ts = rec.get("ts")
        if cutoff_str and ts and ts < cutoff_str:
            continue
        o = outcomes.get(ts)
        if o:
            for k, v in o.items():
                if k not in rec:
                    rec[k] = v
        selected.append(rec)
    return selected, outcomes


def agg_by(
    cycles: List[Dict[str, Any]], key_fn: Callable[[Dict[str, Any]], str]
) -> List[Dict[str, Any]]:
    """按 key_fn 分组：计数 / T+4h 平均收益 / 胜率（direction_correct 非 None 样本）。"""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for c in cycles:
        groups.setdefault(key_fn(c), []).append(c)
    rows = []
    for key in sorted(groups):
        items = groups[key]
        fwds = [
            i.get("forward_return_4h")
            for i in items
            if i.get("forward_return_4h") is not None
        ]
        correct = [
            i["direction_correct_4h"]
            for i in items
            if i.get("direction_correct_4h") is not None
        ]
        rows.append(
            {
                "key": key,
                "count": len(items),
                "with_outcome": len(fwds),
                "avg_fwd_4h": round(sum(fwds) / len(fwds), 6) if fwds else None,
                "win_rate_4h": (
                    round(sum(1 for x in correct if x) / len(correct), 4)
                    if correct
                    else None
                ),
            }
        )
    return rows


def _print_table(title: str, rows: List[Dict[str, Any]]) -> None:
    print(f"\n== {title} ==")
    if not rows:
        print("  (无数据)")
        return
    print(f"  {'key':40s} {'n':>5s} {'回填':>5s} {'T+4h均':>10s} {'T+4h胜率':>9s}")
    for r in rows:
        avg = r["avg_fwd_4h"]
        win = r["win_rate_4h"]
        avg_txt = "%+.4f%%" % (avg * 100) if avg is not None else "n/a"
        win_txt = "%d%%" % (win * 100) if win is not None else "n/a"
        print(
            f"  {r['key']:40s} {r['count']:5d} {r['with_outcome']:5d} "
            f"{avg_txt:>10s} {win_txt:>9s}"
        )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="决策日志周报")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--jev-conf", type=float, default=0.55)
    parser.add_argument("--dir", type=str, default=str(DEFAULT_DIR))
    args = parser.parse_args(argv)

    since = (datetime.now() - timedelta(days=args.days)).strftime(TS_FMT)
    cycles, _ = load_journal(Path(args.dir), since=since)
    if not cycles:
        print(f"无数据（{args.dir}，since {since}）")
        return 0

    def jev_key(c):
        jev = c.get("jev") or {}
        conf = float(jev.get("confidence") or 0.0)
        bucket = (
            "<0.55"
            if conf < args.jev_conf
            else ("0.55-0.75" if conf < 0.75 else ">=0.75")
        )
        return f"jev:{jev.get('choice', '?')}:{bucket}"

    def llm_key(c):
        llm = c.get("llm") or {}
        return f"llm:{llm.get('signal', '?')}"

    def final_key(c):
        return f"final:{c.get('final', '?')}"

    def is_error_cycle(c):
        return ((c.get("execution") or {}).get("action")) == "error"

    # error 周期的 final 不可信（integrator 已写 trace 后异常），
    # 仅「最终信号」/「翻转守卫拦截」表排除，Jev/LLM 表保留
    trusted = [c for c in cycles if not is_error_cycle(c)]

    _print_table(
        f"Jev 分档（近 {args.days} 天，conf 阈值 {args.jev_conf}）",
        agg_by(cycles, jev_key),
    )
    _print_table("LLM 信号", agg_by(cycles, llm_key))
    _print_table("最终信号", agg_by(trusted, final_key))

    blocked = [
        c
        for c in trusted
        if any(
            "被阻止翻转" in a or "不翻转信号" in a
            for a in ((c.get("integrator") or {}).get("adjustments") or [])
        )
    ]
    _print_table(
        f"翻转守卫拦截复盘（{len(blocked)} 次，若放行会怎样）",
        agg_by(blocked, final_key),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
