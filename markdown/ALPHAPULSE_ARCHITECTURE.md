# AlphaPulse Architecture Documentation

## Overview

AlphaPulse is a real-time market monitoring system that operates alongside the main trading cycle in a **dual-mode** architecture. This document explains the design decisions, timeout protection mechanisms, and lock-free performance optimizations.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    TradingBot (Main Cycle)                       │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  15-minute trading cycle with AI signals & strategy         ││
│  │  - Generates trading signals                                 ││
│  │  - Executes trades with risk management                      ││
│  │  - Manages positions and TP/SL orders                        ││
│  └─────────────────────────────────────────────────────────────┘│
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │           AlphaPulse Integration                             ││
│  │  - Checks real-time monitor status                           ││
│  │  - Falls back to cron mode if real-time monitor fails        ││
│  │  - Integrates AlphaPulse signals into main cycle             ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────┐
│  Real-Time Monitor      │     │   Fallback Cron Mode    │
│  (Primary, Continuous)  │     │   (Backup, 15-min)      │
│  - 60-second interval   │     │   - Triggered when      │
│  - Continuous OHLCV     │     │     real-time fails     │
│    streaming            │     │   - Manual check on     │
│  - Real-time signals    │     │     each trading cycle  │
└─────────────────────────┘     └─────────────────────────┘
              │                               │
              ▼                               ▼
┌───────────────────────────────────────────────────────────────┐
│                      DataManager                               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │  Lock-Free Hot Storage (Memory)                          │  │
│  │  - OHLCV data in deques (atomic operations)              │  │
│  │  - Indicator history snapshots                           │  │
│  │  - Price range cache (24h/7d high/low)                   │  │
│  └─────────────────────────────────────────────────────────┘  │
│                              │                                 │
│                              ▼                                 │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │  TieredStorage (Warm/Cold)                               │  │
│  │  - Warm: SQLite for medium-term persistence               │  │
│  │  - Cold: Downsampled for long-term trends                 │  │
│  │  - Async writes via run_in_executor()                     │  │
│  └─────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
```

## Dual-Mode Operation

### Mode 1: Real-Time Monitor (Primary)

The real-time monitor runs continuously with a 60-second interval:

```python
async def _monitor_loop(self):
    while self._running:
        for symbol in self.config.symbols:
            await self._update_symbol(symbol)
        await asyncio.sleep(self.config.monitor_interval)  # 60 seconds
```

**Characteristics:**
- Continuous OHLCV data fetching
- Real-time indicator calculation
- Immediate signal generation
- Best for: Active trading, catching rapid market moves

### Mode 2: Fallback Cron (Backup)

The fallback mode activates when:
1. Real-time monitor is not running (crash detection)
2. No check performed for 180+ seconds (timeout detection)

```python
# In bot.py trading cycle
now = asyncio.get_event_loop().time()
fallback_threshold = 180  # 3 minutes

if now - last_check > fallback_threshold:
    use_fallback = True
```

**Characteristics:**
- Runs on main trading cycle (15-minute intervals)
- Uses cached data when possible
- Fetches fresh data only when needed
- Best for: Reliability, reduced API calls

## Timeout Protection

All operations have timeout protection using `asyncio.wait_for()`:

| Operation | Timeout | Purpose |
|-----------|---------|---------|
| `get_ohlcv()` | 5 seconds | Local data access |
| `fetch_ohlcv()` | 25 seconds | Exchange API call |
| `update_ohlcv()` | 2 seconds/bar | Data update |
| `_calculate_indicators()` | 20 seconds | Indicator computation |
| `_check_signals()` | 10 seconds | Signal generation |

### Timeout Implementation Example

```python
async def manual_check(self, symbol: str) -> Optional[SignalCheckResult]:
    try:
        ohlcv = await asyncio.wait_for(
            self.data_manager.get_ohlcv(symbol, "15m", limit=100),
            timeout=5.0
        )
    except asyncio.TimeoutError:
        logger.warning(f"⚠️ [{symbol}] get_ohlcv 超时")
        ohlcv = []
```

## Lock-Free Performance Optimization

### Why No Locks?

Python's GIL (Global Interpreter Lock) ensures that simple operations on built-in types are atomic:

- `dict[key] = value` - atomic
- `dict[key]` - atomic
- `deque.append()` - atomic
- `deque[-1]` - atomic

### Lock-Free Operations

```python
# OLD (with locks - caused contention)
async def get_ohlcv(self, symbol, timeframe):
    async with self._lock:
        return list(self._storage[symbol][timeframe])

