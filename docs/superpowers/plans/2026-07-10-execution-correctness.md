# Execution Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make adaptive live execution use isolated state, valid OKX contract units, confirmed fills, and a consistent stop-loss/take-profit lifecycle.

**Architecture:** Add a focused instrument metadata service under `exchange/`, extend ordinary orders with explicit execution intent, and centralize fill polling in `OrderService`. Keep `AdaptiveTradingBot` as the coordinator, but make exchange position state authoritative and treat stop-loss plus take-profit as one protective-order set.

**Tech Stack:** Python 3.8+, asyncio, dataclasses, Decimal, ccxt OKX raw endpoints, pytest, pytest-asyncio.

## Global Constraints

- Support the configured USDT-margined linear swap only; unsupported live instruments fail closed.
- Do not change AI prompts, signal fusion, strategy selection, risk-based sizing, or scheduler cadence in this phase.
- Preserve immediate protective close when a newly opened position cannot obtain a stop-loss.
- Do not edit the user's `.env`; document new variables only in `.env.example`.
- Keep `TAKE_PROFIT_MIN_NOTIONAL` denominated in USDT-equivalent notional.
- Use strict type hints and no `# type: ignore` suppressions.
- Write business-logic comments in Chinese and keep formatting compatible with Black line length 88.
- Use test-driven development and run `graphify update .` after code changes.

---

## File Map

- `alpha_trading_bot/core/state_persistence.py`: resolve runtime state directory overrides.
- `alpha_trading_bot/ai/adaptive/performance_tracker.py`: resolve adaptive history below isolated test state.
- `tests/conftest.py`: assign a unique temporary state root to every test.
- `alpha_trading_bot/exchange/models/instruments.py`: immutable OKX instrument rules and unit arithmetic.
- `alpha_trading_bot/exchange/instrument_service.py`: fetch and parse OKX public instrument metadata.
- `alpha_trading_bot/exchange/models/orders.py`: order intent and fill-state helpers.
- `alpha_trading_bot/exchange/order_service.py`: intent-aware params and confirmed-fill polling.
- `alpha_trading_bot/exchange/client.py`: wire metadata and confirmed-order operations into the public exchange facade.
- `alpha_trading_bot/config/models.py`: confirmation timeout and polling configuration.
- `alpha_trading_bot/core/adaptive_bot.py`: consume normalized sizes, actual fills, and instrument-aware notional.
- `alpha_trading_bot/core/position_manager.py`: expose and clear the complete protective-order state.
- `alpha_trading_bot/core/position_recovery.py`: cancel and reconcile the protective-order set.
- `alpha_trading_bot/core/position_close_audit.py`: identify stop-loss or take-profit exits and return structured close data.
- `.env.example`: document state and order-confirmation settings and correct notional wording.

---

### Task 1: Isolate Runtime and Test State

**Files:**
- Modify: `alpha_trading_bot/core/state_persistence.py:53-86`
- Modify: `alpha_trading_bot/ai/adaptive/performance_tracker.py:70-106`
- Modify: `tests/conftest.py:1-54`
- Create: `tests/unit/test_state_directory_isolation.py`
- Modify: `.env.example:97-120`

**Interfaces:**
- Produces: `resolve_state_data_dir(data_dir: Optional[Path] = None) -> Path`
- Produces: `PerformanceTracker(data_dir: Optional[str] = None)` with an isolated default when `TRADING_STATE_DIR` is set.
- Consumes: standard `TRADING_STATE_DIR` environment variable.

- [ ] **Step 1: Write failing state-directory tests**

```python
from pathlib import Path

from alpha_trading_bot.ai.adaptive.performance_tracker import PerformanceTracker
from alpha_trading_bot.core.state_persistence import StatePersistence


def test_state_persistence_uses_environment_override(tmp_path, monkeypatch):
    state_dir = tmp_path / "runtime-state"
    monkeypatch.setenv("TRADING_STATE_DIR", str(state_dir))

    persistence = StatePersistence()

    assert persistence.data_dir == state_dir


def test_explicit_state_directory_wins_over_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_STATE_DIR", str(tmp_path / "environment"))
    explicit = tmp_path / "explicit"

    persistence = StatePersistence(explicit)

    assert persistence.data_dir == explicit


def test_performance_tracker_uses_isolated_sibling_directory(tmp_path, monkeypatch):
    state_dir = tmp_path / "trading-state"
    monkeypatch.setenv("TRADING_STATE_DIR", str(state_dir))

    tracker = PerformanceTracker()

    assert Path(tracker.data_dir) == tmp_path / "adaptive-performance"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest -o addopts='' tests/unit/test_state_directory_isolation.py -v`

Expected: FAIL because `StatePersistence()` ignores `TRADING_STATE_DIR` and `PerformanceTracker` still uses `data_json`.

- [ ] **Step 3: Implement deterministic directory resolution**

Add to `state_persistence.py`:

```python
import os


def resolve_state_data_dir(data_dir: Optional[Path] = None) -> Path:
    """解析状态目录，显式参数优先于环境变量。"""
    if data_dir is not None:
        return Path(data_dir)
    configured = os.getenv("TRADING_STATE_DIR", "").strip()
    if configured:
        return Path(configured)
    return StatePersistence.DEFAULT_DATA_DIR
```

Replace the constructor assignment with:

```python
self.data_dir = resolve_state_data_dir(data_dir)
```

Change `PerformanceTracker.__init__` to:

```python
def __init__(
    self,
    max_trades: int = 500,
    data_dir: Optional[str] = None,
) -> None:
    self.max_trades = max_trades
    if data_dir is not None:
        resolved_data_dir = Path(data_dir)
    else:
        state_override = os.getenv("TRADING_STATE_DIR", "").strip()
        resolved_data_dir = (
            Path(state_override).parent / "adaptive-performance"
            if state_override
            else Path("data_json")
        )
    self.data_dir = str(resolved_data_dir)
```

Import `Path` from `pathlib` in `performance_tracker.py`.

- [ ] **Step 4: Add the autouse isolation fixture**

Add to `tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def isolate_trading_state(tmp_path, monkeypatch):
    """每个测试使用独立状态目录，禁止污染运行时数据。"""
    state_dir = tmp_path / "trading-state"
    monkeypatch.setenv("TRADING_STATE_DIR", str(state_dir))
    yield state_dir
```

Document the optional override in `.env.example`:

```bash
TRADING_STATE_DIR=                                      # 可选：交易状态目录；测试会自动隔离
```

