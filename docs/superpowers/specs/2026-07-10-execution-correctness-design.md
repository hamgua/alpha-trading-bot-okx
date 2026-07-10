# Execution Correctness Design

## 1. Objective

Before increasing trading frequency or changing signal logic, make the live
execution path reliable enough that every quantity, fill, protective order,
position state, and learning event describes the same real exchange position.

This phase addresses four verified problems:

1. Unit tests can write fake positions and trades into the default runtime
   state directory.
2. OKX swap `sz` is treated as if it were always a base-asset amount, so
   notional and quantity calculations can be wrong without instrument metadata.
3. Market orders are queried only once after submission, which can misclassify
   an accepted but not-yet-reported fill as a failure.
4. Stop-loss and take-profit orders do not share a complete lifecycle when a
   position is reduced, manually closed, or closed by one protective order.

The phase is successful when the bot can prove what was filled, calculate its
USDT-equivalent notional from exchange metadata, keep exactly the required
protective orders for the remaining position, and keep tests out of runtime
state.

## 2. Scope

### In scope

- Isolate test state from runtime state.
- Load and cache OKX instrument metadata needed for price and size arithmetic.
- Normalize order size and trigger prices using exchange `minSz`, `lotSz`, and
  `tickSz` constraints.
- Carry an explicit open, close, or reduce intent into ordinary OKX orders so
  close and reduce orders use `reduceOnly` and the correct `posSide`.
- Calculate take-profit minimum notional using instrument-aware units.
- Poll accepted market orders until filled, partially filled, canceled,
  rejected, or timed out.
- Reconcile ambiguous order results with exchange position state before any
  retry that could duplicate exposure.
- Record open and close state only after confirmed fills, using actual filled
  amount and average price.
- Cancel, resize, restore, and clear stop-loss and take-profit orders as one
  protective-order set.
- Preserve the existing fail-safe behavior: if a new position cannot obtain a
  valid stop-loss, immediately attempt a confirmed protective close.

### Out of scope

- AI prompt changes, signal fusion changes, and strategy selection fixes.
- Fast/slow dual-loop scheduling.
- A new risk-based position sizing algorithm.
- Partial take-profit strategy or dynamic take-profit percentages.
- Full fee, funding-rate, slippage, MFE, and MAE analytics. This phase records
  the fill data required for that later work but does not redesign analytics.
- Spot, inverse swap, futures, and options quantity formulas. The configured
  USDT-margined linear swap is the supported live instrument for this phase.

## 3. Architecture

### 3.1 Instrument metadata

Add an exchange-owned `InstrumentSpec` data model and metadata service. The
service loads the configured OKX instrument during exchange initialization and
caches the result for the process lifetime.

Required fields:

- `inst_id`
- `inst_type`
- `contract_value`
- `contract_multiplier` when supplied
- `contract_value_currency`
- `minimum_size`
- `lot_size`
- `tick_size`

The model provides explicit operations instead of spreading formulas through
the bot:

- normalize an order size downward to a valid lot;
- normalize a price to a valid tick;
- calculate USDT-equivalent notional for the supported instrument type;
- reject an amount below exchange minimum size.

For the current `BTC/USDT:USDT` USDT-margined linear swap, notional is derived
from contract count, contract value, multiplier, contract-value currency, and
price. If the metadata does not describe a supported USDT linear swap, live
orders fail closed; the bot must not guess the notional or order size.

### 3.2 State isolation

`StatePersistence` continues to use the existing production directory by
default, but also accepts a `TRADING_STATE_DIR` override. Tests receive a unique
temporary state directory through an autouse pytest fixture. Production code
must not contain pytest-specific detection.

All tests that instantiate `PositionManager` or `StatePersistence` therefore
write only beneath their own temporary directory. A regression test verifies
that running the suite does not change the default runtime state files.

Existing ignored runtime files are not automatically deleted or rewritten by
the migration. They are reconciled with the exchange at startup in the normal
position recovery flow.

### 3.3 Confirmed order execution

Keep order submission and fill confirmation separate:

1. Submit the order with an explicit open, close, or reduce intent and obtain an
   exchange order ID. Close and reduce intents set `reduceOnly=true` and the
   position side required by the detected OKX position mode.
2. Poll order status at a short configurable interval until a terminal state or
   timeout.
3. For a complete fill, return actual filled amount and average price.
4. For a partial fill at timeout, cancel the remaining quantity, query once
   more, and return the confirmed partial fill.
5. For an open order with no fill at timeout, cancel it and return failure.
6. For an unknown status or query failure, reconcile exchange position state
   before deciding whether another order is permitted.

The coordinator must never resubmit merely because the first status query did
not yet report a fill. This prevents duplicate positions during OKX response
latency.

Opening flow records `PositionManager` and performance state only after the
confirmed fill. Closing flow cancels protective orders, obtains a confirmed
close fill, and only then closes performance state using the actual average
exit price. If the close is ambiguous, local position state remains present
until exchange reconciliation proves that the position is gone.

### 3.4 Protective-order set

Treat stop-loss and take-profit orders as a single protective set owned by one
position.

- `PositionManager` exposes both order IDs and trigger prices.
- `clear_position()` clears both stop-loss and take-profit state.
- Manual close cancels both protective orders before submitting the close.
- A successful reduction replaces both protective orders with the remaining
  confirmed amount.
