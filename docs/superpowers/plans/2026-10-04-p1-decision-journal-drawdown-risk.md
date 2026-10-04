# P1 地基与度量实现计划（DecisionJournal + 回撤总闸 + 风险反查）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在零交易行为变化的前提下落地 P1：决策日志（各层信号 + T+4h/T+24h 结果回填）、30% 回撤停机总闸、开仓单笔风险反查。

**Architecture:** 三个独立组件挂入现有周期：`DrawdownGuard`（纯本地状态 + JSON 持久化，周期内检查一次，只拦新开仓）；`DecisionJournal`（JSONL 追加 + 回填，bot 周期统一写入，AIClient 暴露信号溯源）；风险反查（`_open_position` 内仓位缩减/放弃）。配置走 `TradingConfig` + `Config.from_env`，全部有 env 开关。

**Tech Stack:** Python 3.8+（mypy strict）、pytest + @pytest.mark.asyncio、无新依赖。

**Spec:** `docs/superpowers/specs/2026-10-04-dual-direction-trading-design.md`（P1 节）

## Global Constraints

- Python 3.8 类型标注（`from typing import ...`，不用 `X | None`）；mypy strict 通过；black line-length 88；isort --profile black
- 业务逻辑注释用中文；docstring Google 风格
- 异常：自定义异常来自 `alpha_trading_bot.core.exceptions`；禁止裸 `except:`；吞异常必须 WARNING 日志
- 测试放 `tests/unit/`，异步测试用 `@pytest.mark.asyncio`；mock 外部依赖（交易所/AI）
- 每个 task 结束提交；**永不提交 `.env`**（含真实 key）
- 零行为变化不变式：P1 全部组件关闭/未触发时，交易链路与现状逐字节一致（测试兜底）
- 状态文件目录：一律经 `alpha_trading_bot.core.state_persistence.resolve_state_data_dir(data_dir)` 解析（尊重 `TRADING_STATE_DIR` env，测试由 conftest autouse fixture 隔离到 tmp_path）
- spec 偏差说明（均为实现细节，行为目标不变）：
  1. 持久化位置：spec 的 `data_json/trading_state/` 按现有 `StatePersistence` 惯例改为 `data/trading_state/`（经 `resolve_state_data_dir`，尊重 `TRADING_STATE_DIR`）
  2. 回填采用追加 outcome 记录而非重写原行（JSONL 追加更安全，报告脚本按 ts join）
  3. 总闸挂载点：spec 说"挂入 RiskManager 边界链"，实测该边界链（`ai/adaptive/risk_manager.RiskControlManager`）并未接入 bot 交易周期（仅被 `core/managers/risk_manager.py` 包装，无调用方），故改为 bot 周期级检查（`_check_drawdown`）+ `_open_position` 纵深防线，行为与 spec 一致（只拦新开仓、持仓管理不受影响）
  4. spec 的"get_metrics() 暴露状态"：`TradingBot` 无 get_metrics（metrics 在 AIClient），改为 WARNING 日志 + 决策日志 `drawdown_halted` 字段暴露
  5. 风险反查的止损距离 d：`calculate_stop_price_unified` 需要已存在的持仓对象，开仓前无持仓；改用同一 `StopLossConfig.stop_loss_percent` 常量（入场式止损口径，与 StopLossManager 首挂单同一参数源，无双套口径）

## Review Focus

spec 隐含但任务测试未直接覆盖、最可能咬人的输入/失效模式：

1. **`get_balance` API 失败返回 0.0**（account_service 现有行为）→ DrawdownGuard 不得误触发停机（equity<=0 跳过）；bot 周期不得因此中断。→ 钉在 Task 2 `test_invalid_equity_skipped` + Task 3 `test_cycle_survives_balance_fetch_error`
2. **`drawdown_baseline.json` 损坏/半写**（磁盘故障、kill -9）→ guard 以干净高水位启动，不抛异常、不误停机。→ 钉在 Task 2 `test_corrupted_baseline_file`
3. **决策日志写入失败**（磁盘满/权限）→ `record_cycle`/`backfill` 吞异常 + WARNING，周期继续。→ 钉在 Task 6 `test_write_failure_does_not_raise`
4. **回填跨天**（23:50 的 cycle 在次日 03:50 回填 T+4h）→ backfill 必须同时扫当天与前一天文件。→ 钉在 Task 6 `test_backfill_across_day_boundary`
5. **TEST_MODE 固定模拟余额** → 高水位不动、永不触发停机（预期行为，避免"沙盒里总闸莫名 OPEN"的困惑）→ 钉在 Task 3 `test_test_mode_fixed_balance_never_halts`

## File Structure

| 文件 | 职责 | 动作 |
|---|---|---|
| `alpha_trading_bot/config/models.py` | `TradingConfig` +4 字段、`Config.from_env` +4 env、validate 范围检查 | Modify |
| `.env.example` | 4 个新 env 注释（不碰 `.env`） | Modify |
| `alpha_trading_bot/core/drawdown_guard.py` | `DrawdownStatus` + `DrawdownGuard`（高水位持久化 + 停机判定 + 手动恢复） | Create |
| `alpha_trading_bot/core/decision_journal.py` | `DecisionJournal`（JSONL 追加/按日轮转/90 天保留/结果回填） | Create |
| `alpha_trading_bot/core/bot.py` | guard 周期检查 + `_execute_signal` 返回 `ExecutionResult` + 开仓门禁 + 风险反查 + journal 接入 | Modify |
| `alpha_trading_bot/ai/client.py` | `_last_signal_trace` 捕获 + `get_last_signal_trace()` | Modify |
| `alpha_trading_bot/ai/jev/fast_lane.py` | `FastLaneResult` +2 可选字段（risk_noul/choppy_noul）+ decide() 填充 | Modify |
| `scripts/decision_journal_report.py` | 分层胜率报表（Jev/LLM/最终信号/守卫拦截复盘） | Create |
| `tests/unit/test_p1_risk_config.py` | Task 1 | Create |
| `tests/unit/test_drawdown_guard.py` | Task 2 | Create |
| `tests/unit/test_bot_drawdown_guard.py` | Task 3 | Create |
| `tests/unit/test_bot_risk_backcheck.py` | Task 4 | Create |
| `tests/unit/test_ai_client_signal_trace.py` | Task 5 | Create |
| `tests/unit/test_decision_journal.py` | Task 6 | Create |
| `tests/unit/test_bot_decision_journal.py` | Task 7 | Create |
| `tests/unit/test_decision_journal_report.py` | Task 8 | Create |

---

### Task 1: 配置扩展（TradingConfig + from_env + .env.example）

**Files:**
- Modify: `alpha_trading_bot/config/models.py`（`TradingConfig` 类 ~line 116-148；`Config.from_env` ~line 564-600）
- Modify: `.env.example`（末尾追加小节）
- Test: `tests/unit/test_p1_risk_config.py`

**Interfaces:**
- Produces: `TradingConfig.decision_journal_enabled: bool`（默认 True）、`TradingConfig.risk_drawdown_halt: float`（0.30）、`TradingConfig.risk_per_trade_max: float`（0.10）、`TradingConfig.risk_resume: bool`（False）；env：`DECISION_JOURNAL` / `RISK_DRAWDOWN_HALT` / `RISK_PER_TRADE_MAX` / `RISK_RESUME`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_p1_risk_config.py
"""P1 风控与决策日志配置测试（2026-10-04 双向交易 spec P1）"""

from alpha_trading_bot.config.models import Config, TradingConfig


def test_p1_defaults() -> None:
    tc = TradingConfig()
    assert tc.decision_journal_enabled is True
    assert tc.risk_drawdown_halt == 0.30
    assert tc.risk_per_trade_max == 0.10
    assert tc.risk_resume is False
    assert tc.validate() == []


def test_from_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("DECISION_JOURNAL", "false")
    monkeypatch.setenv("RISK_DRAWDOWN_HALT", "0.25")
    monkeypatch.setenv("RISK_PER_TRADE_MAX", "0.05")
    monkeypatch.setenv("RISK_RESUME", "true")
    cfg = Config.from_env()
    assert cfg.trading.decision_journal_enabled is False
    assert cfg.trading.risk_drawdown_halt == 0.25
    assert cfg.trading.risk_per_trade_max == 0.05
    assert cfg.trading.risk_resume is True


def test_validate_rejects_bad_values() -> None:
    assert any("risk_drawdown_halt" in e for e in TradingConfig(risk_drawdown_halt=1.5).validate())
    assert any("risk_drawdown_halt" in e for e in TradingConfig(risk_drawdown_halt=0.0).validate())
    assert any("risk_per_trade_max" in e for e in TradingConfig(risk_per_trade_max=0.0).validate())
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/unit/test_p1_risk_config.py -v`
Expected: FAIL（`TradingConfig` 无 `decision_journal_enabled` 等字段）

- [ ] **Step 3: 实现**

在 `TradingConfig` 字段区（`short_entry_max_daily_change` 之后）追加：

```python
    # ---- P1 风控与决策日志（2026-10-04 双向交易 spec）----
    decision_journal_enabled: bool = True  # 决策日志开关（DECISION_JOURNAL）
    risk_drawdown_halt: float = 0.30  # 回撤停机阈值：权益相对高水位回撤≥30% 禁止新开仓
    risk_per_trade_max: float = 0.10  # 单笔风险上限：止损触发预期亏损 ≤ 账户 10%
    risk_resume: bool = False  # 手动恢复：RISK_RESUME=1 + 重启后清除停机状态
