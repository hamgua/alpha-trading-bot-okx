# 趋势跟踪交易机会优化 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 bot 在锯齿单边趋势中通过独立的趋势跟踪通道开仓（多空对称、半仓、ATR 止损、追踪止盈），并用 HTF 门槛抑制逆势方向建议；12 天回放基线 +6.34R（7 笔，胜率 4/7，修正后诚实基线见 spec 模块 0 修正记录）。

**Architecture:** 在既有"AI 路径 + 独立通道"架构上再加一个独立通道（与超卖抄底/高潮做空同模式，挂 5.8 hook），触发器只用生产已计算的 `technical.trend_direction`（SMA10/20 1h）+ 24h 涨跌幅 + RSI 排除；出场侧给 `PositionManager` 加 R 基准的追踪止损（1R 保本、2R 起 3×ATR 追踪、只收紧），并入既有 `update_stop_loss` 更新路径；`market_data` 补 1h 高低点数组供摆动止损计算；`market_structure` 的 direction 建议加 4h/24h 一致性门槛，AI prompt 加一行趋势上下文。回放脚本产品化作为回归基线。

**Tech Stack:** Python 3.8+ / asyncio / pytest / 现有 OKX 客户端（公共 K 线 API）

**Spec:** `docs/superpowers/specs/2026-11-25-trend-follow-channel-design.md`（回放数据与阈值裁决以该文档"模块 0"节为准）

## Global Constraints

- Python 3.8+，mypy strict（不写 `# type: ignore`），black line-length=88，flake8（E203,W503 忽略），isort profile black
- 业务逻辑注释用中文；日志用 `logger = logging.getLogger(__name__)` 模块级
- 配置一律走 `config/models.py` 的 `TradingConfig` dataclass + `validate()` 校验，支持 env 覆盖（照 `min_confidence_open` 的 `os.getenv` 模式）
- 不修改：P0-1 亏损态平仓门禁、回撤总闸、`post_close_cooldown_minutes`、`daily_open_limit` 语义、OKX 止损价方向规则（51280/51278）、最小 0.01 张、单仓位约束
- 所有新开关默认值 = 回放验证值：`trend_follow_change_pct=2.0`, `trend_follow_short_rsi_floor=20.0`, `trend_follow_long_rsi_ceil=80.0`, `trend_follow_stop_atr_buffer=0.5`, `trend_follow_max_stop_pct=0.025`, `trend_follow_safety_tp_r=10.0`, `trend_follow_daily_limit=1`, `trend_follow_position_factor=0.5`, `trailing_stop_enabled=True`, `trailing_breakeven_at_r=1.0`, `trailing_activate_at_r=2.0`, `trailing_atr_mult=3.0`
- 提交前必须: `pytest` 全绿 + `black --check` + `mypy alpha_trading_bot/` 干净

## Review Focus

1. **OKX 止损价方向规则**: 空头追踪止损必须始终 > 当前价（buy 触发），多头 < 当前价；候选落在错误一侧时必须经 `AdaptiveStopLossManager._calc_safe_stop_price` 钳位后再下单，否则订单被拒 → 裸仓。→ Task 4 测试 `test_trailing_stop_wrong_side_clamped`。
2. **重启降级**: 旧版 JSON（无 `initial_stop_price`）恢复持仓后追踪功能必须静默跳过（返回 None / 保持旧止损行为），不得崩溃或把止损推到 0。→ Task 4 测试 `test_trailing_degrades_without_initial_stop`。
3. **1h 未收盘 K 线**: `market_data` 含进行中的 1h K 线，触发条件可能在 1h 内反复横跳；本设计接受"触发即入场、止损兜底"（回放即此口径），禁止在实现中偷偷改成"仅用已收盘 K 线"。→ 触发口径由 Task 1/Task 6 Step 2 的回放基线回归裁决，口径改动必须重跑基线。
4. **每日上限共享**: 趋势通道与 AI 路径/超卖/高潮共享 `_daily_open_counts`；同一日 AI 已开仓 `daily_open_limit` 次后，趋势通道必须被拦。→ Task 3 测试 `test_trend_follow_blocked_by_shared_daily_limit`。
5. **tolerance 滞后**: `update_stop_loss` 的 `stop_loss_tolerance_percent` 容错会吞掉小幅止损移动；追踪止损更紧时必须强制更新（force_update），否则保本/追踪滞后于行情。→ Task 4 测试 `test_trailing_forces_update_within_tolerance`。

