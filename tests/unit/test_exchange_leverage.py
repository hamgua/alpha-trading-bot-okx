"""交易所杠杆设置回归测试。"""

import sys
import types

import pytest


def _install_fake_ccxt(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ccxt = types.ModuleType("ccxt")
    fake_ccxt.okx = object
    monkeypatch.setitem(sys.modules, "ccxt", fake_ccxt)


@pytest.mark.asyncio
async def test_set_leverage_falls_back_when_ccxt_market_sorting_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_ccxt(monkeypatch)

    from alpha_trading_bot.exchange.client import ExchangeClient

    calls = []

    class _Exchange:
        def set_leverage(self, leverage: int, symbol: str) -> None:
            raise TypeError(
                "'<' not supported between instances of 'NoneType' and 'str'"
            )

        def private_post_account_set_leverage(self, params):
            calls.append(params)
            return {"code": "0", "data": [{}]}

    client = ExchangeClient(symbol="BTC/USDT:USDT")
    client.exchange = _Exchange()

    await client.set_leverage(5)

    assert calls == [{"instId": "BTC-USDT-SWAP", "lever": "5", "mgnMode": "cross"}]