```

`validate()` 的 errors 收集处追加：

```python
        if not 0 < self.risk_drawdown_halt < 1:
            errors.append(f"回撤停机阈值 {self.risk_drawdown_halt} 不在有效范围 (0-1)")
        if not 0 < self.risk_per_trade_max <= 1:
            errors.append(f"单笔风险上限 {self.risk_per_trade_max} 不在有效范围 (0-1]")
```

`Config.from_env` 的 `trading=TradingConfig(...)` 追加 4 个 kwarg：

```python
                decision_journal_enabled=os.getenv("DECISION_JOURNAL", "true").lower()
                == "true",
                risk_drawdown_halt=float(os.getenv("RISK_DRAWDOWN_HALT", "0.30")),
                risk_per_trade_max=float(os.getenv("RISK_PER_TRADE_MAX", "0.10")),
                risk_resume=os.getenv("RISK_RESUME", "false").lower() == "true",
```

`.env.example` 末尾追加：

```bash
# =============================================================================
# P1 风控与决策日志（2026-10-04 双向交易）
# =============================================================================
DECISION_JOURNAL=true                                    # 决策日志开关（true=记录各层信号+T+4h/24h结果）
RISK_DRAWDOWN_HALT=0.30                                  # 回撤停机阈值（权益相对高水位回撤≥30% 禁止新开仓）
RISK_PER_TRADE_MAX=0.10                                  # 单笔风险上限（止损触发预期亏损≤账户10%，超限自动缩仓）
RISK_RESUME=false                                         # 手动恢复（true+重启 后清除停机状态；停机期间必须保持 false）
```

- [ ] **Step 4: 运行确认通过 + 回归**

Run: `pytest tests/unit/test_p1_risk_config.py -v && pytest tests/unit/ -k "config" -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add alpha_trading_bot/config/models.py .env.example tests/unit/test_p1_risk_config.py
git commit -m "feat(p1): TradingConfig 增加决策日志/回撤停机/单笔风险配置项"
```

---

### Task 2: DrawdownGuard（高水位持久化 + 30% 停机 + 手动恢复）

**Files:**
- Create: `alpha_trading_bot/core/drawdown_guard.py`
- Test: `tests/unit/test_drawdown_guard.py`

**Interfaces:**
- Consumes: `resolve_state_data_dir`（`alpha_trading_bot.core.state_persistence`，Task 1 的 config 字段由 Task 3 消费，本 task 纯组件不依赖）
- Produces:
  - `DrawdownStatus` dataclass：`halted: bool`（禁止新开仓）、`drawdown: float`（0-1）、`high_water: float`、`just_tripped: bool`（本次刚触发）、`skipped: bool`（equity<=0 跳过）
  - `DrawdownGuard(threshold: float = 0.30, resume: bool = False, data_dir: Optional[Path] = None)`
  - `DrawdownGuard.check(equity: float) -> DrawdownStatus`（同步，纯本地 IO）
  - 持久化文件：`resolve_state_data_dir(data_dir) / "drawdown_baseline.json"`，内容 `{"high_water": float, "halted_since": float|null, "updated_at": float}`，原子写（tmp+rename）

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_drawdown_guard.py
"""回撤停机总闸测试（P1，spec: RISK_DRAWDOWN_HALT=0.30 + 手动恢复）"""

import pytest

from alpha_trading_bot.core.drawdown_guard import DrawdownGuard


def test_fresh_high_water_not_halted(tmp_path) -> None:
    g = DrawdownGuard(threshold=0.30, data_dir=tmp_path)
    s = g.check(1000.0)
    assert not s.halted and s.high_water == 1000.0
    assert s.drawdown == 0.0 and not s.just_tripped and not s.skipped


def test_trip_at_exact_threshold(tmp_path) -> None:
    g = DrawdownGuard(threshold=0.30, data_dir=tmp_path)
    g.check(1000.0)
    s = g.check(700.0)  # (1000-700)/1000 = 30% → 触发（≥ 语义）
    assert s.halted and s.just_tripped
    assert s.drawdown == pytest.approx(0.30)


def test_no_trip_below_threshold(tmp_path) -> None:
    g = DrawdownGuard(threshold=0.30, data_dir=tmp_path)
    g.check(1000.0)
    s = g.check(750.0)  # 25% → 不触发
    assert not s.halted and not s.just_tripped


def test_high_water_monotonic(tmp_path) -> None:
    g = DrawdownGuard(threshold=0.30, data_dir=tmp_path)
    g.check(1000.0)
    g.check(1100.0)  # 高水位上移
    s = g.check(700.0)  # (1100-700)/1100 ≈ 36.4%
    assert s.halted and s.high_water == 1100.0


def test_persistence_across_restart_keeps_halt(tmp_path) -> None:
    g1 = DrawdownGuard(threshold=0.30, data_dir=tmp_path)
    g1.check(1000.0)
    g1.check(700.0)  # trip
    g2 = DrawdownGuard(threshold=0.30, data_dir=tmp_path)  # 模拟重启
    s = g2.check(690.0)
    assert s.halted and not s.just_tripped and s.high_water == 1000.0


def test_manual_resume_clears_halt_keeps_high_water(tmp_path) -> None:
    g1 = DrawdownGuard(threshold=0.30, data_dir=tmp_path)
    g1.check(1000.0)
    g1.check(700.0)  # trip
    g2 = DrawdownGuard(threshold=0.30, resume=True, data_dir=tmp_path)
    s = g2.check(700.0)
    assert not s.halted and s.high_water == 1000.0  # 高水位保留，重新计回撤


def test_invalid_equity_skipped_no_false_trip(tmp_path) -> None:
    # Review Focus #1: get_balance API 失败返回 0.0，不得误触发停机
    g = DrawdownGuard(threshold=0.30, data_dir=tmp_path)
    s = g.check(0.0)
    assert s.skipped and not s.halted and not s.just_tripped
    s2 = g.check(1000.0)  # 恢复后正常
    assert not s2.skipped and s2.high_water == 1000.0


def test_corrupted_baseline_file(tmp_path) -> None:
    # Review Focus #2: 文件损坏/半写 → 干净启动，不抛异常、不误停机
    (tmp_path / "drawdown_baseline.json").write_text("{not json", encoding="utf-8")
    g = DrawdownGuard(threshold=0.30, data_dir=tmp_path)
    s = g.check(1000.0)
    assert not s.halted and s.high_water == 1000.0
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/unit/test_drawdown_guard.py -v`
Expected: FAIL（`ModuleNotFoundError: alpha_trading_bot.core.drawdown_guard`）

- [ ] **Step 3: 实现**

```python
# alpha_trading_bot/core/drawdown_guard.py
"""回撤停机总闸（P1，2026-10-04 双向交易 spec）

- 权益相对持久化高水位回撤 ≥ threshold（默认 30%）→ 禁止一切新开仓；
  已持仓继续由止损管理，不受影响。
- 高水位持久化到 data/trading_state/drawdown_baseline.json（进程重启不重置，
  避免"亏损后重启重置基准"漏洞）。
- 恢复仅手动：RISK_RESUME=1 + 重启（自动恢复 = 让失效策略继续亏）。
- equity <= 0（get_balance API 失败返回 0.0）视为无效读取，跳过本轮检查。
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .state_persistence import resolve_state_data_dir

logger = logging.getLogger(__name__)

BASELINE_FILENAME = "drawdown_baseline.json"


@dataclass
class DrawdownStatus:
    """单轮回撤检查结果"""

    halted: bool  # True = 禁止新开仓
    drawdown: float  # 当前回撤（相对高水位，0-1）
    high_water: float  # 当前高水位
    just_tripped: bool  # 本轮刚触发停机
    skipped: bool  # equity<=0，本轮检查被跳过


class DrawdownGuard:
    """30% 回撤停机总闸（纯本地状态，无网络 IO）。"""

    def __init__(
        self,
        threshold: float = 0.30,
        resume: bool = False,
        data_dir: Optional[Path] = None,
    ) -> None:
        self._threshold = threshold
        self._file = resolve_state_data_dir(data_dir) / BASELINE_FILENAME
        self._high_water = 0.0
        self._halted_since: Optional[float] = None
        self._load()
        if resume:
            if self._halted_since is not None:
                logger.warning(
                    "[风控总闸] RISK_RESUME=1 手动恢复，清除停机状态"
                    "（高水位 %.2f 保留）",
                    self._high_water,
                )
                self._halted_since = None
        elif self._halted_since is not None:
            logger.warning(
                "[风控总闸] 从上次运行恢复停机状态（触发于 %s），"
                "新开仓继续禁止；恢复需 RISK_RESUME=1 + 重启",
                time.strftime("%Y-%m-%d %H:%M", time.localtime(self._halted_since)),
            )

    def check(self, equity: float) -> DrawdownStatus:
        """用最新权益检查回撤状态（每个交易周期调用一次）。"""
        if equity <= 0:
            # API 失败时 get_balance 返回 0.0：不更新状态，避免误停机
            return DrawdownStatus(
                halted=self._halted_since is not None,
                drawdown=0.0,
                high_water=self._high_water,
                just_tripped=False,
                skipped=True,
            )
        if self._high_water <= 0:
            self._high_water = equity
        else:
            self._high_water = max(self._high_water, equity)
        drawdown = (self._high_water - equity) / self._high_water
        just_tripped = False
        if self._halted_since is None and drawdown >= self._threshold:
            self._halted_since = time.time()
            just_tripped = True
            logger.warning(
                "[风控总闸] OPEN: 回撤 %.1f%% ≥ 阈值 %.0f%%，禁止新开仓"
                "（高水位 %.2f → 当前权益 %.2f）；恢复需 RISK_RESUME=1 + 重启",
                drawdown * 100,
                self._threshold * 100,
                self._high_water,
                equity,
            )
        self._save()
        return DrawdownStatus(
            halted=self._halted_since is not None,
            drawdown=drawdown,
            high_water=self._high_water,
            just_tripped=just_tripped,
            skipped=False,
        )

    # ---- 持久化 ----

    def _load(self) -> None:
        try:
            if self._file.exists():
                raw = self._file.read_text(encoding="utf-8")
                data = json.loads(raw)
                self._high_water = float(data.get("high_water", 0.0))
                halted = data.get("halted_since")
                self._halted_since = float(halted) if halted else None
        except (ValueError, OSError, json.JSONDecodeError) as e:
            # 文件损坏/半写：以干净状态启动（Review Focus #2）
            logger.warning("[风控总闸] 基准文件读取失败，以干净高水位启动: %s", e)
            self._high_water = 0.0
            self._halted_since = None

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._file.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "high_water": self._high_water,
                        "halted_since": self._halted_since,
                        "updated_at": time.time(),
                    }
                ),
                encoding="utf-8",
            )
            os.replace(tmp, self._file)  # 原子替换，避免半写
        except OSError as e:
            logger.warning("[风控总闸] 基准文件写入失败（不影响本轮判定）: %s", e)
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/unit/test_drawdown_guard.py -v`
Expected: 8 个测试全 PASS

