"""OKX raw endpoint regression tests for ccxt load_markets avoidance."""

import sys
import types

import pytest


def _install_fake_ccxt(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ccxt = types.ModuleType("ccxt")
    fake_ccxt.okx = object
    monkeypatch.setitem(sys.modules, "ccxt", fake_ccxt)


@pytest.mark.asyncio
async def test_account_service_uses_raw_balance_and_positions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_ccxt(monkeypatch)
    from alpha_trading_bot.exchange.account_service import AccountService

    calls = []

    class _Exchange:
        def fetch_balance(self):
            raise AssertionError("ccxt fetch_balance should not be called")

        def fetch_positions(self, symbols):
            raise AssertionError("ccxt fetch_positions should not be called")

        def private_get_account_balance(self, params):
            calls.append(("balance", params))
            return {
                "code": "0",
                "data": [
                    {
                        "details": [
                            {
                                "ccy": "USDT",
                                "availEq": "123.45",
                                "availBal": "111.11",
                            }
                        ]
                    }
                ],
            }

        def private_get_account_positions(self, params):
            calls.append(("positions", params))
            return {
                "code": "0",
                "data": [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "pos": "0.25",
                        "posSide": "long",
                        "avgPx": "62000",
                        "upl": "12.3",
                    }
                ],
            }

    service = AccountService(_Exchange(), "BTC/USDT:USDT")

    balance = await service.get_balance()
    position = await service.get_position()

    assert balance == 123.45
    assert position == {
        "symbol": "BTC/USDT:USDT",
        "side": "long",
        "amount": 0.25,
        "entry_price": 62000.0,
        "unrealized_pnl": 12.3,
    }
    assert calls == [
        ("balance", {"ccy": "USDT"}),
        ("positions", {"instId": "BTC-USDT-SWAP"}),
    ]


@pytest.mark.asyncio
async def test_account_service_parses_okx_net_short_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_ccxt(monkeypatch)
    from alpha_trading_bot.exchange.account_service import AccountService

    class _Exchange:
        def fetch_positions(self, symbols):
            raise AssertionError("ccxt fetch_positions should not be called")

        def private_get_account_positions(self, params):
            return {
                "code": "0",
                "data": [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "pos": "-0.25",
                        "posSide": "net",
                        "avgPx": "62000",
                        "upl": "-12.3",
                    }
                ],
            }

    service = AccountService(_Exchange(), "BTC/USDT:USDT")

    position = await service.get_position()

    assert position is not None
    assert position["side"] == "short"
    assert position["amount"] == 0.25


@pytest.mark.asyncio
async def test_order_service_uses_raw_order_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_ccxt(monkeypatch)
    from alpha_trading_bot.exchange.models.orders import OrderStatus
    from alpha_trading_bot.exchange.order_service import OrderService

    calls = []

    class _Exchange:
        def create_order(self, **kwargs):
            raise AssertionError("ccxt create_order should not be called")

        def cancel_order(self, order_id, symbol):
            raise AssertionError("ccxt cancel_order should not be called")

        def fetch_order(self, order_id, symbol):
            raise AssertionError("ccxt fetch_order should not be called")

        def private_post_trade_order(self, params):
            calls.append(("create", params))
            return {
                "code": "0",
                "data": [
                    {
                        "ordId": "ord-1",
                        "state": "live",
                        "side": params["side"],
                        "ordType": params["ordType"],
                        "sz": params["sz"],
                    }
                ],
            }

        def private_post_trade_cancel_order(self, params):
            calls.append(("cancel", params))
            return {"code": "0", "data": [{"ordId": params["ordId"], "sCode": "0"}]}

        def private_get_trade_order(self, params):
            calls.append(("status", params))
            return {
                "code": "0",
                "data": [
                    {
                        "ordId": params["ordId"],
                        "state": "filled",
                        "side": "buy",
                        "ordType": "market",
                        "sz": "0.1",
                        "accFillSz": "0.1",
                        "avgPx": "62000",
                    }
                ],
            }

    service = OrderService(_Exchange(), "BTC/USDT:USDT")

    result = await service.create_order_with_status(
        "BTC/USDT:USDT", "buy", 0.1, order_type="market"
    )
    cancel_result = await service.cancel_order("ord-1", "BTC/USDT:USDT")
    status = await service.get_order_status("ord-1", "BTC/USDT:USDT")

    assert result.order_id == "ord-1"
    assert result.status == OrderStatus.OPEN
    assert cancel_result == (True, "success")
    assert status.status == OrderStatus.CLOSED
    assert status.filled_amount == 0.1
    assert calls == [
        (
            "create",
            {
                "instId": "BTC-USDT-SWAP",
                "tdMode": "cross",
                "side": "buy",
                "ordType": "market",
                "sz": "0.1",
            },
        ),
        ("cancel", {"instId": "BTC-USDT-SWAP", "ordId": "ord-1"}),
        ("status", {"instId": "BTC-USDT-SWAP", "ordId": "ord-1"}),
    ]


