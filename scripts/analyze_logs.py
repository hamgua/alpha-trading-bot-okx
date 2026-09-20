#!/usr/bin/env python3
"""分析 logs/ 目录下 30 天交易日志，量化亏损原因。

用法: python scripts/analyze_logs.py [logs目录]
"""
import glob
import os
import re
import sys
from collections import Counter

LOG_DIR = sys.argv[1] if len(sys.argv) > 1 else "logs"

files = sorted(glob.glob(os.path.join(LOG_DIR, "alpha-trading-bot-okx.log*")))

# 合约单位: OKX BTC-USDT-SWAP ctVal=0.01 BTC, 下单 0.01 张 = 0.0001 BTC
CT_VAL_BTC = 0.01
AMT_CONTRACTS = 0.01
BTC_PER_TRADE = CT_VAL_BTC * AMT_CONTRACTS  # 0.0001 BTC

opens = []          # (ts, side, amount)
confirmed_closes = []  # (ts, side, entry, stop, exit, pnl_pct, algo_id)
inferred_closes = []   # (ts, side, entry, last_stop, last_upnl)
tp_orders = []        # (ts, tp_price, notional)
tracker_opens = []    # (ts, side, price)
tracker_closes = []   # (ts, side, price, pnl_pct, result)
ai_signals = Counter()
decisions = Counter()
sl_param_lines = []

re_submit = re.compile(
    r"^(?P<ts>\S+ \S+).*?提交订单: symbol=\S+, side=(?P<side>buy|sell), type=\S+, amount=(?P<amt>[\d.]+)"
)
re_open_done = re.compile(
    r"^(?P<ts>\S+ \S+).*?绩效追踪.*?记录开仓: (?P<side>buy|sell) @ (?P<price>[\d.]+)"
)
re_close_done = re.compile(
    r"^(?P<ts>\S+ \S+).*?绩效追踪.*?记录平仓: (?P<side>buy|sell) @ (?P<price>[\d.]+), PnL: (?P<pnl>-?[\d.]+)%, 结果: (?P<result>\w+)"
)
re_conf = re.compile(
    r"^(?P<ts>\S+ \S+).*?平仓确认.*?side=(?P<side>\w+), algoId=(?P<aid>\d+), .*?entry=(?P<entry>[\d.]+), 止损价=(?P<stop>[\d.]+), exit=(?P<exit>[\d.]+), amount=[\d.]+, pnl=(?P<pnl>-?[\d.]+)%"
)
re_inf = re.compile(
    r"^(?P<ts>\S+ \S+).*?平仓推断.*?side=(?P<side>\w+), last_stop_algoId=\d+, entry=(?P<entry>[\d.]+), last_stop=(?P<stop>[\d.]+), amount=[\d.]+, last_unrealized_pnl=(?P<upnl>-?[\d.eE]+)"
)
re_tp_notional = re.compile(
    r"^(?P<ts>\S+ \S+).*?\[止盈保护\] 止盈单已设置: id=\d+, price=(?P<tp>[\d.]+), amount=[\d.]+/[\d.]+, notional=(?P<notional>[\d.]+)"
)
re_ai = re.compile(
    r"^(?P<ts>\S+ \S+).*?\[AI信号集成\] 原始=(?P<sig>\w+)\((?P<conf>[\d.]+)%\) → 最终=(?P<final>\w+)\((?P<fconf>[\d.]+)%\)"
)
re_dec = re.compile(r"^(?P<ts>\S+ \S+).*?\[决策\] (?P<dec>.*)")
re_slp = re.compile(r"^(?P<ts>\S+ \S+).*?\[止损参数\] ATR%=([\d.]+)%, 基础止损=([\d.]+)%, 调整后止损=([\d.]+)%, 追踪=([\d.]+)%")
re_tpc = re.compile(r"\[止盈计算-(?P<side>做多|做空)-自适应\] 入场价=(?P<entry>[\d.]+), 止盈价=(?P<tp>[\d.]+)")
re_tpadj = re.compile(r"\[止盈保护\] 全仓止盈目标提前: entry=(?P<entry>[\d.]+), original=(?P<orig>[\d.]+), adjusted=(?P<adj>[\d.]+), ratio=(?P<ratio>[\d.]+)")