- [ ] **Step 5: 提交**

```bash
git add alpha_trading_bot/core/drawdown_guard.py tests/unit/test_drawdown_guard.py
git commit -m "feat(p1): DrawdownGuard 回撤停机总闸（高水位持久化+手动恢复）"
```

---

### Task 3: Bot 接入回撤总闸 + ExecutionResult

**Files:**
- Modify: `alpha_trading_bot/core/bot.py`（imports；`TradingBot.__init__` ~line 24-34；周期内持仓同步之后 ~line 248；`_execute_signal` ~line 295-328；`_open_position` 实盘闸门之后 ~line 340）
- Test: `tests/unit/test_bot_drawdown_guard.py`

**Interfaces:**
- Consumes: `DrawdownGuard` / `DrawdownStatus`（Task 2）；`config.trading.risk_drawdown_halt` / `risk_resume`（Task 1）
- Produces:
  - `bot._drawdown_status: Optional[DrawdownStatus]`（每周期刷新，`_execute_signal` 门禁读它）
  - `ExecutionResult` dataclass（`alpha_trading_bot.core.bot`）：`action: str`（`open_long` / `update_stop` / `close` / `none` / `blocked_drawdown` / `blocked_other` / `error`）、`detail: str`
  - `_execute_signal(signal, current_price, has_position) -> ExecutionResult`（原返回 None，签名变更；调用方只有周期主流程，同文件内）

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_bot_drawdown_guard.py
"""TradingBot × 回撤总闸集成测试（P1）"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from alpha_trading_bot.config.models import Config, ExchangeConfig, TradingConfig
from alpha_trading_bot.core.bot import TradingBot


def _make_bot(tmp_path: Path, balance: float = 1000.0) -> TradingBot:
    config = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(test_mode=True),
    )
    bot = TradingBot(config)
    bot._exchange = MagicMock()
    bot._exchange.get_balance = AsyncMock(return_value=balance)
    bot._exchange.create_order = AsyncMock(return_value="")
    bot._stop_loss_manager = None
    return bot


@pytest.mark.asyncio
async def test_buy_blocked_when_halted(tmp_path) -> None:
    bot = _make_bot(tmp_path)
    bot._drawdown_guard.check(1000.0)
    bot._drawdown_status = bot._drawdown_guard.check(700.0)  # trip
    result = await bot._execute_signal("BUY", 84000.0, has_position=False)
    assert result.action == "blocked_drawdown"
    bot._exchange.create_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_buy_allowed_when_not_halted(tmp_path) -> None:
    bot = _make_bot(tmp_path)
    bot._drawdown_guard.check(1000.0)
    bot._drawdown_status = bot._drawdown_guard.check(990.0)
    # 让开仓流程在 create_order 处止步（返回空 order_id → 正常中止）
    bot._open_position = AsyncMock()  # type: ignore[assignment]
    result = await bot._execute_signal("BUY", 84000.0, has_position=False)
    assert result.action == "open_long"
    bot._open_position.assert_awaited_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_close_and_stop_update_allowed_when_halted(tmp_path) -> None:
    # 总闸只拦新开仓：平仓/止损更新不受影响
    bot = _make_bot(tmp_path)
    bot._drawdown_guard.check(1000.0)
    bot._drawdown_status = bot._drawdown_guard.check(700.0)
    bot._close_position = AsyncMock()  # type: ignore[assignment]
    r1 = await bot._execute_signal("SELL", 84000.0, has_position=True)
    assert r1.action == "close"
    r2 = await bot._execute_signal("HOLD", 84000.0, has_position=True)
    assert r2.action == "update_stop"


@pytest.mark.asyncio
async def test_cycle_survives_balance_fetch_error(tmp_path) -> None:
    # Review Focus #1: get_balance 抛异常 → 跳过本轮总闸检查，周期继续
    bot = _make_bot(tmp_path)
    bot._exchange.get_balance = AsyncMock(side_effect=RuntimeError("api down"))
    bot._drawdown_guard.check(1000.0)  # 正常状态
    await bot._check_drawdown()
    assert bot._drawdown_status is None or not bot._drawdown_status.halted


@pytest.mark.asyncio
async def test_test_mode_fixed_balance_never_halts(tmp_path) -> None:
    # Review Focus #5: TEST_MODE 固定模拟余额 → 高水位不动，永不触发
    bot = _make_bot(tmp_path, balance=100.0)
    for _ in range(5):
        await bot._check_drawdown()
    assert not bot._drawdown_status.halted  # type: ignore[union-attr]
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/unit/test_bot_drawdown_guard.py -v`
Expected: FAIL（`TradingBot` 无 `_drawdown_guard` / `_check_drawdown` / `ExecutionResult`）

- [ ] **Step 3: 实现**

`bot.py` 顶部 imports 区追加：

```python
from dataclasses import dataclass

from .drawdown_guard import DrawdownGuard, DrawdownStatus
```

（`dataclass` 若 bot.py 已 import 则不重复。）

模块级、`class TradingBot` 之前：

```python
@dataclass
class ExecutionResult:
    """信号执行结果（P1：供决策日志记录）"""

    action: str  # open_long / update_stop / close / none / blocked_drawdown / blocked_other / error
    detail: str = ""
```

`TradingBot.__init__` 内 `self.position_manager = PositionManager(config)` 之后：

```python
        # P1 回撤停机总闸（30% 回撤禁止新开仓；高水位持久化，手动恢复）
        self._drawdown_guard = DrawdownGuard(
            threshold=config.trading.risk_drawdown_halt,
            resume=config.trading.risk_resume,
        )
        self._drawdown_status: Optional[DrawdownStatus] = None
```

新增方法（放在 `_execute_signal` 前）：

```python
    async def _check_drawdown(self) -> None:
        """周期内回撤总闸检查（P1）：只拦新开仓，不影响已持仓管理。

        余额获取失败时跳过本轮（不中断周期、不误停机）。
        """
        try:
            equity = await self._exchange.get_balance()
            self._drawdown_status = self._drawdown_guard.check(equity)
        except Exception as e:
            logger.warning("[风控总闸] 权益获取失败，跳过本轮检查: %s", e)
            self._drawdown_status = None
```

周期主流程中、`logger.info(f"[交易决策] 当前价格: {current_price}")` 之前插入：

```python
        # 3.5 回撤总闸检查（P1）
        await self._check_drawdown()
```

`_execute_signal` 整体替换（返回值 + 总闸门禁；分支语义与现状完全一致）：

```python
    async def _execute_signal(
        self, signal: str, current_price: float, has_position: bool
    ) -> ExecutionResult:
        """执行信号"""
        logger.info(
            f"[信号执行] 开始处理信号: {signal}, 当前价格: {current_price}, "
            f"持仓状态: {'有持仓' if has_position else '无持仓'}"
        )

        if signal == "BUY":
            if not has_position:
                # P1 回撤总闸：停机期间禁止新开仓（已持仓管理不受影响）
                if (
                    self._drawdown_status is not None
                    and self._drawdown_status.halted
                ):
                    logger.warning(
                        "[信号执行] BUY信号 + 无持仓 + 回撤总闸生效 -> 禁止新开仓"
                        "（回撤 %.1f%%）",
                        self._drawdown_status.drawdown * 100,
                    )
                    return ExecutionResult(
                        "blocked_drawdown",
                        f"drawdown={self._drawdown_status.drawdown:.2%}",
                    )
                logger.info("[信号执行] BUY信号 + 无持仓 -> 执行开仓")
                await self._open_position(current_price)
                return ExecutionResult("open_long", f"price={current_price}")
            logger.info("[信号执行] BUY信号 + 有持仓 -> 更新止损")
            await self._update_stop_loss(current_price)
            return ExecutionResult("update_stop")

        if signal == "HOLD":
            if has_position:
                logger.info("[信号执行] HOLD信号 + 有持仓 -> 更新止损")
                await self._update_stop_loss(current_price)
                return ExecutionResult("update_stop")
            logger.info("[信号执行] HOLD信号 + 无持仓 -> 不操作")
            logger.info(
                "[机会评估] 当前为HOLD信号，系统持续监控中。如需更多交易机会，可考虑: "
                "1)缩短CYCLE_MINUTES 2)切换AI_FUSION模式 3)调整INVESTMENT_TYPE=aggressive"
            )
            return ExecutionResult("none")

        if signal == "SELL":
            if has_position:
                logger.info("[信号执行] SELL信号 + 有持仓 -> 执行平仓")
                await self._close_position(current_price)
                return ExecutionResult("close", f"price={current_price}")
            logger.info("[信号执行] SELL信号 + 无持仓 -> 不操作")
            return ExecutionResult("none")

        logger.warning(f"[信号执行] 未知信号: {signal}")
        return ExecutionResult("error", f"unknown_signal={signal}")
```

`_open_position` 中实盘闸门（`check_live_trading_preconditions`）之后、`calculate_max_contracts` 之前插入纵深防线：

```python
        # P1 回撤总闸纵深防线（周期级检查之外的兜底）
        if self._drawdown_status is not None and self._drawdown_status.halted:
            logger.warning(
                "[开仓] 回撤总闸生效，拒绝新开仓（回撤 %.1f%%）",
                self._drawdown_status.drawdown * 100,
            )
            return
```

- [ ] **Step 4: 运行确认通过 + 回归**

Run: `pytest tests/unit/test_bot_drawdown_guard.py -v && pytest tests/unit/ -k "bot or signal" -q`
Expected: PASS（含既有的 adaptive_bot / signal 相关测试回归）

- [ ] **Step 5: 提交**

```bash
git add alpha_trading_bot/core/bot.py tests/unit/test_bot_drawdown_guard.py
git commit -m "feat(p1): TradingBot 接入回撤总闸 + _execute_signal 返回 ExecutionResult"
```

---

### Task 4: 开仓单笔风险反查（止损距离 → 仓位缩减/放弃）

**Files:**
- Modify: `alpha_trading_bot/core/bot.py`（`_open_position`；新增 `_apply_risk_backcheck` 方法）
- Test: `tests/unit/test_bot_risk_backcheck.py`

**Interfaces:**
- Consumes: `config.stop_loss.stop_loss_percent`（`StopLossConfig`，默认 0.0005，与 StopLossManager 入场式止损同一口径）；`config.trading.risk_per_trade_max`（Task 1）；`self._exchange.get_balance()`
- Produces: `async def _apply_risk_backcheck(self, price: float, amount: float) -> float`（返回可能缩减后的合约数；`< 0.01` 时由调用方放弃开仓）

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_bot_risk_backcheck.py
"""开仓单笔风险反查测试（P1：止损触发预期亏损 ≤ 账户 10%）"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from alpha_trading_bot.config.models import (
    Config,
    ExchangeConfig,
    StopLossConfig,
    TradingConfig,
)
from alpha_trading_bot.core.bot import TradingBot


