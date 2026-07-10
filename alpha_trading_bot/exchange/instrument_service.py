"""OKX 合约元数据加载服务。"""

import asyncio
from typing import Any, Optional

from alpha_trading_bot.exchange.models import InstrumentSpec
from alpha_trading_bot.exchange.okx_raw import (
    ensure_okx_success,
    get_callable,
    okx_inst_id_from_symbol,
)


class InstrumentService:
    """加载并缓存指定永续合约的 OKX 元数据。"""

    def __init__(self, exchange: Any, symbol: str) -> None:
        self.exchange = exchange
        self.symbol = symbol
        self._cached: Optional[InstrumentSpec] = None

    async def load(self) -> InstrumentSpec:
        """通过 OKX 原始公开接口加载合约规格。"""
        if self._cached is not None:
            return self._cached

        method = get_callable(
            self.exchange,
            "public_get_public_instruments",
            "publicGetPublicInstruments",
        )
        if method is None:
            raise RuntimeError("OKX instrument metadata endpoint is unavailable")

        inst_id = okx_inst_id_from_symbol(self.symbol)
        params = {"instType": "SWAP", "instId": inst_id}
        response = await asyncio.get_running_loop().run_in_executor(
            None, lambda: method(params)
        )
        if not isinstance(response, dict):
            raise RuntimeError("OKX instrument metadata response is malformed")
        ensure_okx_success(response, "instrument metadata")

        data = response.get("data")
        if not isinstance(data, list) or not data:
            raise RuntimeError("OKX instrument metadata is empty")

        raw = data[0]
        if not isinstance(raw, dict):
            raise RuntimeError("OKX instrument metadata is malformed")
        if raw.get("instId") != inst_id:
            raise RuntimeError(
                "OKX instrument metadata instId mismatch: "
                f"expected {inst_id}, got {raw.get('instId')}"
            )

        self._cached = InstrumentSpec.from_okx(raw)
        return self._cached
