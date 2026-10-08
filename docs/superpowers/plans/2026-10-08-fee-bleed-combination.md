# 计划：执行层置信度门禁 + 平仓冷却 + 标准 bot 止盈单（手续费出血修复）

**日期**: 2026-10-08
**分支**: `fix/execution-gates-tp`
**背景**: d53f53a（ctVal 单位修正）后 bot 首次真实交易，4 天 8 个完整往返
净亏 $0.1346（账户 1.84%）。对账（交易所真实成交 + 手续费 + 余额变动，
精确到 5 位小数）：

| 项 | 金额 | 占比 |
|---|---|---|
| 信号毛利（8 笔，3 胜 5 负） | +$0.0005 | ≈0 |
| taker 手续费（0.05%/边，16 腿） | -$0.1351 | 84% |
| 滑点（决策价→成交价） | -$0.0211 | 16% |
| **净亏损** | **-$0.1346** | 100% |

即：**信号毛利 ≈ 0，亏损 100% 来自"低置信度信号驱动的市价开平仓往返
成本"（每往返 ≈ 11.5bp，而信号毛利仅 ≈1.6bp/笔，成本 = 毛利 7 倍）**。

## 关键事实（已核实）

1. 8/8 的 BUY 开仓信号 LLM 原始信号均为 `hold`（置信度 45-53%），由
   `adaptive_buy_condition` 技术条件强制翻转，最终置信度 51-79%
   （3 笔恰好 51%，1 笔 79%）。
2. 8/8 的 SELL 平仓信号最终置信度 54-67%，**全部低于 0.75**。
   `.env` 的 `JEV_CONF_SELL=0.75` 只约束 Jev 快车道（且
   `AI_FAST_LANE=off`），对 LLM 信号与执行层完全无约束
   （`bot.py::_execute_signal` 无任何置信度门禁）。
3. `BOT_MODE=standard` 的开仓流程**从不下止盈单**
   （`create_take_profit` 仅 `adaptive_bot.py` 调用）；`.env` 的
   `TAKE_PROFIT_PERCENT=0.06`（12R）对 standard 是死配置。全部 8 笔
   平仓均由 AI SELL 信号触发，浮盈被提前砍掉（T6 峰值 +0.0343 →
   实际 +0.0117）。
4. 0.5% 止损（`STOP_LOSS_PERCENT=0.005`）4 天 0 触发，仅尾部保护。
5. 平仓后 5 分钟即重开（T3→T4）；T7 持仓仅 4.4 分钟——高频 churn。
6. `PositionManager` 已有 `take_profit_order_id` 追踪 + 持久化 +
   `set_take_profit_order`（adaptive 使用）；`client.create_take_profit`
   已带 TEST_MODE 模拟支持；`client.calculate_notional_usdt` 可用。
7. `state_persistence.TradingState.last_trade_time` 在**每次**
   `save_position` 都刷新（开仓也刷新），不能用作平仓时间戳 →
   需新增 `last_close_at` 字段。

## 修正后行为（验收基准，回放 10-06→10-08 样本，默认配置
`MIN_CONFIDENCE_OPEN=0.75` / `MIN_CONFIDENCE_CLOSE=0.75` /
`POST_CLOSE_COOLDOWN_MINUTES=30` / `TAKE_PROFIT_RR_MULTIPLE=2.0`）

- 8 笔开仓仅 T8（79%）通过置信度门禁 → 1 笔开仓
- 8 笔 SELL（≤67%）全部被拦 → 0 笔信号平仓；仓位由 0.5% 止损 +
  2R 止盈单（交易所侧）兜底
- T3→T4（间隔 5 分钟）被 30 分钟平仓冷却拦截
- T8（入场 83153）挂 2R 止盈单：83153×(1+0.005×2)=83984.5
- 最坏费用暴露：1 个往返 ≈ $0.017（现值 $0.135 的 1/8）
- 向后兼容：`_execute_signal` 3 参旧调用（置信度 None）门禁不生效
  且 WARNING 日志提示；`TAKE_PROFIT_RR_MULTIPLE=0` / 冷却 0 / 门禁 0
  均关闭对应行为

## 任务

### Task 1 — 执行层置信度门禁（P0-1）

**文件**: `alpha_trading_bot/config/models.py`,
`alpha_trading_bot/core/bot.py`, `alpha_trading_bot/ai/client.py`,
`tests/unit/test_execution_confidence_gate.py`（新增）

1. `TradingConfig` 新增（`from_env` 同步读取环境变量）：
   - `min_confidence_open: float = 0.75`（env `MIN_CONFIDENCE_OPEN`，
     0=关闭 BUY 门禁）
   - `min_confidence_close: float = 0.75`（env `MIN_CONFIDENCE_CLOSE`，
     0=关闭 SELL 门禁）
   - 校验：0 ≤ x ≤ 1
