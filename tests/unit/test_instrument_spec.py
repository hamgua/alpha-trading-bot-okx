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
