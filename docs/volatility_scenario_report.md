# 全场景波动矩阵报告 (波动情况 → 业务处理)

场景总数: 41 | 组件: 全部真实组件流水线 (AI 提供商响应按场景注入)

## 一、处理结果汇总

| # | 场景 | ATR | RSI | 趋势 | 状态 | 规则触发 | 门禁 | AI(原→终) | 决策 | 止损 | 止盈 | 仓位 |
|---|------|-----|-----|------|------|----------|------|-----------|------|------|------|------|
| 1 | A1-极低波动 | 0.05% | 45 | U0.3 | ATR 0.05% (极端低波动/死 | volatility_rule | 0.55 | BUY 75%→BUY 82% | **开多** | 0.30% | 0.40% | 7.5% |
| 2 | A2-低波动(实盘场景) | 0.14% | 45 | U0.3 | ATR 0.14% (2026-09 | volatility_rule | 0.55 | BUY 75%→BUY 82% | **开多** | 0.42% | 0.42% | 7.5% |
| 3 | A3-低波动上沿 | 0.19% | 45 | U0.3 | ATR 0.19% (低波动带上沿, | volatility_rule | 0.55 | BUY 75%→BUY 82% | **开多** | 0.50% | 0.50% | 7.5% |
| 4 | A4-中等波动 | 0.30% | 45 | U0.3 | ATR 0.30% (中等波动带)  | volatility_rule | 0.50 | BUY 75%→BUY 82% | **开多** | 0.70% | 0.70% | 5.1% |
| 5 | A5-高波动 | 0.50% | 45 | U0.3 | ATR 0.50% (高波动带) → | volatility_rule | 0.55 | BUY 75%→BUY 82% | **开多** | 1.00% | 1.00% | 3.1% |
| 6 | A6-极高波动 | 0.70% | 45 | U0.3 | ATR 0.7% (极高波动带) → | volatility_rule | 0.55 | BUY 75%→BUY 82% | **跳过** | - | - | - |
| 7 | A7-极端波动 | 1.20% | 45 | U0.3 | ATR 1.2% (极端波动) →  | volatility_rule | 0.55 | BUY 85%→BUY 78% | **跳过** | - | - | - |
| 8 | A8-极端波动门禁 | 0.80% | 45 | U0.3 | ATR 0.8% + 信号过门禁 → | volatility_rule | 0.55 | BUY 85%→BUY 82% | **跳过** | - | - | - |
| 9 | B1-强上升趋势 | 0.15% | 62 | U0.7 | 趋势向上 0.7 + RSI 62  | trend_rule,volatility_rule | 0.55 | BUY 72%→BUY 72% | **开多** | 0.45% | 0.45% | 7.5% |
| 10 | B2-强下降趋势 | 0.15% | 42 | D0.7 | 趋势向下 0.7 + RSI 42  | volatility_rule | 0.55 | SHORT 75%→SHORT 79% | **开空** | 0.45% | 0.45% | 7.5% |
| 11 | B3-下降趋势AI-HOLD | 0.15% | 38 | D0.7 | 趋势向下 0.7 + AI HOLD | rsi_rule,volatility_rule | 0.55 | HOLD 60%→HOLD 63% | **跳过** | - | - | - |
| 12 | B4-震荡超卖 | 0.15% | 25 | S0.1 | 横盘 + RSI 25 超卖 + A | rsi_rule,volatility_rule | 0.55 | HOLD 55%→HOLD 58% | **跳过** | - | - | - |
| 13 | B5-震荡超买做空 | 0.15% | 79 | S0.1 | 横盘 + RSI 79 超买 + 空 | rsi_rule,volatility_rule | 0.55 | HOLD 55%→HOLD 58% | **跳过** | - | - | - |
| 14 | B6-极端超买衰竭 | 0.15% | 84 | S0.1 | RSI 83.5 + 趋势<0.12 | rsi_rule,volatility_rule | 0.55 | HOLD 50%→HOLD 52% | **跳过** | - | - | - |
| 15 | B7-全HOLD(事故回归) | 0.14% | 50 | N0.0 | 2026-09-13 05:17 事 | volatility_rule | 0.55 | HOLD 56%→HOLD 59% | **跳过** | - | - | - |
| 16 | B8-下降趋势RSI超卖 | 0.15% | 25 | D0.6 | 下降趋势 + RSI 25 超卖 + | rsi_rule,volatility_rule | 0.55 | SHORT 80%→SHORT 84% | **跳过** | - | - | - |
| 17 | C1-阻力位附近买入 | 0.15% | 68 | S0.1 | 价格位于区间 95% (近阻力) + | volatility_rule | 0.55 | BUY 60%→HOLD 35% | **跳过** | - | - | - |
| 18 | C2-支撑位附近买入 | 0.15% | 32 | S0.1 | 价格位于区间 8% (近支撑) +  | rsi_rule,volatility_rule | 0.55 | BUY 65%→BUY 82% | **开多** | 0.45% | 0.45% | 7.5% |
| 19 | C3-突破上行 | 0.20% | 58 | U0.5 | 价格突破区间上沿 + 趋势向上 +  | - | 0.50 | BUY 75%→BUY 65% | **开多** | 0.50% | 0.50% | 7.5% |
| 20 | C4-跌破支撑 | 0.20% | 42 | D0.5 | 价格跌破区间下沿 + 趋势向下 +  | - | 0.50 | SHORT 70%→SHORT 74% | **开空** | 0.50% | 0.50% | 7.5% |
| 21 | C5-下跌结构买入 | 0.15% | 50 | D0.4 | bearish 结构 + BUY → | volatility_rule | 0.55 | BUY 80%→BUY 71% | **跳过** | - | - | - |
| 22 | C6-BTC高位风险 | 0.15% | 72 | S0.1 | price_position 0.9 | rsi_rule,volatility_rule | 0.55 | BUY 52%→HOLD 35% | **跳过** | - | - | - |
| 23 | D1-闪崩 | 0.60% | 22 | D0.8 | 15分钟 -3% 闪崩 + BUY  | rsi_rule,volatility_rule | 0.55 | BUY 65%→BUY 83% | **跳过** | - | - | - |
| 24 | D2-V型反弹 | 0.40% | 48 | U0.3 | 暴跌后 V 型反弹 + crash_ | volatility_rule | 0.55 | BUY 62%→BUY 82% | **开多** | 1.00% | 1.00% | 3.1% |
| 25 | D3-持续阴跌 | 0.18% | 30 | D0.4 | 24h -1.8% 持续阴跌 + B | rsi_rule,volatility_rule | 0.55 | BUY 60%→BUY 54% | **跳过** | - | - | - |
| 26 | D4-严重下跌 | 0.80% | 18 | D0.9 | 24h -5% 严重下跌 + BUY | rsi_rule,volatility_rule | 0.55 | BUY 70%→BUY 90% | **跳过** | - | - | - |
| 27 | E1-多头浮盈 | 0.15% | 55 | S0.1 | 持有 long (入场 76400, | volatility_rule | 0.55 | HOLD 50%→HOLD 52% | **跳过** | - | - | - |
| 28 | E2-多头浮亏未触发 | 0.15% | 45 | S0.1 | 持有 long (入场 77400, | volatility_rule | 0.55 | HOLD 50%→HOLD 52% | **跳过** | - | - | - |
| 29 | E3-多头共振卖出 | 0.15% | 70 | D0.3 | 持有 long + AI SELL  | volatility_rule | 0.55 | SELL 78%→SELL 82% | **平仓** | - | - | - |
| 30 | E4-多头中再BUY | 0.15% | 58 | U0.5 | 持有 long + AI BUY → | volatility_rule | 0.55 | BUY 80%→BUY 82% | **跳过** | - | - | - |
| 31 | E5-空头浮盈 | 0.15% | 40 | D0.4 | 持有 short (入场 77600 | volatility_rule | 0.55 | HOLD 50%→HOLD 52% | **跳过** | - | - | - |
| 32 | E6-空单平仓状态 | 0.15% | 45 | S0.1 | short_to_close (空单 | volatility_rule | 0.55 | HOLD 50%→HOLD 52% | **跳过** | - | - | - |
| 33 | F1-连亏3次 | 0.15% | 55 | U0.4 | 连续亏损 3 次 + BUY 70% | volatility_rule,consecutive_loss_rule | 0.60 | BUY 70%→BUY 82% | **开多** | 0.40% | 0.40% | 3.8% |
| 34 | F2-连亏5次 | 0.15% | 55 | U0.4 | 连续亏损 5 次 + BUY 70% | volatility_rule,consecutive_loss_rule | 0.70 | BUY 70%→BUY 82% | **开多** | 0.30% | 0.40% | 1.5% |
| 35 | F3-当日亏损回撤 | 0.15% | 55 | U0.4 | 当日回撤 4% (接近熔断 3% 上 | volatility_rule | 0.55 | BUY 70%→BUY 82% | **开多** | 0.45% | 0.45% | 7.5% |
| 36 | F4-低置信拦截 | 0.15% | 50 | N0.0 | 横盘无技术共振 + BUY 48%  | volatility_rule | 0.55 | BUY 48%→HOLD 38% | **跳过** | - | - | - |
| 37 | G1-明确HOLD不翻转 | 0.15% | 52 | U0.3 | AI HOLD 56% + 技术买入 | volatility_rule | 0.55 | HOLD 56%→HOLD 59% | **跳过** | - | - | - |
| 38 | G2-模糊HOLD可翻转 | 0.15% | 52 | U0.3 | AI HOLD 40% (模糊) + | volatility_rule | 0.55 | HOLD 40%→BUY 82% | **开多** | 0.45% | 0.45% | 7.5% |
| 39 | G3-SELL不翻BUY | 0.15% | 30 | D0.5 | AI SELL 85% + 技术买入 | rsi_rule,volatility_rule | 0.55 | SELL 85%→SELL 89% | **跳过** | - | - | - |
| 40 | G4-BUY超100归一化 | 0.15% | 58 | U0.4 | AI BUY 置信度 75 (百分制 | volatility_rule | 0.55 | BUY 7500%→BUY 82% | **开多** | 0.45% | 0.45% | 7.5% |
| 41 | G5-阴跌中BUY降权 | 0.18% | 38 | D0.5 | BUY 65% + 轻度持续下跌 → | rsi_rule,volatility_rule | 0.55 | BUY 65%→BUY 58% | **跳过** | - | - | - |

## 二.1 A-波动率谱

### A1-极低波动 — 开多

- **场景**: ATR 0.05% (极端低波动/死水市) → SL clamp 下限 0.3%
- **市场快照**: 价格 77000 | ATR 0.05% | RSI 45 | 趋势 up(0.35) | 区间位置 30% | 24h 0.00% | 价格形状 up
- **市场环境**: trend_sideways (置信 0.60)
- **规则引擎**: 触发 volatility_rule | 规则SL 0.30% | 仓位×1.0
- **策略信号**: trend_following=BUY(68%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=BUY(80%)
- **选中策略**: trend_following / BUY (68%)
- **AI 集成**: BUY 75% → **BUY 82%** [自适应买入: pullback_buy模式通过; R/R过滤: R/R=1.00勉强, 置信度降低15%(92%→78%)]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **开多** — AI信号买入 (置信 68%, 策略 trend_following)
- **执行参数**: 止损 76769.0 (0.30%) | 止盈 77308.0 (0.40%) | 建议仓位 7.5% | R/R 1.33
- **学习记录**: provider=qwen38, strategy=trend_following

### A2-低波动(实盘场景) — 开多

- **场景**: ATR 0.14% (2026-09-13 实盘水平) → SL 3×ATR=0.42%
- **市场快照**: 价格 77000 | ATR 0.14% | RSI 45 | 趋势 up(0.35) | 区间位置 30% | 24h 0.00% | 价格形状 up
- **市场环境**: trend_sideways (置信 0.60)
- **规则引擎**: 触发 volatility_rule | 规则SL 0.42% | 仓位×1.0
- **策略信号**: trend_following=BUY(68%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=BUY(80%)
- **选中策略**: trend_following / BUY (68%)
- **AI 集成**: BUY 75% → **BUY 82%** [自适应买入: pullback_buy模式通过; R/R过滤: R/R=1.00勉强, 置信度降低15%(92%→78%)]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **开多** — AI信号买入 (置信 68%, 策略 trend_following)
- **执行参数**: 止损 76676.6 (0.42%) | 止盈 77323.4 (0.42%) | 建议仓位 7.5% | R/R 1.00
- **学习记录**: provider=qwen38, strategy=trend_following

### A3-低波动上沿 — 开多

- **场景**: ATR 0.19% (低波动带上沿, 3×ATR=0.57% 触顶 clamp 0.5%)
- **市场快照**: 价格 77000 | ATR 0.19% | RSI 45 | 趋势 up(0.35) | 区间位置 30% | 24h 0.00% | 价格形状 up
- **市场环境**: trend_sideways (置信 0.60)
- **规则引擎**: 触发 volatility_rule | 规则SL 0.50% | 仓位×1.0
- **策略信号**: trend_following=BUY(68%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=BUY(80%)
- **选中策略**: trend_following / BUY (68%)
- **AI 集成**: BUY 75% → **BUY 82%** [自适应买入: pullback_buy模式通过; R/R过滤: R/R=1.00勉强, 置信度降低15%(92%→78%)]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **开多** — AI信号买入 (置信 68%, 策略 trend_following)
- **执行参数**: 止损 76615.0 (0.50%) | 止盈 77385.0 (0.50%) | 建议仓位 7.5% | R/R 1.00
- **学习记录**: provider=qwen38, strategy=trend_following

### A4-中等波动 — 开多

- **场景**: ATR 0.30% (中等波动带) → SL 2.33×ATR=0.70%
- **市场快照**: 价格 77000 | ATR 0.30% | RSI 45 | 趋势 up(0.35) | 区间位置 30% | 24h 0.00% | 价格形状 up
- **市场环境**: trend_sideways (置信 0.60)
- **规则引擎**: 触发 volatility_rule | 规则SL 0.70% | 仓位×0.85
- **策略信号**: trend_following=BUY(68%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=BUY(80%)
- **选中策略**: trend_following / BUY (68%)
- **AI 集成**: BUY 75% → **BUY 82%** [自适应买入: pullback_buy模式通过; R/R过滤: R/R=1.00勉强, 置信度降低15%(92%→78%)]
- **风险**: 等级 low | 门禁 0.50
- **最终决策**: **开多** — AI信号买入 (置信 68%, 策略 trend_following)
- **执行参数**: 止损 76461.0 (0.70%) | 止盈 77539.0 (0.70%) | 建议仓位 5.1% | R/R 1.00
- **学习记录**: provider=qwen38, strategy=trend_following

### A5-高波动 — 开多

- **场景**: ATR 0.50% (高波动带) → SL 2×ATR=1.0%, 仓位 0.6x
- **市场快照**: 价格 77000 | ATR 0.50% | RSI 45 | 趋势 up(0.35) | 区间位置 30% | 24h 0.00% | 价格形状 up
- **市场环境**: trend_sideways (置信 0.60)
- **规则引擎**: 触发 volatility_rule | 规则SL 1.00% | 仓位×0.7
- **策略信号**: trend_following=BUY(68%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=BUY(80%)
- **选中策略**: trend_following / BUY (68%)
- **AI 集成**: BUY 75% → **BUY 82%** [自适应买入: pullback_buy模式通过; R/R过滤: R/R=1.00勉强, 置信度降低15%(92%→78%)]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **开多** — AI信号买入 (置信 68%, 策略 trend_following)
- **执行参数**: 止损 76230.0 (1.00%) | 止盈 77770.0 (1.00%) | 建议仓位 3.1% | R/R 1.00
- **学习记录**: provider=qwen38, strategy=trend_following

### A6-极高波动 — 跳过

- **场景**: ATR 0.7% (极高波动带) → 超 ATR 上限门禁, 禁止开仓
- **市场快照**: 价格 77000 | ATR 0.70% | RSI 45 | 趋势 up(0.35) | 区间位置 30% | 24h 0.00% | 价格形状 up
- **市场环境**: trend_sideways (置信 0.60)
- **规则引擎**: 触发 volatility_rule | 规则SL 1.50% | 仓位×0.5
- **策略信号**: trend_following=BUY(68%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=BUY(80%)
- **选中策略**: trend_following / BUY (68%)
- **AI 集成**: BUY 75% → **BUY 82%** [自适应买入: pullback_buy模式通过; R/R过滤: R/R=1.00勉强, 置信度降低15%(92%→78%)]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **跳过** — 高波动市场禁止开仓 (置信 68%, 策略 trend_following)

### A7-极端波动 — 跳过

- **场景**: ATR 1.2% (极端波动) → ATR 门禁禁止开仓, 仓位 0.5x
- **市场快照**: 价格 77000 | ATR 1.20% | RSI 45 | 趋势 up(0.35) | 区间位置 30% | 24h 0.00% | 价格形状 up
- **市场环境**: trend_sideways (置信 0.60)
- **规则引擎**: 触发 volatility_rule | 规则SL 1.50% | 仓位×0.5
- **策略信号**: trend_following=BUY(68%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=BUY(80%)
- **选中策略**: trend_following / BUY (68%)
- **AI 集成**: BUY 85% → **BUY 78%** [自适应买入: pullback_buy模式通过; R/R过滤: R/R=1.00勉强, 置信度降低15%(92%→78%)]
- **风险**: 等级 medium | 门禁 0.55
- **最终决策**: **跳过** — 高波动市场禁止开仓 (置信 68%, 策略 trend_following)

### A8-极端波动门禁 — 跳过

- **场景**: ATR 0.8% + 信号过门禁 → ATR 上限门禁禁止开仓
- **市场快照**: 价格 77000 | ATR 0.80% | RSI 45 | 趋势 up(0.35) | 区间位置 30% | 24h 0.00% | 价格形状 up
- **市场环境**: trend_sideways (置信 0.60)
- **规则引擎**: 触发 volatility_rule | 规则SL 1.50% | 仓位×0.5
- **策略信号**: trend_following=BUY(68%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=BUY(80%)
- **选中策略**: trend_following / BUY (68%)
- **AI 集成**: BUY 85% → **BUY 82%** [自适应买入: pullback_buy模式通过; R/R过滤: R/R=1.00勉强, 置信度降低15%(92%→78%)]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **跳过** — 高波动市场禁止开仓 (置信 68%, 策略 trend_following)

## 二.2 B-趋势

### B1-强上升趋势 — 开多

- **场景**: 趋势向上 0.7 + RSI 62 + AI BUY 72% → 顺势开多
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 62 | 趋势 up(0.70) | 区间位置 50% | 24h 0.00% | 价格形状 up
- **市场环境**: trend_up (置信 0.70)
- **规则引擎**: 触发 trend_rule, volatility_rule | 规则SL 0.45% | 仓位×1.0
- **策略信号**: trend_following=HOLD(60%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / HOLD (60%)
- **AI 集成**: BUY 72% → **BUY 72%** [R/R过滤: R/R=1.00勉强, 置信度降低15%(72%→61%)]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **开多** — AI信号买入 (置信 60%, 策略 trend_following)
- **执行参数**: 止损 76653.5 (0.45%) | 止盈 77346.5 (0.45%) | 建议仓位 7.5% | R/R 1.00
- **学习记录**: provider=qwen38, strategy=trend_following

### B2-强下降趋势 — 开空

- **场景**: 趋势向下 0.7 + RSI 42 (非超卖) + AI SHORT 75% → 顺势开空
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 42 | 趋势 down(0.70) | 区间位置 50% | 24h 0.00% | 价格形状 down
- **市场环境**: low_volatility (置信 0.70)
- **规则引擎**: 触发 volatility_rule | 规则SL 0.45% | 仓位×1.0
- **策略信号**: trend_following=SELL(85%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / SELL (85%)
- **AI 集成**: SHORT 75% → **SHORT 79%** [无]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **开空** — AI信号做空 (置信 85%, 策略 trend_following)
- **执行参数**: 止损 77346.5 (0.45%) | 止盈 76653.5 (0.45%) | 建议仓位 7.5% | R/R 1.00
- **学习记录**: provider=qwen38, strategy=trend_following

### B3-下降趋势AI-HOLD — 跳过

- **场景**: 趋势向下 0.7 + AI HOLD 60% → 不反向开多
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 38 | 趋势 down(0.70) | 区间位置 50% | 24h 0.00% | 价格形状 down
- **市场环境**: low_volatility (置信 0.70)
- **规则引擎**: 触发 rsi_rule, volatility_rule | 规则SL 0.45% | 仓位×1.0
- **策略信号**: trend_following=HOLD(60%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / HOLD (60%)
- **AI 集成**: HOLD 60% → **HOLD 63%** [市场结构确认: R/R=1.00不足，HOLD决策合理]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **跳过** — AI和策略都是HOLD (置信 60%, 策略 trend_following)

### B4-震荡超卖 — 跳过

- **场景**: 横盘 + RSI 25 超卖 + AI HOLD + 策略确认 → 超卖买入路径
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 25 | 趋势 sideways(0.05) | 区间位置 50% | 24h 0.00% | 价格形状 chop
- **市场环境**: oversold (置信 0.85)
- **规则引擎**: 触发 rsi_rule, volatility_rule | 规则SL 0.45% | 仓位×1.0
- **策略信号**: trend_following=HOLD(50%), mean_reversion=BUY(85%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: mean_reversion / BUY (85%)
- **AI 集成**: HOLD 55% → **HOLD 58%** [市场结构确认: R/R=1.00不足，HOLD决策合理]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **跳过** — 均值回归BUY等待反转确认 (置信 85%, 策略 mean_reversion)

### B5-震荡超买做空 — 跳过

- **场景**: 横盘 + RSI 79 超买 + 空R/R≥3 → 均值回归做空门禁
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 79 | 趋势 sideways(0.05) | 区间位置 85% | 24h 0.00% | 价格形状 up
- **市场环境**: overbought (置信 0.85)
- **规则引擎**: 触发 rsi_rule, volatility_rule | 规则SL 0.45% | 仓位×1.0
- **策略信号**: trend_following=HOLD(50%), mean_reversion=SELL(80%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: mean_reversion / SELL (80%)
- **AI 集成**: HOLD 55% → **HOLD 58%** [市场结构确认: R/R=1.00不足，HOLD决策合理]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **跳过** — AI-HOLD覆盖策略(sell) (置信 80%, 策略 mean_reversion)

### B6-极端超买衰竭 — 跳过

- **场景**: RSI 83.5 + 趋势<0.12 + RR≥7 → 极端牛市衰竭做空
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 84 | 趋势 sideways(0.10) | 区间位置 95% | 24h 0.00% | 价格形状 up
- **市场环境**: overbought (置信 0.85)
- **规则引擎**: 触发 rsi_rule, volatility_rule | 规则SL 0.45% | 仓位×1.0
- **策略信号**: trend_following=HOLD(50%), mean_reversion=SELL(80%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: mean_reversion / SELL (80%)
- **AI 集成**: HOLD 50% → **HOLD 52%** [市场结构确认: R/R=1.00不足，HOLD决策合理]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **跳过** — AI-HOLD覆盖策略(sell) (置信 80%, 策略 mean_reversion)

### B7-全HOLD(事故回归) — 跳过

- **场景**: 2026-09-13 05:17 事故场景: AI HOLD 56% + 无强策略 → skip
- **市场快照**: 价格 77000 | ATR 0.14% | RSI 50 | 趋势 neutral(0.02) | 区间位置 50% | 24h 0.00% | 价格形状 flat
- **市场环境**: low_volatility (置信 0.70)
- **规则引擎**: 触发 volatility_rule | 规则SL 0.42% | 仓位×1.0
- **策略信号**: trend_following=HOLD(50%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(100%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / HOLD (50%)
- **AI 集成**: HOLD 56% → **HOLD 59%** [市场结构确认: R/R=1.00不足，HOLD决策合理]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **跳过** — AI和策略都是HOLD (置信 50%, 策略 trend_following)

### B8-下降趋势RSI超卖 — 跳过

- **场景**: 下降趋势 + RSI 25 超卖 + AI SHORT → RSI超卖拦截做空
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 25 | 趋势 down(0.60) | 区间位置 50% | 24h 0.00% | 价格形状 down
- **市场环境**: oversold (置信 0.85)
- **规则引擎**: 触发 rsi_rule, volatility_rule | 规则SL 0.45% | 仓位×1.0
- **策略信号**: trend_following=HOLD(60%), mean_reversion=BUY(85%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / HOLD (60%)
- **AI 集成**: SHORT 80% → **SHORT 84%** [无]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **跳过** — RSI超卖禁止做空 (置信 60%, 策略 trend_following)

## 二.3 C-价格结构

### C1-阻力位附近买入 — 跳过

- **场景**: 价格位于区间 95% (近阻力) + BUY → 高位惩罚/拦截
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 68 | 趋势 sideways(0.05) | 区间位置 95% | 24h 0.00% | 价格形状 up
- **市场环境**: low_volatility (置信 0.70)
- **规则引擎**: 触发 volatility_rule | 规则SL 0.45% | 仓位×1.0
- **策略信号**: trend_following=HOLD(50%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / HOLD (50%)
- **AI 集成**: BUY 60% → **HOLD 35%** [R/R过滤: R/R=1.00勉强, 置信度降低15%(60%→51%); 高位过滤: BUY被压到低置信，降级HOLD继续评估策略]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **跳过** — AI和策略都是HOLD (置信 50%, 策略 trend_following)

### C2-支撑位附近买入 — 开多

- **场景**: 价格位于区间 8% (近支撑) + RSI 32 + BUY → 低位增强
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 32 | 趋势 sideways(0.05) | 区间位置 8% | 24h 0.00% | 价格形状 down
- **市场环境**: low_volatility (置信 0.70)
- **规则引擎**: 触发 rsi_rule, volatility_rule | 规则SL 0.45% | 仓位×1.0
- **策略信号**: trend_following=HOLD(50%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=BUY(65%)
- **选中策略**: mean_reversion / HOLD (50%)
- **AI 集成**: BUY 65% → **BUY 82%** [自适应买入: strong_support模式通过; R/R过滤: R/R=1.00勉强, 置信度降低15%(80%→68%)]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **开多** — AI信号买入 (置信 50%, 策略 mean_reversion)
- **执行参数**: 止损 76653.5 (0.45%) | 止盈 77346.5 (0.45%) | 建议仓位 7.5% | R/R 1.00
- **学习记录**: provider=qwen38, strategy=mean_reversion

### C3-突破上行 — 开多

- **场景**: 价格突破区间上沿 + 趋势向上 + BUY 75%
- **市场快照**: 价格 77000 | ATR 0.20% | RSI 58 | 趋势 up(0.50) | 区间位置 100% | 24h 0.00% | 价格形状 up
- **市场环境**: trend_sideways (置信 0.60)
- **规则引擎**: 触发 无
- **策略信号**: trend_following=BUY(75%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / BUY (75%)
- **AI 集成**: BUY 75% → **BUY 65%** [自适应买入: pullback_buy模式通过; R/R过滤: R/R=1.00勉强, 置信度降低15%(90%→76%)]
- **风险**: 等级 low | 门禁 0.50
- **最终决策**: **开多** — AI信号买入 (置信 75%, 策略 trend_following)
- **执行参数**: 止损 76615.0 (0.50%) | 止盈 77385.0 (0.50%) | 建议仓位 7.5% | R/R 1.00
- **学习记录**: provider=qwen38, strategy=trend_following

### C4-跌破支撑 — 开空

- **场景**: 价格跌破区间下沿 + 趋势向下 + SHORT 70% → 开空
- **市场快照**: 价格 77000 | ATR 0.20% | RSI 42 | 趋势 down(0.50) | 区间位置 40% | 24h 0.00% | 价格形状 down
- **市场环境**: low_volatility (置信 0.70)
- **规则引擎**: 触发 无
- **策略信号**: trend_following=SELL(75%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / SELL (75%)
- **AI 集成**: SHORT 70% → **SHORT 74%** [无]
- **风险**: 等级 low | 门禁 0.50
- **最终决策**: **开空** — AI信号做空 (置信 75%, 策略 trend_following)
- **执行参数**: 止损 77385.0 (0.50%) | 止盈 76615.0 (0.50%) | 建议仓位 7.5% | R/R 1.00
- **学习记录**: provider=qwen38, strategy=trend_following

### C5-下跌结构买入 — 跳过

- **场景**: bearish 结构 + BUY → 禁止做多
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 50 | 趋势 down(0.40) | 区间位置 50% | 24h 0.00% | 价格形状 down
- **市场环境**: low_volatility (置信 0.70)
- **规则引擎**: 触发 volatility_rule | 规则SL 0.45% | 仓位×1.0
- **策略信号**: trend_following=SELL(70%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / SELL (70%)
- **AI 集成**: BUY 80% → **BUY 71%** [R/R过滤: R/R=1.00勉强, 置信度降低15%(80%→68%)]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **跳过** — 强下跌趋势，禁止做多 (置信 70%, 策略 trend_following)

### C6-BTC高位风险 — 跳过

- **场景**: price_position 0.98 (极高位) + BUY 52% → 高位风险拦截
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 72 | 趋势 sideways(0.05) | 区间位置 98% | 24h 0.00% | 价格形状 up
- **市场环境**: overbought (置信 0.85)
- **规则引擎**: 触发 rsi_rule, volatility_rule | 规则SL 0.45% | 仓位×1.0
- **策略信号**: trend_following=HOLD(50%), mean_reversion=SELL(80%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: mean_reversion / SELL (80%)
- **AI 集成**: BUY 52% → **HOLD 35%** [R/R过滤: R/R=1.00勉强, 置信度降低15%(52%→44%); 高位过滤: BUY被压到低置信，降级HOLD继续评估策略]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **跳过** — AI-HOLD覆盖策略(sell) (置信 80%, 策略 mean_reversion)

## 二.4 D-崩盘事件

### D1-闪崩 — 跳过

- **场景**: 15分钟 -3% 闪崩 + BUY → 持续下跌阻断买入
- **市场快照**: 价格 77000 | ATR 0.60% | RSI 22 | 趋势 down(0.80) | 区间位置 50% | 24h -3.00% | 价格形状 crash
- **市场环境**: oversold (置信 0.85)
- **规则引擎**: 触发 rsi_rule, volatility_rule | 规则SL 1.00% | 仓位×0.7
- **策略信号**: trend_following=HOLD(60%), mean_reversion=BUY(85%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / HOLD (60%)
- **AI 集成**: BUY 65% → **BUY 83%** [自适应买入: oversold_rebound模式通过; R/R过滤: R/R=1.00勉强, 置信度降低15%(65%→55%)]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **跳过** — 高波动市场禁止开仓 (置信 60%, 策略 trend_following)

### D2-V型反弹 — 开多

- **场景**: 暴跌后 V 型反弹 + crash_bounce 策略 + BUY → 反弹买入路径
- **市场快照**: 价格 77000 | ATR 0.40% | RSI 48 | 趋势 up(0.30) | 区间位置 50% | 24h -4.00% | 价格形状 v_bounce
- **市场环境**: trend_sideways (置信 0.60)
- **规则引擎**: 触发 volatility_rule | 规则SL 1.00% | 仓位×0.7
- **策略信号**: trend_following=HOLD(60%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / HOLD (60%)
- **AI 集成**: BUY 62% → **BUY 82%** [自适应买入: pullback_buy模式通过; R/R过滤: R/R=1.00勉强, 置信度降低15%(92%→78%)]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **开多** — AI信号买入 (置信 60%, 策略 trend_following)
- **执行参数**: 止损 76230.0 (1.00%) | 止盈 77770.0 (1.00%) | 建议仓位 3.1% | R/R 1.00
- **学习记录**: provider=qwen38, strategy=trend_following

### D3-持续阴跌 — 跳过

- **场景**: 24h -1.8% 持续阴跌 + BUY → 下跌检测惩罚/阻断
- **市场快照**: 价格 77000 | ATR 0.18% | RSI 30 | 趋势 down(0.40) | 区间位置 50% | 24h -1.80% | 价格形状 down
- **市场环境**: low_volatility (置信 0.70)
- **规则引擎**: 触发 rsi_rule, volatility_rule | 规则SL 0.50% | 仓位×1.0
- **策略信号**: trend_following=HOLD(60%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: mean_reversion / HOLD (50%)
- **AI 集成**: BUY 60% → **BUY 54%** [R/R过滤: R/R=1.00勉强, 置信度降低15%(60%→51%)]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **跳过** — 最终置信度54%低于阈值55% (置信 54%, 策略 mean_reversion)

### D4-严重下跌 — 跳过

- **场景**: 24h -5% 严重下跌 + BUY → 完全阻断买入
- **市场快照**: 价格 77000 | ATR 0.80% | RSI 18 | 趋势 down(0.90) | 区间位置 50% | 24h -5.00% | 价格形状 down
- **市场环境**: oversold (置信 0.85)
- **规则引擎**: 触发 rsi_rule, volatility_rule | 规则SL 1.50% | 仓位×0.5
- **策略信号**: trend_following=HOLD(60%), mean_reversion=BUY(85%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / HOLD (60%)
- **AI 集成**: BUY 70% → **BUY 90%** [自适应买入: oversold_rebound模式通过; R/R过滤: R/R=1.00勉强, 置信度降低15%(70%→60%)]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **跳过** — 高波动市场禁止开仓 (置信 60%, 策略 trend_following)

## 二.5 E-持仓状态

### E1-多头浮盈 — 跳过

- **场景**: 持有 long (入场 76400, 现价 77000 +0.79%) → 追踪止损上移
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 55 | 趋势 sideways(0.05) | 区间位置 50% | 24h 0.00% | 价格形状 flat
- **持仓**: long 入场 76400 (+0.79%)
- **市场环境**: low_volatility (置信 0.70)
- **规则引擎**: 触发 volatility_rule | 规则SL 0.45% | 仓位×1.0
- **策略信号**: trend_following=HOLD(50%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / HOLD (50%)
- **AI 集成**: HOLD 50% → **HOLD 52%** [市场结构确认: R/R=1.00不足，HOLD决策合理]
- **风险**: 等级 low | 门禁 0.55 | 开仓检查: 触发盈利硬保护: 盈利回吐至 0.79%
- **最终决策**: **跳过** — AI和策略都是HOLD (置信 50%, 策略 trend_following)

### E2-多头浮亏未触发 — 跳过

- **场景**: 持有 long (入场 77400, 现价 77000 -0.52%, 止损 76900 未触发) → 持有
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 45 | 趋势 sideways(0.05) | 区间位置 50% | 24h 0.00% | 价格形状 flat
- **持仓**: long 入场 77400 (-0.52%)
- **市场环境**: low_volatility (置信 0.70)
- **规则引擎**: 触发 volatility_rule | 规则SL 0.45% | 仓位×1.0
- **策略信号**: trend_following=HOLD(50%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / HOLD (50%)
- **AI 集成**: HOLD 50% → **HOLD 52%** [市场结构确认: R/R=1.00不足，HOLD决策合理]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **跳过** — AI和策略都是HOLD (置信 50%, 策略 trend_following)

### E3-多头共振卖出 — 平仓

- **场景**: 持有 long + AI SELL 78% + 策略 SELL → 平仓
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 70 | 趋势 down(0.30) | 区间位置 50% | 24h 0.00% | 价格形状 down
- **持仓**: long 入场 76400 (+0.79%)
- **市场环境**: low_volatility (置信 0.70)
- **规则引擎**: 触发 volatility_rule | 规则SL 0.45% | 仓位×1.0
- **策略信号**: trend_following=HOLD(60%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / HOLD (60%)
- **AI 集成**: SELL 78% → **SELL 82%** [无]
- **风险**: 等级 low | 门禁 0.55 | 开仓检查: 触发盈利硬保护: 盈利回吐至 0.79%
- **最终决策**: **平仓** — SELL信号与多仓反向，平多 (置信 60%, 策略 trend_following)

### E4-多头中再BUY — 跳过

- **场景**: 持有 long + AI BUY → 已有持仓, 跳过开仓
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 58 | 趋势 up(0.50) | 区间位置 50% | 24h 0.00% | 价格形状 up
- **持仓**: long 入场 76400 (+0.79%)
- **市场环境**: trend_sideways (置信 0.60)
- **规则引擎**: 触发 volatility_rule | 规则SL 0.45% | 仓位×1.0
- **策略信号**: trend_following=BUY(75%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / BUY (75%)
- **AI 集成**: BUY 80% → **BUY 82%** [自适应买入: pullback_buy模式通过; R/R过滤: R/R=1.00勉强, 置信度降低15%(92%→78%)]
- **风险**: 等级 low | 门禁 0.55 | 开仓检查: 触发盈利硬保护: 盈利回吐至 0.79%
- **最终决策**: **跳过** — 多仓同向BUY，继续持有 (置信 75%, 策略 trend_following)

### E5-空头浮盈 — 跳过

- **场景**: 持有 short (入场 77600, 现价 77000 盈利) → 持有+追踪
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 40 | 趋势 down(0.40) | 区间位置 50% | 24h 0.00% | 价格形状 down
- **持仓**: short 入场 77600 (-0.77%)
- **市场环境**: low_volatility (置信 0.70)
- **规则引擎**: 触发 volatility_rule | 规则SL 0.45% | 仓位×1.0
- **策略信号**: trend_following=HOLD(60%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / HOLD (60%)
- **AI 集成**: HOLD 50% → **HOLD 52%** [市场结构确认: R/R=1.00不足，HOLD决策合理]
- **风险**: 等级 low | 门禁 0.55 | 开仓检查: 触发盈利硬保护: 盈利回吐至 0.77%
- **最终决策**: **跳过** — AI和策略都是HOLD (置信 60%, 策略 trend_following)

### E6-空单平仓状态 — 跳过

- **场景**: short_to_close (空单触发平仓中) → 进入平仓流程
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 45 | 趋势 sideways(0.05) | 区间位置 50% | 24h 0.00% | 价格形状 flat
- **持仓**: short_to_close 入场 77600 (-0.77%)
- **市场环境**: low_volatility (置信 0.70)
- **规则引擎**: 触发 volatility_rule | 规则SL 0.45% | 仓位×1.0
- **策略信号**: trend_following=HOLD(50%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / HOLD (50%)
- **AI 集成**: HOLD 50% → **HOLD 52%** [市场结构确认: R/R=1.00不足，HOLD决策合理]
- **风险**: 等级 low | 门禁 0.55 | 开仓检查: 触发盈利硬保护: 盈利回吐至 0.77%
- **最终决策**: **跳过** — AI和策略都是HOLD (置信 50%, 策略 trend_following)

## 二.6 F-风控

### F1-连亏3次 — 开多

- **场景**: 连续亏损 3 次 + BUY 70% → 仓位 0.5x + 门禁 0.60
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 55 | 趋势 up(0.40) | 区间位置 50% | 24h 0.00% | 价格形状 up
- **市场环境**: trend_sideways (置信 0.60)
- **规则引擎**: 触发 volatility_rule, consecutive_loss_rule | 规则SL 0.40% | 仓位×0.5
- **策略信号**: trend_following=BUY(70%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / BUY (70%)
- **AI 集成**: BUY 70% → **BUY 82%** [自适应买入: pullback_buy模式通过; R/R过滤: R/R=1.00勉强, 置信度降低15%(92%→78%)]
- **风险**: 等级 low | 门禁 0.60
- **最终决策**: **开多** — AI信号买入 (置信 70%, 策略 trend_following)
- **执行参数**: 止损 76692.0 (0.40%) | 止盈 77308.0 (0.40%) | 建议仓位 3.8% | R/R 1.00
- **学习记录**: provider=qwen38, strategy=trend_following

### F2-连亏5次 — 开多

- **场景**: 连续亏损 5 次 + BUY 70% → 仓位 0.2x + 门禁 0.70
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 55 | 趋势 up(0.40) | 区间位置 50% | 24h 0.00% | 价格形状 up
- **市场环境**: trend_sideways (置信 0.60)
- **规则引擎**: 触发 volatility_rule, consecutive_loss_rule | 规则SL 0.30% | 仓位×0.2
- **策略信号**: trend_following=BUY(70%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / BUY (70%)
- **AI 集成**: BUY 70% → **BUY 82%** [自适应买入: pullback_buy模式通过; R/R过滤: R/R=1.00勉强, 置信度降低15%(92%→78%)]
- **风险**: 等级 low | 门禁 0.70
- **最终决策**: **开多** — AI信号买入 (置信 70%, 策略 trend_following)
- **执行参数**: 止损 76769.0 (0.30%) | 止盈 77308.0 (0.40%) | 建议仓位 1.5% | R/R 1.33
- **学习记录**: provider=qwen38, strategy=trend_following

### F3-当日亏损回撤 — 开多

- **场景**: 当日回撤 4% (接近熔断 3% 上限) + BUY → 风险等级抬升
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 55 | 趋势 up(0.40) | 区间位置 50% | 24h 0.00% | 价格形状 up
- **持仓**: None 入场 0 (+0.00%)
- **市场环境**: trend_sideways (置信 0.60)
- **规则引擎**: 触发 volatility_rule | 规则SL 0.45% | 仓位×1.0
- **策略信号**: trend_following=BUY(70%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / BUY (70%)
- **AI 集成**: BUY 70% → **BUY 82%** [自适应买入: pullback_buy模式通过; R/R过滤: R/R=1.00勉强, 置信度降低15%(92%→78%)]
- **风险**: 等级 medium | 门禁 0.55
- **最终决策**: **开多** — AI信号买入 (置信 70%, 策略 trend_following)
- **执行参数**: 止损 76653.5 (0.45%) | 止盈 77346.5 (0.45%) | 建议仓位 7.5% | R/R 1.00
- **学习记录**: provider=qwen38, strategy=trend_following

### F4-低置信拦截 — 跳过

- **场景**: 横盘无技术共振 + BUY 48% → 被降级/惩罚后低于门禁, 拦截
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 50 | 趋势 neutral(0.02) | 区间位置 50% | 24h 0.00% | 价格形状 flat
- **市场环境**: low_volatility (置信 0.70)
- **规则引擎**: 触发 volatility_rule | 规则SL 0.45% | 仓位×1.0
- **策略信号**: trend_following=HOLD(50%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(100%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / HOLD (50%)
- **AI 集成**: BUY 48% → **HOLD 38%** [R/R过滤: R/R=1.00勉强, 置信度降低15%(48%→41%); 高位过滤: BUY被压到低置信，降级HOLD继续评估策略]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **跳过** — AI和策略都是HOLD (置信 50%, 策略 trend_following)

## 二.7 G-集成流水线

### G1-明确HOLD不翻转 — 跳过

- **场景**: AI HOLD 56% + 技术买入条件 → 保持 HOLD (翻转守卫)
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 52 | 趋势 up(0.30) | 区间位置 50% | 24h 0.00% | 价格形状 up
- **市场环境**: trend_sideways (置信 0.60)
- **规则引擎**: 触发 volatility_rule | 规则SL 0.45% | 仓位×1.0
- **策略信号**: trend_following=HOLD(60%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / HOLD (60%)
- **AI 集成**: HOLD 56% → **HOLD 59%** [自适应买入被阻止翻转: AI 明确 HOLD (置信度 56% >= 55%), 技术买入条件不翻转信号; 市场结构确认: R/R=1.00不足，HOLD决策合理]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **跳过** — AI和策略都是HOLD (置信 60%, 策略 trend_following)

### G2-模糊HOLD可翻转 — 开多

- **场景**: AI HOLD 40% (模糊) + 技术买入条件 → 允许翻转 BUY
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 52 | 趋势 up(0.30) | 区间位置 50% | 24h 0.00% | 价格形状 up
- **市场环境**: trend_sideways (置信 0.60)
- **规则引擎**: 触发 volatility_rule | 规则SL 0.45% | 仓位×1.0
- **策略信号**: trend_following=HOLD(60%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / HOLD (60%)
- **AI 集成**: HOLD 40% → **BUY 82%** [自适应买入: pullback_buy模式通过; R/R过滤: R/R=1.00勉强, 置信度降低15%(92%→78%)]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **开多** — AI信号买入 (置信 60%, 策略 trend_following)
- **执行参数**: 止损 76653.5 (0.45%) | 止盈 77346.5 (0.45%) | 建议仓位 7.5% | R/R 1.00
- **学习记录**: provider=qwen38, strategy=trend_following

### G3-SELL不翻BUY — 跳过

- **场景**: AI SELL 85% + 技术买入条件 → 保持 SELL
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 30 | 趋势 down(0.50) | 区间位置 50% | 24h 0.00% | 价格形状 down
- **市场环境**: low_volatility (置信 0.70)
- **规则引擎**: 触发 rsi_rule, volatility_rule | 规则SL 0.45% | 仓位×1.0
- **策略信号**: trend_following=HOLD(60%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / HOLD (60%)
- **AI 集成**: SELL 85% → **SELL 89%** [无]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **跳过** — SELL信号+无持仓，忽略 (置信 60%, 策略 trend_following)

### G4-BUY超100归一化 — 开多

- **场景**: AI BUY 置信度 75 (百分制误传) → 归一化 0.75
- **市场快照**: 价格 77000 | ATR 0.15% | RSI 58 | 趋势 up(0.40) | 区间位置 50% | 24h 0.00% | 价格形状 up
- **市场环境**: trend_sideways (置信 0.60)
- **规则引擎**: 触发 volatility_rule | 规则SL 0.45% | 仓位×1.0
- **策略信号**: trend_following=BUY(70%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / BUY (70%)
- **AI 集成**: BUY 7500% → **BUY 82%** [自适应买入: pullback_buy模式通过; R/R过滤: R/R=1.00勉强, 置信度降低15%(92%→78%)]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **开多** — AI信号买入 (置信 70%, 策略 trend_following)
- **执行参数**: 止损 76653.5 (0.45%) | 止盈 77346.5 (0.45%) | 建议仓位 7.5% | R/R 1.00
- **学习记录**: provider=qwen38, strategy=trend_following

### G5-阴跌中BUY降权 — 跳过

- **场景**: BUY 65% + 轻度持续下跌 → 置信度惩罚
- **市场快照**: 价格 77000 | ATR 0.18% | RSI 38 | 趋势 down(0.45) | 区间位置 50% | 24h -1.50% | 价格形状 down
- **市场环境**: low_volatility (置信 0.70)
- **规则引擎**: 触发 rsi_rule, volatility_rule | 规则SL 0.50% | 仓位×1.0
- **策略信号**: trend_following=HOLD(60%), mean_reversion=HOLD(50%), breakout=HOLD(50%), safe_mode=HOLD(30%), crash_bounce=HOLD(30%)
- **选中策略**: trend_following / HOLD (60%)
- **AI 集成**: BUY 65% → **BUY 58%** [R/R过滤: R/R=1.00勉强, 置信度降低15%(65%→55%)]
- **风险**: 等级 low | 门禁 0.55
- **最终决策**: **跳过** — 强下跌趋势，禁止做多 (置信 60%, 策略 trend_following)

## 三、关键业务结论

- 41 场景中: 开仓 16 (多 14/空 2), 跳过 24, 其余为持仓持有/平仓路径
- 无持仓 BUY 信号被门禁/趋势/结构拦截: 11 例 (A6-极高波动, A7-极端波动, A8-极端波动门禁, C1-阻力位附近买入, C5-下跌结构买入, C6-BTC高位风险, D1-闪崩, D3-持续阴跌, D4-严重下跌, F4-低置信拦截, G5-阴跌中BUY降权)
- 开仓止损距离范围: 0.30% ~ 1.00% (全在 0.3%~1.5% 安全区间, 风险平价: 仓位×止损≈常数)
- 全部场景通过全局不变量: 门禁 ≥ 0.50 | SL 距离 0.25%~1.6% | TP ≥ min(SL×1.0, 4×ATR) R/R 下限
