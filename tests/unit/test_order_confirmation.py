"""Market-order confirmation tests."""

from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from alpha_trading_bot.config.models import Config, ExchangeConfig, TradingConfig
from alpha_trading_bot.core.adaptive_bot import AdaptiveTradingBot
from alpha_trading_bot.core.bot import TradingBot
from alpha_trading_bot.exchange.models.orders import (
    OrderIntent,
    OrderResult,
    OrderStatus,
)
from alpha_trading_bot.exchange.order_service import OrderService

SYMBOL = "BTC/USDT:USDT"


def _result(
    status: OrderStatus,
    filled: float = 0.0,
    remaining: float = 0.01,
    average: float = 0.0,
    order_id: str = "ord-1",
) -> OrderResult:
    return OrderResult(
        order_id=order_id,
        status=status,
        symbol=SYMBOL,
        side="buy",
        order_type="market",
        requested_amount=0.01,
        filled_amount=filled,
        remaining_amount=remaining,
        average_price=average,
    )


async def _noop(_: float = 0.0) -> None:
    return None


class _Clock:
    def __init__(self, values: List[float]) -> None:
        self._values = iter(values)

    def time(self) -> float:
        return next(self._values)


@pytest.mark.asyncio
async def test_immediate_fill_returns_submission_without_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = OrderService(object(), SYMBOL)
    submit = AsyncMock(return_value=_result(OrderStatus.CLOSED, 0.01, 0.0, 100.5))
    status = AsyncMock()
    monkeypatch.setattr(service, "create_order_with_status", submit)
    monkeypatch.setattr(service, "get_order_status", status)

    result = await service.create_confirmed_market_order(
        SYMBOL, "buy", 0.01, OrderIntent.OPEN, "long", 1.0, 0.25
    )

    assert result.has_fill is True
    assert result.status == OrderStatus.CLOSED
    submit.assert_awaited_once()
    status.assert_not_awaited()


@pytest.mark.asyncio
async def test_delayed_fill_is_polled_without_resubmission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = OrderService(object(), SYMBOL)
    submit = AsyncMock(return_value=_result(OrderStatus.OPEN))
    status = AsyncMock(
        side_effect=[
            _result(OrderStatus.OPEN),
            _result(OrderStatus.CLOSED, 0.01, 0.0, 100.5),
        ]
    )
    monkeypatch.setattr(service, "create_order_with_status", submit)
    monkeypatch.setattr(service, "get_order_status", status)
    monkeypatch.setattr(
        "alpha_trading_bot.exchange.order_service.asyncio.get_running_loop",
        lambda: _Clock([0.0, 0.0]),
    )
    monkeypatch.setattr("alpha_trading_bot.exchange.order_service.asyncio.sleep", _noop)

    result = await service.create_confirmed_market_order(
        SYMBOL, "buy", 0.01, OrderIntent.OPEN, "long", 1.0, 0.25
    )

    assert result.status == OrderStatus.CLOSED
    assert result.average_price == pytest.approx(100.5)
    submit.assert_awaited_once()
    assert status.await_count == 2


@pytest.mark.asyncio
async def test_rejected_submission_does_not_poll_or_resubmit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = OrderService(object(), SYMBOL)
    submit = AsyncMock(return_value=_result(OrderStatus.REJECTED, order_id=""))
    status = AsyncMock()
    monkeypatch.setattr(service, "create_order_with_status", submit)
    monkeypatch.setattr(service, "get_order_status", status)

    result = await service.create_confirmed_market_order(
        SYMBOL, "buy", 0.01, OrderIntent.OPEN, "long", 1.0, 0.25
    )

    assert result.is_rejected is True
    submit.assert_awaited_once()
    status.assert_not_awaited()


@pytest.mark.asyncio
async def test_partial_fill_timeout_cancels_remainder_and_preserves_fill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = OrderService(object(), SYMBOL)
    partial = _result(OrderStatus.OPEN, 0.006, 0.004, 100.2)
    submit = AsyncMock(return_value=_result(OrderStatus.OPEN))
    status = AsyncMock(
        side_effect=[partial, _result(OrderStatus.CANCELED, 0.0, 0.0, 0.0)]
    )
    cancel = AsyncMock(return_value=(True, "success"))
    monkeypatch.setattr(service, "create_order_with_status", submit)
    monkeypatch.setattr(service, "get_order_status", status)
    monkeypatch.setattr(service, "cancel_order", cancel)
    monkeypatch.setattr(
        "alpha_trading_bot.exchange.order_service.asyncio.get_running_loop",
        lambda: _Clock([0.0, 0.0]),
    )

    result = await service.create_confirmed_market_order(
        SYMBOL, "buy", 0.01, OrderIntent.OPEN, "long", 0.0, 0.25
    )

    assert result.status == OrderStatus.CANCELED
    assert result.has_fill is True
    assert result.filled_amount == pytest.approx(0.006)
    assert result.average_price == pytest.approx(100.2)
    submit.assert_awaited_once()
    cancel.assert_awaited_once_with("ord-1", SYMBOL)
    assert status.await_count == 2