---

### Task 1: 回放脚本产品化（回归基线工具）

把 /tmp/replay/sim_final.py 的变体 E 逻辑产品化为可测试的纯函数 + CLI。这是后续每个 Task 的回归基线（上线前重跑）。

**Files:**
- Create: `alpha_trading_bot/utils/trend_replay.py`
- Create: `scripts/replay_trend_channel.py`
- Test: `tests/unit/test_trend_replay.py`

**Interfaces:**
- Consumes: 无（独立模块；指标用 `alpha_trading_bot.utils.technical.calculate_trend/calculate_rsi/calculate_atr`）
- Produces:
  - `@dataclass ReplayConfig`（字段与 Global Constraints 的默认值一一对应，另含 `be_at_r: float = 1.0`, `trail_at_r: float = 2.0`, `trail_atr_mult: float = 3.0`, `safety_tp_r: float = 10.0`, `daily_limit: int = 1`, `cooldown_minutes: int = 30`, `change_pct: float = 2.0`, `short_rsi_floor: float = 20.0`, `long_rsi_ceil: float = 80.0`, `stop_atr_buffer: float = 0.5`, `max_stop_pct: float = 0.025`）
  - `Candle = Dict[str, float]`（键: ts, o, h, l, c）
  - `trigger_at(closes: List[float], highs: List[float], lows: List[float], t: int, cfg: ReplayConfig) -> Optional[str]`（返回 "short"/"long"/None，t 为 0-based 最旧起）
  - `simulate_trades(h1: List[Candle], m15: List[Candle], cfg: ReplayConfig) -> List[Dict[str, Any]]`（每笔: side, entry_ts, entry, risk, exit_ts, exit, reason, pnl_r）
  - CLI: `python scripts/replay_trend_channel.py --inst BTC-USDT-SWAP --days 14 [--data-dir DIR] [--fetch]`（无 --fetch 时用 data-dir 下 okx_1H.json/okx_15m_full.json，格式 = OKX 原始 JSON 行数组）

- [ ] **Step 1: 写失败测试** `tests/unit/test_trend_replay.py`

```python
def test_trigger_short_on_sawtooth_decline():
    # 构造 60 根 1h: 前 30 根 62000 平盘, 后 30 根锯齿跌到 59000
    # (每小时 -100 ~ +60 交替), 24h 变 < -2%, RSI(1h) 保持 >= 20
    # assert trigger_at(..., t=59, ReplayConfig()) == "short"

def test_trigger_long_on_sawtooth_rally():
    # 镜像构造上涨; assert == "long"

def test_no_trigger_in_chop():
    # 60 根 1h 围绕 60000 ±0.5% 震荡, 24h 变 |x| < 2%
    # assert trigger_at(...) is None

def test_rsi_exclusion_blocks_short():
    # 下跌构造 + 末段连续暴跌使 RSI(1h) < 20
    # assert trigger_at(...) is None

def test_simulate_captures_decline_with_trail():
    # h1/m15 用同一锯齿数据派生 (m15 = h1 每根拆 4 根)
    # trades = simulate_trades(h1, m15, ReplayConfig())
    # assert len(trades) >= 1 and trades[0]["side"] == "short" and trades[0]["pnl_r"] > 0
```

