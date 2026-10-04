# 双向（多/空）交易与全链路优化设计

- 日期：2026-10-04
- 状态：待用户评审
- 关联数据报告：`markdown/JEV_SHADOW_ANALYSIS_2026-10-04.md`、`markdown/AI_SIGNAL_ANALYSIS_REPORT_V2.md`（历史）

## Context（背景与证据）

8 天日志（2026-09-27 ~ 10-04，~1050 个 15 分钟周期，BTC/USDT:USDT，10x）：

| 事实 | 数据 |
|---|---|
| 成交 | **0 笔**。5 个最终 BUY 信号全部因余额 $7.30 < 最小 1 手（需 ~$277）取消 |
| LLM (qwen38) | 575 次响应 **100% hold**，置信度 55–65% 集中在 55% 翻转守卫线附近 |
| Jev 快车道 | 8 天 ~950 次决策：hold 占比 ~78%；**buy 置信度峰值 0.67、short 峰值 0.30**，从未达到 0.75 采用线；高置信 hold 与 LLM 一致率 100% |
| 本地技术层 | 8 天 5 个 BUY 全部出自自适应买入层翻转（oversold_rebound / pullback_buy / trend_confirmation）；**无任何卖出/做空对称逻辑** |
| 执行层 | `_execute_signal` 仅处理 BUY(开多)/HOLD/SELL(平多)；**"short" 落入"未知信号"被丢弃，系统结构上纯做多** |
| 错过的双向机会 | 9/28：84.4k→82.6k（-2.1% 完整下跌段）；10/02：84.2k→86.9k（+3.2% 上涨段，Jev buy 0.65–0.67 方向正确但被 LLM hold 拒绝）；10/03：85.5k→83.9k（-1.9%） |

已确认的用户目标与参数（本 spec 的约束）：

- **目标**：最大化交易盈利机会，做多与做空双向捕捉
- **风险预算（B 均衡）**：单笔最大亏损 ≤ 账户 10%；账户回撤 ≥ 30% 触发停机总闸；维持 10x 杠杆 + 30% 仓位系数（max_position_usage）
- **持仓时间（B 日内+波段）**：默认 4–24h 离场；趋势强时由移动止损（trailing stop）自然持有 2–3 天，不强制尾盘平仓
- **Jev**：保留为第一道门（adopt 后继续过风控层，不"直接结束"）；优化其对走势与入仓的判断准确性
- 交易对：仅 BTC/USDT:USDT；周期：15 分钟

## Goal

1. **双向盈利能力**：补齐做空信号链与执行路径（P3），多/空机会对称捕捉。
2. **Jev 更准**（P2）：重写 state 特征与问题 criteria、增加 4h 视野，使其在趋势识别与入场先验上更可信；阈值用结果数据校准而非拍脑袋。
3. **一切调参有数据**（P1）：决策日志（decision journal）记录每层信号 + T+4h/T+24h 结果回填，2 周后即可回答"每层放行/拦截了什么、赚/亏了"。
4. **风险可控**（P1）：30% 回撤停机总闸 + 单笔风险（ATR 止损距离）仓位反查。

## Non-Goals（明确不做）

- 不做同时持有多+空的对冲仓位（单标的单仓位；反向信号 = 先平、下周期再开）。
- 不新增交易对、交易所、策略类型（不做网格/套利/高频）。
- 不做自动参数优化（贝叶斯调参等）——本周期内阈值调整全部基于决策日志的人工评审，一次一个参数。
- 不做 Jev 本地部署、不引入 TypeSafe SDK（沿用 HTTP 直连）。
- 不修改 `VALID_SIGNALS` 词表（buy/hold/sell/short）与下游接口签名。
- 不解决入金（用户外部动作，本设计假设账户可交易，即余额 ≥ ~$280）。

## 现有基建盘点（复用，不重造）

| 组件 | 现状 | 本设计用法 |
|---|---|---|
| `OrderService.create_order(symbol, side, amount, intent, position_side)` | 已支持 OPEN/CLOSE intent + posSide（hedge/one-way 自动检测） | 开空：side="sell" + intent=OPEN + position_side="short"；平空：side="buy" + intent=CLOSE |
| `StopLossManager`（core/stop_loss_manager.py） | 已支持多空（stop_side 按 position.side 决定，统一止损入口 `calculate_stop_price_unified`） | 空头仓位直接复用 |
| `account_service` | 已解析 posSide、contracts<0 → side="short" | 空头持仓追踪已可用 |
| `RiskManager` 边界体系（ai/adaptive/risk_manager.py） | HardStopLoss / DynamicPosition / CircuitBreaker（3% 日亏熔断 4h） | P1 新增 DrawdownBoundary 挂入同一体系 |
| Jev 快车道（ai/jev/） | 熔断器/决策矩阵/shadow 完整 | P2 只改 questions/state/配置 |
| AI fusion（deepseek/kimi/qwen38 provider 已就绪） | AI_MODE=single/fusion 可切 | P4 兜底与投票复用 |
| 数据落盘模式 | `data_json/trade_history.json`（JSON 文件） | P1 沿用 JSONL 文件模式 |

