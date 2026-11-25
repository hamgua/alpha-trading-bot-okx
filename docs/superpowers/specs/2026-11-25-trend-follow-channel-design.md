# 趋势跟踪交易机会优化 — 设计文档

日期: 2026-11-25
状态: 已与用户确认（含模块 0 回放数据）

## 意图与背景

**问题**: 2026-11-24 08:00 → 11-25 06:00 BTC 从 64,570 阴跌至 58,707（-9.1%，锯齿式下跌）。
bot 全程空仓观望（AI 88 连 HOLD），甚至在 11-24 13:43 逆势开多 60,685（-0.45% 离场）。
用户诉求：在这种价格波动中增加更多合理交易机会，**收益优先**。

**根因**（日志 + 代码分析）:
1. 信号层没有趋势中段入口：AI 单模型（qwen38）保守输出 HOLD；
   integrator 的 HOLD→SHORT 技术翻转要求 `持续下跌确认`，而持续下跌检测器
   要求"1h 连续 3 根阴线或 60% K 线收阴"，锯齿下跌永远不满足（11/25 全天
   `is_sustained=False`，`下跌周期=0/99`）。
2. 市场结构分析器只看 1h 支撑/阻力，阴跌中仍判 `结构=bullish, direction=long`，
   导致 13:43 逆势开多。
3. 出场为固定止盈，趋势单吃不到 3R 以上。
4. 已有两个独立通道（超卖抄底 / 高潮做空）只抓底部/顶部，中段趋势是空白。

## 模块 0 回放验证（真实 OKX 数据 10-15 → 11-25）

原候选触发器（24h 低点破位 + ER≥0.4 + RSI 25-55 + HTF 过滤）在目标场景
**一次都不触发**：锯齿下跌 ER(24h) 仅 0.1-0.3，HTF 全程 bullish/sideways，
唯一破位 K 线（11-25 15:00）RSI 已 21.7。ER 指标对锯齿趋势无效，**放弃 ER 路线**。

最终采用触发器（变体 E，12 天回放 11-13 → 11-25，完整 15m 出场路径）：
- **触发**: 生产 `calculate_trend` 方向（SMA10/SMA20 1h）+ 24h 涨跌幅 ≤ -2%（空）
  / ≥ +2%（多）+ RSI(1h) 排除（RSI<20 禁空 / RSI>80 禁多）
- **入场**: 触发 1h 收盘后下一根 15m K 线开盘（ts ≥ 1h bar ts + 1h，无 lookahead）
- **止损**: 24h 摆动点 ∓ 0.5×ATR(1h)，距离上限 2.5%
- **出场**: +1R 保本；+2R 起 3.0×ATR(1h) 追踪（只收紧；多头 = 极值高 − k×ATR，
  空头 = 极值低 + k×ATR）；10R 安全止盈
- **约束**: 每方向每日 1 次，30min 平仓冷却，共享 daily_open_limit，回撤总闸

> **修正记录 (2026-11-25 模块 0 产品化时)**: 初版 /tmp 回放脚本有两处 bug，
> 已修入 `alpha_trading_bot/utils/trend_replay.py`：(1) 空头追踪止损方向写反
> （extreme − k×ATR 落在现价下方，模拟中产生不可能成交的有利虚拟单，虚增收益）；
> (2) ATR 预热门槛 28 根误伤数据窗口头部触发（生产始终 100 根 1h，改为
> calculate_atr 自身最小要求 15 根）。入场口径同步修正为无 lookahead。
> 以下为修正后的诚实基线（原始 /tmp 基线 +10.34R 含虚拟成交，作废）。

**回放结果（修正后基线）**: 7 笔，总 +6.34R，胜率 4/7，最差 -1.0R。关键命中：
| 时间 | 方向 | 入场 | 出场 | PnL |
|---|---|---|---|---|
| 11-14 05:00 | 空 | 68,888 | 63,563 (11-15 10:00, 追踪) | +3.09R |
| 11-16 21:00 | 空 | 64,143 | 59,304 (11-21 05:30, 追踪) | +3.02R |
| 11-21 06:00 | 空 | 58,982 | 58,209 (11-21 15:00, 追踪) | +0.52R |
| 11-22 03:00 | 多 | 60,132 | 61,115 (11-23 21:45, 追踪) | +0.65R |
| **11-24 17:00** | **空** | **60,223** | **@11-25 15:45 仍持仓 +1.06R（保本已生效）** | 进行中 |
| 11-15 16:00 / 11-23 23:00 | 空/多 | 63,977 / 62,869 | 止损离场 | 各 -1.00R |

对照组：2% 门槛（E）> 3% 门槛（F，+7.69R，入场更晚更差）；
TP 3R→10R 结果不变（大单由追踪止损离场），trail 3.0ATR 略优于 2.5/2.0。

## 目标 / 非目标 / 反目标

- 目标: 锯齿单边趋势中出现趋势跟踪开仓（多空对称），趋势利润由追踪止损兑现；
  抑制 15m 结构分析在 HTF 逆向时的 direction 建议；AI prompt 增加 HTF 趋势上下文。
- 非目标: 不放宽 P0 平仓门禁 / 回撤总闸 / 每日亏损上限 / 冷却；
  不修改超卖抄底、高潮做空通道；不引入新数据源（只用现有 OKX 1h/15m/4h 聚合）。