（构造数据的具体数值以实现者能写出**恰好触发/恰好不触发**的最小序列为准；
RSI 边界用例以 `calculate_rsi` 实际输出校准。）

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_trend_replay.py -v`
Expected: FAIL（ModuleNotFoundError: alpha_trading_bot.utils.trend_replay）

- [ ] **Step 3: 实现 `alpha_trading_bot/utils/trend_replay.py`**

从 /tmp/replay/sim_final.py 移植变体 E 逻辑为纯函数（`trigger_at` = 其中
`trigger_at(t, "E")` 去掉模块级状态；`simulate_trades` = `run()` 的循环体 +
`simulate_trade`，参数全部经 cfg 传入；RSI 用 `calculate_rsi(closes[:t+1], 14)`，
趋势方向用 `calculate_trend(closes[:t+1])["direction"]`，ATR 用
`calculate_atr(...)`；每日上限/冷却/单仓位语义与 bot 一致：
key=(日期, side)，冷却比较 exit_ts 与 entry_ts）。中文注释说明回放口径
（1h 含未收盘 K 线、入场 = 触发 1h 后的下一根 15m 开盘）。

- [ ] **Step 4: 实现 `scripts/replay_trend_channel.py`**

argparse CLI：`--fetch` 时用 subprocess+curl 拉
`/api/v5/market/candles?bar=1H&limit=300` 与 `/api/v5/market/history-candles`
分页 15m（每页 100，翻页 `after`，间隔 0.2s，直到覆盖 `--days` 天），存
`--data-dir`（默认 `scripts/.replay_data/`，加入 .gitignore）；
然后调 `simulate_trades` 打印交易表 + 汇总（格式同 /tmp/replay 输出）。
脚本头部注释注明：仅供回放/回归，不参与实盘。

- [ ] **Step 5: 跑测试 + lint**

Run: `pytest tests/unit/test_trend_replay.py -v && black --check alpha_trading_bot/utils/trend_replay.py scripts/replay_trend_channel.py tests/unit/test_trend_replay.py && mypy alpha_trading_bot/utils/trend_replay.py`
Expected: PASS

- [ ] **Step 6: 实盘数据冒烟**

Run: `python scripts/replay_trend_channel.py --fetch --days 14`
Expected: 打印交易表（数据窗口 11-13 04:00 起时与 spec 模块 0 修正后基线一致：
7 笔 +6.34R，首笔 11-14 05:00 空 @68,888，末笔 11-24 17:00 空 @60,223 open@eod +1.06R；
窗口不同会有出入，量级必须一致；差异 >50% 时停止并报告）

- [ ] **Step 7: Commit**

```bash
git add alpha_trading_bot/utils/trend_replay.py scripts/replay_trend_channel.py tests/unit/test_trend_replay.py
git commit -m "feat(replay): 趋势跟踪通道回放工具 (模块0 基线, 变体E 参数)"
```

---

### Task 2: market_data 暴露 1h 高低点

**Files:**
- Modify: `alpha_trading_bot/exchange/market_data.py`（`get_market_data()` 返回 dict，约 :180-195）
- Test: `tests/unit/test_market_data.py`（若无则新建）

**Interfaces:**
- Consumes: `get_ohlcv(limit=100)`（既有，1h，oldest-first）
- Produces: `market_data["high_history"]: List[float]`、`market_data["low_history"]: List[float]` —— 1h 高低点，oldest-first，与 `price_history` 逐根对齐、同长度；OHLCV 获取失败时为空列表（不抛异常，不影响主流程）

- [ ] **Step 1: 写失败测试**

```python
async def test_market_data_includes_1h_high_low_history():
    # mock get_ohlcv 返回固定 OHLCV (100 根, ts 递增)
    # md = await market_data.get_market_data()
    # assert len(md["high_history"]) == len(md["price_history"])
    # assert md["high_history"][0] == ohlcv[0][2] and md["low_history"][-1] == ohlcv[-1][3]