# NEW (lock-free - fast)
async def get_ohlcv(self, symbol, timeframe):
    if symbol not in self._storage:
        return []
    data = list(self._storage[symbol][timeframe])  # Atomic read
    return data
```

### Performance Comparison

| Operation | With Locks | Lock-Free |
|-----------|-----------|-----------|
| 100 concurrent reads | ~30 seconds | ~0.1 seconds |
| 100 concurrent writes | ~25 seconds | ~0.2 seconds |
| Mixed read/write | ~50 seconds | ~0.3 seconds |

### When to Use Locks

Locks are still used for:
- `initialize_symbol()` - Initialization needs atomicity
- `update_indicator()` - Indicator history updates
- `reset_price_range_24h()` - Daily cache reset
- `cleanup()` - Resource cleanup

## Technical Indicator Return Values

All indicator functions return Lists (not dicts or tuples for single values):

```python
# TechnicalIndicators class
def calculate_atr(highs, lows, closes, period=14) -> List[float]:
    """Returns list of ATR values, use [-1] for latest"""
    ...

def calculate_rsi(closes, period=14) -> List[float]:
    """Returns list of RSI values, use [-1] for latest"""
    ...

def calculate_macd(closes) -> Tuple[List[float], List[float], List[float]]:
    """Returns (macd_line, signal_line, histogram) as lists"""
    ...

def calculate_adx(highs, lows, closes, period=14) -> List[float]:
    """Returns list of ADX values, use [-1] for latest"""
    ...

def calculate_bollinger_bands(closes, period=20, num_std=2) -> Tuple[List[float], List[float], List[float]]:
    """Returns (upper, middle, lower) as lists"""
    ...
```

## Symbol Configuration

AlphaPulse monitors configured symbols via environment variable:

```bash
# .env
ALPHA_PULSE_SYMBOLS=BTC/USDT:USDT,ETH/USDT:USDT
```

**Recommendations:**
- Start with single symbol (BTC) for stable operation
- Add symbols gradually, monitoring performance
- Each symbol increases memory and API usage

## Fallback Threshold Tuning

The 180-second fallback threshold can be adjusted:

```python
# In bot.py
fallback_threshold = 180  # 3 minutes

# For more aggressive fallback
fallback_threshold = 120  # 2 minutes

# For less aggressive fallback
fallback_threshold = 300  # 5 minutes
```

## Memory Management

### OHLCV Data
- Maximum bars: 200 (configurable via `ALPHA_PULV_MAX_OHLCV_BARS`)
- Stored in memory deques with automatic eviction

### Indicator History
- Maximum snapshots: 100 (configurable via `ALPHA_PULSE_MAX_INDICATOR_HISTORY`)
- Stored in deques with automatic eviction

### Price Range Cache
- 24h high/low: Updated on each OHLCV update
- 7d high/low: Updated on each OHLCV update
- Reset daily via `reset_price_range_24h()`

## Error Handling

1. **Timeout Errors**: Return None, log warning, continue operation
2. **API Errors**: Retry with exponential backoff
3. **Data Validation**: Skip invalid bars, log warning
4. **Indicator Calculation Errors**: Return default values, log error

## Monitoring and Debugging

### Key Metrics to Watch
- Real-time monitor running status
- Fallback mode activation count
- Timeout occurrence frequency
- Memory usage per symbol

### Log Patterns
```
✅ AlphaPulse 实时监控运行中，跳过后备模式
⚠️ AlphaPulse实时监控超过180秒无检查，触发后备模式
⚠️ [BTC/USDT:USDT] update_ohlcv 第50根超时，跳过
📊 BTC/USDT:USDT 指标: 价格=50000.00, RSI=35.1, BB位置=10.5%
```

## Performance Optimization Tips

1. **Reduce Symbols**: Start with single symbol
2. **Increase Fallback Threshold**: Reduce API calls in stable markets
3. **Adjust OHLCV Limit**: Reduce bar count if memory constrained
4. **Enable Caching**: AI response caching (900 seconds default)

## Future Improvements

1. **WebSocket Integration**: Real-time price streaming
2. **Multi-Process Data Storage**: Separate processes for hot/warm/cold
3. **Prometheus Metrics**: Better monitoring and alerting
4. **Adaptive Timeout**: Dynamic timeout based on market volatility