## 架构总览

```
market_data
   ▼
AIClient.get_signal
   │ ① 缓存命中 → 返回（不变）
   │ ② Jev 快车道（第一道门，mode=on；P2 校准期可 shadow）
   │    ├─ 高置信 adopt（hold/buy/short）→ 跳过 LLM
   │    └─ 低置信/风险旗标 → 升级 LLM（single 或 fusion，503 兜底 [P4]）
   ▼
AISignalIntegrator（本地层）
   │  自适应买入 [现有] + 自适应卖出 [P3 新增] + 翻转守卫(多空对称) + R/R + 优化器
   ▼
RiskManager 边界链
   │  新增 DrawdownBoundary（30% 回撤总闸）[P1]
   │  现有 CircuitBreaker（3% 日亏 4h 冷却）/ HardStopLoss / DynamicPosition
   ▼
DecisionEngine（策略选择/覆盖，多空对称 [P3]）
   ▼
Bot._execute_signal（新增 SHORT 开空 / SELL+空仓平空 / 反向信号先平 [P3]）
   ▼
OrderService（现有）→ StopLossManager（现有，多空支持）

[旁路] DecisionJournal（P1）：每周期记录各层信号+价格 → 回填 T+4h/T+24h 结果
```

**关键不变式**：所有新增能力均有独立配置开关，关闭任一开关行为回退到当前状态；Jev/LLM/本地层的接口签名不变。

---

## P1 地基与度量（不改交易行为，零风险）

### 1.1 DecisionJournal（决策日志）

- **存储**：`data_json/decision_journal.jsonl`，每周期一行 JSON，按日期轮转（`decision_journal-YYYY-MM-DD.jsonl`），保留 90 天。
- **每周期记录字段**：
  - 市场：timestamp、price、rsi、atr、change_24h、change_1h
  - Jev：choice、confidence、probabilities、outcome（adopt/escalate/…）、risk_noul、choppy_noul、latency_ms、mode（on/shadow）
  - LLM：provider、signal、confidence、是否注入 jev_context、503/失败标记
  - 本地层：can_buy+mode、can_sell+mode（P3 后）、final_flip（HOLD→BUY 等）、flip_block_reason
  - 最终：signal、confidence、执行动作、blocked_reason（含余额不足）
- **结果回填**：每周期开始时扫描 4h / 24h 前的记录，计算
  `forward_return_4h = (P_{t+4h} - P_t) / P_t`（方向性正确 = return × 信号方向 > 0.1% 阈值），
  以追加字段写回（JSONL 按 timestamp 索引定位，重写该行）。
- **报告**：`scripts/decision_journal_report.py`，输出分层准确率表：
  - Jev 各 choice×conf 档位的 T+4h 正收益比例 / 平均收益
  - LLM 信号同理；本地层各 mode 同理
  - 翻转守卫拦截样本的 T+4h 表现（回答"55% 守卫挡掉的 64 次，错过了多少"）
- **配置**：`DECISION_JOURNAL=true`（默认开，纯增量不影响交易）。

### 1.2 DrawdownBoundary（30% 回撤停机总闸）

- 新增 `RiskBoundary` 实现，挂入 RiskManager 边界链（与 3% 日亏熔断并行，互不替代）。
- 基准：**高水位**（权益历史最高值），持久化到 `data_json/trading_state/drawdown_baseline.json`（进程重启不重置，避免“亏损后重启重置基准”的漏洞）；可配置改为“启动基准”（默认不用）。
- 触发：`equity ≤ baseline × (1 - 0.30)` → **禁止一切新开仓（多/空均禁）**，已持仓继续由止损管理至平仓；WARNING 日志 `[风控总闸] OPEN: 回撤 3x%`，`get_metrics()` 暴露状态。
- 恢复：**仅手动**——`RISK_RESUME=1` + 重启进程。不自动恢复（30% 回撤意味着策略大概率失效，自动恢复 = 让失效策略继续亏）。
- 参数：`RISK_DRAWDOWN_HALT=0.30`。

