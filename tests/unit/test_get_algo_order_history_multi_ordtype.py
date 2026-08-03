"""get_algo_order_history 多 ordType 合并与容错回归测试。"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_client() -> Any:
    from alpha_trading_bot.exchange.client import ExchangeClient

    client = ExchangeClient.__new__(ExchangeClient)
    client.exchange = MagicMock()
    client.symbol = "BTC/USDT:USDT"
    return client


def _patch_raw_executor(client: Any, side_effects: Any) -> None:
    executor = MagicMock()
    executor.call = AsyncMock(side_effect=side_effects)
    client._raw_executor = executor
    client._get_raw_executor = lambda: executor


@pytest.mark.asyncio
async def test_default_ord_types_is_conditional_only(monkeypatch: Any) -> None:
    """未传 ord_types 时缺省仅 conditional（向后兼容）。"""
    from alpha_trading_bot.exchange import client as client_mod

    monkeypatch.setattr(
        client_mod,
        "get_callable",
        lambda *a, **kw: lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        client_mod, "okx_inst_id_from_symbol", lambda s: "BTC-USDT-SWAP"
    )
    monkeypatch.setattr(
        client_mod, "parse_okx_algo_orders", lambda response, symbol: []
    )

    inst = _make_client()
    captured_params = []

    executor = MagicMock()

    async def _call(*args: Any, **kwargs: Any) -> list:
        captured_params.append(args[2] if len(args) > 2 else kwargs.get("params"))
        return []

    executor.call = AsyncMock(side_effect=_call)
    inst._get_raw_executor = lambda: executor

    out = await inst.get_algo_order_history("BTC/USDT:USDT", algo_id="sl-1")
    assert out == []
    assert len(captured_params) == 1
    assert captured_params[0]["ordType"] == "conditional"


@pytest.mark.asyncio
async def test_multi_ord_types_merged_and_deduped(monkeypatch: Any) -> None:
    """多 ordType 结果合并且按 id 去重。"""
    from alpha_trading_bot.exchange import client as client_mod

    monkeypatch.setattr(
        client_mod,
        "get_callable",
        lambda *a, **kw: lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        client_mod, "okx_inst_id_from_symbol", lambda s: "BTC-USDT-SWAP"
    )
    monkeypatch.setattr(
        client_mod, "parse_okx_algo_orders", lambda response, symbol: []
    )

    inst = _make_client()

    seen = []
    executor = MagicMock()

    async def _call(*args: Any, **kwargs: Any) -> list:
        params = args[2]
        seen.append(params["ordType"])
        if params["ordType"] == "conditional":
            return [{"id": "A"}, {"id": "B"}]
        if params["ordType"] == "trigger":
            return [{"id": "B"}, {"id": "C"}]
        if params["ordType"] == "move_order_stop":
            return [{"id": "D"}]
        return []

    executor.call = AsyncMock(side_effect=_call)
    inst._get_raw_executor = lambda: executor

    out = await inst.get_algo_order_history(
        "BTC/USDT:USDT", ord_types=["conditional", "trigger", "move_order_stop"]
    )
    ids = [o["id"] for o in out]
    assert ids == ["A", "B", "C", "D"]
    assert seen == ["conditional", "trigger", "move_order_stop"]


@pytest.mark.asyncio
async def test_one_ord_type_failure_does_not_block_others(monkeypatch: Any) -> None:
    """某一类查询失败，其它类仍能返回并合并。"""
    from alpha_trading_bot.exchange import client as client_mod

    monkeypatch.setattr(
        client_mod,
        "get_callable",
        lambda *a, **kw: lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        client_mod, "okx_inst_id_from_symbol", lambda s: "BTC-USDT-SWAP"
    )
    monkeypatch.setattr(
        client_mod, "parse_okx_algo_orders", lambda response, symbol: []
    )

    inst = _make_client()
    executor = MagicMock()

    async def _call(*args: Any, **kwargs: Any) -> list:
        params = args[2]
        if params["ordType"] == "trigger":
            raise RuntimeError("boom")
        return [{"id": params["ordType"] + "-x"}]

    executor.call = AsyncMock(side_effect=_call)
    inst._get_raw_executor = lambda: executor

    out = await inst.get_algo_order_history(
        "BTC/USDT:USDT", ord_types=["conditional", "trigger", "move_order_stop"]
    )
    ids = [o["id"] for o in out]
    assert "conditional-x" in ids
    assert "move_order_stop-x" in ids
    assert "trigger-x" not in ids


@pytest.mark.asyncio
async def test_all_ord_types_failure_returns_empty_list(monkeypatch: Any) -> None:
    """全部失败时返回空列表（向后兼容原有"返回 []"语义）。"""
    from alpha_trading_bot.exchange import client as client_mod

    monkeypatch.setattr(
        client_mod,
        "get_callable",
        lambda *a, **kw: lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        client_mod, "okx_inst_id_from_symbol", lambda s: "BTC-USDT-SWAP"
    )
    monkeypatch.setattr(
        client_mod, "parse_okx_algo_orders", lambda response, symbol: []
    )

    inst = _make_client()
    executor = MagicMock()
    executor.call = AsyncMock(side_effect=RuntimeError("down"))
    inst._get_raw_executor = lambda: executor

    out = await inst.get_algo_order_history(
        "BTC/USDT:USDT", ord_types=["conditional", "trigger"]
    )
    assert out == []