def test_market_data_graceful_on_ohlcv_failure():
    # mock get_ohlcv 抛异常 -> high_history/low_history == []，price 仍来自 ticker
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_market_data.py -v`
Expected: FAIL（KeyError: 'high_history' 或文件不存在）

- [ ] **Step 3: 实现** — `get_market_data()` 中在 `closes/highs/lows` 已计算处
把 `highs`/`lows` 加进返回 dict（键 `high_history`/`low_history`）；OHLCV 为空时
两字段为 `[]`（closes 空时 highs/lows 本就为空，天然满足）。
中文注释: "趋势跟踪通道 24h 摆动止损用 (2026-11-25)"。

- [ ] **Step 4: 跑测试 + lint + 全量**

Run: `pytest tests/unit/test_market_data.py -v && black --check alpha_trading_bot/exchange/market_data.py && pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add alpha_trading_bot/exchange/market_data.py tests/unit/test_market_data.py
git commit -m "feat(market_data): 暴露 1h high_history/low_history (趋势通道摆动止损用)"
```

---

### Task 3: 趋势跟踪独立通道（核心）

**Files:**
- Modify: `alpha_trading_bot/config/models.py`（`TradingConfig`，约 :185-190 climax_short_* 附近新增字段；`validate()` 约 :311-335 同区域加校验；env 加载约 :779 附近同模式）
- Modify: `alpha_trading_bot/core/bot.py`（新增 `_maybe_trend_follow` 方法，照 `_maybe_climax_short` :1080-1220 的结构；5.6 高潮通道调用块 :455-475 之后新增 5.8 调用）
- Test: `tests/unit/test_trend_follow_channel.py`

**Interfaces:**
- Consumes: `market_data["technical"]["trend_direction"/"rsi"/"atr_percent"]`、`market_data["change_percent"]`、`market_data["high_history"/"low_history"]`（Task 2）、`self._open_position(price, size_factor, side, atr_percent, stop_price_override, tp_price_override)`（:1323）、门禁读取 `self._drawdown_status`/`self.position_manager.is_in_post_close_cooldown(min)`/`self._daily_open_counts`/`self.config.trading.*`
- Produces: `async _maybe_trend_follow(self, market_data: Dict[str, Any], current_price: float) -> Optional[ExecutionResult]`；成功时 `ExecutionResult("open_trend_follow", ...)` 并累加 `_trend_follow_counts[today]` 与 `_daily_open_counts[today]`；配置字段 `trend_follow_enabled: bool = True` + 上述 8 个参数（默认值见 Global Constraints）

**触发与门禁顺序**（与回放口径一致，短路返回 None 并打 `[趋势跟踪] 跳过(原因)`）:
1. `trend_follow_enabled` 且 `current_price > 0`
2. 无持仓（调用点已守卫，方法内再 assert 一次防御）
3. 空侧: `allow_short_selling`；`trend_direction == "down"` 且 `change_percent <= -change_pct` 且 `rsi >= short_rsi_floor`
   多侧: `trend_direction == "up"` 且 `change_percent >= +change_pct` 且 `rsi <= long_rsi_ceil`
4. `high_history/low_history` 长度 ≥ 24（否则跳过）
5. 回撤总闸 `halted` / 平仓冷却 / 共享 `daily_open_limit` / 本通道 `_trend_follow_counts[today] >= trend_follow_daily_limit`
6. 止损价: 空 `stop = min(max(high_history[-24:]) + stop_atr_buffer*atr_abs, entry*(1+max_stop_pct))`（atr_abs = atr_percent*entry, atr_percent 为 0~1 比率；stop<=entry 时取 entry*(1+max_stop_pct)）；多镜像
7. `tp = entry - safety_tp_r*(stop-entry)`（空）/ `entry + safety_tp_r*(entry-stop)`（多）
8. `await self._open_position(current_price, size_factor=trend_follow_position_factor, side=..., atr_percent=..., stop_price_override=stop, tp_price_override=tp)`；成功才计数

- [ ] **Step 1: 写失败测试** `tests/unit/test_trend_follow_channel.py`
（mock `Bot` 依赖：`config`、`position_manager`、`_open_position` 打桩、
`_drawdown_status=None`、`_daily_open_counts={}`；market_data 用 dict 构造）

```python
async def test_trend_follow_opens_short_on_downtrend():
    # trend_direction="down", change_percent=-2.5, rsi=35, atr_percent=0.005,
    # high_history 24 个 61000, low_history 24 个 59500, current_price=59000
    # res = await bot._maybe_trend_follow(md, 59000)
    # assert res is not None and res.action == "open_trend_follow"
    # 断言 _open_position 收到 side="short", size_factor=0.5,
    # stop_price_override == min(61000 + 0.5*atr_abs, 59000*1.025),
    # tp_price_override == 59000 - 10*(stop-59000)

