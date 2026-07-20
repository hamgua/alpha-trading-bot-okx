# Stability-First Trading Adjustments Design

## Context

Commit `c7e4a2599b7a6fdf756101c9980e51763f3e01a3` has been running since
2026-07-17 15:01:58 +0800. Logs from 2026-07-17 through 2026-07-19 show
six trades, low realized profitability, two `disk I/O error` ML write failures,
many AI-HOLD strategy overrides, and repeated position reconciliation events.

The first adjustment batch must improve stability before increasing trade
frequency. The bot should avoid orphaned protection orders, avoid duplicate or
misleading close audit records, and use take-profit / trailing-stop defaults
that fit low-volatility conditions.

## Goals

- Cancel all protection algo orders for a position before any confirmed local
  clear or active market close.
- Prevent active-close and stale algo history from being recorded as fresh
  stop-loss / take-profit triggered exits.
- Keep long and short protection order direction correct.
- Replace the unreachable default 6% take-profit with a low-volatility default.
- Prevent stop-loss tightening while price is still near entry.
- Slightly improve high-quality AI-HOLD strategy overrides without broadly
  increasing trade frequency.

## Non-Goals

- No new strategy family.
- No leverage or max-position increase.
- No broad cooldown removal.
- No database migration.
- No exchange API dependency changes.

## Design

### 1. Protection Order Lifecycle

`PositionRecoveryManager` will gain a general protection-order cancellation
path. Before active close, it will query current algo orders and cancel orders
that belong to the current symbol and contain either stop-loss or take-profit
trigger fields. It will also use locally stored `stop_order_id` and
`take_profit_order_id` as fallbacks when exchange order discovery is incomplete.

After cancellation, `PositionManager` will clear both protection IDs and last
prices. Existing close flow in `AdaptiveTradingBot._execute_trade` will call the
new method instead of the stop-loss-only method.

### 2. Close Audit Dedupe

`PositionCloseAuditContext` will track whether the current position was closed
actively by the bot. When an active close is confirmed, the bot will mark the
audit context as active-close before clearing local state.

`PositionCloseAuditor.log_disappeared_position_close_event` will skip algorithm
history logging when the context indicates a recent active close. It will also
only treat algo history as a triggered close if the history record has trigger
evidence rather than only static trigger price fields.

This keeps real exchange-triggered stop-loss / take-profit logs, while avoiding
the current pattern where a canceled or stale stop algo can be logged later as a
fresh stop-loss trigger.

### 3. Low-Volatility Profit Target

`StopLossConfig.take_profit_percent` default will change from `0.06` to
`0.008`. The existing calculation remains symmetric:

- Long take-profit: `entry_price * (1 + take_profit_percent)`.
- Short take-profit: `entry_price * (1 - take_profit_percent)`.

This turns the default target from 6% to 0.8%, closer to the observed 0.13% to
0.63% ATR range, while still requiring a meaningful move after fees and spread.

### 4. Stop Tightening Gate

`StopLossConfig` will add
`min_profit_to_tighten_stop_percent: float = 0.003`.

Entry-based long stop tightening and traditional trailing updates will only
tighten beyond the base protective stop after unrealized profit reaches this
threshold. The same idea applies to short trailing updates: do not tighten based
on the low-water mark until short profit reaches the threshold.

This prevents the bot from moving stops too close while price is still within
normal entry noise.

### 5. Conservative Opportunity Overrides

The first batch will keep AI-HOLD as a meaningful brake. It will only clarify
and slightly relax high-quality override paths already present in
`DecisionEngine`:

- Prefer existing market-structure and high short-R/R override branches.
- Keep RSI and ATR safety gates.
- Keep direction cooldown after losing exits.
- Do not add a new source of trades.

The goal is to reduce missed high-quality entries without turning every
strategy-vs-AI disagreement into a trade.

## Testing

Tests will be added or updated before implementation:

- Active close cancels both stop-loss and take-profit algo orders.
- Active close marks audit context so later disappearance does not log stale
  stop-loss trigger history.
- Algorithm close audit only logs triggered records, not records that only have
  configured trigger prices.
- Long and short take-profit / stop-loss sides remain correct.
- Default take-profit is `0.008`.
- Stop tightening waits until profit reaches
  `min_profit_to_tighten_stop_percent`.

## Rollout

This is a code-only change with existing configuration defaults updated. Run the
focused unit tests first, then the relevant broader test files. After code
changes, run `graphify update .` because the repository instructions require it
after modifying code files.

