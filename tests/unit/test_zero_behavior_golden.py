"""Golden-master tests for zero-behavior slimming refactors.

These tests pin externally relevant behavior before structural cleanup.  They
intentionally assert exact outputs for decision, order parameter, scheduler, and
state-persistence flows so later refactors cannot quietly change trading
behavior.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from alpha_trading_bot.config.models import Config, ExchangeConfig, TradingConfig
from alpha_trading_bot.core.cycle_timing import calculate_cycle_timing
from alpha_trading_bot.core.decision_engine import DecisionEngine
from alpha_trading_bot.core.position_manager import PositionManager
from alpha_trading_bot.core.state_persistence import StatePersistence
from alpha_trading_bot.core.trading_scheduler import TradingScheduler
from alpha_trading_bot.core.trading_state_machine import (
    TradingLifecycleState,
    derive_lifecycle_state,
)
from alpha_trading_bot.exchange.models.orders import (
    OrderIntent,
    OrderResult,
    OrderStatus,
)
from alpha_trading_bot.exchange.order_service import OrderService


def _selected(signal: str, confidence: float, strategy_type: str):
    selected = MagicMock()
    selected.signal = signal
    selected.confidence = confidence
    selected.strategy_type = strategy_type
    selected.reasons = ["golden"]
    return selected


def _config(
    *,
    allow_short_selling: bool = True,
    cycle_minutes: int = 15,
    random_offset_range: int = 180,
) -> Config:
    return Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(
            test_mode=True,
            allow_short_selling=allow_short_selling,
            cycle_minutes=cycle_minutes,
            random_offset_range=random_offset_range,
        ),
    )


@pytest.mark.parametrize(
    "ai_signal,selected,market_data,expected",
    [
        (
            "BUY",
            _selected("BUY", 0.82, "trend_following"),
            {
                "technical": {"atr_percent": 0.02, "rsi": 55},
                "has_position": False,
                "risk_reward_ratio": 2.4,
                "market_structure": "bullish",
                "final_confidence": 0.82,
                "min_trade_confidence": 0.60,
            },
            {
                "action": "open",
                "reason": "AI信号买入",
                "confidence": 0.82,
                "strategy": "trend_following",
                "position_advice": "R/R=2.40良好，正常仓位",
            },
        ),
        (
            "SHORT",
            _selected("SHORT", 0.78, "market_structure_short"),
            {
                "technical": {"atr_percent": 0.03, "rsi": 52},
                "has_position": False,
                "risk_reward_ratio": 0.75,
                "market_structure": "bearish",
                "final_confidence": 0.78,
                "min_trade_confidence": 0.60,
            },
            {
                "action": "sell",
                "reason": "AI信号做空",
                "confidence": 0.78,
                "strategy": "market_structure_short",
            },
        ),
        (
            "HOLD",
            _selected("SHORT", 0.80, "breakdown"),
            {
                "technical": {"atr_percent": 0.02, "rsi": 50},
                "has_position": False,
                "risk_reward_ratio": 1.5,
                "market_structure": "bearish",
                "final_confidence": 0.80,
                "min_trade_confidence": 0.60,
            },
            {
                "action": "sell",
                "reason": "策略SHORT覆盖AI-HOLD(置信度80%, 短R/R=1.50)",
                "confidence": 0.6400000000000001,
                "strategy": "breakdown",
                "position_advice": "短R/R=1.50，做空开仓",
            },
        ),
        (
            "SELL",
            _selected("HOLD", 0.61, "safe_mode"),
            {
                "technical": {"atr_percent": 0.02, "rsi": 55},
                "has_position": True,
                "risk_reward_ratio": 0,
                "market_structure": "sideways",
            },
            {
                "action": "reduce",
                "reason": "安全模式降低仓位: ['golden']",
                "confidence": 0.305,
                "strategy": "safe_mode",
            },
        ),
    ],
)
def test_decision_engine_golden_outputs(
    ai_signal, selected, market_data, expected
) -> None:
    engine = DecisionEngine(_config())

    assert engine.make_decision(ai_signal, selected, market_data) == expected


def test_order_service_raw_order_and_algo_params_are_stable() -> None:
    service = OrderService(MagicMock(), "BTC/USDT:USDT")
    order_calls = []
    algo_calls = []

    def order_method(params):
        order_calls.append(params)
        return {"code": "0", "data": [{"ordId": "ord-1", "sCode": "0"}]}

    def algo_method(params):
        algo_calls.append(params)
        return {"code": "0", "data": [{"algoId": "algo-1", "sCode": "0"}]}

    order = service._create_order_direct(
        order_method, "BTC/USDT:USDT", "buy", 0.01, None, "market"
    )
    algo = service._create_algo_order_direct(
        algo_method,
        "BTC/USDT:USDT",
        "sell",
        0.01,
        {"slTriggerPx": 99950.0, "slOrdPx": -1},
    )

    assert order_calls == [
        {
            "instId": "BTC-USDT-SWAP",
            "tdMode": "cross",
            "side": "buy",
            "ordType": "market",
            "sz": "0.01",
        }
    ]
    assert order["id"] == "ord-1"
    assert algo_calls == [
        {
            "instId": "BTC-USDT-SWAP",
            "tdMode": "cross",
            "side": "sell",
            "ordType": "conditional",
            "sz": "0.01",
            "reduceOnly": "true",
            "posSide": "net",
            "slTriggerPx": "99950",
            "slOrdPx": "-1",
        }
    ]
    assert algo == {"id": "algo-1", "info": {"algoId": "algo-1", "sCode": "0"}}


def test_close_order_is_reduce_only_in_one_way_mode() -> None:
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


def test_reduce_order_uses_position_side_in_hedge_mode() -> None:
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


def test_open_order_uses_position_side_in_hedge_mode() -> None:
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


@pytest.mark.parametrize(
    ("status", "filled_amount", "has_fill", "is_terminal"),
    [
        (OrderStatus.OPEN, 0.0, False, False),
        (OrderStatus.OPEN, 0.01, True, False),
        (OrderStatus.CLOSED, 0.01, True, True),
        (OrderStatus.CANCELED, 0.0, False, True),
        (OrderStatus.REJECTED, 0.0, False, True),
        (OrderStatus.EXPIRED, 0.0, False, True),
    ],
)
def test_order_result_fill_and_terminal_helpers(
    status: OrderStatus,
    filled_amount: float,
    has_fill: bool,
    is_terminal: bool,
) -> None:
    result = OrderResult(
        order_id="ord-1",
        status=status,
        symbol="BTC/USDT:USDT",
        side="buy",
        order_type="market",
        requested_amount=0.01,
        filled_amount=filled_amount,
        remaining_amount=0.01 - filled_amount,
        average_price=100000.0,
    )

    assert result.has_fill is has_fill
    assert result.is_terminal is is_terminal


def test_position_and_state_persistence_golden_outputs(tmp_path) -> None:
    config = _config()
    manager = PositionManager(config, data_dir=tmp_path / "long")
    manager.update_position(0.01, 100000.0, "BTC/USDT:USDT", side="long")
    manager.set_stop_order("sl-1", 99950.0)
    manager.set_take_profit_order("tp-1", 106000.0)
    short_manager = PositionManager(config, data_dir=tmp_path / "short")
    short_manager.update_position(0.01, 100000.0, "BTC/USDT:USDT", side="short")

    assert manager.calculate_stop_price_unified(100500.0) == 99980.0
    assert short_manager.calculate_short_stop_price(100000.0) == 100050.0
    assert manager.calculate_take_profit_price(100000.0) == 106000.0
    assert short_manager.calculate_short_take_profit_price(100000.0) == 94000.0
    assert manager.stop_order_id == "sl-1"
    assert manager.last_stop_price == 99950.0

    state = StatePersistence(tmp_path / "long").load_state()
    assert state.position is not None
    assert state.position.symbol == "BTC/USDT:USDT"
    assert state.position.side == "long"
    assert state.position.stop_order_id == "sl-1"
    assert state.position.take_profit_order_id == "tp-1"
    assert state.position.last_stop_price == 99950.0
    assert state.position.last_take_profit_price == 106000.0


def test_scheduler_next_cycle_seconds_golden_output() -> None:
    scheduler = TradingScheduler(_config(cycle_minutes=15, random_offset_range=180))

    with (
        patch("alpha_trading_bot.core.trading_scheduler.datetime") as dt,
        patch(
            "alpha_trading_bot.core.trading_scheduler.random.randint", return_value=120
        ),
    ):
        dt.now.return_value = datetime(2026, 6, 11, 14, 7, 30)
        dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

        assert scheduler.get_next_cycle_seconds() == 570.0


def test_cycle_timing_and_lifecycle_state_golden_outputs() -> None:
    timing = calculate_cycle_timing(
        datetime(2026, 6, 11, 14, 7, 30),
        cycle_minutes=15,
        offset_range=180,
        random_offset=120,
    )

    assert timing.wait_seconds == 570.0
    assert timing.random_offset == 120
    assert timing.next_time == datetime(2026, 6, 11, 14, 17, 0)
    assert derive_lifecycle_state(False) == TradingLifecycleState.NO_POSITION
    assert derive_lifecycle_state(True, "sl-1") == TradingLifecycleState.STOP_PROTECTED
    assert (
        derive_lifecycle_state(True, "sl-1", "tp-1")
        == TradingLifecycleState.FULLY_PROTECTED
    )
