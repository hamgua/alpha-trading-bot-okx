# Trading Opportunity Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add telemetry and safe decision changes that help the bot capture bearish/short opportunities seen in recent logs and chart context.

**Architecture:** Keep the final execution path in `AdaptiveTradingBot` and decision policy in `DecisionEngine`. Add a small audit helper for skipped decisions and update rule-adjustment propagation before `_make_decision`.

**Tech Stack:** Python 3.8+, pytest, standard logging and JSON.

## Global Constraints

- Keep live-trading behavior conservative by default.
- Write failing tests before production changes.
- Do not modify unrelated files or user changes.
- Run focused tests and `graphify update .` after code changes.

---

### Task 1: Adaptive Threshold Propagation

**Files:**
- Modify: `alpha_trading_bot/core/adaptive_bot.py`
- Test: `tests/unit/test_cycle_log_optimization.py`

**Interfaces:**
- Consumes: `rule_result["adjustments"]["fusion_threshold"]`
- Produces: `market_data["min_trade_confidence"]`

- [ ] Write a failing test that proves rule `fusion_threshold` becomes `min_trade_confidence`.
- [ ] Run the focused test and confirm it fails.
- [ ] Add a helper on `AdaptiveTradingBot` that copies rule fusion threshold into market data before final decision.
- [ ] Run the focused test and confirm it passes.

### Task 2: Controlled Short Overrides

**Files:**
- Modify: `alpha_trading_bot/core/decision_engine.py`
- Test: `tests/unit/test_decision_engine_hold_override.py`

**Interfaces:**
- Consumes: `short_risk_reward_ratio`, `market_structure`, `market_structure_direction`, `technical.rsi`, `technical.atr_percent`, `technical.trend_strength`
- Produces: final decisions with `action == "sell"` for safe short setups.

- [ ] Write failing tests for bearish AI-HOLD short override and excellent strategy SELL override without reversal confirmation.
- [ ] Run the focused tests and confirm they fail.
- [ ] Add conservative constants and decision branches for these short overrides.
- [ ] Run the focused tests and confirm they pass.

### Task 3: Skipped Opportunity Audit

**Files:**
- Create: `alpha_trading_bot/core/opportunity_audit.py`
- Modify: `alpha_trading_bot/core/adaptive_bot.py`
- Test: `tests/unit/test_opportunity_audit.py`

**Interfaces:**
- Consumes: final decision, AI signal, selected strategy, market data, position flag.
- Produces: structured skip audit dictionaries and log lines.

- [ ] Write failing tests for audit record shape and safe JSON serialization.
- [ ] Run the focused tests and confirm they fail.
- [ ] Implement `OpportunityAuditor` and wire skip logging in `AdaptiveTradingBot`.
- [ ] Run focused tests and confirm they pass.

