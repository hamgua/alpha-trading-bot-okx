#!/usr/bin/env python3
"""
Jev 快车道日志分析报告（观察期数据 → 调参决策）

用法:
    .venv/bin/python scripts/jev_fast_lane_report.py <logfile> [logfile2 ...]

从 bot 日志中提取 Jev 快车道的完整观测数据：
- 结果分布（adopt / low_confidence / risk_gate / timeout / auth_error /
  api_error / bad_response / shadow / 未启用）
- Jev 置信度分布（总体直方图 + 按 choice 分组的统计）
- Jev 延迟 vs LLM 延迟（p50/p95）
- 采用事件清单（Jev 真实驱动的交易决策，供人工复盘）
- 升级周期的一致率（Jev 初读 choice vs LLM 终态；on 模式下 LLM prompt
  含 Jev 初读，一致率仅作参考）
- 熔断事件清单 / 错误清单
- 潜在延迟节省估算（采用周期 × 升级周期 LLM 延迟中位数）

仅用标准库，只读日志文件，不产生任何副作用。
"""

import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from statistics import median
from typing import Dict, List, Optional, Tuple

# 日志行: "2026-09-27 19:31:39,817 - INFO - alpha_trading_bot.xxx - 消息"
LOG_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\s+-\s+"
    r"(?P<level>\w+)\s+-\s+(?P<logger>[\w.]+)\s+-\s+(?P<msg>.*)$"
)

CYCLE_START = "[AI信号] 正在获取交易信号..."
CALC_RE = re.compile(
    r"\[Jev快车道\] 置信度计算: choice=(\w+), API返回confidence=([\d.]+), "
    r"概率分布\{(.*)\}, 采用阈值(\w+)=(\d+\.?\d*), 反转风险Noul=([\d.]+)"
    r"(?:.*耗时=(\d+)ms)?"
)
ADOPT_FL = re.compile(
    r"\[Jev快车道\] 采用 (\w+) \(conf=([\d.]+) ≥ 阈值([\d.]+), (\d+)ms\)"
)
SHADOW_WOULD = re.compile(
    r"\[Jev快车道\]\[shadow\] 本可采用 (\w+) \(conf=([\d.]+), (\d+)ms\)"
)
RISK_GATE = re.compile(
    r"\[Jev快车道\] 反转风险旗标\(([\d.]+) > ([\d.]+)\)，强制升级 LLM"
)
LOW_CONF = re.compile(r"\[Jev快车道\] 置信度不足 \(([\d.]+) < ([\d.]+)\)，升级 LLM")
OUT_OF_VOCAB = re.compile(r"\[Jev快车道\] 词表外 choice=")
BAD_RESPONSE = re.compile(r"\[Jev快车道\] 响应缺少 trade_decision，升级 LLM")
ADOPT_CLIENT = re.compile(
    r"\[AI请求\] Jev快车道采用: (\w+) \(置信=([\d.]+), (\d+)ms, 跳过LLM\)"
)
ENABLED = re.compile(r"\[Jev快车道\] 已启用 mode=(\S+) model=(\S+) (.*$)")
CB_OPEN = re.compile(r"\[Jev熔断\] OPEN: (.+?)，冷却 (\d+)s，原因=(.*)")
CB_HALF_OPEN = re.compile(
    r"\[Jev熔断\] HALF-OPEN: 冷却结束\(上次原因: (.{0,120})\)，放行探测"
)
CB_CLOSED = re.compile(r"\[Jev熔断\] CLOSED: 调用成功，快车道恢复")
JEV_TIMEOUT = re.compile(r"\[Jev\] 请求超时 \(>([\d.]+)s\)")
JEV_AUTH = re.compile(r"\[Jev\] 鉴权/欠费失败 status=(\d+)")
JEV_HTTP = re.compile(r"\[Jev\] HTTP错误 status=(\d+)")
JEV_NETWORK = re.compile(r"\[Jev\] 网络错误: (\S+)")
LLM_REQ_SINGLE = re.compile(r"\[AI请求\] 单AI模式, 提供商: (\w+)")
LLM_REQ_FUSION = re.compile(r"\[AI请求\] 多AI融合模式, 提供商列表: (.+)")
LLM_RESP = re.compile(r"\[AI响应\] 提供商=(\w+)[,:]\s*信号=(\w+)")
FINAL_SIGNAL = re.compile(r"\[AI信号集成\] 原始=\w+\(\d+%\) → 最终=(\w+)\(")
FINAL_SIGNAL_ALT = re.compile(r"\[AI信号\] 原始信号: (\w+)")