async def test_trend_follow_opens_long_on_uptrend():  # 镜像断言 side="long"

def test_trend_follow_rsi_floor_blocks_short():
    # 同下跌构造但 rsi=18 -> None

def test_trend_follow_requires_24_bars():
    # high_history 只有 20 根 -> None

async def test_trend_follow_daily_cap():
    # 第一次成功; 同一天再次调用 -> None (并 _trend_follow_counts==1)

async def test_trend_follow_blocked_by_shared_daily_limit():
    # bot._daily_open_counts[today] = config.trading.daily_open_limit
    # -> None (Review Focus 4)

def test_trend_follow_disabled_config():
    # trend_follow_enabled=False -> None

def test_trend_follow_short_requires_allow_short_selling():
    # allow_short_selling=False + 下跌构造 -> None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_trend_follow_channel.py -v`
Expected: FAIL（AttributeError: no _maybe_trend_follow）

- [ ] **Step 3: 配置字段** — `TradingConfig` 加 9 字段（默认值见 Global Constraints，
中文注释注明回放依据"11-13→25 回放 +10.34R / 9 笔"）；`validate()` 校验
`change_pct in (0, 50]`、`0 <= short_rsi_floor < long_rsi_ceil <= 100`、
`stop_atr_buffer >= 0`、`0 < max_stop_pct <= 0.1`、`safety_tp_r >= 1`、
`daily_limit >= 0`、`0 < position_factor <= 1`；env 覆盖至少给
`TREND_FOLLOW_ENABLED`（模式照 `CLIMAX_SHORT_ENABLED` 等既有实现，若无则
照 MIN_CONFIDENCE_OPEN 的 `os.getenv` 模式）。

- [ ] **Step 4: 实现 `_maybe_trend_follow` + 5.8 hook**

方法放 `_maybe_climax_short` 之后；hook 代码块照 5.6 原样复制改三处：
`signal not in ("BUY", "SHORT")` 守卫、action 允许列表（同 5.6 的 7 个值）、
调用与日志 `[趋势跟踪] 独立通道开仓成功 (AI信号=%s 路径未开仓)`。
`_trend_follow_counts: Dict[str, int]` 加在 `__init__`（照 `_climax_short_counts`）。

- [ ] **Step 5: 跑测试 + 全量 + lint**

Run: `pytest tests/unit/test_trend_follow_channel.py -v && pytest -q && black --check alpha_trading_bot/ tests/ && mypy alpha_trading_bot/core/bot.py alpha_trading_bot/config/models.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add alpha_trading_bot/config/models.py alpha_trading_bot/core/bot.py tests/unit/test_trend_follow_channel.py
git commit -m "feat(bot): 趋势跟踪独立通道 (SMA趋势+24h±2%触发, 半仓, 摆动止损+10R安全止盈, 每日1次/方向)"
```

---

### Task 4: 追踪止盈（1R 保本 + 2R 起 3×ATR 追踪，只收紧）

**Files:**
- Modify: `alpha_trading_bot/core/position_manager.py`（`Position` dataclass :21-29 加 `initial_stop_price: float = 0.0`；开仓成功处 `open_position` 流程里 `set_initial_stop`；新增 `calculate_trailing_stop`）
- Modify: `alpha_trading_bot/core/state_persistence.py`（`PositionState` :56-74 加 `initial_stop_price: float = 0.0`；`save_position` 签名与调用同步；恢复路径 `:73-78` 同步）
- Modify: `alpha_trading_bot/core/stop_loss_manager.py`（`update_stop_loss` :74 合并 trailing；更紧时 force_update 绕过 tolerance :169-178；下单前经 `AdaptiveStopLossManager._calc_safe_stop_price` 钳位方向错误侧）
- Modify: `alpha_trading_bot/config/models.py`（`trailing_stop_enabled` 等 4 字段 + validate）
- Test: `tests/unit/test_trailing_stop.py`