2. `TradingBot._execute_signal` 签名扩展
   `final_confidence: Optional[float] = None`；BUY+无持仓 / SELL+有持仓
   分支入口处比较置信度：
   - 低于门禁 → `ExecutionResult("blocked_low_confidence", ...)`，
     INFO 日志（含置信度/门禁值/动作），**不下单、不清仓**
     （SELL 被拦时持仓继续由止损单保护）
   - `final_confidence is None`（旧调用路径）→ 门禁不生效 + WARNING
     日志（保证既有 3 参测试零回归）
   - 0（关闭）→ 不比较
3. 调用点 `_execute_trading_cycle`：`get_signal` 后从
   `market_data["final_confidence"]` 取值（float 解析失败→None）传入。
4. `SignalCache.get_with_confidence`：返回 `(signal, confidence)`；
   `AIClient.get_signal` 缓存命中分支补齐
   `market_data["final_confidence"]` + trace 的 `integrator` 段
   （含 cache_hit 标记），保证缓存路径门禁同样拿到置信度。

### Task 2 — 平仓后冷却（P0-2）

**文件**: `alpha_trading_bot/config/models.py`,
`alpha_trading_bot/core/state_persistence.py`,
`alpha_trading_bot/core/position_manager.py`,
`alpha_trading_bot/core/bot.py`,
`tests/unit/test_post_close_cooldown.py`（新增）

1. `TradingConfig.post_close_cooldown_minutes: int = 30`
   （env `POST_CLOSE_COOLDOWN_MINUTES`，0=关闭；校验 ≥0 且 ≤1440）
2. `TradingState.last_close_at: str = ""`（ISO）；`load_state`/
   `_save_state`/备份 dict 同步；新增
   `StatePersistence.mark_last_close()`（刷新并持久化）。
3. `PositionManager`：内存 `_last_close_at`（`_restore_from_persistence`
   恢复）+ `last_close_at` property + `mark_last_close()` +
   `is_in_post_close_cooldown(minutes)`（解析失败→False，fail-open）。
4. bot 落点（两条平仓路径都盖章）：
   - `_close_position` 成功（`clear_position()` 之后）
   - 周期对账分支：本地有持仓但 API 无持仓（止损/止盈在交易所侧触发）
     → `mark_last_close()` 后 `update_from_exchange({})`
   - BUY 分支门禁（置信度门禁之后、开仓之前）：冷却期内 →
     `ExecutionResult("blocked_cooldown", ...)`，不下单

### Task 3 — 标准 bot 1–2R 止盈单（P1-3）

**文件**: `alpha_trading_bot/config/models.py`,
`alpha_trading_bot/core/bot.py`,
`tests/unit/test_standard_bot_take_profit.py`（新增）

1. `StopLossConfig.take_profit_rr_multiple: float = 2.0`
   （env `TAKE_PROFIT_RR_MULTIPLE`，0=关闭止盈单；TP 距离 =
   止损距离 × max(本值, take_profit_min_rr_ratio)，默认 = 2R = 1.0%）
2. `_open_position`：止损单创建成功后计算
   `tp_price = entry × (1 + tp_dist)` 并
   `create_take_profit(symbol, side="sell", amount, tp_price)`：
   - 成功 → `position_manager.set_take_profit_order(id, price)` + INFO
   - 失败/异常 → WARNING「止盈单创建失败，仓位由止损单兜底」，
     **不回滚仓位**（止损单已存在，安全不变式保持）
   - 名义 < `take_profit_min_notional`（默认 0=不拦）→ 跳过 + INFO；
     名义计算异常 → fail-open（照挂）
3. `_close_position`：取消旧止损单后同样取消旧止盈单（同一
   `cancel_algo_order`，复用 same-block 日志结构）。
4. 启动恢复 `_check_stop_order_recovery`：有持仓且本地无止盈单 ID →
   按入场价重建 2R 止盈单（与止损重建对称；持久化已恢复
   `take_profit_order_id` 时跳过）。
5. 不变式：止盈失败不得导致裸仓；止盈单与止损单数量截断值同源
   （同一 `amount`）。

## 验证

- 每任务：新增单测先红后绿；`pytest` 全量零回归（基线 1105 passed /
  26 skipped）；`mypy alpha_trading_bot/` 零新增错误；改动文件
  `black` clean；`pre-commit run --all-files` 通过
- 上线建议（部署后）：服务器观察首个交易周期日志确认门禁/冷却/止盈
  日志出现；回放口径与本报告一致
