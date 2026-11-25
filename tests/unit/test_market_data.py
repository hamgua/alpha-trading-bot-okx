# -*- coding: utf-8 -*-
"""market_data 1h 高低点暴露测试 (Task 2)。

趋势跟踪通道 24h 摆动止损需要 1h 高低点序列 (high_history/low_history),
口径与 price_history 对齐 (1h, oldest-first, 同长度)。
"""

import sys
import types

import pytest


def _install_fake_ccxt() -> None:
    fake_ccxt = types.ModuleType("ccxt")
    fake_ccxt.okx = object
    sys.modules.setdefault("ccxt", fake_ccxt)


def _mk_ohlcv(n: int = 100, base: float = 60000.0):
    """n 根 1h OHLCV (ts 递增, OKX 原始格式)。"""
    out = []
    ts0 = 1765000000000
    for i in range(n):
        o = base + i * 10.0
        c = o + 5.0
        out.append(
            [
                str(ts0 + i * 3600000),
                str(o),
                str(o + 20.0),
                str(o - 15.0),
                str(c),
                "100",
            ]
        )
    return out


@pytest.mark.asyncio
async def test_market_data_includes_1h_high_low_history() -> None:
    _install_fake_ccxt()
    from alpha_trading_bot.exchange.market_data import MarketDataService

    ohlcv_1h = _mk_ohlcv(100)
    ohlcv_15m = _mk_ohlcv(96)

    class _Exchange:
        def public_get_market_ticker(self, params):
            return {
                "code": "0",
                "data": [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "last": "60995.0",
                        "high24h": "61000.0",
                        "low24h": "59000.0",
                        "open24h": "60000.0",
                        "volCcy24h": "100.0",
                    }
                ],
            }

        def public_get_market_candles(self, params):
            # get_market_data 先拉 1h (limit=100), 15m 摘要拉 limit=96
            if params.get("bar") == "1H":
                return {"code": "0", "data": ohlcv_1h}
            return {"code": "0", "data": ohlcv_15m}

    service = MarketDataService(_Exchange(), "BTC/USDT:USDT")
    md = await service.get_market_data()

    assert len(md["high_history"]) == len(md["price_history"])
    assert len(md["low_history"]) == len(md["price_history"])
    assert len(md["high_history"]) == 100
    # 与 OHLCV 逐根对齐 (oldest-first)
    assert md["high_history"][0] == pytest.approx(float(ohlcv_1h[0][2]))
    assert md["low_history"][-1] == pytest.approx(float(ohlcv_1h[-1][3]))
    assert md["price_history"][-1] == pytest.approx(float(ohlcv_1h[-1][4]))


@pytest.mark.asyncio
async def test_market_data_graceful_on_ohlcv_failure() -> None:
    _install_fake_ccxt()
    from alpha_trading_bot.exchange.market_data import MarketDataService

    class _Exchange:
        def public_get_market_ticker(self, params):
            return {
                "code": "0",
                "data": [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "last": "60000.0",
                        "high24h": "61000.0",
                        "low24h": "59000.0",
                        "open24h": "60500.0",
                        "volCcy24h": "100.0",
                    }
                ],
            }

        # 无 public_get_market_candles -> get_ohlcv 返回 [] (容错路径)

    service = MarketDataService(_Exchange(), "BTC/USDT:USDT")
    md = await service.get_market_data()

    assert md["high_history"] == []
    assert md["low_history"] == []
    # 价格仍来自 ticker, 主流程不受影响
    assert md["price"] == 60000.0