- [ ] **Step 5: Run focused and pollution regression tests**

Run: `pytest -o addopts='' tests/unit/test_state_directory_isolation.py tests/unit/test_risk_params.py tests/unit/test_zero_behavior_golden.py -v`

Expected: PASS, and `git status --short --ignored data/trading_state data_json` shows no newly modified runtime files.

- [ ] **Step 6: Commit**

```bash
git add .env.example tests/conftest.py tests/unit/test_state_directory_isolation.py alpha_trading_bot/core/state_persistence.py alpha_trading_bot/ai/adaptive/performance_tracker.py
git commit -m "fix: isolate trading state in tests"
```

---

### Task 2: Model OKX Instrument Constraints

**Files:**
- Create: `alpha_trading_bot/exchange/models/instruments.py`
- Modify: `alpha_trading_bot/exchange/models/__init__.py`
- Create: `tests/unit/test_instrument_spec.py`

**Interfaces:**
- Produces: `InstrumentSpec.from_okx(raw: Dict[str, Any]) -> InstrumentSpec`
- Produces: `InstrumentSpec.normalize_size(amount: float) -> float`
- Produces: `InstrumentSpec.normalize_price(price: float, rounding: str) -> float`
- Produces: `InstrumentSpec.notional_usdt(amount: float, price: float) -> float`
- Consumes: raw OKX fields `instId`, `instType`, `settleCcy`, `ctVal`, `ctMult`, `ctValCcy`, `minSz`, `lotSz`, and `tickSz`.

- [ ] **Step 1: Write failing instrument arithmetic tests**

```python
import pytest

from alpha_trading_bot.exchange.models.instruments import InstrumentSpec


def _btc_swap() -> InstrumentSpec:
    return InstrumentSpec.from_okx(
        {
            "instId": "BTC-USDT-SWAP",
            "instType": "SWAP",
            "settleCcy": "USDT",
            "ctVal": "0.01",
            "ctMult": "1",
            "ctValCcy": "BTC",
            "minSz": "0.01",
            "lotSz": "0.01",
            "tickSz": "0.1",
        }
    )


def test_linear_swap_notional_uses_contract_value_and_price():
    spec = _btc_swap()

    assert spec.notional_usdt(amount=2.0, price=100000.0) == pytest.approx(2000.0)


def test_size_is_rounded_down_to_lot_size():
    assert _btc_swap().normalize_size(0.019) == pytest.approx(0.01)


def test_size_below_minimum_is_rejected():
    with pytest.raises(ValueError, match="below minimum"):
        _btc_swap().normalize_size(0.009)


def test_stop_prices_use_directional_tick_rounding():
    spec = _btc_swap()

    assert spec.normalize_price(99999.96, "down") == pytest.approx(99999.9)
    assert spec.normalize_price(99999.94, "up") == pytest.approx(100000.0)


def test_inverse_or_non_usdt_instrument_is_rejected():
    spec = InstrumentSpec.from_okx(
        {
            "instId": "BTC-USD-SWAP",
            "instType": "SWAP",
            "settleCcy": "BTC",
            "ctVal": "100",
            "ctMult": "1",
            "ctValCcy": "USD",
            "minSz": "1",
            "lotSz": "1",
            "tickSz": "0.1",
        }
    )

    with pytest.raises(ValueError, match="unsupported instrument"):
        spec.notional_usdt(1.0, 100000.0)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest -o addopts='' tests/unit/test_instrument_spec.py -v`

Expected: FAIL because `InstrumentSpec` does not exist.

- [ ] **Step 3: Implement the immutable instrument model**

Create `instruments.py` with Decimal-based arithmetic:

```python
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from typing import Any, Dict


def _decimal(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


@dataclass(frozen=True)
class InstrumentSpec:
    inst_id: str
    inst_type: str
    settle_currency: str
    contract_value: Decimal
    contract_multiplier: Decimal
    contract_value_currency: str
    minimum_size: Decimal
    lot_size: Decimal
    tick_size: Decimal

    @classmethod
    def from_okx(cls, raw: Dict[str, Any]) -> "InstrumentSpec":
        return cls(
            inst_id=str(raw.get("instId", "")),
            inst_type=str(raw.get("instType", "")),
            settle_currency=str(raw.get("settleCcy", "")),
            contract_value=_decimal(raw.get("ctVal")),
            contract_multiplier=_decimal(raw.get("ctMult"), "1"),
            contract_value_currency=str(raw.get("ctValCcy", "")),
            minimum_size=_decimal(raw.get("minSz")),
            lot_size=_decimal(raw.get("lotSz")),
            tick_size=_decimal(raw.get("tickSz")),
        )

    @property
    def base_currency(self) -> str:
        return self.inst_id.split("-", 1)[0]

    def normalize_size(self, amount: float) -> float:
        value = _decimal(amount)
        if self.lot_size <= 0 or self.minimum_size <= 0:
            raise ValueError("invalid instrument size metadata")
        lots = (value / self.lot_size).to_integral_value(rounding=ROUND_FLOOR)
        normalized = lots * self.lot_size
        if normalized < self.minimum_size:
            raise ValueError("normalized size is below minimum")
        return float(normalized)

    def normalize_price(self, price: float, rounding: str = "down") -> float:
        value = _decimal(price)
        if self.tick_size <= 0:
            raise ValueError("invalid instrument tick metadata")
        mode = ROUND_CEILING if rounding == "up" else ROUND_FLOOR
        ticks = (value / self.tick_size).to_integral_value(rounding=mode)
        return float(ticks * self.tick_size)

    def notional_usdt(self, amount: float, price: float) -> float:
        if self.inst_type != "SWAP" or self.settle_currency != "USDT":
            raise ValueError("unsupported instrument for USDT notional")
        contracts = _decimal(amount)
        multiplier = self.contract_value * self.contract_multiplier
        if self.contract_value_currency == self.base_currency:
            return float(contracts * multiplier * _decimal(price))
        if self.contract_value_currency == "USDT":
            return float(contracts * multiplier)
        raise ValueError("unsupported instrument contract value currency")
```

Export `InstrumentSpec` from `exchange/models/__init__.py`.

- [ ] **Step 4: Run tests and static compilation**

Run: `pytest -o addopts='' tests/unit/test_instrument_spec.py -v`

Expected: PASS.

Run: `python3 -m py_compile alpha_trading_bot/exchange/models/instruments.py`