**Interfaces:**
- Consumes: `PositionManager.entry_price`、`last_stop_price`、`_highest_price_since_entry`/`_lowest_price_since_entry`（既有 `update_price_tracking` 维护、已持久化）、`config.trading.trailing_*`
- Produces:
  - `Position.initial_stop_price: float`（开仓写入一次，平仓清零）
  - `PositionManager.set_initial_stop(stop_price: float) -> None`（开仓路径调用；已设过则忽略）
  - `PositionManager.calculate_trailing_stop(current_price: float, atr_percent: float) -> Optional[float]`（多: 浮盈≥be_at_r → 候选 entry×1.001；浮盈≥activate_at_r → 候选=max(候选, highest−atr_mult×ATR)；返回**仅比当前 last_stop_price 更紧**的价，否则 None；空镜像用 min/lowest；`initial_stop_price<=0` 或 R<=0 或 `trailing_stop_enabled=False` → None）
  - R = `abs(entry − initial_stop_price)`；ATR_abs = `atr_percent/100*current_price`

**行为契约**:
- 只收紧不放松: 多头 trailing 候选 ≤ last_stop_price 时返回 None；空头 ≥ 时 None
- trailing 非 None 时 `update_stop_loss` 强制更新（不进入 tolerance 比较），且最终止损 = max(unified, trailing)（多）/ min（空）
- 安全钳位: 空头最终止损若 ≤ current_price → `current_price + max(current_price*0.001, 1.0)`（复用 `_calc_safe_stop_price`）；多头镜像
- 开仓路径: `_open_position` 成功创建止损单后调 `set_initial_stop(实际止损价)`；平仓/止损离场路径（`_close_position`、保护单归因、position 清零处）调 `reset`（initial_stop=0、`reset_price_tracking` 既有）

- [ ] **Step 1: 写失败测试** `tests/unit/test_trailing_stop.py`
（构造 `PositionManager` + mock exchange/position；entry=100, initial_stop=102（空）/98（多）→ R=2）

```python
def test_trailing_long_breakeven_at_1r():
    # 多, entry=100, initial_stop=98, current=102.0 (恰 1R), last_stop=98
    # assert pm.calculate_trailing_stop(102.0, atr_percent=0.005) == pytest.approx(100*1.001)

def test_trailing_long_trail_at_2r_uses_extreme():
    # current=104 (2R), highest_since_entry=104, ATR_abs=0.5, mult=3.0
    # 候选 = max(100.1, 104-1.5) = 102.5 > last_stop(98) -> 102.5

def test_trailing_never_relaxes():
    # 多, last_stop 已被推高到 103, 候选 102.5 < 103 -> None

def test_trailing_short_mirror():
    # 空, entry=100, initial_stop=102, current=98 (1R) -> 100*0.999
    # current=96 (2R), lowest=96 -> min 侧镜像

def test_trailing_degrades_without_initial_stop():
    # initial_stop=0 (旧 JSON) -> None, 不抛异常 (Review Focus 2)

def test_trailing_disabled_config():
    # trailing_stop_enabled=False -> None

async def test_trailing_forces_update_within_tolerance():
    # last_stop=98, trailing=102.5, tolerance 设大 (0.05)
    # update_stop_loss 后 assert 新止损单 == 102.5 (未被 tolerance 吞) (Review Focus 5)

async def test_trailing_stop_wrong_side_clamped():
    # 空, 追踪候选 <= current_price 的构造 (如 extreme 更新延迟)
    # 最终 create_stop_loss 收到的 stop_price == current_price + max(current_price*0.001, 1.0)
    # (Review Focus 1)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_trailing_stop.py -v`
Expected: FAIL（AttributeError: calculate_trailing_stop / set_initial_stop）

- [ ] **Step 3: 实现 position_manager 侧**

`Position` 加字段；`set_initial_stop`（幂等：`if self._initial_stop_price <= 0` 才写，
持久化走既有 `save_position` 路径）；`calculate_trailing_stop` 按契约实现，
中文注释写明 1R/2R 语义与"只收紧"；`reset_price_tracking` 里同步清
`_initial_stop_price` 并持久化。恢复路径（state 加载 :73-78）读回
`initial_stop_price`。`save_position` 调用点同步传参。