- 反目标: 不做无脑高频化（回放证明 2% 门槛 + 每日 1 次已够捕获趋势段）；
  不做 ER 指标改造（数据证伪）。

## 方案对比（模块 0 数据裁决）

| 方案 | 12 天结果 | 裁决 |
|---|---|---|
| G: 24h 破位 + ER≥0.4 + RSI 区间 + HTF | 1 笔 +1.91R，错过目标场景 | 否决 |
| E: SMA 趋势方向 + 24h 2% + RSI 排除 | 7 笔 +6.34R（修正后），命中目标场景 | **采用** |
| F: 同 E 但 24h 3% | 7 笔 +7.69R | 否决（入场更晚） |

## 设计细节（实现契约）

### 1. 趋势跟踪独立通道（`core/bot.py`）

`_maybe_trend_follow(market_data, current_price) -> Optional[ExecutionResult]`，
照抄高潮做空通道骨架，挂在 5.6 高潮通道之后的 5.8 hook（同样守卫：
`not has_position and signal not in (BUY/SHORT) and execution_result.action
in (none, blocked_*)`）。

- 做空条件: `trend_direction=="down"` 且 `change_percent <= -trend_follow_change_pct`
  且 `rsi >= trend_follow_short_rsi_floor`（默认 20）
- 做多条件: `trend_direction=="up"` 且 `change_percent >= +change_pct` 且
  `rsi <= trend_follow_long_rsi_ceil`（默认 80）
- 止损价: 空 = min(24h 最高, entry×1.025) + … 准确式:
  `stop_short = min(max(high_24h) + 0.5×ATR, entry×(1+max_stop_pct))`；
  `stop_long = max(min(low_24h) - 0.5×ATR, entry×(1-max_stop_pct))`；
  max_stop_pct=0.025。24h 摆动高低取 `market_data["high_history"]/["low_history"]`
  最近 24 根 1h（Task 2 新增字段）。
- TP: `entry ∓ 10×R`（安全网，正常由追踪止损离场）
- 仓位: `size_factor=0.5`；复用 `allow_short_selling`（空侧）、daily_open_limit、
  post_close_cooldown、drawdown halted 门禁；独立每日计数 `trend_follow_daily_limit=1`。
- 日志: `[趋势跟踪] 触发/跳过(原因)`, `[趋势跟踪] 开仓成功 ...`（与既有机会审计风格一致）。

### 2. market_data 暴露 1h 高低点（`exchange/market_data.py`）

`get_market_data()` 返回新增 `high_history` / `low_history`（1h，oldest-first，
与 `price_history` 对齐同长度）。

### 3. 追踪止盈（`core/position_manager.py` + `core/stop_loss_manager.py`）

- `Position` / `PositionState` 新增 `initial_stop_price: float = 0.0`
  （开仓时写入一次，重启可恢复；旧 JSON 无此字段 → 0 → 追踪功能静默降级，
  不影响旧行为）。
- `PositionManager.calculate_trailing_stop(current_price, atr_percent) -> Optional[float]`:
  - R = |entry − initial_stop|；R≤0 或 initial_stop≤0 → None（降级）
  - 多头: 浮盈 ≥ 1R → 候选 = entry×(1+0.001)；浮盈 ≥ 2R → 候选 = max(候选,
    highest_since_entry − 3.0×ATR)；最终 = max(候选, 0)（只收紧）
  - 空头镜像（min）。
- `StopLossManager.update_stop_loss` 合并: `effective = max(unified, trailing)`（多）
  / `min`（空）；trailing 更紧时强制更新（绕过 tolerance 防滞后），
  并经 `AdaptiveStopLossManager._calc_safe_stop_price` 钳位（OKX 51280/51278）。
- 极值追踪复用既有 `update_price_tracking`（已持久化）。
- 配置: `trailing_stop_enabled=true`, `trailing_breakeven_at_r=1.0`,
  `trailing_activate_at_r=2.0`, `trailing_atr_mult=3.0`。

### 4. 结构方向 HTF 门槛 + prompt 上下文（`ai/market_structure.py` + prompt 构建器）

- `analyze()` 新增可选参 `change_percent: float = 0.0`；
  direction=long 必须 htf != "bearish" 且 change_percent > -3；
  direction=short 必须 htf != "bullish" 且 change_percent < +3。
- AI prompt 增一行趋势上下文: `4h结构={htf}, 24h涨跌={change}%,
  24h区间位置={position_pct}%`（数据均已在 market_data）。
- 修复目标: 11-24 13:43 型"阴跌中 direction=long"不再出现。

## 风险红线（不动）

P0-1 亏损态平仓门禁、回撤总闸、每日亏损上限、平仓冷却、最小 0.01 张、
OKX 止损价方向规则、单仓位约束、TEST_MODE 闸门。

## 验证策略

1. 每 Task: TDD 单测（pytest，mock 交易所）+ `black/mypy/flake8`。
2. 回放: `scripts/replay_trend_channel.py`（纯函数核心 + CLI），
   实盘数据回放打印交易表，作为每次上线前回归基线。
3. 上线: TEST_MODE 影子跑 ≥24h，对比日志与回放预期。