Expected: exit code 0.

- [ ] **Step 5: Commit**

```bash
git add alpha_trading_bot/exchange/models/instruments.py alpha_trading_bot/exchange/models/__init__.py tests/unit/test_instrument_spec.py
git commit -m "feat: model OKX instrument constraints"
```

---

### Task 3: Load Instrument Metadata Through ExchangeClient

**Files:**
- Create: `alpha_trading_bot/exchange/instrument_service.py`
- Modify: `alpha_trading_bot/exchange/client.py:12-90`
- Modify: `alpha_trading_bot/exchange/__init__.py`
- Create: `tests/unit/test_instrument_service.py`
- Modify: `tests/unit/test_exchange_raw_endpoints.py`

**Interfaces:**
- Consumes: `InstrumentSpec.from_okx(raw)` from Task 2.
- Produces: `InstrumentService.load() -> InstrumentSpec`
- Produces: `ExchangeClient.instrument_spec -> InstrumentSpec`
- Produces: `ExchangeClient.normalize_order_size(amount: float) -> float`
- Produces: `ExchangeClient.normalize_trigger_price(price: float, position_side: str) -> float`
- Produces: `ExchangeClient.calculate_notional_usdt(amount: float, price: float) -> float`

- [ ] **Step 1: Write failing metadata-service tests**

```python
import pytest

from alpha_trading_bot.exchange.instrument_service import InstrumentService


@pytest.mark.asyncio
async def test_instrument_service_uses_okx_public_endpoint():
    calls = []

    class Exchange:
        def public_get_public_instruments(self, params):
            calls.append(params)
            return {
                "code": "0",
                "data": [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "instType": "SWAP",
                        "settleCcy": "USDT",
                        "ctVal": "0.01",
                        "ctMult": "1",
                        "ctValCcy": "BTC",
                        "minSz": "0.01",
                        "lotSz": "0.01",
                        "tickSz": "0.1",
                    }
                ],
            }

    spec = await InstrumentService(Exchange(), "BTC/USDT:USDT").load()

    assert spec.inst_id == "BTC-USDT-SWAP"
    assert calls == [{"instType": "SWAP", "instId": "BTC-USDT-SWAP"}]


@pytest.mark.asyncio
async def test_instrument_service_rejects_empty_metadata():
    class Exchange:
        def public_get_public_instruments(self, params):
            return {"code": "0", "data": []}

    with pytest.raises(RuntimeError, match="instrument metadata"):
        await InstrumentService(Exchange(), "BTC/USDT:USDT").load()
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest -o addopts='' tests/unit/test_instrument_service.py -v`

Expected: FAIL because `InstrumentService` does not exist.

- [ ] **Step 3: Implement the metadata service**

```python
import asyncio
from typing import Optional

from .models.instruments import InstrumentSpec
from .okx_raw import ensure_okx_success, get_callable, okx_inst_id_from_symbol


class InstrumentService:
    def __init__(self, exchange, symbol: str) -> None:
        self.exchange = exchange
        self.symbol = symbol
        self._cached: Optional[InstrumentSpec] = None

    async def load(self) -> InstrumentSpec:
        if self._cached is not None:
            return self._cached
        method = get_callable(
            self.exchange,
            "public_get_public_instruments",
            "publicGetPublicInstruments",
        )
        if method is None:
            raise RuntimeError("OKX instrument metadata endpoint is unavailable")
        params = {
            "instType": "SWAP",
            "instId": okx_inst_id_from_symbol(self.symbol),
        }
        response = await asyncio.get_running_loop().run_in_executor(
            None, lambda: method(params)
        )
        ensure_okx_success(response, "instrument metadata")
        data = response.get("data") or []
        if not data:
            raise RuntimeError("OKX instrument metadata is empty")
        self._cached = InstrumentSpec.from_okx(data[0])
        return self._cached
```

- [ ] **Step 4: Wire metadata into ExchangeClient**

Add `_instrument_service` and `_instrument_spec` fields. During `initialize()`,
construct the service and await metadata before logging initialization success:

```python
self._instrument_service = InstrumentService(self.exchange, self.symbol)
self._instrument_spec = await self._instrument_service.load()
```

Expose strict facade methods:

```python
@property
def instrument_spec(self) -> InstrumentSpec:
    if self._instrument_spec is None:
        raise RuntimeError("instrument metadata is not initialized")
    return self._instrument_spec

def normalize_order_size(self, amount: float) -> float:
    return self.instrument_spec.normalize_size(amount)

def normalize_trigger_price(self, price: float, position_side: str) -> float:
    rounding = "up" if position_side == "short" else "down"
    return self.instrument_spec.normalize_price(price, rounding)

def calculate_notional_usdt(self, amount: float, price: float) -> float:
    return self.instrument_spec.notional_usdt(amount, price)
```

- [ ] **Step 5: Run service and exchange regression tests**

Run: `pytest -o addopts='' tests/unit/test_instrument_service.py tests/unit/test_exchange_raw_endpoints.py -v`

Expected: PASS. Existing exchange initialization tests must add the raw public instrument endpoint to their fake exchange.

- [ ] **Step 6: Commit**

```bash
git add alpha_trading_bot/exchange/instrument_service.py alpha_trading_bot/exchange/client.py alpha_trading_bot/exchange/__init__.py tests/unit/test_instrument_service.py tests/unit/test_exchange_raw_endpoints.py
git commit -m "feat: load OKX instrument metadata"
```

---

### Task 4: Add Explicit Open, Close, and Reduce Order Intent

**Files:**
- Modify: `alpha_trading_bot/exchange/models/orders.py:1-68`
- Modify: `alpha_trading_bot/exchange/models/__init__.py`
- Modify: `alpha_trading_bot/exchange/order_service.py:75-215`
- Modify: `alpha_trading_bot/exchange/client.py:190-240`
- Modify: `tests/unit/test_zero_behavior_golden.py:138-185`
- Modify: `tests/unit/test_exchange_raw_endpoints.py:130-198`

**Interfaces:**
- Produces: `OrderIntent.OPEN`, `OrderIntent.CLOSE`, and `OrderIntent.REDUCE`.
- Produces: `OrderResult.has_fill -> bool` and `OrderResult.is_terminal -> bool`.
- Changes: `create_order_with_status(..., intent: OrderIntent = OrderIntent.OPEN, position_side: str = "")`.
- Consumes: existing `OrderService._detect_pos_mode()`.