for f in files:
    with open(f, errors="replace") as fh:
        for line in fh:
            m = re_submit.search(line)
            if m:
                opens.append((m.group("ts"), m.group("side"), m.group("amt")))
                continue
            m = re_conf.search(line)
            if m:
                confirmed_closes.append(
                    (m.group("ts"), m.group("side"), float(m.group("entry")),
                     float(m.group("stop")), float(m.group("exit")),
                     float(m.group("pnl")), m.group("aid")))
                continue
            m = re_inf.search(line)
            if m:
                inferred_closes.append(
                    (m.group("ts"), m.group("side"), float(m.group("entry")),
                     float(m.group("stop")), float(m.group("upnl"))))
                continue
            m = re_tp_notional.search(line)
            if m:
                tp_orders.append((m.group("ts"), float(m.group("tp")), float(m.group("notional"))))
                continue
            m = re_open_done.search(line)
            if m:
                tracker_opens.append((m.group("ts"), m.group("side"), float(m.group("price"))))
                continue
            m = re_close_done.search(line)
            if m:
                tracker_closes.append(
                    (m.group("ts"), m.group("side"), float(m.group("price")),
                     float(m.group("pnl")), m.group("result")))
                continue
            m = re_ai.search(line)
            if m:
                ai_signals[m.group("final")] += 1
                continue
            m = re_dec.search(line)
            if m:
                dec = m.group("dec")
                key = re.sub(r"\d[\d.,%]*", "N", dec)
                decisions[key[:60]] += 1
                continue
            m = re_slp.search(line)
            if m:
                sl_param_lines.append((m.group("ts"), m.groups()))
            m = re_tpc.search(line)
            if m:
                e, t = float(m.group("entry")), float(m.group("tp"))
                tp_orders.append((line[:19], abs(t - e) / e * 100, float(m.group("entry"))))

# 止盈距离单独统计
tp_dists_raw = []
tp_adj_ratios = Counter()
tp_adj_cnt = 0
for f in files:
    with open(f, errors="replace") as fh:
        for line in fh:
            m = re_tpc.search(line)
            if m:
                e, t = float(m.group("entry")), float(m.group("tp"))
                tp_dists_raw.append(abs(t - e) / e * 100)
            m = re_tpadj.search(line)
            if m:
                tp_adj_cnt += 1
                tp_adj_ratios[m.group("ratio")] += 1

print("=" * 70)
print("总览")
print("=" * 70)
print(f"日志文件数: {len(files)}")
if files:
    first_line = open(files[0], errors="replace").readline()
    last_file = open(files[-1], errors="replace")
    last_ts = ""
    for ln in last_file:
        last_ts = ln
    print(f"首行时间: {first_line[:19] if first_line else '?'}  末行时间: {last_ts[:19] if last_ts else '?'}")
print(f"开仓订单(提交): {len(opens)}")
side_cnt = Counter(s for _, s, _ in opens)
print(f"  方向: {dict(side_cnt)}  (buy=开多, sell=开空)")
print(f"AI最终信号分布: {dict(ai_signals)}")
print(f"决策类型 TOP15:")
for k, v in decisions.most_common(15):
    print(f"  {v:5d}  {k}")

print()
print("=" * 70)
print("平仓统计 (position_close_audit)")
print("=" * 70)
print(f"确认平仓(止损单触发): {len(confirmed_closes)}")
print(f"推断平仓(持仓消失):   {len(inferred_closes)}")
conf_pnls = [c[5] for c in confirmed_closes]
wins = [p for p in conf_pnls if p > 0.01]
losses = [p for p in conf_pnls if p < -0.01]
flat = [p for p in conf_pnls if -0.01 <= p <= 0.01]
print(f"  确认平仓: 盈={len(wins)} 亏={len(losses)} 平={len(flat)}")
if wins:
    print(f"  平均盈利: +{sum(wins)/len(wins):.3f}%  最大: +{max(wins):.3f}%")
if losses:
    print(f"  平均亏损: {sum(losses)/len(losses):.3f}%  最大: {min(losses):.3f}%")
print(f"  确认平仓净PnL(价格%): {sum(conf_pnls):+.3f}%")
if wins and losses:
    print(f"  盈亏比(平均): {sum(wins)/len(wins) / abs(sum(losses)/len(losses)):.2f}")