def _make_bot(tmp_path: Path) -> TradingBot:
    config = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(test_mode=True),
        stop_loss=StopLossConfig(),
    )
    bot = TradingBot(config)
    bot._exchange = MagicMock()
    return bot


@pytest.mark.asyncio
async def test_normal_path_unchanged(tmp_path) -> None:
    """默认止损 0.05% 下反查几乎不触发（护栏语义，正常路径零行为变化）。"""
    bot = _make_bot(tmp_path)
    bot._exchange.get_balance = AsyncMock(return_value=1000.0)
    # 0.03 张 × 84000 × 0.0005 = 1.26 USDT << 1000 × 10%
    assert await bot._apply_risk_backcheck(84000.0, 0.03) == 0.03


@pytest.mark.asyncio
async def test_shrinks_on_wide_stop(tmp_path) -> None:
    """宽止损（未来 ATR 化后可能出现）时按比例缩仓到风险上限。"""
    bot = _make_bot(tmp_path)
    bot.config.stop_loss.stop_loss_percent = 0.05  # 5% 宽止损
    bot._exchange.get_balance = AsyncMock(return_value=1000.0)
    # 0.03×84000×0.05 = 126 > 100 → 缩至 100/(84000×0.05) = 0.0238
    amt = await bot._apply_risk_backcheck(84000.0, 0.03)
    assert amt == pytest.approx(0.0238, abs=1e-4)


@pytest.mark.asyncio
async def test_invalid_balance_skips_backcheck(tmp_path) -> None:
    """余额获取失败（0.0）→ 跳过反查，保持原仓位（与总闸"跳过"语义一致）。"""
    bot = _make_bot(tmp_path)
    bot._exchange.get_balance = AsyncMock(return_value=0.0)
    assert await bot._apply_risk_backcheck(84000.0, 0.03) == 0.03


@pytest.mark.asyncio
async def test_balance_fetch_error_skips_backcheck(tmp_path) -> None:
    bot = _make_bot(tmp_path)
    bot._exchange.get_balance = AsyncMock(side_effect=RuntimeError("down"))
    assert await bot._apply_risk_backcheck(84000.0, 0.03) == 0.03
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/unit/test_bot_risk_backcheck.py -v`
Expected: FAIL（`_apply_risk_backcheck` 不存在）

- [ ] **Step 3: 实现**

`bot.py` 新增方法（放在 `_open_position` 前）：

```python
    async def _apply_risk_backcheck(self, price: float, amount: float) -> float:
        """单笔风险反查（P1）：止损触发时的预期亏损 ≤ 账户 risk_per_trade_max。

        止损距离 d 取 StopLossManager 入场式止损同一口径（stop_loss_percent），
        避免双套止损价口径。余额无效/获取失败时跳过反查（不阻断开仓，
        与回撤总闸的"跳过"语义一致；此时风险由止损单本身兜底）。
        """
        d = self.config.stop_loss.stop_loss_percent
        if d <= 0 or price <= 0 or amount <= 0:
            return amount
        try:
            balance = await self._exchange.get_balance()
        except Exception as e:
            logger.warning("[开仓] 风险反查: 余额获取失败，跳过反查: %s", e)
            return amount
        if balance <= 0:
            return amount
        expected_loss = amount * price * d
        max_loss = balance * self.config.trading.risk_per_trade_max
        if expected_loss <= max_loss:
            return amount
        shrunk = float(f"{max_loss / (price * d):.4f}")
        logger.warning(
            "[开仓][风险反查] 止损距离 %.2f%% 下预期亏损 %.2f USDT 超过账户 "
            "%.0f%% (%.2f USDT)，仓位 %s → %s 张",
            d * 100,
            expected_loss,
            self.config.trading.risk_per_trade_max * 100,
            max_loss,
            amount,
            shrunk,
        )
        return shrunk