### 1.3 仓位公式统一 + 单笔风险反查

- 现状：`contracts = balance × 0.30 × leverage / price`（多空同公式，已对称）。
- 新增风险反查（开仓前）：
  1. 止损距离 `d`：取现有统一止损入口 `calculate_stop_price_unified` 的计算结果（与 StopLossManager 实际挂单同一口径，避免双套止损价），`d = |price - stop_price| / price`；
  2. 预期止损亏损 `= 仓位名义 × d / price`；
  3. 若 `> balance × 0.10`（`RISK_PER_TRADE_MAX`），缩减仓位至满足，仍 < 最小 1 手则放弃开仓（日志标明原因）。
- 该反查对多/空同样适用；参数进 `RiskConfig`（env 可配）。

---

## P2 Jev 增强（只动 `alpha_trading_bot/ai/jev/` + 配置）

### 2.1 state 显式趋势特征（`questions.build_state`）

目标：把"需要 Jev 自己算的趋势"变成"喂给 Jev 的事实"。全部从现有 market_data 字段计算（price_history 20 根 15m K 线 + 现有指标），**不新增 API 调用**；缺键跳过不报错（沿用现有约定）。新增事实项：

| 特征 | 计算 | 输出示例 |
|---|---|---|
| EMA20 偏离 | price / EMA(price_history, 20) - 1 | "价格高于20周期EMA 1.2%" |
| 4h 趋势 | 最后 16 根 15m 聚合：首尾变化 + 斜率方向 | "4小时级别趋势: 上行 (+2.1%)" |
| 距摆动高低点 | 距 20 根 high/low 的 % | "距20周期高点 0.8% / 低点 2.3%" |
| ATR 归一化动量 | (price - price[-7]) / ATR | "近6根K线动量 +1.8 ATR" |
| 量能趋势 | 近 6 根均量 / 20 根均量 | "成交量为20周期均量 1.35 倍" |

state token 预算目标 400–700（当前 400–600，超出时按优先级裁剪原始指标行，保留新增事实行）。

### 2.2 问题 criteria 重写（多空对称 + 对齐系统 edge + 4h 视野）

`TRADE_DECISION` 的 instructions 增加决策视野声明："判断未来 1-4 小时内最合适的交易方向"；criteria 改为与本地层验证过的盈利模式对齐：

- `buy`：「上行趋势（价格位于 EMA20 上方且 4h 趋势向上）中回踩支撑企稳，或深度超卖（RSI<30）出现反弹信号，入场点明确」
- `short`：「下行趋势（价格位于 EMA20 下方且 4h 趋势向下）中反弹至阻力受阻，或放量破位下行动能延续，入场点明确」
- `hold` / `sell`：语义不变（观望 / 平多离场）。

### 2.3 新增 4h 视野 Noul（路由 + 上下文用，不直接产生信号）

- `IS_LONG_SETUP_4H`：「未来 4 小时内出现高确定性多头入场机会（趋势入场或超卖反弹）」
- `IS_SHORT_SETUP_4H`：「未来 4 小时内出现高确定性空头入场机会（趋势入场或超买反转）」
- 两者数值注入 `jev_context`（升级 LLM 时），供 LLM 参考；不参与采用/熔断逻辑。
- 请求仍为单次（1 Choice + 4 Noul），延迟/成本影响可忽略（input token +~80）。

### 2.4 观察与阈值校准（数据驱动，不拍脑袋）

- 新增观察日志：`choice ∈ {buy, short}` 且 `conf ≥ 0.55` → 独立行 `[Jev观察] choice=buy conf=0.61 probs{...} price=... rsi=...`（供周报聚合）。
- 2 周数据后，用 DecisionJournal 统计该批调用的 T+4h 胜率：
  - 胜率 ≥ 55% 且样本 ≥ 30 → 对应 conf 阈值 0.75 降至 0.65 试运行；
  - 否则维持 0.75（该分支继续作死分支，无副作用）。
- `conf_hold` 不动（已验证：与 LLM 100% 一致，否决质量无问题）。
- `risk_noul_gate` 不动。

### 2.5 测试

- `build_state`：新特征键存在时输出正确值、缺键时不报错且不输出该行；token 预算裁剪逻辑。
- 问题集回归：结构（1 Choice 4 选项 + 4 Noul）、criteria 文案断言。
- fast_lane 决策矩阵回归（adopt/escalate/risk_gate/circuit/shadow 全覆盖，含新 Noul 解析缺失兜底）。
- `jev_context` 含新 Noul 值。

