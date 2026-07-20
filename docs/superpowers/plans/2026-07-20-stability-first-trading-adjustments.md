# Stability-First Trading Adjustments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the live trading flow more stable by cleaning up both stop-loss and take-profit protection orders, deduplicating active-close audit logs, and fitting default profit/stop behavior to low-volatility trading.

**Architecture:** Keep changes inside existing execution, position, and configuration boundaries. `AdaptiveTradingBot` remains the orchestrator, `PositionRecoveryManager` owns exchange-side protection-order cancellation, `PositionManager` owns local protection state, and `PositionCloseAuditor` owns disappeared-position audit decisions.

**Tech Stack:** Python 3.8+, pytest, pytest-asyncio, existing OKX exchange adapter interfaces.

## Global Constraints

- Follow existing Python style: Black line length 88, absolute project imports, type hints on new public signatures.
- Use TDD: write each failing test before production code.
- Do not increase leverage, max position, or remove cooldowns.
- Do not add new exchange dependencies or database migrations.
- Long protection orders must close with `sell`; short protection orders must close with `buy`.
- After modifying code files, run `graphify update .`.

---

### Task 1: Protection Order Lifecycle

**Files:**
- Modify: `tests/unit/test_adaptive_execution_safety.py`
- Modify: `alpha_trading_bot/core/position_manager.py`
- Modify: `alpha_trading_bot/core/position_recovery.py`
- Modify: `alpha_trading_bot/core/adaptive_bot.py`

**Interfaces:**
- Consumes: `PositionManager.set_stop_order(stop_order_id: str, stop_price: float = 0.0) -> None`, `PositionManager.set_take_profit_order(take_profit_order_id: str, take_profit_price: float = 0.0) -> None`
- Produces: `PositionManager.take_profit_order_id -> Optional[str]`, `PositionManager.last_take_profit_price -> float`, `PositionManager.clear_protection_orders() -> None`, `PositionRecoveryManager.cancel_protection_orders_before_close() -> None`

- [x] **Step 1: Write the failing tests**

```python
def test_clear_position_clears_take_profit_state(tmp_path: Any) -> None:
    pm = PositionManager(_live_config(), data_dir=tmp_path)
    pm.update_position(0.01, 100.0, "BTC/USDT:USDT", "long")
    pm.set_stop_order("sl-1", 99.0)
    pm.set_take_profit_order("tp-1", 100.8)

    pm.clear_position()

    assert pm.stop_order_id is None
    assert pm.last_stop_price == 0.0
    assert pm.take_profit_order_id is None
    assert pm.last_take_profit_price == 0.0
```

```python
async def test_close_cancels_stop_loss_and_take_profit_before_market_close(
    tmp_path: Any,
) -> None:
    bot = AdaptiveTradingBot(_live_config())
    _wire_execution_deps(bot, tmp_path, _RiskAllows())
    bot.position_manager.update_position(0.01, 100.0, "BTC/USDT:USDT", "long")
    bot.position_manager.set_stop_order("sl-local", 99.5)
    bot.position_manager.set_take_profit_order("tp-local", 100.8)
```

- [x] **Step 2: Run tests to verify they fail**

Run:
`pytest tests/unit/test_adaptive_execution_safety.py::test_clear_position_clears_take_profit_state tests/unit/test_adaptive_execution_safety.py::test_close_cancels_stop_loss_and_take_profit_before_market_close -v`

Expected: FAIL because take-profit properties and broad protection cancellation do not exist.

- [x] **Step 3: Write minimal implementation**

Add read-only take-profit properties, clear both local protection states, add `cancel_protection_orders_before_close`, keep `cancel_stop_loss_before_close` as a compatibility wrapper, and make `AdaptiveTradingBot._cancel_stop_loss_before_close` call the new method.

- [x] **Step 4: Run tests to verify they pass**

Run:
`pytest tests/unit/test_adaptive_execution_safety.py::test_clear_position_clears_take_profit_state tests/unit/test_adaptive_execution_safety.py::test_close_cancels_stop_loss_and_take_profit_before_market_close -v`

Expected: PASS.

### Task 2: Close Audit Dedupe