- [ ] **Step 1: Write failing raw-parameter tests**

Add tests that call `_create_order_direct` with explicit intent:

```python
from alpha_trading_bot.exchange.models.orders import OrderIntent


def test_close_order_is_reduce_only_in_one_way_mode():
    calls = []

    class Exchange:
        def private_get_account_config(self):
            return {"code": "0", "data": [{"posMode": "net_mode"}]}

    service = OrderService(Exchange(), "BTC/USDT:USDT")

    service._create_order_direct(
        lambda params: calls.append(params)
        or {"code": "0", "data": [{"ordId": "close-1", "sCode": "0"}]},
        "BTC/USDT:USDT",
        "sell",
        0.01,
        None,
        "market",
        OrderIntent.CLOSE,
        "long",
    )

    assert calls[0]["reduceOnly"] == "true"
    assert calls[0]["posSide"] == "net"


def test_reduce_order_uses_position_side_in_hedge_mode():
    calls = []

    class Exchange:
        def private_get_account_config(self):
            return {"code": "0", "data": [{"posMode": "long_short_mode"}]}

    service = OrderService(Exchange(), "BTC/USDT:USDT")

    service._create_order_direct(
        lambda params: calls.append(params)
        or {"code": "0", "data": [{"ordId": "reduce-1", "sCode": "0"}]},
        "BTC/USDT:USDT",
        "buy",
        0.01,
        None,
        "market",
        OrderIntent.REDUCE,
        "short",
    )

    assert calls[0]["reduceOnly"] == "true"
    assert calls[0]["posSide"] == "short"


def test_open_order_uses_position_side_in_hedge_mode():
    calls = []

    class Exchange:
        def private_get_account_config(self):
            return {"code": "0", "data": [{"posMode": "long_short_mode"}]}

    service = OrderService(Exchange(), "BTC/USDT:USDT")

    service._create_order_direct(
        lambda params: calls.append(params)
        or {"code": "0", "data": [{"ordId": "open-1", "sCode": "0"}]},
        "BTC/USDT:USDT",
        "buy",
        0.01,
        None,
        "market",
        OrderIntent.OPEN,
        "long",
    )

    assert calls[0]["posSide"] == "long"
    assert "reduceOnly" not in calls[0]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest -o addopts='' tests/unit/test_zero_behavior_golden.py::test_order_service_raw_order_and_algo_params_are_stable tests/unit/test_exchange_raw_endpoints.py -v`

Expected: FAIL because ordinary orders do not accept intent or emit `reduceOnly` and `posSide`.

- [ ] **Step 3: Implement intent and fill helpers**

Add to `orders.py`:

```python
class OrderIntent(Enum):
    OPEN = "open"
    CLOSE = "close"
    REDUCE = "reduce"
```

Add to `OrderResult`:

```python
@property
def has_fill(self) -> bool:
    return self.filled_amount > 0

@property
def is_terminal(self) -> bool:
    return self.status in {
        OrderStatus.CLOSED,
        OrderStatus.CANCELED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    }
```

Change `_create_order_direct` so hedge mode always carries the explicit
position side, while close and reduce intents are reduce-only:

```python
pos_mode = self._detect_pos_mode()
if pos_mode == self.POS_MODE_HEDGE:
    if position_side not in {"long", "short"}:
        raise ValueError("position_side is required in hedge mode")
    params["posSide"] = position_side
if intent in {OrderIntent.CLOSE, OrderIntent.REDUCE}:
    params["reduceOnly"] = "true"
    if pos_mode != self.POS_MODE_HEDGE:
        params["posSide"] = "net"
```

Thread `intent` and `position_side` through `OrderService` and `ExchangeClient` public methods, with defaults preserving existing open-order callers.

- [ ] **Step 4: Update golden expected parameters**

Keep the existing open-order golden output unchanged. Add separate close/reduce assertions rather than changing the open-order contract.

- [ ] **Step 5: Run order tests**

Run: `pytest -o addopts='' tests/unit/test_zero_behavior_golden.py tests/unit/test_exchange_raw_endpoints.py tests/unit/test_stop_loss_posside_fix.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add alpha_trading_bot/exchange/models/orders.py alpha_trading_bot/exchange/models/__init__.py alpha_trading_bot/exchange/order_service.py alpha_trading_bot/exchange/client.py tests/unit/test_zero_behavior_golden.py tests/unit/test_exchange_raw_endpoints.py
git commit -m "fix: mark close orders reduce only"
```

---

### Task 5: Poll Market Orders to a Confirmed Fill

**Files:**
- Modify: `alpha_trading_bot/config/models.py:115-165,439-490`
- Modify: `alpha_trading_bot/exchange/order_service.py:96-285,559-608`
- Modify: `alpha_trading_bot/exchange/client.py:33-90,190-244`
- Create: `tests/unit/test_order_confirmation.py`
- Modify: `.env.example:19-25`

**Interfaces:**
- Consumes: `OrderIntent` and `OrderResult.has_fill` from Task 4.
- Produces: `OrderService.create_confirmed_market_order(...) -> OrderResult`.
- Produces: `ExchangeClient.create_confirmed_market_order(...) -> OrderResult`.
- Produces config fields `order_confirm_timeout_seconds: float` and `order_confirm_poll_interval_seconds: float`.

- [ ] **Step 1: Write failing confirmation tests**

Use an in-memory service subclass to avoid real sleeps:

