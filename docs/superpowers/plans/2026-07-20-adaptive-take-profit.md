# Adaptive Take Profit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a conservative adaptive first take-profit target from ATR and nearby support/resistance.

**Architecture:** Keep one take-profit algo order after entry. `TakeProfitCalculator` owns target selection; `AdaptiveTradingBot` passes current `market_data`; `StopLossConfig` owns tunable limits and fallback.

**Tech Stack:** Python 3.8+, pytest, pytest-asyncio, existing OKX exchange adapter interfaces.

## Global Constraints

- Use TDD: write failing tests before production changes.
- Preserve the existing single take-profit order lifecycle.
- Long take-profit close side remains `sell`; short take-profit close side remains `buy`.
- Fallback fixed take-profit remains `0.008`.
- After modifying code files, run `graphify update .`.

---

### Task 1: Adaptive Take-Profit Calculator

**Files:**
- Modify: `tests/unit/test_smart_stop_loss.py`
- Modify: `alpha_trading_bot/config/models.py`
- Modify: `alpha_trading_bot/core/take_profit_calculator.py`

**Interfaces:**
- Produces: `TakeProfitCalculator.calculate(entry_price: float, position_side: str, market_data: Optional[Dict[str, Any]] = None) -> float`
- Produces: `StopLossConfig.take_profit_mode`, `take_profit_atr_multiplier`, `take_profit_min_percent`, `take_profit_max_percent`, `take_profit_structure_buffer_percent`

- [x] **Step 1: Write failing tests**

Add tests for long resistance target, short support target, ATR fallback, min/max clamp, and fixed-mode fallback.

- [x] **Step 2: Run tests to verify they fail**

Run: `pytest -o addopts= tests/unit/test_smart_stop_loss.py -v`

- [x] **Step 3: Implement calculator and config**

Add adaptive config validation and target-selection helpers.

- [x] **Step 4: Run tests to verify they pass**

Run: `pytest -o addopts= tests/unit/test_smart_stop_loss.py -v`

### Task 2: Execution Wiring

**Files:**
- Modify: `tests/unit/test_adaptive_execution_safety.py`
- Modify: `alpha_trading_bot/core/adaptive_bot.py`

**Interfaces:**
- Consumes: `TakeProfitCalculator.calculate(..., market_data=market_data)`

- [x] **Step 1: Write failing test**

Add an execution test proving open flow passes structure/ATR data into take-profit pricing.

- [x] **Step 2: Run test to verify it fails**

Run: `pytest -o addopts= tests/unit/test_adaptive_execution_safety.py::test_open_creates_adaptive_take_profit_from_market_structure -v`

- [x] **Step 3: Wire `market_data` through `_maybe_create_take_profit_order`**

Pass market data from `_execute_trade` into the calculator.

- [x] **Step 4: Run focused regression**

Run: `pytest -o addopts= tests/unit/test_adaptive_execution_safety.py tests/unit/test_smart_stop_loss.py -v`

### Task 3: Verification

**Files:**
- Verify only.

- [x] **Step 1: Run full test suite**

Run: `pytest -o addopts=`

- [x] **Step 2: Update graphify**

Run: `graphify update .`