@pytest.mark.asyncio
async def test_partial_fill_preserves_average_when_terminal_status_omits_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = OrderService(object(), SYMBOL)
    partial = _result(OrderStatus.OPEN, 0.006, 0.004, 100.2)
    submit = AsyncMock(return_value=_result(OrderStatus.OPEN))
    status = AsyncMock(
        side_effect=[partial, _result(OrderStatus.CANCELED, 0.006, 0.004, 0.0)]
    )
    cancel = AsyncMock(return_value=(True, "success"))
    monkeypatch.setattr(service, "create_order_with_status", submit)
    monkeypatch.setattr(service, "get_order_status", status)
    monkeypatch.setattr(service, "cancel_order", cancel)
    monkeypatch.setattr(
        "alpha_trading_bot.exchange.order_service.asyncio.get_running_loop",
        lambda: _Clock([0.0, 0.0]),
    )

    result = await service.create_confirmed_market_order(
        SYMBOL, "buy", 0.01, OrderIntent.OPEN, "long", 0.0, 0.25
    )

    assert result.status == OrderStatus.CANCELED
    assert result.filled_amount == pytest.approx(0.006)
    assert result.average_price == pytest.approx(100.2)


@pytest.mark.asyncio
async def test_zero_fill_timeout_cancels_remainder_without_sleeping_after_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = OrderService(object(), SYMBOL)
    submit = AsyncMock(return_value=_result(OrderStatus.OPEN))
    status = AsyncMock(
        side_effect=[_result(OrderStatus.OPEN), _result(OrderStatus.CANCELED, 0.0, 0.0)]
    )
    cancel = AsyncMock(return_value=(True, "success"))
    sleep = AsyncMock()
    monkeypatch.setattr(service, "create_order_with_status", submit)
    monkeypatch.setattr(service, "get_order_status", status)
    monkeypatch.setattr(service, "cancel_order", cancel)
    monkeypatch.setattr(
        "alpha_trading_bot.exchange.order_service.asyncio.get_running_loop",
        lambda: _Clock([10.0, 10.0]),
    )
    monkeypatch.setattr("alpha_trading_bot.exchange.order_service.asyncio.sleep", sleep)

    result = await service.create_confirmed_market_order(
        SYMBOL, "buy", 0.01, OrderIntent.OPEN, "long", 0.0, 0.25
    )

    assert result.has_fill is False
    assert result.status == OrderStatus.CANCELED
    submit.assert_awaited_once()
    cancel.assert_awaited_once_with("ord-1", SYMBOL)
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_status_times_out_without_duplicate_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = OrderService(object(), SYMBOL)
    submit = AsyncMock(return_value=_result(OrderStatus.OPEN))
    status = AsyncMock(
        side_effect=[_result(OrderStatus.UNKNOWN), _result(OrderStatus.UNKNOWN)]
    )
    cancel = AsyncMock(return_value=(False, "failed"))
    monkeypatch.setattr(service, "create_order_with_status", submit)
    monkeypatch.setattr(service, "get_order_status", status)
    monkeypatch.setattr(service, "cancel_order", cancel)
    monkeypatch.setattr(
        "alpha_trading_bot.exchange.order_service.asyncio.get_running_loop",
        lambda: _Clock([0.0, 0.0]),
    )

    result = await service.create_confirmed_market_order(
        SYMBOL, "buy", 0.01, OrderIntent.OPEN, "long", 0.0, 0.25
    )

    assert result.status == OrderStatus.UNKNOWN
    submit.assert_awaited_once()
    cancel.assert_awaited_once_with("ord-1", SYMBOL)
    assert status.await_count == 2