```

`_open_position` 中 `if amount <= 0: ... return` 块之后插入：

```python
        # P1 单笔风险反查：止损触发预期亏损 ≤ 账户 10%（超限缩仓，缩到最小 1 手以下则放弃）
        amount = await self._apply_risk_backcheck(price, amount)
        if amount < 0.01:
            logger.warning(
                "[开仓] 风险反查后仓位 %.4f 张 < 最小 0.01 张，取消开仓", amount
            )
            return
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/unit/test_bot_risk_backcheck.py -v`
Expected: 4 PASS

- [ ] **Step 5: 提交**

```bash
git add alpha_trading_bot/core/bot.py tests/unit/test_bot_risk_backcheck.py
git commit -m "feat(p1): 开仓单笔风险反查（止损距离→仓位缩减/放弃，默认止损下零行为变化）"
```

---

### Task 5: AIClient 信号溯源（get_last_signal_trace）+ FastLaneResult noul 字段

**Files:**
- Modify: `alpha_trading_bot/ai/client.py`（`__init__` 初始化 `_last_signal_trace`；`get_signal` 各捕获点；新增 `get_last_signal_trace()`；`_get_single_signal`/fusion 处记录 provider）
- Modify: `alpha_trading_bot/ai/jev/fast_lane.py`（`FastLaneResult` +2 字段；`decide()` 填充）
- Test: `tests/unit/test_ai_client_signal_trace.py`

**Interfaces:**
- Produces: `AIClient.get_last_signal_trace() -> Dict[str, Any]`，结构：
  ```python
  {
    "cache_hit": bool,
    "jev": {"choice": str, "confidence": float, "probabilities": Dict[str, float],
            "reason": str, "latency_ms": float, "mode": str,
            "risk_noul": Optional[float], "choppy_noul": Optional[float]} | None,
    "llm": {"provider": str, "signal": str, "confidence": float,
            "jev_context_injected": bool} | None,
    "integrator": {"original_signal": str, "original_confidence": float,
                   "final_signal": str, "final_confidence": float,
                   "adjustments": List[str]} | None,
  }
  ```
  未调用过 `get_signal` 时返回 `{}`。
- `FastLaneResult` 新增可选字段 `risk_noul: Optional[float] = None`、`choppy_noul: Optional[float] = None`（默认 None，向后兼容；`decide()` 在有响应时填充实际值）

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_ai_client_signal_trace.py
"""AIClient 信号溯源测试（P1 决策日志的数据源）"""

from typing import Any, Dict

import pytest

from alpha_trading_bot.ai.client import AIClient
from alpha_trading_bot.ai.jev.fast_lane import FastLaneResult
from alpha_trading_bot.config.models import AIConfig


class _FakeFastLane:
    def __init__(self, result: FastLaneResult) -> None:
        self._result = result

    async def decide(self, market_data: Dict[str, Any]) -> FastLaneResult:
        return self._result

    def get_stats(self) -> Dict[str, int]:
        return {"fast_lane_adopted": 0, "fast_lane_escalated": 0, "fast_lane_errors": 0}

    @property
    def breaker(self):
        class _V:
            def get_stats(self) -> Dict[str, Any]:
                return {"circuit_state": "closed"}
        return _V()

    @property
    def config(self):
        class _C:
            mode = "on"
        return _C()


def _make_client(result: FastLaneResult, llm_signal: str = "hold") -> AIClient:
    client = AIClient(
        config=AIConfig(),
        api_keys={"qwen38": "fake-key"},
        enable_cache=False,
        fast_lane=_FakeFastLane(result),
    )

    async def _fake_llm(market_data, jev_context=None):
        return llm_signal, 0.5

    client._get_llm_signal = _fake_llm  # type: ignore[assignment]
    return client


MARKET = {"symbol": "BTC/USDT:USDT", "price": 84000.0, "price_history": [84000.0] * 20}


def _adopted_result() -> FastLaneResult:
    return FastLaneResult(
        adopted=True,
        signal="hold",
        confidence=0.95,
        probabilities={"hold": 0.95},
        reason="adopt",
        latency_ms=180.0,
        risk_noul=0.2,
        choppy_noul=0.5,
    )


def _escalated_result() -> FastLaneResult:
    return FastLaneResult(
        adopted=False,
        signal="buy",
        confidence=0.4,
        probabilities={"buy": 0.5, "hold": 0.4},
        reason="low_confidence",
        latency_ms=190.0,
        jev_context="[Jev初读] ...",
        risk_noul=0.1,
        choppy_noul=0.6,
    )


@pytest.mark.asyncio
async def test_adopted_trace_has_jev_no_llm() -> None:
    client = _make_client(_adopted_result())
    await client.get_signal(dict(MARKET))
    t = client.get_last_signal_trace()
    assert t["cache_hit"] is False
    assert t["jev"]["choice"] == "hold"
    assert t["jev"]["confidence"] == 0.95
    assert t["jev"]["reason"] == "adopt"
    assert t["jev"]["risk_noul"] == 0.2
    assert t["llm"] is None
    assert t["integrator"]["final_signal"].upper() in ("HOLD", "BUY", "SELL", "SHORT")


@pytest.mark.asyncio
async def test_escalated_trace_has_jev_and_llm() -> None:
    client = _make_client(_escalated_result())
    await client.get_signal(dict(MARKET))
    t = client.get_last_signal_trace()
    assert t["jev"]["choice"] == "buy"
    assert t["jev"]["reason"] == "low_confidence"
    assert t["llm"]["signal"] == "hold"
    assert t["llm"]["confidence"] == 0.5
    assert t["llm"]["jev_context_injected"] is True
    assert t["llm"]["provider"]  # 非空


def test_trace_empty_before_any_call() -> None:
    client = _make_client(_adopted_result())
    assert client.get_last_signal_trace() == {}


@pytest.mark.asyncio
async def test_no_fast_lane_regression() -> None:
    """fast_lane=None（AI_FAST_LANE=off）：trace 无 jev 段，行为回归不变。"""
    client = AIClient(
        config=AIConfig(),
        api_keys={"qwen38": "fake-key"},
        enable_cache=False,
        fast_lane=None,
    )

    async def _fake_llm(market_data, jev_context=None):
        return "hold", 0.5

    client._get_llm_signal = _fake_llm  # type: ignore[assignment]
    await client.get_signal(dict(MARKET))
    t = client.get_last_signal_trace()
    assert t["jev"] is None
    assert t["llm"] is not None
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/unit/test_ai_client_signal_trace.py -v`
Expected: FAIL（`get_last_signal_trace` 不存在；`FastLaneResult` 无 noul 字段）

- [ ] **Step 3: 实现**

`fast_lane.py` `FastLaneResult` 追加字段（`latency_ms` 之后）：

```python
    risk_noul: Optional[float] = None  # is_high_risk_reversal 的 Noul（有响应时填充）
    choppy_noul: Optional[float] = None  # is_choppy_no_edge 的 Noul（有响应时填充）
```

`decide()` 中：在 `latency_ms = ...` 之后统一计算（供各返回路径复用）：

```python
        choppy = response.answers.get("is_choppy_no_edge")
        choppy_noul = choppy.noul if isinstance(choppy, NoulAnswer) else None
```

并在以下返回处填充 `risk_noul=.../choppy_noul=...`：
- `bad_response` 两个返回：不填（保持 None）
- `risk_gate` 返回：`risk_noul=risk_noul, choppy_noul=choppy_noul`
- shadow 返回：同上
- adopt 返回：同上
- low_confidence 返回：同上
（`risk_noul` 在 `risk = response.answers.get("is_high_risk_reversal")` 之后已有：
`risk_noul = risk.noul if isinstance(risk, NoulAnswer) else 0.0` —— 填充时直接用该值。）

`client.py`：

`__init__` 末尾追加：

```python
        # P1 决策日志：本次 get_signal 的信号溯源（各层中间结果）
        self._last_signal_trace: Dict[str, Any] = {}
```

`get_signal` 内（`async with self._signal_lock:` 之后、缓存检查之前）：

```python
            # P1: 重置信号溯源（只反映本次 get_signal）
            self._last_signal_trace = {
                "cache_hit": False,
                "jev": None,
                "llm": None,
                "integrator": None,
            }
```

缓存命中分支的 `return cached_signal` 前：

```python
                if cached_signal:
                    self._last_signal_trace["cache_hit"] = True
                    return cached_signal
```

把 `get_signal` 内从"# 获取原始信号（Jev 快车道优先；低置信/故障时升级 LLM）"到 `else: ... await self._get_llm_signal(market_data)` 结束的整个 if/else 块，替换为以下代码（除新增的 P1 记录行外，其余行与现状完全一致）：

```python
            # 获取原始信号（Jev 快车道优先；低置信/故障时升级 LLM）
            # _fast_lane=None（默认）时本分支不生效，零行为变化
            if self._fast_lane is not None:
                fast_result = await self._fast_lane.decide(market_data)
                # P1: Jev 段（adopted/escalated 都记录）
                self._last_signal_trace["jev"] = {
                    "choice": fast_result.signal,
                    "confidence": fast_result.confidence,
                    "probabilities": fast_result.probabilities,
                    "reason": fast_result.reason,
                    "latency_ms": fast_result.latency_ms,
                    "mode": self._fast_lane.config.mode,
                    "risk_noul": fast_result.risk_noul,
                    "choppy_noul": fast_result.choppy_noul,
                }
                if fast_result.adopted:
                    # 采用路径：跳过 LLM，但信号仍走下游集成器安全层
                    # （adopted 与 escalated 共用同一下游，spec 关键不变式）
                    self._metrics["fast_lane_adopted"] += 1
                    original_signal = fast_result.signal or "hold"
                    original_confidence = fast_result.confidence
                    await log_signal_distribution(original_signal, source="jev")
                    logger.info(
                        "[AI请求] Jev快车道采用: %s " "(置信=%.2f, %dms, 跳过LLM)",
                        original_signal,
                        original_confidence,
                        fast_result.latency_ms,
                    )
                else:
                    self._metrics["fast_lane_escalated"] += 1
                    original_signal, original_confidence = await self._get_llm_signal(
                        market_data, jev_context=fast_result.jev_context
                    )
                    # P1: LLM 段（升级路径）
                    self._last_signal_trace["llm"] = {
                        "provider": self._last_llm_provider
                        or self.config.default_provider,
                        "signal": original_signal,
                        "confidence": original_confidence,
                        "jev_context_injected": fast_result.jev_context is not None,
                    }
            else:
                original_signal, original_confidence = await self._get_llm_signal(
                    market_data
                )
                # P1: LLM 段（快车道关闭时）
                self._last_signal_trace["llm"] = {
                    "provider": self._last_llm_provider
                    or self.config.default_provider,
                    "signal": original_signal,
                    "confidence": original_confidence,
                    "jev_context_injected": False,
                }
```

（说明：trace 记录在各分支内就地写入，不存在 `fast_result` 跨分支引用问题。）

`__init__` 再加 `self._last_llm_provider: str = ""`；`_get_single_signal` 内 `provider = self.config.default_provider` 之后加 `self._last_llm_provider = provider`；fusion 路径（`_get_fusion_signal` 或等价处）加 `self._last_llm_provider = "fusion"`。

integrator 调用后（`result = self.integrator.process(...)` 之后）：

```python
            self._last_signal_trace["integrator"] = {
                "original_signal": original_signal,
                "original_confidence": confidence_float,
                "final_signal": result.final_signal,
                "final_confidence": result.final_confidence,
                "adjustments": list(result.adjustments_made or []),
            }
```

新增方法（`get_signal` 之后）：

```python
    def get_last_signal_trace(self) -> Dict[str, Any]:
        """返回本次 get_signal 的信号溯源（P1 决策日志数据源；未调用过返回 {}）。"""
        import copy

        return copy.deepcopy(self._last_signal_trace)
```

- [ ] **Step 4: 运行确认通过 + Jev 回归**

Run: `pytest tests/unit/test_ai_client_signal_trace.py tests/unit/test_ai_client_fast_lane.py tests/unit/test_jev_fast_lane.py -v`
Expected: 全 PASS（FastLaneResult 加字段不破坏既有测试——新字段有默认值）

- [ ] **Step 5: 提交**

```bash
git add alpha_trading_bot/ai/client.py alpha_trading_bot/ai/jev/fast_lane.py tests/unit/test_ai_client_signal_trace.py
git commit -m "feat(p1): AIClient 信号溯源 get_last_signal_trace + FastLaneResult noul 字段"
```