- [ ] **Step 4: 实现 stop_loss_manager 合并 + 钳位**

`update_stop_loss` 中 `new_stop` 计算后：
`trailing = self._position_manager.calculate_trailing_stop(current_price, atr)`
（atr 从 `self._position_manager` 可得的最近 atr_percent 传入——若无现成字段，
由 bot 调用 `_update_stop_loss(current_price, atr_percent=...)` 透传，
签名加可选参，默认 0 → trailing 不启用追踪段、保本段仍可用；
`atr_percent` 参数默认 0.0 保持旧调用零回归）；
trailing 非 None 时 `new_stop = max/min(...)` 且 `force_update = True`；
`create`/重试路径下单前钳位（复用 `AdaptiveStopLossManager._calc_safe_stop_price`）。
bot 侧 `_update_stop_loss` 调用点（:813/819/834/847）透传
`market_data["technical"]["atr_percent"]`（HOLD+持仓 :818 处 market_data 在作用域内）。

- [ ] **Step 5: 跑测试 + 全量 + lint**

Run: `pytest tests/unit/test_trailing_stop.py -v && pytest -q && black --check alpha_trading_bot/core/ && mypy alpha_trading_bot/core/position_manager.py alpha_trading_bot/core/stop_loss_manager.py`
Expected: PASS

- [ ] **Step 6: 回放交叉验证**

Run: `python scripts/replay_trend_channel.py --days 14`（Task 1 工具）
Expected: 输出与基线一致（本 Task 不改触发，PnL 不应变化；若变化说明
simulate 与实现口径漂移 → 修实现对齐回放）

- [ ] **Step 7: Commit**

```bash
git add alpha_trading_bot/core/position_manager.py alpha_trading_bot/core/stop_loss_manager.py alpha_trading_bot/core/state_persistence.py alpha_trading_bot/config/models.py alpha_trading_bot/core/bot.py tests/unit/test_trailing_stop.py
git commit -m "feat(stop): 追踪止盈——1R保本+2R起3×ATR追踪(只收紧), initial_stop持久化, 容错强制更新+方向钳位"
```

---

### Task 5: 结构方向 HTF 门槛 + AI prompt 趋势上下文

**Files:**
- Modify: `alpha_trading_bot/ai/market_structure.py`（`analyze` :109 签名加 `change_percent: float = 0.0`；方向降级逻辑 :160-163 区域加 24h 一致性门槛）
- Modify: `alpha_trading_bot/ai/prompt_builder.py`（`_format_prompt` :259 附近，`recent_15m_summary` 块 :308-315 后加一行 4h 结构 + 24h 涨跌）
- Modify: `alpha_trading_bot/ai/integrator.py`（调用 `analyze(...)` 处透传 `market_data.get("change_percent", 0.0)`，约 :636）
- Test: `tests/unit/test_market_structure_htf_gate.py`

**Interfaces:**
- Consumes: `market_data["change_percent"]`（24h %）、既有 `htf_structure`（"bullish"/"bearish"/"sideways"/"unknown"）、`recent_15m_summary["position_pct"]`
- Produces: `analyze(price_history, current_price, atr_percent, change_percent=0.0)`；新门槛:
  - `suggested_direction == "long"` 必须 `htf != "bearish"` 且 `change_percent > -3.0`
  - `suggested_direction == "short"` 必须 `htf != "bullish"` 且 `change_percent < +3.0`
  - 不满足时 direction 降级 "none"，`htf_note` 追加 "24h/4h 一致性门槛" 说明
  - `change_percent == 0`（未传/未知）时**不启用** 24h 门槛（零回归保护，仅 4h 门槛生效——4h 门槛为既有 P1-4 行为保持）
- 修复目标（写进注释）: 11-24 13:43 阴跌中（24h -5%、HTF sideways）
  `direction=long` 不再出现

- [ ] **Step 1: 写失败测试** `tests/unit/test_market_structure_htf_gate.py`