---

## P3 做空子系统（config 开关，默认 off；开 = 新增交易行为）

### 3.1 配置

- `ENABLE_SHORT_TRADING=false`（dataclass + `from_env`，对齐现有惯例）。
- **off 时行为零变化**：任何链路产生的 short 信号在 AIClient 出口降级为 hold（日志 `[做空开关] short 信号降级为 hold（ENABLE_SHORT_TRADING=false）`）。

### 3.2 信号层对称：AdaptiveSellCondition

新增 `alpha_trading_bot/ai/adaptive_sell_condition.py`（镜像 `adaptive_buy_condition.py` 的 dataclass 结构 + `should_sell(market_data) -> SellConditionResult`）：

| mode（对齐做多侧） | 条件（默认值，均可配） |
|---|---|
| `overbought_reversal`（对应 oversold_rebound） | RSI > 75（`SELL_RSI_OVERBOUGHT`）+ 价格触及布林上轨/阻力位 + 出现长上影或连续 3 根滞涨 |
| `breakdown`（对应 breakout_confirmation） | 跌破 20 周期支撑 + 量能 > 1.2× 均量 + 4h 趋势向下，2/3 条件通过 |
| `trend_confirmation`（镜像） | 连续 3 根阴线 + RSI < 50 + 4h 趋势向下，2/3 条件通过 |
| `pullback_sell`（对应 pullback_buy） | 下行趋势中反弹至阻力位（反弹幅度 < 0.618× 下跌段）遇阻 |

- 复用现有 `market_structure` / `risk_reward_calculator` 的**做空侧 R/R**（日志中已计算但从未使用）。
- **翻转守卫对称**（integrator）：
  - 现有：AI 明确 HOLD（≥55%）不翻转为 BUY；SELL 永不翻转为 BUY。
  - 新增镜像：AI 明确 HOLD（≥55%）不翻转为 SELL；BUY 永不翻转为 SELL（防止技术规则在 AI 明确看多时反向开空）。
- LLM prompt：P3 阶段保证 SHORT 可解析可执行（`response_parser` 词表已含 short）；prompt 文案对称化与去保守化归 P4。

### 3.3 执行层（`bot._execute_signal` 扩展）

信号 × 持仓状态矩阵（新增部分加粗）：

| 信号 \ 持仓 | 无持仓 | 持多 | 持空 |
|---|---|---|---|
| BUY | 开多（现有） | 更新止损（现有） | **平空（side=buy, intent=CLOSE），本周期不开多** |
| HOLD | 不操作（现有） | 更新止损（现有） | **更新止损（复用，方向=buy）** |
| SELL | 不操作（现有） | 平多（现有） | **平空（side=buy, intent=CLOSE）** |
| **SHORT** | **开空（side=sell, intent=OPEN, position_side=short；仓位公式+风险反查）** | **平多（side=sell, intent=CLOSE），本周期不开空** | **更新止损（复用）** |

- **反向信号只平不开**（同周期）：BUY+持空 → 只平空；SHORT+持多 → 只平多。避免同周期滑点双向损耗；下一周期信号若仍反向则开仓。
- 开空前过一遍现有"实盘闸门"（`check_live_trading_preconditions`）与 P1 风险反查。
- 平仓方向 posSide：平空 = posSide="short", side="buy"（`_resolve_pos_side` 已支持，one-way 模式 posSide="net" 自动兼容）。

### 3.4 止损/移动止损

- `StopLossManager` 已支持空头（`stop_side = buy`），`calculate_stop_price_unified` 统一入口；本阶段仅补测试覆盖 + 验证 trailing 参数对空头方向正确（止损只向盈利方向移动）。

### 3.5 Paper 验证门槛

`ENABLE_SHORT_TRADING=true` + TEST_MODE（沙盒）运行 ≥ 1 周，DecisionJournal 满足：
- 空头信号 T+4h 胜率 ≥ 50%（样本 ≥ 20），且无单笔亏损 > 10% 账户的沙盒记录 → 才允许实盘开启。

### 3.6 测试

- `_execute_signal` 全矩阵 4×4（信号 × 持仓状态）：开空/平空/反向先平/止损方向。
- `AdaptiveSellCondition` 四 mode 条件覆盖 + 边界（RSI 阈值、量能倍数）。
- 翻转守卫对称用例（HOLD≥55% 不翻 SELL；BUY 不翻 SELL；回归：BUY 不翻 SELL 不影响现有 hold→buy）。
- `ENABLE_SHORT_TRADING=false` 回归：short 降级 hold，全链路零行为变化。
- 仓位风险反查：ATR 距离 → 仓位缩减 → 最小 1 手以下放弃。