**Files:**
- Create: `tests/unit/test_position_close_audit.py`
- Modify: `alpha_trading_bot/core/position_close_audit.py`
- Modify: `alpha_trading_bot/core/adaptive_bot.py`

**Interfaces:**
- Consumes: `PositionCloseAuditContext.remember(...) -> None`
- Produces: `PositionCloseAuditContext.mark_active_close(order_id: str = "") -> None`

- [x] **Step 1: Write the failing tests**

```python
def test_audit_ignores_static_algo_config_without_trigger_evidence() -> None:
    context = PositionCloseAuditContext(stop_order_id="sl-1")
    auditor = PositionCloseAuditor(context)
    history = [{"id": "sl-1", "info": {"algoId": "sl-1", "slTriggerPx": "99950"}}]

    assert auditor.find_close_algo_history(history) is None
```

```python
async def test_active_close_skips_disappeared_position_algo_audit(caplog: Any) -> None:
    context = PositionCloseAuditContext(side="long", entry_price=100.0)
    context.mark_active_close("close-1")
    auditor = PositionCloseAuditor(context)
```

- [x] **Step 2: Run tests to verify they fail**

Run:
`pytest tests/unit/test_position_close_audit.py -v`

Expected: FAIL because active-close marker does not exist and static trigger fields are treated as triggered history.

- [x] **Step 3: Write minimal implementation**

Add active-close fields to the dataclass, reset them in `remember`, skip audit when active close is marked, and require actual trigger/fill evidence before returning algo history.

- [x] **Step 4: Run tests to verify they pass**

Run:
`pytest tests/unit/test_position_close_audit.py -v`

Expected: PASS.

### Task 3: Low-Volatility Defaults And Stop Tightening Gate

**Files:**
- Modify: `tests/unit/test_smart_stop_loss.py`
- Modify: `alpha_trading_bot/config/models.py`
- Modify: `alpha_trading_bot/core/take_profit_calculator.py`
- Modify: `alpha_trading_bot/core/position_manager.py`
- Modify: `alpha_trading_bot/core/adaptive_bot.py`

**Interfaces:**
- Consumes: `StopLossConfig.validate() -> List[str]`
- Produces: `StopLossConfig.min_profit_to_tighten_stop_percent: float = 0.003`

- [x] **Step 1: Write the failing tests**

```python
def test_default_take_profit_percent_is_low_volatility_target() -> None:
    assert StopLossConfig().take_profit_percent == pytest.approx(0.008)
```

```python
def test_entry_based_stop_waits_until_min_profit_to_tighten() -> None:
    pm = _make_position_manager(entry_price=100000.0, side="long")
    assert pm.calculate_stop_price(100200.0) == pytest.approx(100000.0 * 0.9995)
```

```python
def test_entry_based_stop_tightens_after_min_profit_gate() -> None:
    pm = _make_position_manager(entry_price=100000.0, side="long")
    assert pm.calculate_stop_price(100400.0) == pytest.approx(100000.0 * 0.9998)
```

- [x] **Step 2: Run tests to verify they fail**

Run:
`pytest tests/unit/test_smart_stop_loss.py -v`

Expected: FAIL for the old 6% default and old 0.1% tightening behavior.

- [x] **Step 3: Write minimal implementation**

Change default/env fallback take-profit to `0.008`, add nonnegative validation for `min_profit_to_tighten_stop_percent`, and gate entry-based/traditional trailing stop tightening until unrealized profit reaches the configured threshold.

- [x] **Step 4: Run tests to verify they pass**

Run:
`pytest tests/unit/test_smart_stop_loss.py -v`

Expected: PASS.

### Task 4: Focused Regression Verification

**Files:**
- Verify only.

**Interfaces:**
- Consumes: completed Tasks 1-3.
- Produces: verified stability-first batch.

- [x] **Step 1: Run focused tests**

Run:
`pytest tests/unit/test_adaptive_execution_safety.py tests/unit/test_position_close_audit.py tests/unit/test_smart_stop_loss.py tests/unit/test_adaptive_stop_loss_retry.py tests/unit/test_risk_reward_calculator.py -v`

Expected: PASS.

- [x] **Step 2: Update graphify**

Run:
`graphify update .`

Expected: completes successfully.

- [x] **Step 3: Check worktree**

Run:
`git status --short`

Expected: only planned files changed.