@pytest.mark.asyncio
async def test_partial_fill_survives_unavailable_cancellation_and_final_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = OrderService(object(), SYMBOL)
    partial = _result(OrderStatus.OPEN, 0.006, 0.004, 100.2)
    submit = AsyncMock(return_value=_result(OrderStatus.OPEN))
    status = AsyncMock(side_effect=[partial, _result(OrderStatus.UNKNOWN, order_id="")])
    cancel = AsyncMock(side_effect=RuntimeError("cancel endpoint unavailable"))
    monkeypatch.setattr(service, "create_order_with_status", submit)
    monkeypatch.setattr(service, "get_order_status", status)
    monkeypatch.setattr(service, "cancel_order", cancel)
    monkeypatch.setattr(
        "alpha_trading_bot.exchange.order_service.asyncio.get_running_loop",
        lambda: _Clock([0.0, 0.0]),
    )

    result = await service.create_confirmed_market_order(
        SYMBOL, "buy", 0.01, OrderIntent.OPEN, "long", 0.0, 0.25
    )

    assert result.has_fill is True
    assert result.filled_amount == pytest.approx(0.006)
    assert result.average_price == pytest.approx(100.2)
    submit.assert_awaited_once()
    cancel.assert_awaited_once_with("ord-1", SYMBOL)


@pytest.mark.parametrize(
    ("timeout_seconds", "poll_interval_seconds", "message"),
    [
        (0.0, 0.25, "订单确认超时必须大于0"),
        (5.0, 0.0, "订单确认轮询间隔必须大于0"),
        (0.25, 0.5, "订单确认轮询间隔不能大于确认超时"),
    ],
)
def test_order_confirmation_config_rejects_invalid_settings(
    timeout_seconds: float, poll_interval_seconds: float, message: str
) -> None:
    config = TradingConfig(
        order_confirm_timeout_seconds=timeout_seconds,
        order_confirm_poll_interval_seconds=poll_interval_seconds,
    )

    assert message in config.validate()


def test_order_confirmation_config_loads_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OKX_API_KEY", "key")
    monkeypatch.setenv("OKX_SECRET", "secret")
    monkeypatch.setenv("OKX_PASSWORD", "password")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ai-key")
    monkeypatch.setenv("ORDER_CONFIRM_TIMEOUT_SECONDS", "7.5")
    monkeypatch.setenv("ORDER_CONFIRM_POLL_INTERVAL_SECONDS", "0.4")

    config = Config.from_env()

    assert config.trading.order_confirm_timeout_seconds == pytest.approx(7.5)
    assert config.trading.order_confirm_poll_interval_seconds == pytest.approx(0.4)


@pytest.mark.asyncio
async def test_exchange_client_simulates_confirmed_market_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alpha_trading_bot.exchange.client import ExchangeClient

    client = ExchangeClient(test_mode=True)
    service = AsyncMock()
    client._order_service = service
    monkeypatch.setattr("alpha_trading_bot.exchange.client.time.time", lambda: 1.0)

    result = await client.create_confirmed_market_order(
        SYMBOL, "buy", 0.01, OrderIntent.OPEN, "long"
    )

    assert result.order_id == "SIMULATED_ORDER_BUY_1"
    assert result.has_fill is True
    service.create_confirmed_market_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_exchange_client_confirmation_requires_initialized_order_service() -> (
    None
):
    from alpha_trading_bot.exchange.client import ExchangeClient

    client = ExchangeClient(test_mode=False)

    with pytest.raises(RuntimeError, match="Order service is not initialized"):
        await client.create_confirmed_market_order(
            SYMBOL, "buy", 0.01, OrderIntent.OPEN, "long"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("bot_class", [AdaptiveTradingBot, TradingBot])
async def test_bot_initialization_passes_confirmation_settings_to_exchange_client(
    bot_class: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alpha_trading_bot.exchange import client as exchange_client_module

    captured: List[Dict[str, Any]] = []

    class _FailingExchange:
        def __init__(self, **kwargs: Any) -> None:
            captured.append(kwargs)

        async def initialize(self) -> None:
            raise RuntimeError("stop after construction")

    monkeypatch.setattr(exchange_client_module, "ExchangeClient", _FailingExchange)
    config = Config(
        exchange=ExchangeConfig(api_key="key", secret="secret", password="password"),
        trading=TradingConfig(
            order_confirm_timeout_seconds=7.5,
            order_confirm_poll_interval_seconds=0.4,
        ),
    )

    initialized = await bot_class(config).initialize()

    assert initialized is False
    assert captured == [
        {
            "api_key": "key",
            "secret": "secret",
            "password": "password",
            "symbol": "BTC/USDT:USDT",
            "allow_short_selling": True,
            "test_mode": True,
            "max_position_usage": 0.30,
            "order_confirm_timeout_seconds": 7.5,
            "order_confirm_poll_interval_seconds": 0.4,
        }
    ]
