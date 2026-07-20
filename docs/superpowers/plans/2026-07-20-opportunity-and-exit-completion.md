# Opportunity And Exit Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete partial take-profit, AI-HOLD override outcome metrics, and dynamic cooldown while keeping the trading system conservative.

**Architecture:** `AdaptiveTradingBot` continues to orchestrate decisions and orders. `DecisionEngine` marks AI-HOLD override metadata, `PerformanceTracker` records override outcomes, and `PositionManager` keeps local amount in sync after partial exits.

**Tech Stack:** Python 3.8+, pytest, pytest-asyncio, existing OKX exchange adapter interfaces.

## Global Constraints

- Use TDD: write failing tests before production changes.
- Do not add new exchange dependencies or database migrations.
- Keep one take-profit algo order per entry; use partial size by default.
- Keep long close side `sell` and short close side `buy`.
- Preserve full cooldown for high-risk long re-entry and real stop-loss losses.
- After modifying code files, run `graphify update .`.

---

### Task 1: Dynamic Cooldown

**Files:**
- Modify: `tests/unit/test_adaptive_bot_cooldown.py`
- Modify: `alpha_trading_bot/core/adaptive_bot.py`

**Interfaces:**
- Produces: `AdaptiveTradingBot._last_close_pnl_percent: float`
- Consumes: `AdaptiveTradingBot._get_direction_cooldown_seconds(final_signal, market_data, side) -> int`

- [x] **Step 1: Write failing tests**

Add tests for small-loss/breakeven `600s` cooldown and high-quality opposite-direction `300s` cooldown.

- [x] **Step 2: Run tests to verify they fail**

Run: `pytest -o addopts= tests/unit/test_adaptive_bot_cooldown.py -v`

- [x] **Step 3: Implement dynamic cooldown**

Track last close PnL percent and branch cooldown by loss size, profitability, quality, and direction.

- [x] **Step 4: Run tests to verify they pass**

Run: `pytest -o addopts= tests/unit/test_adaptive_bot_cooldown.py -v`

### Task 2: AI-HOLD Override Metrics

**Files:**
- Modify: `tests/unit/test_decision_engine_hold_override.py`
- Modify: `tests/unit/test_adaptive_execution_safety.py`
- Modify: `tests/unit/test_ml_dynamic_weights.py`
- Modify: `alpha_trading_bot/core/decision_engine.py`
- Modify: `alpha_trading_bot/core/adaptive_bot.py`
- Modify: `alpha_trading_bot/ai/adaptive/performance_tracker.py`

**Interfaces:**
- Produces: decision result `metadata.ai_hold_override: bool`
- Produces: `PerformanceTracker.get_ai_hold_override_metrics() -> Dict[str, Any]`
- Extends: `PerformanceTracker.record_trade(..., metadata: Optional[Dict[str, Any]] = None)`

- [x] **Step 1: Write failing tests**

Add metadata tests for HOLD override decisions and outcome metrics tests for win/loss closes.

- [x] **Step 2: Run tests to verify they fail**

Run: `pytest -o addopts= tests/unit/test_decision_engine_hold_override.py tests/unit/test_ml_dynamic_weights.py -v`

- [x] **Step 3: Implement metadata and metrics**

Mark override decisions, pass metadata into trade records, persist metrics in memory and JSON history.

- [x] **Step 4: Run tests to verify they pass**

Run: `pytest -o addopts= tests/unit/test_decision_engine_hold_override.py tests/unit/test_ml_dynamic_weights.py tests/unit/test_adaptive_execution_safety.py -v`

### Task 3: Partial Take-Profit And Remaining Position Tracking

**Files:**
- Modify: `tests/unit/test_adaptive_execution_safety.py`
- Modify: `tests/unit/test_smart_stop_loss.py`
- Modify: `alpha_trading_bot/config/models.py`
- Modify: `alpha_trading_bot/core/adaptive_bot.py`
- Modify: `alpha_trading_bot/core/position_manager.py`

**Interfaces:**
- Produces: `StopLossConfig.take_profit_partial_ratio: float = 0.5`
- Consumes: `PositionManager.update_from_exchange(position_data: dict) -> None`

- [x] **Step 1: Write failing tests**

Add tests for partial take-profit order amount and reduced live amount sync.

- [x] **Step 2: Run tests to verify they fail**

Run: `pytest -o addopts= tests/unit/test_adaptive_execution_safety.py tests/unit/test_smart_stop_loss.py -v`

- [x] **Step 3: Implement partial amount and sync handling**

Use `filled_amount * take_profit_partial_ratio` for TP order size, validate the ratio, and preserve reduced amount from exchange sync.

- [x] **Step 4: Run tests to verify they pass**

Run: `pytest -o addopts= tests/unit/test_adaptive_execution_safety.py tests/unit/test_smart_stop_loss.py -v`

### Task 4: Verification

**Files:**
- Verify only.

- [x] **Step 1: Run full tests**

Run: `pytest -o addopts=`

- [x] **Step 2: Run whitespace/syntax checks**

Run: `git diff --check`

- [x] **Step 3: Update graphify**

Run: `graphify update .`
