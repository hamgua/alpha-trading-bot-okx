"""市场数据 ticker 获取回归测试。"""

import pytest
import sys
import types


def _install_fake_ccxt() -> None:
    fake_ccxt = types.ModuleType("ccxt")
    fake_ccxt.okx = object
    sys.modules.setdefault("ccxt", fake_ccxt)


@pytest.mark.asyncio
async def test_get_ticker_uses_okx_raw_endpoint_without_loading_markets() -> None:
    _install_fake_ccxt()
    from alpha_trading_bot.exchange.market_data import MarketDataService

    calls = []

    class _Exchange:
        def fetch_ticker(self, symbol: str):
            raise AssertionError("ccxt fetch_ticker should not be called")

        def public_get_market_ticker(self, params):
            calls.append(params)
            return {
                "code": "0",
                "data": [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "last": "108000.5",
                        "high24h": "109000.0",
                        "low24h": "106000.0",
                        "open24h": "107000.0",
                        "volCcy24h": "12345.6",
                    }
                ],
            }

    service = MarketDataService(_Exchange(), "BTC/USDT:USDT")

    ticker = await service.get_ticker()

    assert calls == [{"instId": "BTC-USDT-SWAP"}]
    assert ticker["last"] == 108000.5
    assert ticker["high"] == 109000.0
    assert ticker["low"] == 106000.0
    assert ticker["baseVolume"] == 12345.6
    assert ticker["percentage"] == pytest.approx(0.9350467289719626)


@pytest.mark.asyncio
async def test_get_ticker_falls_back_to_ccxt_when_raw_endpoint_is_unavailable() -> None:
    _install_fake_ccxt()
    from alpha_trading_bot.exchange.market_data import MarketDataService

    calls = []

    class _Exchange:
        def fetch_ticker(self, symbol: str):
            calls.append(symbol)
            return {"last": 108000.5, "high": 109000.0, "low": 106000.0}

    service = MarketDataService(_Exchange(), "BTC/USDT:USDT")

    ticker = await service.get_ticker()

    assert calls == ["BTC/USDT:USDT"]
    assert ticker["last"] == 108000.5


@pytest.mark.asyncio
async def test_get_ohlcv_uses_okx_raw_endpoint_without_loading_markets() -> None:
    _install_fake_ccxt()
    from alpha_trading_bot.exchange.market_data import MarketDataService

    calls = []

    class _Exchange:
        def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int):
            raise AssertionError("ccxt fetch_ohlcv should not be called")

        def public_get_market_candles(self, params):
            calls.append(params)
            return {
                "code": "0",
                "data": [
                    [
                        "1718064000000",
                        "107000.0",
                        "108500.0",
                        "106800.0",
                        "108000.5",
                        "123.45",
                    ]
                ],
            }

    service = MarketDataService(_Exchange(), "BTC/USDT:USDT")

    ohlcv = await service.get_ohlcv(timeframe="1h", limit=1)

    assert calls == [{"instId": "BTC-USDT-SWAP", "bar": "1H", "limit": "1"}]
    assert ohlcv == [[1718064000000, 107000.0, 108500.0, 106800.0, 108000.5, 123.45]]


@pytest.mark.asyncio
async def test_get_ohlcv_falls_back_to_ccxt_when_raw_endpoint_is_unavailable() -> None:
    _install_fake_ccxt()
    from alpha_trading_bot.exchange.market_data import MarketDataService

    calls = []

    class _Exchange:
        def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int):
            calls.append((symbol, timeframe, limit))
            return [[1718064000000, 107000.0, 108500.0, 106800.0, 108000.5, 123.45]]

    service = MarketDataService(_Exchange(), "BTC/USDT:USDT")

    ohlcv = await service.get_ohlcv(timeframe="1h", limit=1)

    assert calls == [("BTC/USDT:USDT", "1h", 1)]
    assert ohlcv == [[1718064000000, 107000.0, 108500.0, 106800.0, 108000.5, 123.45]]
