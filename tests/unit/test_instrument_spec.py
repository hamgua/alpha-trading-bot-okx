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
    with pytest.raises(ValueError, match="unsupported instrument"):
        InstrumentSpec.from_okx(
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


def test_linear_swap_accepts_a_non_btc_base_currency():
    spec = InstrumentSpec.from_okx(
        {
            "instId": "ETH-USDT-SWAP",
            "instType": "SWAP",
            "settleCcy": "USDT",
            "ctVal": "0.1",
            "ctMult": "1",
            "ctValCcy": "ETH",
            "minSz": "0.1",
            "lotSz": "0.1",
            "tickSz": "0.01",
        }
    )

    assert spec.notional_usdt(amount=2.0, price=3000.0) == pytest.approx(600.0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("instId", "BTC-USD-SWAP"),
        ("instType", "FUTURES"),
        ("settleCcy", "BTC"),
        ("ctValCcy", "USD"),
        ("ctValCcy", "ETH"),
    ],
)
def test_unsupported_instrument_metadata_is_rejected(field, value):
    raw = {
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
    raw[field] = value

    with pytest.raises(ValueError, match="unsupported instrument"):
        InstrumentSpec.from_okx(raw)


@pytest.mark.parametrize("field", ["ctVal", "ctMult", "minSz", "lotSz", "tickSz"])
@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "0", "-1"])
def test_invalid_arithmetic_metadata_is_rejected(field, value):
    raw = {
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
    raw[field] = value

    with pytest.raises(ValueError, match="invalid instrument metadata"):
        InstrumentSpec.from_okx(raw)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_size_input_is_rejected(value):
    with pytest.raises(ValueError, match="finite"):
        _btc_swap().normalize_size(value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_price_input_is_rejected(value):
    with pytest.raises(ValueError, match="finite"):
        _btc_swap().normalize_price(value)


@pytest.mark.parametrize("amount", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_notional_amount_is_rejected(amount):
    with pytest.raises(ValueError, match="finite"):
        _btc_swap().notional_usdt(amount, 100000.0)


@pytest.mark.parametrize("price", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_notional_price_is_rejected(price):
    with pytest.raises(ValueError, match="finite"):
        _btc_swap().notional_usdt(1.0, price)