---

## P4 LLM 层提频（P1 数据到位后逐项进行）

1. **prompt 去保守化（主杠杆）**：
   - 现状证据：575/575 hold；55–65% 置信度正好压在 55% 翻转守卫线上——prompt 默认倾向观望。
   - 改法：不对称指令（"满足明确条件时给出 60–75% 置信度；仅在真正无 edge 时 hold"）+ 多空对称章节（与 P2 的 Jev criteria 同口径）。
   - 验证：改前改后各 ≥ 1 周，DecisionJournal 对比 T+4h 胜率与频率。
2. **fusion 投票（可选）**：prompt 仍不够 → `AI_MODE=fusion`（deepseek+kimi+qwen38，现有权重机制），2/3 同向且无强否决才采用。
3. **503 兜底链**：主 provider 最终失败 → 依序尝试 `AI_FALLBACK_PROVIDERS`（默认 `qwen38,deepseek`）→ 全失败 → 本周期降级 hold + WARNING（不再异常中止整周期，修复 9/28 42 周期作废问题）。
4. **阈值调优（最后一次进行，一次一个参数）**：
   - 翻转守卫 55%、R/R 最低 1.0、高位买入惩罚——每项调整前用 DecisionJournal 的"被拦截样本 T+4h 表现"论证，调整后重审 9/13 亏损案例（守卫的由来）不复现。

## 可观测性（全周期）

- 日志前缀：`[决策日志]` `[风控总闸]` `[做空开关]` `[Jev观察]`
- `AIClient.get_metrics()` / bot metrics 增加：`decision_journal_entries`、`drawdown_halt_open`、`short_positions_count`、`short_pnl`
- 周报输入：`scripts/decision_journal_report.py` 输出（Jev/LLM/本地层分层胜率表 + 守卫拦截复盘）。

## Rollout 与回退

| 顺序 | 阶段 | 上线条件 | 回退方式 |
|---|---|---|---|
| 1 | P1（度量+风控） | 无（零行为变化），先跑 1 周积累基线 | `DECISION_JOURNAL=false` |
| 2 | P2（Jev 增强） | P1 有 1 周基线；先 shadow 2 周 | `AI_FAST_LANE=shadow/off` |
| 3 | P3（做空） | P2 完成；沙盒 paper ≥ 1 周达标 | `ENABLE_SHORT_TRADING=false`（= 纯做多现状） |
| 4 | P4（LLM 提频） | P1 数据 ≥ 2 周；一次一个参数 | 参数逐项回滚 / `AI_MODE` 切回 |

**前置（用户外部动作）**：入金 ≥ $280（最小 1 手）；建议 ≥ $830（0.03 手）以便双向仓位有意义。

## 关键决策与理由

1. **反向信号"先平后开"而非同周期反手**：单标的单仓位 + 15 分钟周期，同周期反手 = 市价平+市价开两段滑点且情绪化信号未冷却；分周期执行更稳。
2. **30% 停机只手动恢复**：自动恢复会让"策略已失效"的状态继续交易。
3. **P1 必须先于 P2–P4**：8 天数据已证明"无结果数据时调参是猜"；P1 让后续每次调参都有 T+4h/T+24h 胜率背书。
4. **Jev 阈值不先降**：47 次低置信 buy 无结果背书；DecisionJournal 达标（胜率≥55% 且 n≥30）才降 0.75→0.65。
5. **复用 OrderService/StopLossManager/posMode 检测**：开空管道已存在，P3 风险集中在信号与执行分支，工作量与回归面可控。
6. **翻转守卫做对称镜像而不是放宽**：9/13 亏损教训对空头同样成立（AI 明确 HOLD 时技术规则反向开空 = 重蹈覆辙）。

## 测试总览（TDD，mock 外部依赖）

- P1：journal 写入/轮转/回填（含跨周期重启恢复）；DrawdownBoundary 状态机（触发/持续/手动恢复）；风险反查仓位公式（正常/缩减/放弃三路径）。
- P2：build_state 特征与缺键容错；问题结构回归；新 Noul 解析与缺失兜底；jev_context 内容；观察日志输出。
- P3：执行矩阵 4×4；AdaptiveSellCondition 四 mode；翻转守卫对称 + 现有回归；开关 off 全链路回归；沙盒开空/平空端到端（mock 交易所）。
- P4：prompt 快照测试；fallback 链（主失败→兜底成功/全失败降级）；fusion 投票逻辑。