```python
import pytest

from alpha_trading_bot.exchange.models.orders import OrderIntent, OrderResult, OrderStatus
from alpha_trading_bot.exchange.order_service import OrderService


def _result(status, filled=0.0, remaining=0.01, average=0.0):
    return OrderResult(
        order_id="ord-1",
        status=status,
        symbol="BTC/USDT:USDT",
        side="buy",
        order_type="market",
        requested_amount=0.01,
        filled_amount=filled,
        remaining_amount=remaining,
        average_price=average,
    )


@pytest.mark.asyncio
async def test_delayed_fill_is_polled_without_resubmission(monkeypatch):
    service = OrderService(object(), "BTC/USDT:USDT")
    submissions = []
    statuses = [_result(OrderStatus.OPEN), _result(OrderStatus.CLOSED, 0.01, 0, 100.5)]

    async def submit(*args, **kwargs):
        submissions.append(kwargs)
        return _result(OrderStatus.OPEN)

    async def status(order_id, symbol):
        return statuses.pop(0)

    monkeypatch.setattr(service, "create_order_with_status", submit)
    monkeypatch.setattr(service, "get_order_status", status)
    monkeypatch.setattr("alpha_trading_bot.exchange.order_service.asyncio.sleep", lambda _: _noop())

    result = await service.create_confirmed_market_order(
        "BTC/USDT:USDT", "buy", 0.01, OrderIntent.OPEN, "long", 1.0, 0.01
    )

    assert result.status == OrderStatus.CLOSED
    assert result.average_price == pytest.approx(100.5)
    assert len(submissions) == 1


@pytest.mark.asyncio
async def test_partial_fill_at_timeout_cancels_remainder(monkeypatch):
    service = OrderService(object(), "BTC/USDT:USDT")
    canceled = []
    partial = _result(OrderStatus.OPEN, filled=0.006, remaining=0.004, average=100.2)

    monkeypatch.setattr(service, "create_order_with_status", _async_return(_result(OrderStatus.OPEN)))
    monkeypatch.setattr(service, "get_order_status", _async_return(partial))
    monkeypatch.setattr(service, "cancel_order", _async_cancel(canceled))

    result = await service.create_confirmed_market_order(
        "BTC/USDT:USDT", "buy", 0.01, OrderIntent.OPEN, "long", 0.0, 0.01
    )

    assert result.has_fill is True
    assert result.filled_amount == pytest.approx(0.006)
    assert canceled == ["ord-1"]
```

Define the test helpers in the same file:

```python
async def _noop():
    return None


def _async_return(value):
    async def inner(*args, **kwargs):
        return value
    return inner


def _async_cancel(calls):
    async def inner(order_id, symbol):
        calls.append(order_id)
        return True, "success"
    return inner
```

Also cover immediate fill, rejected submission, zero-fill timeout, and unknown status without resubmission.

Add configuration coverage to the same test file:

```python
from alpha_trading_bot.config.models import Config


def test_order_confirmation_config_loads_from_environment(monkeypatch):
    monkeypatch.setenv("OKX_API_KEY", "key")
    monkeypatch.setenv("OKX_SECRET", "secret")
    monkeypatch.setenv("OKX_PASSWORD", "password")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ai-key")
    monkeypatch.setenv("ORDER_CONFIRM_TIMEOUT_SECONDS", "7.5")
    monkeypatch.setenv("ORDER_CONFIRM_POLL_INTERVAL_SECONDS", "0.4")

    config = Config.from_env()

    assert config.trading.order_confirm_timeout_seconds == pytest.approx(7.5)
    assert config.trading.order_confirm_poll_interval_seconds == pytest.approx(0.4)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest -o addopts='' tests/unit/test_order_confirmation.py -v`

Expected: FAIL because `create_confirmed_market_order` does not exist.

- [ ] **Step 3: Add confirmation configuration**

Add to `TradingConfig`:

```python
order_confirm_timeout_seconds: float = 5.0
order_confirm_poll_interval_seconds: float = 0.25
```

Validation:

```python
if self.order_confirm_timeout_seconds <= 0:
    errors.append("订单确认超时必须大于0")
if self.order_confirm_poll_interval_seconds <= 0:
    errors.append("订单确认轮询间隔必须大于0")
if self.order_confirm_poll_interval_seconds > self.order_confirm_timeout_seconds:
    errors.append("订单确认轮询间隔不能大于确认超时")
```

Load `ORDER_CONFIRM_TIMEOUT_SECONDS` and `ORDER_CONFIRM_POLL_INTERVAL_SECONDS` in `Config.from_env()` and document:

```bash
ORDER_CONFIRM_TIMEOUT_SECONDS=5                          # 市价单成交确认超时
ORDER_CONFIRM_POLL_INTERVAL_SECONDS=0.25                 # 成交状态轮询间隔
```

- [ ] **Step 4: Implement polling without duplicate submission**

Add to `OrderService`:

```python
async def create_confirmed_market_order(
    self,
    symbol: str,
    side: str,
    amount: float,
    intent: OrderIntent,
    position_side: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> OrderResult:
    result = await self.create_order_with_status(
        symbol=symbol,
        side=side,
        amount=amount,
        order_type="market",
        intent=intent,
        position_side=position_side,
    )
    if not result.order_id or result.is_rejected:
        return result
    if result.is_terminal and result.has_fill:
        return result

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    latest = result
    while True:
        latest = await self.get_order_status(result.order_id, symbol)
        if latest.is_terminal:
            return latest
        if loop.time() >= deadline:
            break
        await asyncio.sleep(poll_interval_seconds)

    if latest.status == OrderStatus.OPEN:
        await self.cancel_order(result.order_id, symbol)
        final = await self.get_order_status(result.order_id, symbol)
        return final if final.order_id else latest
    return latest
```

The method submits exactly once. It returns partial fills even when cancellation makes the terminal status `CANCELED`; callers inspect `has_fill`.

- [ ] **Step 5: Expose the facade operation**

Store timeout values in `ExchangeClient.__init__` and proxy to `OrderService`. Pass values from both `AdaptiveTradingBot.initialize()` and standard `TradingBot` construction so constructors remain explicit.

The facade must preserve simulation behavior:

```python
if self.test_mode:
    return await self.create_order_with_status(
        symbol=symbol,
        side=side,
        amount=amount,
        order_type="market",
        intent=intent,
        position_side=position_side,
    )
return await self._order_service.create_confirmed_market_order(
    symbol,
    side,
    amount,
    intent,
    position_side,
    self._order_confirm_timeout_seconds,
    self._order_confirm_poll_interval_seconds,
)
```

- [ ] **Step 6: Run confirmation and configuration tests**

Run: `pytest -o addopts='' tests/unit/test_order_confirmation.py tests/unit/test_exchange_raw_endpoints.py -v`

Expected: PASS, including the environment-loading assertions in `test_order_confirmation.py`.

- [ ] **Step 7: Commit**

```bash
git add .env.example alpha_trading_bot/config/models.py alpha_trading_bot/exchange/order_service.py alpha_trading_bot/exchange/client.py alpha_trading_bot/core/adaptive_bot.py alpha_trading_bot/core/bot.py tests/unit/test_order_confirmation.py tests/unit/test_exchange_raw_endpoints.py
git commit -m "fix: confirm market order fills"
```

---

### Task 6: Use Instrument-Aware Fill Data in Adaptive Execution

**Files:**
- Modify: `alpha_trading_bot/core/adaptive_bot.py:683-1110`
- Modify: `tests/unit/test_adaptive_execution_safety.py:145-510`
- Modify: `.env.example:91-94`

