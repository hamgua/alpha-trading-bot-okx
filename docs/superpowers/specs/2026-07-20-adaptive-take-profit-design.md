# Adaptive Take Profit Design

## Context

The first stability batch lowered the default take-profit from 6% to 0.8%.
That is safer than a fixed 6% target in low-volatility conditions, but it still
does not use the market structure already calculated in `market_data`.

## Goal

Replace the default fixed take-profit target with a conservative adaptive first
target based on ATR and nearby support/resistance, while preserving the existing
single take-profit order lifecycle.

## Scope

- Use one take-profit algorithm order after opening a position.
- Do not add partial close, multiple take-profit legs, or new trailing take-profit
  exchange orders in this batch.
- Keep long close side as `sell` and short close side as `buy`.
- Preserve the 0.8% fixed target as the fallback when ATR and structure data are
  missing or invalid.

## Design

`StopLossConfig` gains adaptive take-profit parameters:

- `take_profit_mode: str = "adaptive"`
- `take_profit_atr_multiplier: float = 1.5`
- `take_profit_min_percent: float = 0.004`
- `take_profit_max_percent: float = 0.02`
- `take_profit_structure_buffer_percent: float = 0.001`

`TakeProfitCalculator.calculate` accepts optional `market_data`.

For long positions:

- ATR target: `entry_price * (1 + atr_percent * multiplier)`.
- Structure target: `nearest_resistance * (1 - buffer)` when it remains above
  entry.
- Choose the closer valid target.

For short positions:

- ATR target: `entry_price * (1 - atr_percent * multiplier)`.
- Structure target: `nearest_support * (1 + buffer)` when it remains below entry.
- Choose the closer valid target.

The chosen target is clamped to the configured min/max percent range. If adaptive
data is missing, invalid, or disabled, calculation falls back to the fixed
`take_profit_percent`.

## Testing

- Calculator chooses resistance before ATR for long when resistance is closer.
- Calculator chooses support before ATR for short when support is closer.
- Calculator uses ATR when structure data is missing.
- Calculator clamps too-close/too-far targets.
- Adaptive bot passes `market_data` into take-profit creation.