@pytest.mark.asyncio
async def test_order_service_uses_raw_algo_order_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_ccxt(monkeypatch)
    from alpha_trading_bot.exchange.order_service import OrderService

    calls = []

    class _Exchange:
        def create_order(self, **kwargs):
            raise AssertionError("ccxt create_order should not be called")

        def private_post_trade_order_algo(self, params):
            calls.append(params)
            return {"code": "0", "data": [{"algoId": f"algo-{len(calls)}"}]}

    service = OrderService(_Exchange(), "BTC/USDT:USDT")

    stop = await service.create_stop_loss_with_status(
        "BTC/USDT:USDT", "sell", 0.1, 61000
    )
    take_profit = await service.create_take_profit("BTC/USDT:USDT", "sell", 0.1, 65000)

    assert stop.order_id == "algo-1"
    assert take_profit.order_id == "algo-2"
    assert calls == [
        {
            "instId": "BTC-USDT-SWAP",
            "tdMode": "cross",
            "side": "sell",
            "ordType": "conditional",
            "sz": "0.1",
            "reduceOnly": "true",
            "posSide": "long",
            "slTriggerPx": "61000",
            "slOrdPx": "-1",
        },
        {
            "instId": "BTC-USDT-SWAP",
            "tdMode": "cross",
            "side": "sell",
            "ordType": "conditional",
            "sz": "0.1",
            "reduceOnly": "true",
            "posSide": "long",
            "tpTriggerPx": "65000",
            "tpOrdPx": "-1",
        },
    ]


@pytest.mark.asyncio
async def test_order_service_sets_short_reduce_only_algo_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_ccxt(monkeypatch)
    from alpha_trading_bot.exchange.order_service import OrderService

    calls = []

    class _Exchange:
        def private_post_trade_order_algo(self, params):
            calls.append(params)
            return {"code": "0", "data": [{"algoId": "algo-short"}]}

    service = OrderService(_Exchange(), "BTC/USDT:USDT")

    stop = await service.create_stop_loss_with_status(
        "BTC/USDT:USDT", "buy", 0.1, 63000
    )

    assert stop.order_id == "algo-short"
    assert calls == [
        {
            "instId": "BTC-USDT-SWAP",
            "tdMode": "cross",
            "side": "buy",
            "ordType": "conditional",
            "sz": "0.1",
            "reduceOnly": "true",
            "posSide": "short",
            "slTriggerPx": "63000",
            "slOrdPx": "-1",
        }
    ]


@pytest.mark.asyncio
async def test_exchange_client_uses_raw_open_order_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_ccxt(monkeypatch)
    from alpha_trading_bot.exchange.client import ExchangeClient

    calls = []

    class _Exchange:
        def fetch_open_orders(self, symbol, params=None):
            raise AssertionError("ccxt fetch_open_orders should not be called")

        def private_get_trade_orders_pending(self, params):
            calls.append(("open", params))
            return {"code": "0", "data": [{"ordId": "ord-1", "state": "live"}]}

        def private_get_trade_orders_algo_pending(self, params):
            calls.append(("algo", params))
            return {"code": "0", "data": [{"algoId": "algo-1", "slTriggerPx": "61000"}]}

    client = ExchangeClient(symbol="BTC/USDT:USDT")
    client.exchange = _Exchange()

    open_orders = await client.get_open_orders("BTC/USDT:USDT")
    algo_orders = await client.get_algo_orders("BTC/USDT:USDT")

    assert open_orders[0]["id"] == "ord-1"
    assert algo_orders[0]["id"] == "algo-1"
    assert calls == [
        ("open", {"instId": "BTC-USDT-SWAP"}),
        ("algo", {"instId": "BTC-USDT-SWAP", "ordType": "conditional"}),
    ]


@pytest.mark.asyncio
async def test_exchange_client_uses_raw_algo_order_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_ccxt(monkeypatch)
    from alpha_trading_bot.exchange.client import ExchangeClient

    calls = []

    class _Exchange:
        def private_get_trade_orders_algo_history(self, params):
            calls.append(params)
            return {
                "code": "0",
                "data": [
                    {
                        "algoId": "algo-stop-1",
                        "state": "effective",
                        "ordType": "conditional",
                        "side": "sell",
                        "sz": "0.01",
                        "slTriggerPx": "107680",
                        "actualPx": "107675.2",
                        "triggerTime": "1781179923000",
                    }
                ],
            }

    client = ExchangeClient(symbol="BTC/USDT:USDT")
    client.exchange = _Exchange()

    history = await client.get_algo_order_history(
        "BTC/USDT:USDT", algo_id="algo-stop-1", limit=20
    )

    assert history[0]["id"] == "algo-stop-1"
    assert history[0]["status"] == "closed"
    assert history[0]["info"]["actualPx"] == "107675.2"
    assert calls == [
        {
            "instId": "BTC-USDT-SWAP",
            "ordType": "conditional",
            "algoId": "algo-stop-1",
            "limit": "20",
        }
    ]