```python
def test_long_direction_blocked_when_24h_declining():
    # 构造 1h 序列: 15m 结构 bullish (价在支撑上/摆动 HH+HL) 但整体 24h 跌 5%
    # res = analyzer.analyze(hist, price, 0.01, change_percent=-5.0)
    # assert res.suggested_direction != "long"
    # assert "一致性门槛" in res.htf_note

def test_long_direction_allowed_when_24h_flat_or_up():
    # 同 bullish 结构, change_percent=-1.0 -> direction 保持 long

def test_short_direction_blocked_when_24h_rising():
    # 镜像: bearish 结构 + change_percent=+4.0 -> != "short"

def test_gate_off_when_change_percent_zero():
    # change_percent=0 -> 行为与既有 P1-4 完全一致 (仅 4h 门槛)
    # 用 git stash 对照或断言 htf_note 不含 "24h/4h 一致性门槛"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_market_structure_htf_gate.py -v`
Expected: FAIL

- [ ] **Step 3: 实现** — `analyze` 加参并在 direction 定稿处加门槛
（门槛写在 `htf_note` 供日志审计）；integrator 调用点透传 change_percent；
prompt_builder 在 recent_15m_summary 块后加一行:
`- 高级别结构(4h): {htf} | 24h 涨跌幅: {change:+.2f}%`
（htf 从 `market_data.get("market_structure_htf", "unknown")` 取——
该键由 integrator :663 写入；prompt 构建时若无则跳过该行）。

- [ ] **Step 4: 跑测试 + 全量 + lint**

Run: `pytest tests/unit/test_market_structure_htf_gate.py -v && pytest -q && black --check alpha_trading_bot/ai/ && mypy alpha_trading_bot/ai/market_structure.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add alpha_trading_bot/ai/market_structure.py alpha_trading_bot/ai/integrator.py alpha_trading_bot/ai/prompt_builder.py tests/unit/test_market_structure_htf_gate.py
git commit -m "feat(structure): direction 建议加 24h/4h 一致性门槛 + AI prompt 趋势上下文 (防 11-24 13:43 型逆势抄底)"
```

---

### Task 6: 全量回归 + 回放基线 + 上线检查单

**Files:**
- Modify: `.env.example`（新增 `TREND_FOLLOW_ENABLED` 等 env 变量说明，照既有风格）
- No new source code（纯验证任务）

**Interfaces:**
- Consumes: Task 1-5 全部产物

- [ ] **Step 1: 全量测试 + 静态检查**

Run: `pytest -q && black --check alpha_trading_bot/ scripts/ tests/ && mypy alpha_trading_bot/ && flake8 alpha_trading_bot/ --max-line-length=88 --extend-ignore=E203,W503 && isort --check-only alpha_trading_bot/ --profile black`
Expected: 全绿（任何失败先修再继续）

- [ ] **Step 2: 回放基线重跑**

Run: `python scripts/replay_trend_channel.py --fetch --days 14`
Expected: 交易表与 Task 1 Step 6 基线一致（触发口径未变；PnL 量级一致）

- [ ] **Step 3: TEST_MODE 冒烟（影子 1 周期）**

Run: `TEST_MODE=true python -m alpha_trading_bot ...`（按项目既有启动方式，
`scripts/okx_sandbox_smoke.py` 或 start_bot 的测试模式）跑 ≥1 个完整 15m 周期
Expected: 日志出现 `[趋势跟踪] 跳过(原因=...)` 或 `开仓成功`（TEST_MODE 模拟单）；
`[追踪]` 相关日志在持仓周期出现；无异常栈

- [ ] **Step 4: 更新 .env.example + 提交**

```bash
git add .env.example
git commit -m "chore: 趋势跟踪通道 env 配置说明"
```

## 上线顺序与回滚

按 Task 3 → 4 → 5 的部署顺序（通道先于追踪、追踪先于 prompt）；
每步之间跑 Task 6 Step 1-2。回滚: `TREND_FOLLOW_ENABLED=false`
+ `TRAILING_STOP_ENABLED=false` 即可关闭全部新行为（配置级回滚，无需代码回退）。