---

### Task 6: DecisionJournal（JSONL 追加 + 回填 + 保留期）

**Files:**
- Create: `alpha_trading_bot/core/decision_journal.py`
- Test: `tests/unit/test_decision_journal.py`

**Interfaces:**
- Produces:
  - `DecisionJournal(enabled: bool, data_dir: Optional[Path] = None)`
  - 文件：`resolve_state_data_dir(data_dir) / "decision_journal-YYYY-MM-DD.jsonl"`（按日轮转；init 时清理 90 天前文件）
  - `record_cycle(entry: Dict[str, Any]) -> None`：追加一行 `{"type": "cycle", "ts": "YYYY-MM-DD HH:MM:SS", ...entry}`
  - `backfill(current_ts: datetime, current_price: float) -> int`：扫描**当天+前一天**文件，对满足 `current_ts - ts ∈ [3h50m, 4h10m]`（T+4h）或 `[23h50m, 24h10m]`（T+24h）的 cycle 记录，追加一行 `{"type": "outcome", "ts": <原cycle ts>, "forward_return_4h": float, "forward_return_24h": float, "direction_correct_4h": Optional[bool], "direction_correct_24h": Optional[bool]}`；HOLD 的 direction_correct 为 None；返回回填行数
  - 所有 IO 失败吞异常 + WARNING（Review Focus #3）

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_decision_journal.py
"""DecisionJournal 测试（P1 决策日志）"""

import json
from datetime import datetime, timedelta
from pathlib import Path

from alpha_trading_bot.core.decision_journal import DecisionJournal

TS_FMT = "%Y-%m-%d %H:%M:%S"


def _read(journal_dir: Path, day: str) -> list:
    f = journal_dir / f"decision_journal-{day}.jsonl"
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l]


def test_disabled_writes_nothing(tmp_path) -> None:
    j = DecisionJournal(enabled=False, data_dir=tmp_path)
    j.record_cycle({"price": 1.0})
    assert list(tmp_path.glob("decision_journal-*.jsonl")) == []


def test_record_cycle_appends_jsonl(tmp_path) -> None:
    j = DecisionJournal(enabled=True, data_dir=tmp_path)
    j.record_cycle({"price": 84000.0, "final": "HOLD"})
    lines = _read(tmp_path, datetime.now().strftime("%Y-%m-%d"))
    assert len(lines) == 1
    assert lines[0]["type"] == "cycle"
    assert lines[0]["price"] == 84000.0
    assert "ts" in lines[0]