**Interfaces:**
- Consumes: `ExchangeClient.normalize_order_size`, `normalize_trigger_price`, `calculate_notional_usdt`, and `create_confirmed_market_order`.
- Produces: `_rebase_stop_price(stop_price: float, quoted_price: float, fill_price: float, position_side: str) -> float`.
- Changes: `_create_confirmed_market_order(..., intent: OrderIntent, position_side: str)` delegates to the exchange facade.

- [ ] **Step 1: Replace the existing notional tests with instrument-aware fakes**

Update test exchanges to expose:

```python
def normalize_order_size(self, amount: float) -> float:
    return amount

def normalize_trigger_price(self, price: float, position_side: str) -> float:
    return price

def calculate_notional_usdt(self, amount: float, price: float) -> float:
    return amount * 0.01 * price
```

Use `amount=0.01`, `price=100000`, and assert notional `10 USDT`, proving the gate no longer uses `amount * price`.

Add a delayed-fill facade test:

```python
@pytest.mark.asyncio
async def test_open_uses_exchange_confirmed_order_once(tmp_path):
    bot = AdaptiveTradingBot(_live_config())
    _wire_execution_deps(bot, tmp_path, _RiskAllows())
    exchange = _ConfirmedExchange(fill_amount=0.01, fill_price=101.25)
    bot._exchange = exchange

    await bot._execute_trade(
        action="open",
        current_price=100.0,
        has_position=False,
        position_data={},
        market_data={"technical": {}},
        cached_rule_result={"adjustments": {"position_multiplier": 1.0}},
    )

    assert exchange.confirmed_order_calls == 1
    assert bot.position_manager.entry_price == pytest.approx(101.25)
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pytest -o addopts='' tests/unit/test_adaptive_execution_safety.py -v`

Expected: FAIL because adaptive execution still computes `amount * entry_price` and performs its own one-shot confirmation.

- [ ] **Step 3: Rebase stop distance to actual fill price**

Add a module helper:

```python
def _rebase_stop_price(
    stop_price: float,
    quoted_price: float,
    fill_price: float,
    position_side: str,
) -> float:
    if stop_price <= 0 or quoted_price <= 0 or fill_price <= 0:
        return stop_price
    distance = abs(quoted_price - stop_price) / quoted_price
    if position_side == "short":
        return fill_price * (1 + distance)
    return fill_price * (1 - distance)
```

After a confirmed fill, rebase and normalize before creating the stop-loss:

```python
stop_loss_price = _rebase_stop_price(
    stop_loss_price,
    current_price,
    entry_price,
    position_side,
)
stop_loss_price = self._exchange.normalize_trigger_price(
    stop_loss_price, position_side
)
```

- [ ] **Step 4: Delegate confirmed execution and normalize size**

Replace the local one-shot query with:

```python
amount = self._exchange.normalize_order_size(amount)
result = await self._exchange.create_confirmed_market_order(
    symbol=symbol,
    side=order_side,
    amount=amount,
    intent=OrderIntent.OPEN,
    position_side=position_side,
)
if not result.has_fill:
    await self._verify_and_recover_position()
    return None
```

Return actual `filled_amount` and `average_price`. Do not retry the submission in `AdaptiveTradingBot`.

- [ ] **Step 5: Use instrument-aware take-profit gating**

Replace the raw multiplication:

```python
try:
    notional = self._exchange.calculate_notional_usdt(amount, entry_price)
except (RuntimeError, ValueError) as exc:
    logger.error(f"[止盈保护] 无法计算合约名义金额: {exc}")
    return
```

Update `.env.example`:

```bash
TAKE_PROFIT_MIN_NOTIONAL=50                              # 启用止盈单的最小USDT等值名义金额
                                                        # 永续合约按合约面值和成交价换算，不直接使用数量×价格
```

- [ ] **Step 6: Run adaptive execution tests**

Run: `pytest -o addopts='' tests/unit/test_adaptive_execution_safety.py tests/unit/test_stop_loss_protection.py tests/unit/test_zero_behavior_golden.py -v`

Expected: PASS, including stop-loss failure protective close.

- [ ] **Step 7: Commit**

```bash
git add .env.example alpha_trading_bot/core/adaptive_bot.py tests/unit/test_adaptive_execution_safety.py tests/unit/test_stop_loss_protection.py tests/unit/test_zero_behavior_golden.py
git commit -m "fix: use instrument aware execution data"
```

---

### Task 7: Manage Stop-Loss and Take-Profit as One Protective Set

**Files:**
- Modify: `alpha_trading_bot/core/position_manager.py:95-128,511-659`
- Modify: `alpha_trading_bot/core/position_recovery.py:14-100`
- Modify: `alpha_trading_bot/core/adaptive_bot.py:748-966,1185-1192`
- Create: `tests/unit/test_protective_order_lifecycle.py`
- Modify: `tests/unit/test_zero_behavior_golden.py:188-211`

**Interfaces:**
- Produces: `PositionManager.take_profit_order_id -> Optional[str]`.
- Produces: `PositionManager.last_take_profit_price -> float`.
- Produces: `PositionManager.clear_protective_orders() -> None`, persisted when a position exists.
- Produces: `PositionRecoveryManager.cancel_protective_orders_before_close() -> Dict[str, Tuple[bool, str]]`.
- Produces: `AdaptiveTradingBot._restore_protective_orders(position_data, current_price, market_data) -> None`.
- Consumes: confirmed reduce and close fills from Task 5.

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_clear_position_clears_both_protective_orders(tmp_path):
    manager = PositionManager(_config(), data_dir=tmp_path)
    manager.update_position(0.02, 100000.0, "BTC/USDT:USDT", "long")
    manager.set_stop_order("sl-1", 99500.0)
    manager.set_take_profit_order("tp-1", 106000.0)

    manager.clear_position()

    assert manager.stop_order_id is None
    assert manager.take_profit_order_id is None
    assert manager.last_stop_price == 0.0
    assert manager.last_take_profit_price == 0.0