- After reconciliation finds no exchange position, any remaining reduce-only
  protective orders for the symbol are canceled and local state is cleared.
- Position-close auditing stores both IDs and identifies which order actually
  triggered.
- A stop-loss creation failure still triggers an immediate protective close.
- A take-profit creation failure leaves the valid stop-loss in place and is
  reported as a recoverable warning.

Protective-order replacement follows a conservative sequence: confirm the
current position amount, cancel the old protective order, create the new one,
and immediately re-query exchange protection if creation fails. A missing
stop-loss after replacement is treated as critical exposure.

## 4. Data Flow

### Open position

1. Signal and risk gates approve an opening action.
2. Instrument metadata validates and normalizes the requested size.
3. The market order is submitted and polled to a confirmed fill.
4. Position state is recorded from actual fill amount and average price.
5. Stop-loss price and take-profit notional are recalculated from the confirmed
   fill and instrument metadata.
6. Stop-loss is created first.
7. Take-profit is created only when the instrument-aware notional meets
   `TAKE_PROFIT_MIN_NOTIONAL`.

### Close or reduce position

1. Refresh exchange position amount.
2. Cancel the existing protective-order set.
3. Submit and confirm the close or reduce order.
4. For full close, close performance state and clear all local position and
   protective-order state.
5. For partial close, update to the confirmed remaining amount and recreate the
   protective-order set for that amount.
6. If execution is ambiguous, reconcile before changing local state or sending
   another order.

### Startup and disappearance reconciliation

1. Load local persisted state.
2. Query exchange position and open algorithm orders.
3. Exchange position state is authoritative.
4. Restore missing local protective IDs from matching exchange orders.
5. If the position is gone, identify the triggered stop-loss or take-profit,
   cancel its sibling if still open, record the close event, and clear state.

## 5. Error Handling

- Missing or unsupported instrument metadata blocks new live orders.
- Invalid normalized size blocks the order with a descriptive reason.
- Order timeout attempts cancellation and reconciliation before returning.
- Ambiguous order state never causes an automatic duplicate submission.
- Stop-loss absence after opening or replacement triggers the existing
  protective-close path and a critical log.
- Take-profit failures do not remove stop-loss protection.
- Failure to cancel a protective order does not leave the position open merely
  to avoid a race. The bot submits a reduce-only close, then reconciles the
  position and algorithm orders; an already-gone protective order is treated
  as successfully resolved.
- Persistence errors are logged with symbol, side, amount, and order IDs, while
  exchange state remains authoritative.

## 6. Configuration

Add or formalize these settings with conservative defaults:

- `TRADING_STATE_DIR`: optional runtime state directory override.
- `ORDER_CONFIRM_TIMEOUT_SECONDS`: maximum fill-confirmation wait.
- `ORDER_CONFIRM_POLL_INTERVAL_SECONDS`: status polling interval.

`TAKE_PROFIT_MIN_NOTIONAL` remains a USDT-equivalent threshold. The current
`.env.example` explanation will be updated so it no longer implies that every
OKX swap notional is simply `filled_amount * entry_price`.

No automatic edit is made to the user's `.env`; enabling the threshold still
requires adding `TAKE_PROFIT_MIN_NOTIONAL` there.

## 7. Testing

Implementation follows test-driven development.

Required tests:

- instrument metadata parsing and normalization;
- USDT-margined linear-swap notional calculations for base-denominated contract
  value metadata;
- unsupported instrument types fail closed;
- missing metadata fails closed in live mode;
- size below `minSz` is rejected;
- immediate fill, delayed fill, partial fill, rejection, timeout, cancellation,
  and ambiguous-query order flows;
- close and reduce orders carry `reduceOnly` and correct `posSide` parameters;
- no duplicate order submission after an ambiguous result;
- confirmed entry price is used for stop-loss and take-profit calculations;
- manual close clears and cancels both protective orders;
- reduction recreates protection for the remaining amount;
- stop-loss-triggered and take-profit-triggered disappearance reconciliation;
- `clear_position()` removes all protective-order state;
- pytest state isolation and default runtime-state non-mutation;
- existing adaptive execution, position recovery, stop-loss, persistence, and
  golden-master tests remain green.

Verification includes the full pytest suite, Python compilation for touched
modules, available lint/type checks, and `graphify update .` after code changes.

## 8. Rollout

1. Run the full suite with isolated temporary state.
2. Run the bot in `TEST_MODE=true` and inspect normalized size, notional, fill,
   and protective-order logs.
3. Use an OKX demo account to verify delayed fill and algorithm-order behavior.
4. Enable live mode only after startup reconciliation shows one exchange
   position mapped to one local position and the expected protective-order set.

## 9. Success Criteria

- Tests cannot modify `data/trading_state` or `data_json`.
- Every live order size and trigger price is valid for the configured
  instrument.
- Take-profit gating uses correct USDT-equivalent notional.
- No accepted order is duplicated because fill reporting was delayed.
- Local open/close state changes only after confirmed exchange outcomes.
- A live position has one valid stop-loss and at most one intended take-profit
  for its confirmed remaining amount.
- Full close removes all local and exchange protective-order leftovers.
- Existing behavior outside this execution-correctness scope remains unchanged.
