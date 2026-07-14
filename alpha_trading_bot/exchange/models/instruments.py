import math
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

    def __post_init__(self) -> None:
        parts = self.inst_id.split("-")
        if (
            len(parts) != 3
            or not parts[0]
            or parts[1] != "USDT"
            or parts[2] != "SWAP"
            or self.inst_type != "SWAP"
            or self.settle_currency != "USDT"
        ):
            raise ValueError("unsupported instrument metadata")
        if self.contract_value_currency not in (self.base_currency, "USDT"):
            raise ValueError("unsupported instrument metadata")
        for value in (
            self.contract_value,
            self.contract_multiplier,
            self.minimum_size,
            self.lot_size,
            self.tick_size,
        ):
            if not value.is_finite() or value <= 0:
                raise ValueError("invalid instrument metadata")

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
        if not value.is_finite():
            raise ValueError("amount must be finite")
        lots = (value / self.lot_size).to_integral_value(rounding=ROUND_FLOOR)
        normalized = lots * self.lot_size
        if normalized < self.minimum_size:
            raise ValueError("normalized size is below minimum")
        return _finite_float(normalized, "normalized size")

    def normalize_price(self, price: float, rounding: str = "down") -> float:
        value = _decimal(price)
        if not value.is_finite():
            raise ValueError("price must be finite")
        mode = ROUND_CEILING if rounding == "up" else ROUND_FLOOR
        ticks = (value / self.tick_size).to_integral_value(rounding=mode)
        return _finite_float(ticks * self.tick_size, "normalized price")

    def notional_usdt(self, amount: float, price: float) -> float:
        if self.inst_type != "SWAP" or self.settle_currency != "USDT":
            raise ValueError("unsupported instrument for USDT notional")
        contracts = _decimal(amount)
        quote = _decimal(price)
        if not contracts.is_finite() or not quote.is_finite():
            raise ValueError("notional inputs must be finite")
        multiplier = self.contract_value * self.contract_multiplier
        if self.contract_value_currency == self.base_currency:
            return _finite_float(contracts * multiplier * quote, "USDT notional")
        if self.contract_value_currency == "USDT":
            return _finite_float(contracts * multiplier, "USDT notional")
        raise ValueError("unsupported instrument contract value currency")


def _finite_float(value: Decimal, label: str) -> float:
    if not value.is_finite():
        raise ValueError(f"{label} must be finite")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result