```

```python
@pytest.mark.asyncio
async def test_manual_close_cancels_stop_and_take_profit(tmp_path):
    exchange = _ProtectiveExchange()
    manager = PositionManager(_config(), data_dir=tmp_path)
    manager.update_position(0.02, 100000.0, "BTC/USDT:USDT", "long")
    manager.set_stop_order("sl-1", 99500.0)
    manager.set_take_profit_order("tp-1", 106000.0)
    recovery = PositionRecoveryManager(exchange, manager)

    result = await recovery.cancel_protective_orders_before_close()

    assert exchange.canceled_algo_ids == ["sl-1", "tp-1"]
    assert result == {
        "stop_loss": (True, "success"),
        "take_profit": (True, "success"),
    }
```

Add an adaptive reduction test asserting the remaining confirmed amount is persisted and both protective orders are recreated with that amount.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest -o addopts='' tests/unit/test_protective_order_lifecycle.py -v`

Expected: FAIL because take-profit properties and unified cancellation do not exist.

- [ ] **Step 3: Complete PositionManager protective state**

Add properties:

```python
@property
def take_profit_order_id(self) -> Optional[str]:
    return self._take_profit_order_id

@property
def last_take_profit_price(self) -> float:
    return self._last_take_profit_price
```

Change both setters to accept optional IDs and reset their price when the ID is cleared:

```python
def set_stop_order(
    self, stop_order_id: Optional[str], stop_price: float = 0.0
) -> None:
    self._stop_order_id = stop_order_id
    self._last_stop_price = stop_price if stop_order_id and stop_price > 0 else 0.0


def set_take_profit_order(
    self, take_profit_order_id: Optional[str], take_profit_price: float = 0.0
) -> None:
    self._take_profit_order_id = take_profit_order_id
    self._last_take_profit_price = (
        take_profit_price
        if take_profit_order_id and take_profit_price > 0
        else 0.0
    )


def clear_protective_orders(self) -> None:
    self.set_stop_order(None, 0.0)
    self.set_take_profit_order(None, 0.0)
```

Keep the existing persistence body in each setter so clearing IDs is persisted
while a position exists. Call `clear_protective_orders()` inside
`clear_position()` before persistence is cleared.

- [ ] **Step 4: Replace stop-only cancellation**

Import `Dict` and `Tuple` from `typing`, then implement in
`PositionRecoveryManager`:

```python
async def cancel_protective_orders_before_close(
    self,
) -> Dict[str, Tuple[bool, str]]:
    results: Dict[str, Tuple[bool, str]] = {}
    protective_ids = {
        "stop_loss": self._position_manager.stop_order_id,
        "take_profit": self._position_manager.take_profit_order_id,
    }
    for name, algo_id in protective_ids.items():
        if not algo_id:
            continue
        results[name] = await self._exchange.cancel_algo_order(
            str(algo_id), self._exchange.symbol
        )
        success, reason = results[name]
        if success or reason == "already_gone":
            if name == "stop_loss":
                self._position_manager.set_stop_order(None, 0.0)
            else:
                self._position_manager.set_take_profit_order(None, 0.0)
    return results
```

If stored IDs are absent, query open algorithm orders and classify IDs by `slTriggerPx` and `tpTriggerPx` before cancellation.

- [ ] **Step 5: Make close and reduce use the protective set**

For full close:

```python
await self._position_recovery.cancel_protective_orders_before_close()
fill = await self._create_confirmed_market_order(
    symbol=symbol,
    side=close_side,
    amount=amount,
    current_price=current_price,
    intent=OrderIntent.CLOSE,
    position_side=position_side,
)
```

For reduce, cancel protection first, submit `OrderIntent.REDUCE`, then calculate remaining amount from the confirmed fill:

```python
remaining_amount = max(amount - fill["amount"], 0.0)
if remaining_amount > 0:
    self.position_manager.update_position(
        amount=remaining_amount,
        entry_price=entry_price,
        symbol=self._exchange.symbol,
        side=position_side,
    )
    remaining_position = {
        "symbol": self._exchange.symbol,
        "side": position_side,
        "amount": remaining_amount,
        "entry_price": entry_price,
    }
    await self._restore_protective_orders(
        remaining_position, current_price, market_data
    )
else:
    self.position_manager.clear_position()
```

Add the restoration helper:

```python
async def _restore_protective_orders(
    self,
    position_data: Dict[str, Any],
    current_price: float,
    market_data: Dict[str, Any],
) -> None:
    await self._update_stop_loss(current_price, position_data, market_data)
    if not self.position_manager.stop_order_id:
        logger.critical("[保护单] 未能恢复止损保护")
        return
    await self._maybe_create_take_profit_order(
        position_side=position_data["side"],
        amount=position_data["amount"],
        entry_price=position_data["entry_price"],
        symbol=position_data["symbol"],
    )
```

If a full close or reduction returns no confirmed fill after protection was
canceled, call `_restore_protective_orders` with the pre-order position data and
return without changing local amount. If the result is ambiguous, call
`_verify_and_recover_position()` before restoring so exchange position state is
refreshed first.

Before `_restore_protective_orders` creates new orders after a confirmed
reduction, query current algorithm orders and retry cancellation of any stale
stop-loss or take-profit from the pre-reduction amount. If cancellation still
returns `failed`, do not create a duplicate protective order of the same type;
keep the existing reduce-only order, log a critical reconciliation message, and
retry on the next cycle.

- [ ] **Step 6: Run lifecycle regressions**

Run: `pytest -o addopts='' tests/unit/test_protective_order_lifecycle.py tests/unit/test_adaptive_execution_safety.py tests/unit/test_stop_loss_all_paths.py tests/unit/test_zero_behavior_golden.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add alpha_trading_bot/core/position_manager.py alpha_trading_bot/core/position_recovery.py alpha_trading_bot/core/adaptive_bot.py tests/unit/test_protective_order_lifecycle.py tests/unit/test_adaptive_execution_safety.py tests/unit/test_zero_behavior_golden.py
git commit -m "fix: manage protective orders as a set"
```

---

### Task 8: Reconcile Protective Exits and Finalize Trade State

**Files:**
- Modify: `alpha_trading_bot/core/position_close_audit.py:1-139`
- Modify: `alpha_trading_bot/core/adaptive_bot.py:553-620,907-965`
- Modify: `alpha_trading_bot/core/position_recovery.py`
- Create: `tests/unit/test_position_close_reconciliation.py`
- Modify: `tests/unit/test_adaptive_bot_cooldown.py`
- Modify: `tests/unit/test_adaptive_bot_position_sync.py`