SIGNALS = ("buy", "hold", "sell", "short")


def parse_ts(text: str) -> Optional[datetime]:
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S,%f")
    except ValueError:
        return None


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    frac = k - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def latency_stats(values: List[float]) -> str:
    if not values:
        return "n/a"
    return (
        f"min={min(values):.0f}ms p50={percentile(values, 50):.0f}ms "
        f"p95={percentile(values, 95):.0f}ms max={max(values):.0f}ms"
    )


class Cycle:
    """一个交易周期内与 Jev 快车道相关的事件集合。"""

    def __init__(self, ts: datetime) -> None:
        self.ts = ts
        self.choice: Optional[str] = None
        self.confidence: Optional[float] = None
        self.top1_prob: Optional[float] = None
        self.jev_latency: Optional[float] = None
        self.outcome: str = "no_jev"  # adopt/low_confidence/risk_gate/timeout/
        # auth_error/api_error/bad_response/shadow/no_jev
        self.final_signal: Optional[str] = None
        self.llm_latency: Optional[float] = None
        self.llm_provider: Optional[str] = None
        self.notes: List[str] = []
        self._llm_req_ts: Optional[datetime] = None


def load_cycles(
    paths: List[str],
) -> Tuple[List[Cycle], List[Tuple[datetime, str]], Optional[str]]:
    cycles: List[Cycle] = []
    events: List[Tuple[datetime, str]] = []  # (时间, 描述)：熔断/错误/配置
    current: Optional[Cycle] = None
    config_line: Optional[str] = None

    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as f:
            for raw in f:
                m = LOG_LINE.match(raw.strip())
                if not m:
                    continue
                ts = parse_ts(m.group("ts"))
                if ts is None:
                    continue
                msg = m.group("msg")

                cm = ENABLED.search(msg)
                if cm:
                    config_line = msg.strip()

                if CYCLE_START in msg:
                    current = Cycle(ts)
                    cycles.append(current)
                    continue

                if current is None:
                    continue

                am = ADOPT_FL.search(msg)
                if am:
                    current.choice = am.group(1)
                    current.confidence = float(am.group(2))
                    current.jev_latency = float(am.group(4))
                    current.outcome = "adopt"
                    continue

                sm = SHADOW_WOULD.search(msg)
                if sm:
                    current.choice = sm.group(1)
                    current.confidence = float(sm.group(2))
                    current.jev_latency = float(sm.group(3))
                    current.outcome = "shadow"
                    continue

                rm = RISK_GATE.search(msg)
                if rm:
                    current.outcome = "risk_gate"
                    continue

                if OUT_OF_VOCAB.search(msg) or BAD_RESPONSE.search(msg):
                    current.outcome = "bad_response"
                    continue

                cm2 = CALC_RE.search(msg)
                if cm2:
                    current.choice = cm2.group(1)
                    current.confidence = float(cm2.group(2))
                    probs: Dict[str, float] = {}
                    for pair in cm2.group(3).split(", "):
                        if "=" in pair:
                            k, v = pair.split("=", 1)
                            try:
                                probs[k] = float(v)
                            except ValueError:
                                pass
                    if probs:
                        current.top1_prob = max(probs.values())
                    if cm2.group(7):
                        current.jev_latency = float(cm2.group(7))
                    if current.outcome == "no_jev":
                        current.outcome = "calc_only"
                    continue

                tm = JEV_TIMEOUT.search(msg)
                if tm:
                    current.outcome = "timeout"
                    continue
                am2 = JEV_AUTH.search(msg)
                if am2:
                    current.outcome = "auth_error"
                    continue
                hm = JEV_HTTP.search(msg)
                if hm:
                    current.outcome = "api_error"
                    continue
                nm = JEV_NETWORK.search(msg)
                if nm:
                    current.outcome = "api_error"
                    continue

                lrm = LLM_REQ_SINGLE.search(msg) or LLM_REQ_FUSION.search(msg)
                if lrm:
                    current._llm_req_ts = ts
                    current.llm_provider = lrm.group(1)
                    continue

                lrm2 = LLM_RESP.search(msg)
                if lrm2 and current._llm_req_ts is not None:
                    current.llm_latency = (
                        ts - current._llm_req_ts
                    ).total_seconds() * 1000.0
                    continue

                fm = FINAL_SIGNAL.search(msg) or FINAL_SIGNAL_ALT.search(msg)
                if fm:
                    current.final_signal = fm.group(1).lower()
                    continue

                acm = ADOPT_CLIENT.search(msg)
                if acm and current.outcome == "calc_only":
                    current.outcome = "adopt"
                    continue

                # 熔断/错误事件（跨周期记录）
                om = CB_OPEN.search(msg)
                if om:
                    events.append(
                        (
                            ts,
                            f"熔断 OPEN: {om.group(1)}（冷却 {om.group(2)}s，"
                            f"原因: {om.group(3)[:80]}）",
                        )
                    )
                hm2 = CB_HALF_OPEN.search(msg)
                if hm2:
                    events.append(
                        (ts, f"熔断 HALF-OPEN: 放行探测（上次原因: {hm2.group(1)}）")
                    )
                cdm = CB_CLOSED.search(msg)
                if cdm:
                    events.append((ts, "熔断 CLOSED: 快车道恢复"))

    # calc_only：有置信度计算但没抓到采用/低置信/风险行（日志截断等）→ 按升级处理
    for c in cycles:
        if c.outcome == "calc_only":
            c.outcome = "low_confidence"
    return cycles, events, config_line


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cycles, events, config_line = load_cycles(sys.argv[1:])
    if not cycles:
        print("未在日志中找到交易周期（[AI信号] 正在获取交易信号...）")
        sys.exit(1)

    total = len(cycles)
    outcomes = Counter(c.outcome for c in cycles)
    start, end = cycles[0].ts, cycles[-1].ts
    span_h = (end - start).total_seconds() / 3600.0

    print("=" * 72)
    print("Jev 快车道观察期报告")
    print("=" * 72)
    if config_line:
        print(f"配置快照   : {config_line}")
    print(f"时间范围   : {start} ~ {end}（跨度 {span_h:.1f}h）")
    print(f"交易周期数 : {total}")
    print()
    print("结果分布:")
    label_map = {
        "adopt": "采用 Jev（跳过 LLM）",
        "shadow": "shadow 本可采用",
        "low_confidence": "升级 LLM（置信度不足）",
        "risk_gate": "升级 LLM（反转风险旗标）",
        "timeout": "升级 LLM（Jev 超时）",
        "auth_error": "升级 LLM（欠费/鉴权失败）",
        "api_error": "升级 LLM（API/网络错误）",
        "bad_response": "升级 LLM（响应结构异常）",
        "no_jev": "未走快车道（mode=off 或无 Key）",
    }
    for key in (
        "adopt",
        "shadow",
        "low_confidence",
        "risk_gate",
        "timeout",
        "auth_error",
        "api_error",
        "bad_response",
        "no_jev",
    ):
        n = outcomes.get(key, 0)
        if n:
            print(f"  {key:<15} {n:>5}  ({n * 100.0 / total:5.1f}%)  {label_map[key]}")

    jev_lat = [c.jev_latency for c in cycles if c.jev_latency is not None]
    llm_lat = [c.llm_latency for c in cycles if c.llm_latency is not None]
    print()
    print(f"Jev 延迟   : {latency_stats(jev_lat)}  (n={len(jev_lat)})")
    print(f"LLM 延迟   : {latency_stats(llm_lat)}  (n={len(llm_lat)}, 升级周期)")
    if jev_lat and llm_lat and outcomes.get("adopt"):
        saved = median(llm_lat) * outcomes["adopt"] / 1000.0
        print(
            f"延迟节省估算: {outcomes['adopt']} 个采用周期 × LLM p50"
            f"({median(llm_lat):.0f}ms) ≈ {saved:.0f}s（按 p50 估算，未计 LLM 费用）"
        )

    confs = [c.confidence for c in cycles if c.confidence is not None]
    print()
    print(f"置信度分布 (n={len(confs)}):")
    if confs:
        hist: Counter = Counter(int(c * 20) for c in confs)  # 0.05 一档
        for bucket in range(20):
            lo, hi = bucket * 0.05, (bucket + 1) * 0.05
            n = hist.get(bucket, 0)
            bar = "#" * n
            print(f"  [{lo:.2f}, {hi:.2f}) {n:>4} {bar}")
        per_choice: Dict[str, List[float]] = defaultdict(list)
        top1: List[float] = []
        for c in cycles:
            if c.confidence is not None and c.choice:
                per_choice[c.choice].append(c.confidence)
            if c.top1_prob is not None:
                top1.append(c.top1_prob)
        print()
        print("按 choice 分组（count / 平均 / p50 / max / 采用门槛参考）:")
        for s in SIGNALS:
            vals = per_choice.get(s)
            if not vals:
                continue
            print(
                f"  {s:<6} n={len(vals):>4} avg={sum(vals) / len(vals):.2f} "
                f"p50={percentile(vals, 50):.2f} max={max(vals):.2f}"
            )
        if top1:
            print(
                f"  top1概率(最大选项概率) n={len(top1)} avg={sum(top1) / len(top1):.2f} "
                f"p50={percentile(top1, 50):.2f} max={max(top1):.2f}"
            )
            # confidence vs top1 概率的背离度（判断门控指标是否要换）
            pairs = [
                (c.confidence, c.top1_prob)
                for c in cycles
                if c.confidence is not None and c.top1_prob is not None
            ]
            if pairs:
                gaps = [t - cf for cf, t in pairs]
                print(
                    f"  confidence 与 top1概率 差值: avg={sum(gaps) / len(gaps):+.2f} "
                    f"(正=top1概率更高，说明 confidence 偏保守)"
                )

    adopted = [c for c in cycles if c.outcome == "adopt"]
    if adopted:
        print()
        print(f"采用事件清单（Jev 驱动的实际决策，n={len(adopted)}，建议逐条复盘）:")
        for c in adopted:
            print(
                f"  {c.ts} choice={c.choice} conf={c.confidence:.2f} "
                f"top1={c.top1_prob if c.top1_prob is not None else 'n/a'} "
                f"lat={c.jev_latency:.0f}ms LLM终态={c.final_signal or 'n/a'}"
            )
    else:
        print()
        print("采用事件清单: 无（观察期内 Jev 未直接驱动任何决策）")

    esc = [c for c in cycles if c.outcome in ("low_confidence", "risk_gate")]
    esc_with_final = [c for c in esc if c.final_signal and c.choice]
    if esc_with_final:
        agree = sum(1 for c in esc_with_final if c.choice == c.final_signal)
        print()
        print(
            f"升级周期一致率: {agree}/{len(esc_with_final)} "
            f"({agree * 100.0 / len(esc_with_final):.1f}%)"
        )
        print(
            "  ⚠️ on 模式下 LLM prompt 含 Jev 初读，此一致率非独立对照，"
            "仅反映'同向率'；严格一致率需 shadow 数据。"
        )
        disagree = [c for c in esc_with_final if c.choice != c.final_signal]
        if disagree:
            print(f"  分歧样本（前10）: {len(disagree)} 条")
            for c in disagree[:10]:
                print(
                    f"    {c.ts} jev={c.choice}(conf={c.confidence:.2f}) → "
                    f"LLM终态={c.final_signal}"
                )

    if events:
        print()
        print(f"熔断/恢复事件 (n={len(events)}):")
        for ts, desc in events:
            print(f"  {ts} {desc}")

    errors = [
        c
        for c in cycles
        if c.outcome in ("timeout", "auth_error", "api_error", "bad_response")
    ]
    if errors:
        print()
        print(f"Jev 故障升级 (n={len(errors)}):")
        for c in errors:
            print(f"  {c.ts} {c.outcome} → LLM终态={c.final_signal or 'n/a'}")

    print()
    print("调参提示:")
    if confs:
        n_above_hold = sum(1 for cf in confs if cf >= 0.50)
        print(
            f"  - conf_hold=0.50 时 {n_above_hold}/{len(confs)} 个周期可直接采用 "
            f"(hold 方向)；若多数 hold 周期 confidence 落在 0.40-0.50，"
            "可考虑 JEV_CONF_HOLD=0.40。"
        )
    print(
        "  - 若 'confidence 与 top1概率 差值' 持续为正且采用率≈0，"
        "说明 confidence 标定偏保守，可评估改用 top1 概率门控（需代码改动）。"
    )
    print("  - auth_error 持续出现 = Key 欠费/失效，检查 TypeSafe 账户。")


if __name__ == "__main__":
    main()
