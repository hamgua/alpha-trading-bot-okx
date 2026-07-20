# Opportunity And Exit Completion Design

## Context

The current stabilization work already fixed protection-order cleanup, close
audit dedupe, adaptive first take-profit, and stop-tightening gates. The
remaining requested items are higher risk because they change entry frequency,
cooldown behavior, and take-profit order size.

## Goals

- Add partial take-profit for the first target without expanding order
  lifecycle complexity too far.
- Keep the remaining position protected by existing trailing-stop logic.
- Let high-quality structure signals cover AI-HOLD more consistently.
- Track AI-HOLD override outcomes so later log analysis can evaluate whether
  coverage improves win rate.
- Make same-direction cooldown dynamic: preserve long cooldown after real
  losses, shorten it for breakeven/small-loss/high-quality cases.

## Design

### Partial Take-Profit

The bot keeps a single take-profit algorithm order, but its size becomes a
configurable fraction of the filled entry amount. Default fraction is `0.5`.
The remaining position is managed by existing stop-loss update logic.

When exchange position sync reports the live amount is lower than local amount
but still above zero, `PositionManager.update_from_exchange` updates local
amount while preserving entry price and protection IDs. This lets later cycles
rebuild protection orders around the reduced remaining position.

### AI-HOLD Override Metrics

Decision results that override AI-HOLD get a `metadata.ai_hold_override` flag and
`metadata.ai_hold_override_type`. The execution layer copies these fields into
`PerformanceTracker.record_trade`. When the trade closes, the tracker increments
override metrics by type and outcome.

The override rules remain gated by confidence, R/R, ATR, RSI, and position
state. This batch adds observability and a slightly more stable high-quality
structure route rather than broadly opening every AI-HOLD disagreement.

### Dynamic Cooldown

Cooldown tiers:

- `1800s` after normal losses.
- `600s` after breakeven or small loss.
- `300s` after profitable close with high-quality same-direction signal.
- `300s` for high-quality opposite-direction signal.

The existing high-risk long gate still keeps full cooldown.

## Testing

- Partial take-profit order uses `filled_amount * take_profit_partial_ratio`.
- Position sync preserves reduced live amount after partial take-profit.
- AI-HOLD override decisions contain metadata.
- Performance tracker counts AI-HOLD override win/loss/breakeven outcomes.
- Dynamic cooldown returns `600s` for small loss/breakeven and `300s` for
  high-quality opposite-direction signal.
