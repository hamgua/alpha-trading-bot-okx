import pytest

from alpha_trading_bot.exchange.instrument_service import InstrumentService


def _instrument_metadata(inst_id: str = "BTC-USDT-SWAP"):
    return {
        "instId": inst_id,
        "instType": "SWAP",
        "settleCcy": "USDT",
        "ctVal": "0.01",
        "ctMult": "1",
        "ctValCcy": "BTC",
        "minSz": "0.01",
        "lotSz": "0.01",
        "tickSz": "0.1",
    }


@pytest.mark.asyncio
async def test_instrument_service_uses_okx_public_endpoint():
    calls = []

    class Exchange:
        def public_get_public_instruments(self, params):
            calls.append(params)
            return {"code": "0", "data": [_instrument_metadata()]}

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


@pytest.mark.asyncio
async def test_instrument_service_rejects_metadata_for_a_different_instrument():
    class Exchange:
        def public_get_public_instruments(self, params):
            return {"code": "0", "data": [_instrument_metadata("ETH-USDT-SWAP")]}

    with pytest.raises(RuntimeError, match="instrument metadata instId mismatch"):
        await InstrumentService(Exchange(), "BTC/USDT:USDT").load()
