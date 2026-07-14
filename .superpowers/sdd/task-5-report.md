# Task 5 Report: Confirm Market Order Fills

## Status

DONE

## Scope

- Added explicit market-order confirmation timeout and poll interval settings.
- Added `OrderService.create_confirmed_market_order`, which submits exactly once,
  polls with the event loop's monotonic clock, caps each sleep at the deadline,
  and cancels an unresolved remainder after timeout.
- Added fill reconciliation so sparse cancellation or final-status responses cannot
  erase an already observed partial fill or its average price.
- Added `ExchangeClient.create_confirmed_market_order`, preserving test-mode
  simulation and forwarding live confirmation settings to `OrderService`.
- Propagated confirmation settings through both bot client constructions without
  changing Task 3 instrument metadata initialization or facades.

## RED Evidence

Command:

```bash
pytest -o addopts='' tests/unit/test_order_confirmation.py tests/unit/test_exchange_raw_endpoints.py -v
```

Result: 15 failures and 10 passes. The new tests failed because
`OrderService.create_confirmed_market_order` and
`ExchangeClient.create_confirmed_market_order` did not exist, and the new
configuration and constructor parameters were not accepted.

Additional RED regression:

```bash
pytest -o addopts='' tests/unit/test_order_confirmation.py::test_partial_fill_preserves_average_when_terminal_status_omits_it -v
```

Result: failed because the terminal response replaced the observed `100.2`
average price with `0.0`.

Additional RED facade guard:

```bash
pytest -o addopts='' tests/unit/test_order_confirmation.py::test_exchange_client_confirmation_requires_initialized_order_service -v
```

Result: failed with an `AttributeError` from an uninitialized live
`_order_service`; the facade now raises a descriptive `RuntimeError` instead.

## GREEN Evidence

```bash
pytest -o addopts='' tests/unit/test_order_confirmation.py tests/unit/test_exchange_raw_endpoints.py tests/unit/test_live_trading_guard.py tests/unit/test_adaptive_execution_safety.py tests/unit/test_stop_loss_protection.py tests/unit/test_zero_behavior_golden.py -v
```

Result: 61 passed in 0.65s.

Additional checks passed:

```bash
python3 -m py_compile alpha_trading_bot/config/models.py alpha_trading_bot/exchange/order_service.py alpha_trading_bot/exchange/client.py alpha_trading_bot/core/adaptive_bot.py alpha_trading_bot/core/bot.py tests/unit/test_order_confirmation.py tests/unit/test_exchange_raw_endpoints.py
uvx --from black==25.9.0 black --check alpha_trading_bot/exchange/order_service.py alpha_trading_bot/exchange/client.py tests/unit/test_order_confirmation.py tests/unit/test_exchange_raw_endpoints.py
uvx --from isort==6.0.1 isort --check-only --profile black alpha_trading_bot/exchange/order_service.py alpha_trading_bot/exchange/client.py tests/unit/test_order_confirmation.py tests/unit/test_exchange_raw_endpoints.py
git diff --check
```

## Coverage

- Immediate terminal fill returns without polling.
- Delayed fill is polled without resubmission.
- Rejected submission returns without polling or resubmission.
- Partial fill timeout cancels the remainder and preserves fill data.
- Terminal status records that omit the average price retain the observed price.
- Zero-fill timeout cancels without sleeping after the deadline.
- Unknown status fails closed without duplicate submission.
- Partial fills survive unavailable cancellation and empty final lookup data.
- Nonpositive and inverted timing settings are rejected.
- Environment loading, simulated confirmation behavior, facade propagation, and
  both bot constructor propagations are covered.
- A live facade without initialization fails closed with a descriptive error.

## Files

- `.env.example`
- `alpha_trading_bot/config/models.py`
- `alpha_trading_bot/exchange/order_service.py`
- `alpha_trading_bot/exchange/client.py`
- `alpha_trading_bot/core/adaptive_bot.py`
- `alpha_trading_bot/core/bot.py`
- `tests/unit/test_order_confirmation.py`
- `tests/unit/test_exchange_raw_endpoints.py`
- `graphify-out/GRAPH_REPORT.md`
- `graphify-out/graph.html`
- `graphify-out/graph.json`
- `graphify-out/manifest.json`

## Graphify

Ran `graphify update .` after the final code changes. The graph now records
4,882 nodes, 7,008 edges, and 336 communities.

## Self-Review

- The confirmation method has one call to `create_order_with_status`; polling
  and final lookup use the submitted order ID only.
- Deadline calculation uses `asyncio.get_running_loop().time()` and skips sleep
  when no time remains.
- Timeout always attempts a cancel for a nonterminal state, including unknown
  status, and does not issue a new order.
- Reconciliation retains the largest observed fill and a known average price
  when later status records are sparse or unavailable.
- Task 3 instrument metadata initialization and the existing client facades
  remain unchanged.

## Commit

`fix: confirm market order fills`

## Concerns

The repository's targeted mypy invocation still reports 90 pre-existing errors
across 19 imported modules. The new live-facade nullability path is guarded;
the remaining diagnostics are outside Task 5 scope. Full-file Black/isort
checks for `models.py`, `adaptive_bot.py`, and `bot.py` would reformat legacy,
unrelated sections, so those edits were intentionally not retained. Adaptive
execution will begin using the new confirmation facade in Task 6, as scoped by
the implementation plan.