**Interfaces:**
- Produces: `PositionCloseEvent` dataclass with `close_type`, `algo_id`, `exit_price`, `amount`, `pnl_percent`, and `trigger_time`.
- Changes: `PositionCloseAuditor.log_disappeared_position_close_event(...) -> Optional[PositionCloseEvent]`.
- Consumes: both protective IDs from `PositionManager` and actual confirmed close fill from Task 5.

- [ ] **Step 1: Write failing stop-loss and take-profit reconciliation tests**

```python
from alpha_trading_bot.core.position_close_audit import (
    PositionCloseAuditContext,
    PositionCloseAuditor,
)


@pytest.mark.asyncio
async def test_take_profit_history_returns_structured_close_event():
    context = PositionCloseAuditContext(
        side="long",
        entry_price=100.0,
        amount=0.01,
        stop_order_id="sl-1",
        stop_price=99.5,
        take_profit_order_id="tp-1",
        take_profit_price=106.0,
    )
    exchange = _HistoryExchange(
        {
            "tp-1": [
                {
                    "id": "tp-1",
                    "info": {
                        "algoId": "tp-1",
                        "tpTriggerPx": "106",
                        "actualPx": "106.1",
                        "sz": "0.01",
                        "triggerTime": "123",
                    },
                }
            ]
        }
    )

    event = await PositionCloseAuditor(context).log_disappeared_position_close_event(
        exchange, "BTC/USDT:USDT"
    )

    assert event is not None
    assert event.close_type == "take_profit"
    assert event.algo_id == "tp-1"
    assert event.exit_price == pytest.approx(106.1)
```

Add equivalent stop-loss coverage and a bot-level test asserting:

```python
assert tracker.closed_exit_price == pytest.approx(106.1)
assert risk_manager.recorded_results == [
    {"pnl_percent": pytest.approx(0.061), "outcome": "win"}
]
assert bot.position_manager.position is None
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest -o addopts='' tests/unit/test_position_close_reconciliation.py -v`

Expected: FAIL because the audit context stores only the stop-loss ID and the auditor returns no event.

- [ ] **Step 3: Return structured close events**

Add:

```python
@dataclass(frozen=True)
class PositionCloseEvent:
    close_type: str
    algo_id: str
    exit_price: float
    amount: float
    pnl_percent: float
    trigger_time: str
```

Extend `PositionCloseAuditContext`:

```python
take_profit_order_id: str = ""
take_profit_price: float = 0.0
```

Query each known protective ID independently, combine results, and select the history row containing `slTriggerPx` or `tpTriggerPx`. Return:

```python
return PositionCloseEvent(
    close_type="take_profit" if info.get("tpTriggerPx") else "stop_loss",
    algo_id=str(matched.get("id") or info.get("algoId") or ""),
    exit_price=exit_price,
    amount=amount,
    pnl_percent=pnl_percent / 100.0,
    trigger_time=str(trigger_time or ""),
)
```

The returned `pnl_percent` uses the 0-1 ratio expected by `PerformanceTracker` and `RiskControlManager`, while logs may continue displaying percentage values.

- [ ] **Step 4: Close learning and risk state after confirmed outcomes**

For manual close, move `performance_tracker.close_trade()` after the confirmed fill and use `fill["average_price"]`.

For protective disappearance:

```python
event = await self._position_close_auditor.log_disappeared_position_close_event(
    self._exchange, symbol
)
if event is not None:
    closed_trade = self.performance_tracker.close_trade(
        exit_time=datetime.now(timezone.utc).isoformat(),
        exit_price=event.exit_price,
        reason=event.close_type,
    )
    if closed_trade is not None:
        self._update_strategy_weights(closed_trade)
        self.risk_manager.record_trade_result(
            {
                "pnl_percent": closed_trade.pnl_percent or 0.0,
                "outcome": closed_trade.outcome.value,
            }
        )
```

Also call `risk_manager.record_trade_result` after confirmed manual closes.

- [ ] **Step 5: Cancel the sibling protective order and clear authoritative state**

When exchange position is gone, cancel any still-open algorithm order whose ID differs from `event.algo_id`, treating `already_gone` as resolved. Then call `PositionManager.clear_position()` exactly once.

If history is unavailable, retain the existing inferred log, cancel known protective IDs, and clear local state only because the exchange position query already proved there is no position.

- [ ] **Step 6: Run reconciliation and execution tests**

Run: `pytest -o addopts='' tests/unit/test_position_close_reconciliation.py tests/unit/test_adaptive_bot_cooldown.py tests/unit/test_adaptive_bot_position_sync.py tests/unit/test_adaptive_execution_safety.py -v`

Expected: PASS.

- [ ] **Step 7: Run full verification**

Run: `pytest -o addopts=''`

Expected: all tests pass.

Run: `python3 -m py_compile alpha_trading_bot/exchange/models/instruments.py alpha_trading_bot/exchange/instrument_service.py alpha_trading_bot/exchange/order_service.py alpha_trading_bot/exchange/client.py alpha_trading_bot/core/adaptive_bot.py alpha_trading_bot/core/position_manager.py alpha_trading_bot/core/position_recovery.py alpha_trading_bot/core/position_close_audit.py`

Expected: exit code 0.

Run: `mypy alpha_trading_bot/`

Expected: exit code 0, or record the pre-existing errors separately without suppressing new errors.

Run: `flake8 alpha_trading_bot/ --max-line-length=88 --extend-ignore=E203,W503`

Expected: exit code 0, or record unavailable/broken local tooling explicitly.

Run: `graphify update .`

Expected: graph update completes successfully.

Run: `git status --short`

Expected: only intentional graphify output changes remain before the final commit.

- [ ] **Step 8: Commit**

```bash
git add alpha_trading_bot/core/position_close_audit.py alpha_trading_bot/core/adaptive_bot.py alpha_trading_bot/core/position_recovery.py tests/unit/test_position_close_reconciliation.py tests/unit/test_adaptive_bot_cooldown.py tests/unit/test_adaptive_bot_position_sync.py graphify-out
git commit -m "fix: reconcile protective exits and trade state"
```

---

## Completion Review

- Confirm `TAKE_PROFIT_MIN_NOTIONAL` remains absent from the user's `.env` unless the user adds it explicitly.
- Confirm no test wrote to `data/trading_state` or `data_json` by comparing file mtimes before and after the full suite.
- Inspect final diff for accidental signal, strategy, scheduler, or dynamic-sizing changes.
- Verify every close and reduce ordinary order is `reduceOnly` in raw parameter tests.
- Verify every local position transition is backed by a confirmed fill or an authoritative no-position exchange response.