def test_backfill_4h_window(tmp_path) -> None:
    j = DecisionJournal(enabled=True, data_dir=tmp_path)
    now = datetime.now()
    old_ts = (now - timedelta(hours=4)).strftime(TS_FMT)
    # 直接写一条旧 cycle 记录（模拟 4 小时前的周期）
    day = (now - timedelta(hours=4)).strftime("%Y-%m-%d")
    with open(tmp_path / f"decision_journal-{day}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "cycle", "ts": old_ts, "price": 84000.0, "final": "BUY"}) + "\n")
    n = j.backfill(now, 86000.0)
    assert n == 1
    # outcome 行落在当前天文件
    outcomes = [l for l in _read(tmp_path, now.strftime("%Y-%m-%d")) if l["type"] == "outcome"]
    assert len(outcomes) == 1
    assert outcomes[0]["forward_return_4h"] == round((86000.0 - 84000.0) / 84000.0, 8)
    assert outcomes[0]["direction_correct_4h"] is True  # BUY 且正收益


def test_backfill_hold_direction_none(tmp_path) -> None:
    j = DecisionJournal(enabled=True, data_dir=tmp_path)
    now = datetime.now()
    old_ts = (now - timedelta(hours=4)).strftime(TS_FMT)
    day = (now - timedelta(hours=4)).strftime("%Y-%m-%d")
    with open(tmp_path / f"decision_journal-{day}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "cycle", "ts": old_ts, "price": 84000.0, "final": "HOLD"}) + "\n")
    j.backfill(now, 86000.0)
    outcomes = [l for l in _read(tmp_path, now.strftime("%Y-%m-%d")) if l["type"] == "outcome"]
    assert outcomes[0]["direction_correct_4h"] is None


def test_backfill_across_day_boundary(tmp_path) -> None:
    # Review Focus #4: 23:50 的 cycle 在次日 03:50 回填 T+4h
    now = datetime(2026, 10, 4, 3, 50, 0)
    j = DecisionJournal(enabled=True, data_dir=tmp_path)
    old = datetime(2026, 10, 3, 23, 50, 0)
    f = tmp_path / "decision_journal-2026-10-03.jsonl"
    f.write_text(json.dumps({"type": "cycle", "ts": old.strftime(TS_FMT), "price": 84000.0, "final": "BUY"}) + "\n", encoding="utf-8")
    n = j.backfill(now, 84800.0)
    assert n == 1


def test_backfill_no_double_write(tmp_path) -> None:
    j = DecisionJournal(enabled=True, data_dir=tmp_path)
    now = datetime.now()
    old_ts = (now - timedelta(hours=4)).strftime(TS_FMT)
    day = (now - timedelta(hours=4)).strftime("%Y-%m-%d")
    with open(tmp_path / f"decision_journal-{day}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "cycle", "ts": old_ts, "price": 84000.0, "final": "BUY"}) + "\n")
    j.backfill(now, 86000.0)
    j.backfill(now + timedelta(minutes=15), 86100.0)  # 第二次同窗口
    outcomes = [l for l in _read(tmp_path, (now + timedelta(minutes=15)).strftime("%Y-%m-%d")) if l["type"] == "outcome"]
    assert len(outcomes) == 1  # 已有 outcome 的不重复写


def test_write_failure_does_not_raise(tmp_path) -> None:
    # Review Focus #3: 写失败吞异常 + WARNING，不抛出
    j = DecisionJournal(enabled=True, data_dir=tmp_path)
    import unittest.mock as mock
    with mock.patch("pathlib.Path.open", side_effect=OSError("disk full")):
        j.record_cycle({"price": 1.0})  # 不得抛异常
    j.backfill(datetime.now(), 1.0)  # 同样不得抛


def test_retention_prunes_old_files(tmp_path) -> None:
    j = DecisionJournal(enabled=True, data_dir=tmp_path)
    old = tmp_path / "decision_journal-2026-01-01.jsonl"
    old.write_text("{}\n", encoding="utf-8")
    DecisionJournal(enabled=True, data_dir=tmp_path)  # 重新 init 触发清理
    assert not old.exists()
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/unit/test_decision_journal.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

```python
# alpha_trading_bot/core/decision_journal.py
"""决策日志（P1，2026-10-04 双向交易 spec）

每周期追加一行 JSONL（各层信号 + 价格），并在后续周期回填 T+4h/T+24h
前向收益（追加 outcome 行，按 ts join）。文件按日轮转，保留 90 天。
所有 IO 失败吞异常 + WARNING：决策日志故障永不中断交易周期。
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from .state_persistence import resolve_state_data_dir

logger = logging.getLogger(__name__)

FILE_PREFIX = "decision_journal-"
RETENTION_DAYS = 90
# 15 分钟周期的回填容错窗口（±10 分钟）
WINDOW_4H = (timedelta(hours=4) - timedelta(minutes=10), timedelta(hours=4) + timedelta(minutes=10))
WINDOW_24H = (timedelta(hours=24) - timedelta(minutes=10), timedelta(hours=24) + timedelta(minutes=10))

TS_FMT = "%Y-%m-%d %H:%M:%S"


class DecisionJournal:
    """JSONL 决策日志（追加式，单进程写入）。"""

    def __init__(self, enabled: bool, data_dir: Optional[Path] = None) -> None:
        self._enabled = enabled
        self._dir = resolve_state_data_dir(data_dir)
        if self._enabled:
            try:
                self._dir.mkdir(parents=True, exist_ok=True)
                self._prune_old_files()
            except OSError as e:
                logger.warning("[决策日志] 初始化目录失败，日志功能禁用: %s", e)
                self._enabled = False

    # ---- 写入 ----

    def record_cycle(self, entry: Dict[str, Any]) -> None:
        """追加一条 cycle 记录（ts 取当前时间）。"""
        if not self._enabled:
            return
        record = {"type": "cycle", "ts": datetime.now().strftime(TS_FMT)}
        record.update(entry)
        self._append(record, datetime.now())

    def backfill(self, current_ts: datetime, current_price: float) -> int:
        """回填 4h/24h 前向收益，返回本次回填的 outcome 行数。

        先汇总当天+前一天全部记录，done 集合跨文件去重（防跨天重复回填）。
        """
        if not self._enabled:
            return 0
        days = {
            current_ts.strftime("%Y-%m-%d"),
            (current_ts - timedelta(days=1)).strftime("%Y-%m-%d"),
        }
        all_records: list = []
        for day in sorted(days):
            f = self._dir / f"{FILE_PREFIX}{day}.jsonl"
            if not f.exists():
                continue
            try:
                lines = f.read_text(encoding="utf-8").splitlines()
            except OSError as e:
                logger.warning("[决策日志] 读取 %s 失败: %s", f.name, e)
                continue
            all_records.extend(self._parse(lines))
        done_4h = {
            r["ts"]
            for r in all_records
            if r.get("type") == "outcome" and r.get("forward_return_4h") is not None
        }
        done_24h = {
            r["ts"]
            for r in all_records
            if r.get("type") == "outcome" and r.get("forward_return_24h") is not None
        }
        written = 0
        for rec in all_records:
            if rec.get("type") != "cycle":
                continue
            try:
                entry_ts = datetime.strptime(rec["ts"], TS_FMT)
            except (KeyError, ValueError):
                continue
            age = current_ts - entry_ts
            for label, window, key, done in (
                ("4h", WINDOW_4H, "forward_return_4h", done_4h),
                ("24h", WINDOW_24H, "forward_return_24h", done_24h),
            ):
                if not (window[0] <= age <= window[1]) or rec["ts"] in done:
                    continue
                try:
                    base_price = float(rec.get("price", 0))
                except (TypeError, ValueError):
                    continue
                if base_price <= 0:
                    continue
                fwd = round((current_price - base_price) / base_price, 8)
                final_sig = str(rec.get("final", "")).strip().upper()
                if final_sig == "BUY":
                    correct: Optional[bool] = fwd > 0.001
                elif final_sig in ("SELL", "SHORT"):
                    correct = fwd < -0.001
                else:
                    correct = None
                outcome = {
                    "type": "outcome",
                    "ts": rec["ts"],
                    key: fwd,
                    f"direction_correct_{label}": correct,
                }
                self._append(outcome, current_ts)
                done.add(rec["ts"])
                written += 1
        return written

    # ---- 内部 ----

    @staticmethod
    def _parse(lines: list) -> list:
        out = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # 半写/损坏行跳过
        return out

    def _append(self, record: Dict[str, Any], ts: datetime) -> None:
        try:
            f = self._dir / f"{FILE_PREFIX}{ts.strftime('%Y-%m-%d')}.jsonl"
            with f.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning("[决策日志] 写入失败（周期不受影响）: %s", e)

    def _prune_old_files(self) -> None:
        cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
        for f in self._dir.glob(f"{FILE_PREFIX}*.jsonl"):
            try:
                day = datetime.strptime(f.stem.replace(FILE_PREFIX, ""), "%Y-%m-%d")
            except ValueError:
                continue
            if day < cutoff:
                try:
                    f.unlink()
                except OSError:
                    pass
```

（说明：`_prune_old_files` 只在 `__init__` 跑一次；`backfill` 的 `done_*` 集合扫描范围含当天文件，保证同窗口二次 backfill 不重复写——`test_backfill_no_double_write` 依赖此行为。）

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/unit/test_decision_journal.py -v`
Expected: 8 PASS

- [ ] **Step 5: 提交**

```bash
git add alpha_trading_bot/core/decision_journal.py tests/unit/test_decision_journal.py
git commit -m "feat(p1): DecisionJournal JSONL 决策日志（轮转/回填/90天保留/失败不阻断）"
```

---

### Task 7: Bot 接入决策日志

**Files:**
- Modify: `alpha_trading_bot/core/bot.py`（`__init__` 创建 journal；周期开始处 `backfill`；`_execute_signal` 之后 `record_cycle`；异常路径也记录）
- Test: `tests/unit/test_bot_decision_journal.py`

**Interfaces:**
- Consumes: `DecisionJournal`（Task 6）；`AIClient.get_last_signal_trace()`（Task 5）；`ExecutionResult`（Task 3）；`config.trading.decision_journal_enabled`（Task 1）
- Produces: 每周期一条 JSONL cycle 记录，字段：
  ```python
  {"market": {"price", "rsi", "atr", "change_24h"},
   "jev": {...}|None, "llm": {...}|None, "integrator": {...}|None,
   "cache_hit": bool,
   "execution": {"action", "detail"},
   "drawdown_halted": bool}
  ```
  其中 `final` 字段 = integrator 的 final_signal（供 backfill 判方向；缺失时用 execution 推断）

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_bot_decision_journal.py
"""TradingBot × DecisionJournal 集成测试（P1）"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from alpha_trading_bot.config.models import Config, ExchangeConfig, TradingConfig
from alpha_trading_bot.core.bot import TradingBot


def _make_bot(tmp_path: Path) -> TradingBot:
    config = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(test_mode=True),
    )
    bot = TradingBot(config)
    bot._exchange = MagicMock()
    bot._exchange.get_balance = AsyncMock(return_value=1000.0)
    bot._exchange.create_order = AsyncMock(return_value="")
    bot._stop_loss_manager = None
    # 模拟 AIClient 溯源
    bot._ai_client = MagicMock()
    bot._ai_client.get_last_signal_trace = MagicMock(
        return_value={
            "cache_hit": False,
            "jev": {"choice": "hold", "confidence": 0.95, "reason": "adopt"},
            "llm": None,
            "integrator": {
                "original_signal": "hold",
                "original_confidence": 0.95,
                "final_signal": "HOLD",
                "final_confidence": 0.95,
                "adjustments": [],
            },
        }
    )
    return bot


def _journal_lines(tmp_path: Path) -> list:
    lines = []
    for f in tmp_path.glob("decision_journal-*.jsonl"):
        lines += [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l]
    return lines


@pytest.mark.asyncio
async def test_cycle_writes_journal_entry(tmp_path) -> None:
    bot = _make_bot(tmp_path)
    market_data = {
        "price": 84000.0,
        "rsi": 50.0,
        "atr": 300.0,
        "change_24h_percent": 0.5,
    }
    await bot._record_decision(market_data, "HOLD", None)
    # 无持仓路径：execution 由调用方传入
    from alpha_trading_bot.core.bot import ExecutionResult
    await bot._record_decision(market_data, "HOLD", ExecutionResult("none"))
    entries = [l for l in _journal_lines(tmp_path) if l["type"] == "cycle"]
    assert len(entries) == 2
    e = entries[-1]
    assert e["market"]["price"] == 84000.0
    assert e["jev"]["choice"] == "hold"
    assert e["execution"]["action"] == "none"
    assert e["final"] == "HOLD"


@pytest.mark.asyncio
async def test_journal_disabled_writes_nothing(tmp_path, monkeypatch) -> None:
    bot = _make_bot(tmp_path)
    bot.config.trading.decision_journal_enabled = False
    bot._decision_journal = None  # 模拟未启用
    market_data = {"price": 84000.0}
    from alpha_trading_bot.core.bot import ExecutionResult
    await bot._record_decision(market_data, "HOLD", ExecutionResult("none"))
    assert _journal_lines(tmp_path) == []


@pytest.mark.asyncio
async def test_record_survives_journal_failure(tmp_path) -> None:
    # Review Focus #3：journal 内部抛异常也不得中断周期
    bot = _make_bot(tmp_path)
    import unittest.mock as mock
    with mock.patch.object(
        bot._decision_journal, "record_cycle", side_effect=RuntimeError("boom")
    ):
        from alpha_trading_bot.core.bot import ExecutionResult
        await bot._record_decision({"price": 1.0}, "HOLD", ExecutionResult("none"))  # 不抛
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/unit/test_bot_decision_journal.py -v`
Expected: FAIL（`_record_decision` / `_decision_journal` 不存在）

- [ ] **Step 3: 实现**

`bot.py`：import `DecisionJournal`；`__init__` 中 drawdown guard 之后：

```python
        # P1 决策日志（各层信号 + T+4h/24h 结果回填）
        self._decision_journal = (
            DecisionJournal(enabled=config.trading.decision_journal_enabled)
            if config.trading.decision_journal_enabled
            else None
        )
```

新增方法（`_check_drawdown` 旁）：

```python
    async def _record_decision(
        self,
        market_data: Dict[str, Any],
        signal: str,
        execution: Optional[ExecutionResult],
    ) -> None:
        """记录本周期决策日志（P1）：任何异常都不得中断周期。"""
        if self._decision_journal is None:
            return
        try:
            trace = (
                self._ai_client.get_last_signal_trace()
                if self._ai_client is not None
                else {}
            )
            integrator = trace.get("integrator") or {}
            final = integrator.get("final_signal") or signal
            entry = {
                "market": {
                    "price": market_data.get("price"),
                    "rsi": (market_data.get("technical") or {}).get("rsi")
                    or market_data.get("rsi"),
                    "atr": (market_data.get("technical") or {}).get("atr")
                    or market_data.get("atr"),
                    "change_24h": market_data.get("change_24h_percent"),
                },
                "jev": trace.get("jev"),
                "llm": trace.get("llm"),
                "integrator": integrator,
                "cache_hit": bool(trace.get("cache_hit")),
                "final": str(final).upper(),
                "execution": {
                    "action": execution.action if execution else "error",
                    "detail": execution.detail if execution else "",
                },
                "drawdown_halted": bool(
                    self._drawdown_status is not None and self._drawdown_status.halted
                ),
            }
            self._decision_journal.record_cycle(entry)
        except Exception as e:
            logger.warning("[决策日志] 记录失败（周期不受影响）: %s", e)
```

周期主流程中：
0. `try:` 块之前（"# 4. 获取AI信号" 注释处）声明 `signal: Optional[str] = None`——异常路径会引用它，若 get_signal 抛异常时未定义会 NameError
1. 市场数据获取之后、持仓同步之前：

```python
        # P1: 回填 4h/24h 前向收益（用本周期最新价格）
        if self._decision_journal is not None:
            from datetime import datetime as _dt

            self._decision_journal.backfill(_dt.now(), current_price)
```

（`current_price` 取自 market_data：现有代码在"格式化显示"处已有 `current_price = market_data.get("price")` 等价赋值，复用它。）

2. 正常路径 `await self._execute_signal(...)` 之后：

```python
            await self._record_decision(market_data, signal, execution_result)
```

（`_execute_signal` 的返回值接住：`execution_result = await self._execute_signal(signal, current_price, has_position)`）

3. 异常路径（`except Exception as e: ... return` 处）return 之前：

```python
            await self._record_decision(
                market_data, signal, ExecutionResult("error", f"{e}")
            )
```

- [ ] **Step 4: 运行确认通过 + 全量回归**

Run: `pytest tests/unit/test_bot_decision_journal.py -v && pytest tests/unit/ -q`
Expected: 全 PASS（既有测试零破坏——journal 失败不阻断 + 默认开关下行为不变）

- [ ] **Step 5: 提交**

```bash
git add alpha_trading_bot/core/bot.py tests/unit/test_bot_decision_journal.py
git commit -m "feat(p1): TradingBot 周期接入决策日志（记录+回填，失败不阻断）"
```

---

### Task 8: 报表脚本 scripts/decision_journal_report.py

**Files:**
- Create: `scripts/decision_journal_report.py`（可执行脚本 + 可导入的聚合函数）
- Test: `tests/unit/test_decision_journal_report.py`

**Interfaces:**
- Consumes: `data/trading_state/decision_journal-*.jsonl`（Task 6 产出）
- Produces: 模块级纯函数（可单测）：
  - `load_journal(days_dir: Path, since: Optional[str] = None) -> Tuple[List[Dict], Dict[str, Dict]]`（cycle 记录 + ts→outcome 映射）
  - `agg_by(cycles, key_fn) -> List[Dict]`：分组统计 {count, avg_fwd_4h, win_rate_4h（direction_correct 非 None 的样本）}
  - CLI：`python scripts/decision_journal_report.py [--days 14] [--jev-conf 0.55]` 输出四张表：
    1. Jev：choice × conf 档（<0.55 / 0.55-0.75 / ≥0.75）→ 计数 / T+4h 平均收益 / 胜率
    2. LLM：signal → 同上
    3. 最终信号：final → 同上
    4. 翻转守卫拦截复盘：`integrator.adjustments` 含"被阻止翻转"的 cycle → T+4h 表现

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_decision_journal_report.py
"""决策日志报表聚合函数测试（P1）"""

import json
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
from decision_journal_report import agg_by, load_journal  # noqa: E402

TS_FMT = "%Y-%m-%d %H:%M:%S"


def _write_day(dir_path: Path, day: str, records) -> None:
    (dir_path / f"decision_journal-{day}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )


def _cycle(ts, price, final, **extra):
    r = {"type": "cycle", "ts": ts, "price": price, "final": final}
    r.update(extra)
    return r


def test_load_journal_joins_outcomes(tmp_path) -> None:
    _write_day(tmp_path, "2026-10-01", [
        _cycle("2026-10-01 10:00:00", 100.0, "BUY",
               jev={"choice": "buy", "confidence": 0.6}),
        {"type": "outcome", "ts": "2026-10-01 10:00:00",
         "forward_return_4h": 0.02, "direction_correct_4h": True},
    ])
    cycles, outcomes = load_journal(tmp_path)
    assert len(cycles) == 1 and len(outcomes) == 1
    assert cycles[0]["forward_return_4h"] == 0.02


def test_agg_by_jev_conf_buckets(tmp_path) -> None:
    _write_day(tmp_path, "2026-10-01", [
        _cycle(f"2026-10-01 10:{i:02d}:00", 100.0, "HOLD",
               jev={"choice": "buy", "confidence": c})
        for i, c in enumerate([0.5, 0.6, 0.8])
    ])
    _write_day(tmp_path, "2026-10-01", [
        {"type": "outcome", "ts": f"2026-10-01 10:{i:02d}:00",
         "forward_return_4h": v, "direction_correct_4h": v > 0.001}
        for i, v in enumerate([0.01, 0.02, -0.01])
    ])
    cycles, _ = load_journal(tmp_path)

    def key_fn(c):
        jev = c.get("jev") or {}
        conf = jev.get("confidence", 0.0)
        bucket = "<0.55" if conf < 0.55 else ("0.55-0.75" if conf < 0.75 else ">=0.75")
        return f"jev:{jev.get('choice', '?')}:{bucket}"

    rows = agg_by(cycles, key_fn)
    by_key = {r["key"]: r for r in rows}
    assert by_key["jev:buy:<0.55"]["count"] == 1
    assert by_key["jev:buy:0.55-0.75"]["count"] == 1
    assert by_key["jev:buy:>=0.75"]["count"] == 1
    assert by_key["jev:buy:0.55-0.75"]["avg_fwd_4h"] == 0.02
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/unit/test_decision_journal_report.py -v`
Expected: FAIL（脚本不存在）

- [ ] **Step 3: 实现**

```python
#!/usr/bin/env python3
"""决策日志周报（P1）：各层信号的分层胜率/收益统计。

用法:
  python scripts/decision_journal_report.py [--days 14] [--jev-conf 0.55]

输出四张表：Jev 分档 / LLM 信号 / 最终信号 / 翻转守卫拦截复盘。
数据源: data/trading_state/decision_journal-*.jsonl（Task 6 产出）。
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
    """读取 journal 文件，返回 (cycle 记录列表[已 join outcome], ts→outcome 映射)。"""
    cutoff = None
    if since:
        cutoff = datetime.strptime(since, TS_FMT)
    cycles: List[Dict[str, Any]] = []
    outcomes: Dict[str, Dict[str, Any]] = {}
    for f in sorted(days_dir.glob("decision_journal-*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") == "outcome":
                ts = rec.get("ts")
                if ts:
                    prev = outcomes.get(ts, {})
                    prev.update(rec)
                    outcomes[ts] = prev
            elif rec.get("type") == "cycle":
                ts = rec.get("ts")
                if cutoff and ts and ts < cutoff.strftime(TS_FMT):
                    continue
                o = outcomes.get(ts)
                if o:
                    for k, v in o.items():
                        if k not in rec:
                            rec[k] = v
                cycles.append(rec)
    return cycles, outcomes


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
        fwds = [i.get("forward_return_4h") for i in items if i.get("forward_return_4h") is not None]
        correct = [i["direction_correct_4h"] for i in items if i.get("direction_correct_4h") is not None]
        rows.append(
            {
                "key": key,
                "count": len(items),
                "with_outcome": len(fwds),
                "avg_fwd_4h": round(sum(fwds) / len(fwds), 6) if fwds else None,
                "win_rate_4h": round(sum(1 for x in correct if x) / len(correct), 4)
                if correct
                else None,
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
        print(
            f"  {r['key']:40s} {r['count']:5d} {r['with_outcome']:5d} "
            f"{('%+.4f%%' % (r['avg_fwd_4h'] * 100)) if r['avg_fwd_4h'] is not None else 'n/a':>10s} "
            f"{('%d%%' % (r['win_rate_4h'] * 100)) if r['win_rate_4h'] is not None else 'n/a':>9s}"
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

    _print_table(f"Jev 分档（近 {args.days} 天，conf 阈值 {args.jev_conf}）", agg_by(cycles, jev_key))
    _print_table("LLM 信号", agg_by(cycles, llm_key))
    _print_table("最终信号", agg_by(cycles, final_key))

    blocked = [
        c
        for c in cycles
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
```

- [ ] **Step 4: 运行确认通过 + 冒烟**

Run: `pytest tests/unit/test_decision_journal_report.py -v && python scripts/decision_journal_report.py --days 1`
Expected: 测试 PASS；脚本对空数据输出"无数据"且退出码 0

- [ ] **Step 5: 提交**

```bash
git add scripts/decision_journal_report.py tests/unit/test_decision_journal_report.py
git commit -m "feat(p1): 决策日志周报脚本（Jev/LLM/最终信号/守卫拦截分层胜率）"
```

---

### Task 9: 全量回归 + mypy + 收尾

**Files:**
- 无新代码（验证任务）；如发现问题，修最小范围

- [ ] **Step 1: 全量单测**

Run: `pytest tests/unit/ -q`
Expected: 全 PASS（零回归）

- [ ] **Step 2: 类型检查**

Run: `mypy alpha_trading_bot/`
Expected: 无新增错误（既有错误保持既有状态，不引入新错误）

- [ ] **Step 3: 格式化**

Run: `black alpha_trading_bot/ scripts/decision_journal_report.py && isort alpha_trading_bot/ --profile black`
Expected: 格式化后重跑 `pytest tests/unit/ -q` 仍全 PASS

- [ ] **Step 4: 行为不变冒烟（关键验收）**

在本地以 `AI_FAST_LANE=off` + 默认风险参数跑 1 个周期（TEST_MODE=true），核对日志与 P1 前行为一致：
- 无 `[风控总闸] OPEN`（高水位刚建立）
- `data/trading_state/` 新增 `drawdown_baseline.json` + `decision_journal-YYYY-MM-DD.jsonl`（各 1 条记录）
- 信号链路日志与改动前逐行一致（Jev/LLM/集成器部分）

- [ ] **Step 5: 提交（如有格式化/修复改动）**

```bash
git add -A && git commit -m "chore(p1): 格式化与回归修复"  # 无改动则跳过
```

- [ ] **Step 6: 向用户报告 P1 完成**

报告内容：测试/mypy 结果、冒烟日志摘要、上线方式（`docker compose up -d --build` 后观察 1 周决策日志；`RISK_DRAWDOWN_HALT`/`DECISION_JOURNAL` 可调）、P2 启动条件（1 周基线数据 + `scripts/decision_journal_report.py` 首份周报）。
