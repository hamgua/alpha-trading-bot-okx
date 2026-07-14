# Trading Opportunity Improvements Design

## Goal

Improve opportunity capture without weakening live-trading safety by adding skipped-opportunity telemetry, making adaptive confidence thresholds visible to the final decision gate, and allowing tightly gated short entries in bearish/high-quality setups.

## Chart And Log Context

The 2026-07-09 to 2026-07-14 BTCUSDT chart shows an uptrend into 2026-07-11, a high consolidation around 2026-07-11 to 2026-07-12, a sharp 2026-07-13 breakdown, and a 2026-07-14 rebound. Logs match that picture: long entries were mostly blocked correctly during the 2026-07-13 bearish structure, but the bot did not convert the breakdown into short opportunities.

## Scope

- Add structured audit logging for skipped trade opportunities.
- Apply rule-engine `fusion_threshold` adjustments to `market_data["min_trade_confidence"]` before final decisions.
- Add controlled AI-HOLD short overrides for bearish structure or high-quality strategy SELL setups.
- Keep position sizing, take-profit rewrites, and AI timeout fallback as later phases after telemetry confirms behavior.

## Safety Constraints

- Never open long positions in `market_structure == "bearish"`.
- Never open short positions when short selling is disabled, RSI is below the oversold block, ATR is above the existing max-trade limit, or there is already a position.
- Prefer existing `DecisionEngine` and `AdaptiveTradingBot` boundaries.
- Use tests before production code.

