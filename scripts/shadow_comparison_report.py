#!/usr/bin/env python3
"""Shadow 模式对比报告：Jev 快车道（本会怎么判） vs LLM 实际决策。

用法: python scripts/shadow_comparison_report.py [log文件...]
默认分析 logs/ 下所有 alpha-trading-bot-okx.log.* 文件。

输出:
- 模式切换点（on -> shadow）
- Jev shadow 决策分布（choice/confidence）
- Jev 高置信 vs LLM 实际信号一致率（分档）
- 分歧案例明细（Jev 与 LLM 不一致的周期）
- LLM 信号分布 / 503 失败 / BUY 信号与执行
- 每日价格轨迹与 RSI
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"

RE_CYCLE_START = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ .*开始新的交易周期")
RE_PRICE = re.compile(r"\[市场数据\] 当前价格: ([\d.]+)")
RE_RSI = re.compile(r"\[市场数据\] RSI: ([\d.]+)")
RE_CHG24 = re.compile(r"\[市场数据\] 24h涨跌幅: ([\-\d.]+)%")
RE_JEV_ADOPT = re.compile(r"\[Jev快车道\] 采用 (\w+) \(conf=([\d.]+)")
RE_JEV_SHADOW = re.compile(r"\[Jev快车道\]\[shadow\] 本可采用 (\w+) \(conf=([\d.]+)")
RE_JEV_ESCALATE = re.compile(r"置信度计算: choice=(\w+), API返回confidence=([\d.]+), 概率分布\{([^}]*)\}")
RE_LLM = re.compile(r"\[AI响应\] 提供商=(\w+), 信号=(\w+), 置信度=(\d+)%")
RE_INTEGRATOR = re.compile(r"\[AI信号集成\] 原始=(\w+)\((\d+)%\) → 最终=(\w+)\((\d+)%\)")
RE_503 = re.compile(r"最终失败.*HTTP 503")
RE_BUY_EXEC = re.compile(r"BUY信号 \+ 无持仓 -> 执行开仓")
RE_CANCEL = re.compile(r"无法计算有效交易量")

# shadow 模式生效时间（用户于该时刻修改 .env 并重启容器）
SHADOW_FROM = "2026-10-01 12:01:57"


@dataclass
class Cycle:
    start: str = ""
    price: Optional[float] = None
    rsi: Optional[float] = None
    chg24: Optional[float] = None
    jev_mode: str = ""  # on / shadow（按时间切分）
    jev_outcome: str = ""  # adopt / would_adopt / escalate / risk_gate / none
    jev_choice: str = ""
    jev_conf: float = 0.0
    jev_probs: str = ""
    llm_provider: str = ""
    llm_signal: str = ""
    llm_conf: int = 0
    final_signal: str = ""
    final_conf: int = 0
    llm_503: bool = False
    buy_exec: bool = False
    buy_cancel: bool = False


def parse_file(path: Path) -> List[Cycle]:
    cycles: List[Cycle] = []
    cur = Cycle()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = RE_CYCLE_START.search(line)
        if m:
            if cur.start:
                cycles.append(cur)
            cur = Cycle(start=m.group(1))
            cur.jev_mode = "shadow" if cur.start >= SHADOW_FROM else "on"
            continue
        m = RE_PRICE.search(line)
        if m and cur.price is None:
            cur.price = float(m.group(1))
        m = RE_RSI.search(line)
        if m and cur.rsi is None:
            cur.rsi = float(m.group(1))
        m = RE_CHG24.search(line)
        if m and cur.chg24 is None:
            cur.chg24 = float(m.group(1))
        m = RE_JEV_ADOPT.search(line)
        if m and not cur.jev_choice:
            cur.jev_outcome = "adopt"
            cur.jev_choice, cur.jev_conf = m.group(1), float(m.group(2))
            continue
        m = RE_JEV_SHADOW.search(line)
        if m and not cur.jev_choice:
            cur.jev_outcome = "would_adopt"
            cur.jev_choice, cur.jev_conf = m.group(1), float(m.group(2))
            continue
        m = RE_JEV_ESCALATE.search(line)
        if m and not cur.jev_choice:
            cur.jev_outcome = "escalate"
            cur.jev_choice, cur.jev_conf, cur.jev_probs = (
                m.group(1), float(m.group(2)), m.group(3),
            )
        m = RE_LLM.search(line)
        if m and not cur.llm_signal:
            cur.llm_provider, cur.llm_signal, cur.llm_conf = (
                m.group(1), m.group(2), int(m.group(3)),
            )
        m = RE_INTEGRATOR.search(line)
        if m and not cur.final_signal:
            cur.final_signal, cur.final_conf = m.group(3), int(m.group(4))
        if RE_503.search(line):
            cur.llm_503 = True
        if RE_BUY_EXEC.search(line):
            cur.buy_exec = True
        if RE_CANCEL.search(line):
            cur.buy_cancel = True
    if cur.start:
        cycles.append(cur)
    return cycles


def bucket(conf: float, choice: str) -> str:
    if choice == "buy":
        return "clear-buy" if conf >= 0.75 else "weak-buy"
    if choice == "hold":
        return "clear-hold" if conf >= 0.75 else "weak-hold"
    return f"weak-{choice}"


def pct(n: int, d: int) -> str:
    return f"{100.0 * n / d:.1f}%" if d else "n/a"


def main() -> None:
    if len(sys.argv) > 1:
        files = [Path(p) for p in sys.argv[1:]]
    else:
        files = sorted(LOG_DIR.glob("alpha-trading-bot-okx.log.*"))
    all_cycles: List[Cycle] = []
    for f in files:
        all_cycles.extend(parse_file(f))

    # ---- 模式确认 ----
    print("=" * 72)
    print("模式与决策总览")
    print("=" * 72)
    on = [c for c in all_cycles if c.jev_mode == "on"]
    shadow = [c for c in all_cycles if c.jev_mode == "shadow"]
    print(f"  on 模式周期: {len(on)} (10/01 00:00 ~ 12:01, Jev 直接采用)")
    print(f"  shadow 周期: {len(shadow)} (10/01 12:01:57 起, 全部走 LLM)")
    outcome_cnt = Counter(c.jev_outcome for c in shadow)
    print(f"  shadow 内 Jev 结果: {dict(outcome_cnt)}")
    on_outcome = Counter(c.jev_outcome for c in on)
    print(f"  on    内 Jev 结果: {dict(on_outcome)}")

    # ---- Jev 决策分布（shadow 全量）----
    print("\n" + "=" * 72)
    print("Jev (shadow) 全量决策分布（adopted 档位 = 若开 on 会直接采用）")
    print("=" * 72)
    for ch in ("buy", "hold", "sell", "short"):
        group = [c for c in shadow if c.jev_choice == ch]
        if not group:
            continue
        confs = sorted(c.jev_conf for c in group)
        hist = Counter(int(c * 20) / 20 for c in confs)
        dist = ", ".join(f"{k:.2f}×{v}" for k, v in sorted(hist.items()))
        print(f"  choice={ch:6s} n={len(group):3d}  max={max(confs):.2f}  分布: {dist}")

    # ---- LLM / 最终信号 ----
    print("\n" + "=" * 72)
    print("LLM 实际响应 / 最终信号（shadow 周期内）")
    print("=" * 72)
    llm_cnt = Counter(c.llm_signal for c in shadow if c.llm_signal)
    print(f"  LLM 响应: {dict(llm_cnt)}  (503失败周期: {sum(1 for c in shadow if c.llm_503)})")
    final_cnt = Counter(c.final_signal for c in shadow if c.final_signal)
    print(f"  最终信号: {dict(final_cnt)}")

    # ---- 核心对比：按用户假设的三分支 ----
    print("\n" + "=" * 72)
    print("三分支验证（LLM 有响应的 shadow 周期）")
    print("=" * 72)
    valid = [c for c in shadow if c.llm_signal]
    print(f"  有效周期: {len(valid)}\n")
    # 分支1: Jev 高置信 hold（清晰不符合买入）
    for label, sel in (
        ("分支1a: Jev hold conf≥0.50(现阈值, 会直接终止)",
         [c for c in valid if c.jev_choice == "hold" and c.jev_conf >= 0.50]),
        ("分支1b: Jev hold conf≥0.75(更严的'清晰')",
         [c for c in valid if c.jev_choice == "hold" and c.jev_conf >= 0.75]),
        ("分支2 : Jev buy  conf≥0.75(清晰符合, 会直接买)",
         [c for c in valid if c.jev_choice == "buy" and c.jev_conf >= 0.75]),
        ("分支3 : Jev 其余(不清晰, 升级 LLM)",
         [c for c in valid if not (
             c.jev_choice == "hold" and c.jev_conf >= 0.50
             or c.jev_choice == "buy" and c.jev_conf >= 0.75)]),
    ):
        llm_dist = Counter(c.llm_signal for c in sel)
        final_dist = Counter(c.final_signal for c in sel if c.final_signal)
        missed = [c for c in sel if c.final_signal == "BUY"]
        print(
            f"  {label}\n"
            f"      n={len(sel):3d}  LLM: {str(dict(llm_dist) or '-'):28s}  最终: {dict(final_dist) or '-'}"
            f"  其中最终BUY={len(missed)}"
        )

    # ---- 关键分歧案例 ----
    print("\n" + "=" * 72)
    print("关键分歧案例（shadow 全量）")
    print("=" * 72)
    print("  [A] Jev 高置信 hold(≥0.50) 但最终信号=BUY（若 Jev 直接终止会错过的买入）:")
    for c in shadow:
        if c.jev_choice == "hold" and c.jev_conf >= 0.50 and c.final_signal == "BUY":
            print(
                f"      {c.start} price={c.price} rsi={c.rsi} jev_hold={c.jev_conf:.2f} "
                f"llm={c.llm_signal}({c.llm_conf}%) final=BUY({c.final_conf}%)"
            )
    print("  [B] Jev buy 置信度 Top 10（'直接买'分支的接近程度）:")
    buys = sorted((c for c in shadow if c.jev_choice == "buy"), key=lambda x: -x.jev_conf)[:10]
    for c in buys:
        print(
            f"      {c.start} jev_buy={c.jev_conf:.2f} ({c.jev_probs}) "
            f"llm={c.llm_signal}({c.llm_conf}%) final={c.final_signal}({c.final_conf}%)"
        )
    print("  [C] 最终 BUY 信号与执行:")
    for c in shadow:
        if c.final_signal == "BUY" or c.buy_exec:
            print(
                f"      {c.start} price={c.price} rsi={c.rsi} final={c.final_signal}({c.final_conf}%) "
                f"开仓尝试={c.buy_exec} 开仓取消={c.buy_cancel}"
            )
    print("  [D] Jev 高置信(≥0.75) 但非 hold（sell/short/buy 的'清晰'案例）:")
    for c in shadow:
        if c.jev_choice in ("sell", "short", "buy") and c.jev_conf >= 0.75:
            print(
                f"      {c.start} {c.jev_choice}={c.jev_conf:.2f} ({c.jev_probs}) "
                f"llm={c.llm_signal}({c.llm_conf}%) final={c.final_signal}({c.final_conf}%)"
            )

    # ---- 每日价格轨迹 ----
    print("\n" + "=" * 72)
    print("每日价格 / RSI 轨迹（shadow 周期）")
    print("=" * 72)
    by_day: dict = {}
    for c in shadow:
        day = c.start[:10]
        by_day.setdefault(day, []).append(c)
    for day in sorted(by_day):
        cs = by_day[day]
        prices = [c.price for c in cs if c.price]
        rsis = [c.rsi for c in cs if c.rsi]
        chgs = [c.chg24 for c in cs if c.chg24 is not None]
        print(
            f"  {day}: n={len(cs):3d} 价格 {min(prices):.0f}~{max(prices):.0f} "
            f"(首{prices[0]:.0f}→尾{prices[-1]:.0f})  RSI {min(rsis):.0f}~{max(rsis):.0f} "
            f"24h涨跌 {min(chgs):.2f}%~{max(chgs):.2f}%"
        )


if __name__ == "__main__":
    main()