if inferred_closes:
    up = [c[4] for c in inferred_closes]
    print(f"  推断平仓最后浮盈: 合计={sum(up):+.4f} USDT, 正={sum(1 for x in up if x>0.001)} 负={sum(1 for x in up if x<-0.001)} 零/平={sum(1 for x in up if -0.001<=x<=0.001)}")

print()
print("=" * 70)
print("绩效追踪记录 (performance_tracker)")
print("=" * 70)
print(f"记录开仓: {len(tracker_opens)}  记录平仓: {len(tracker_closes)}")
tc = tracker_closes
res = Counter(t[4] for t in tc)
print(f"结果分布: {dict(res)}")
for r in ("win", "loss", "breakeven"):
    grp = [t[3] for t in tc if t[4] == r]
    if grp:
        print(f"  {r}: n={len(grp)}, 平均={sum(grp)/len(grp):+.3f}%, 合计={sum(grp):+.3f}%, 区间=[{min(grp):+.2f}%, {max(grp):+.2f}%]")
all_pnl = [t[3] for t in tc]
if all_pnl:
    print(f"全部平仓净PnL(价格%): {sum(all_pnl):+.3f}%")
    w = res.get("win", 0)
    l = res.get("loss", 0)
    print(f"胜率(win/(win+loss)): {w}/{w+l} = {w/max(1,w+l)*100:.1f}%")

print()
print("=" * 70)
print("止损/止盈距离分析")
print("=" * 70)
sl_dists = []
for _, side, entry, stop, exit_, pnl, _ in confirmed_closes:
    d = (stop - entry) / entry * 100
    if side == "long" and d < 0:
        sl_dists.append(abs(d))
    elif side == "short" and d > 0:
        sl_dists.append(abs(d))
if sl_dists:
    print(f"止损距离(确认平仓): n={len(sl_dists)}, 平均={sum(sl_dists)/len(sl_dists):.3f}%, min={min(sl_dists):.3f}%, max={max(sl_dists):.3f}%")
if tp_dists_raw:
    print(f"原始止盈距离(自适应): n={len(tp_dists_raw)}, 平均={sum(tp_dists_raw)/len(tp_dists_raw):.3f}%, 区间=[{min(tp_dists_raw):.2f}%, {max(tp_dists_raw):.2f}%]")
print(f"止盈保护'目标提前'次数: {tp_adj_cnt}, ratio分布: {dict(tp_adj_ratios)}")
if tp_adj_cnt:
    print(f"  => 50%压缩(止盈距离减半)占比: {tp_adj_ratios.get('0.50', 0)/tp_adj_cnt*100:.0f}%")

print()
print("=" * 70)
print("资金换算 (0.0001 BTC/单)")
print("=" * 70)
avg_price = 78000
notional = BTC_PER_TRADE * avg_price
fee_rt = notional * 0.0005 * 2
print(f"每单名义价值 ≈ ${notional:.2f} (10x杠杆下保证金≈${notional/10:.2f})")
print(f"每单往返taker手续费 ≈ ${fee_rt:.4f} (≈{fee_rt/notional*100:.2f}% 名义)")
if all_pnl:
    print(f"绩效追踪30天净PnL(价格%) = {sum(all_pnl):+.3f}% => 约 ${sum(all_pnl)/100*notional:.4f}")
n_closed = len(tc) + len(confirmed_closes)
print(f"平仓总数(追踪+确认): {n_closed}, 手续费总支出估算: ${fee_rt*n_closed:.4f}")

print()
print("=" * 70)
print("止损参数变化 (基础/调整后/追踪)")
print("=" * 70)
if sl_param_lines:
    first = sl_param_lines[0]
    last = sl_param_lines[-1]
    print(f"首条 {first[0]}: ATR={first[1][0]}%, 基础={first[1][1]}%, 调整后={first[1][2]}%, 追踪={first[1][3]}%")
    print(f"末条 {last[0]}: ATR={last[1][0]}%, 基础={last[1][1]}%, 调整后={last[1][2]}%, 追踪={last[1][3]}%")
    bases = Counter(x[1][1] for x in sl_param_lines)
    trails = Counter(x[1][3] for x in sl_param_lines)
    print(f"基础止损分布: {dict(bases.most_common(5))}")
    print(f"追踪止损分布: {dict(trails.most_common(5))}")
