"""合约张数换算测试（Task 1）：market_data 语义 + client 单位转换。

背景：`MarketDataService.calculate_max_contracts` 返回的量纲是 BTC 数量
（余额×usage×leverage÷价格），但被 ExchangeClient 直接当 OKX 张数
（1 张 = ctVal 0.01 BTC）使用。本测试钉死：

- market_data 返回最大可交易 BTC 数量（非张数），且不再拒绝 <0.01 的小值；
- client 负责 ÷ctVal 换算为张数并向下截断到最小张数；
- 规格不可用时保守回退旧公式值（BTC 数量）。
"""

import logging
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from alpha_trading_bot.exchange.client import ExchangeClient
from alpha_trading_bot.exchange.market_data import MarketDataService
from alpha_trading_bot.exchange.models.instruments import InstrumentSpec

PRICE = 85100.0
LEVERAGE = 10
USAGE = 0.30


def _btc_swap_spec() -> InstrumentSpec:
    """真实 BTC-USDT-SWAP 合约规格（不用 mock 数学）。"""
    return InstrumentSpec(
        inst_id="BTC-USDT-SWAP",
        inst_type="SWAP",
        settle_currency="USDT",
        contract_value=Decimal("0.01"),
        contract_multiplier=Decimal("1"),
        contract_value_currency="BTC",
        minimum_size=Decimal("0.01"),
        lot_size=Decimal("0.01"),
        tick_size=Decimal("0.1"),
    )


def _make_client(spec=None) -> ExchangeClient:
    client = ExchangeClient(symbol="BTC/USDT:USDT", test_mode=True)
    client._instrument_spec = spec
    client._market_data_service = MarketDataService(
        exchange=None, symbol="BTC/USDT:USDT"
    )
    return client


@pytest.mark.asyncio
async def test_market_data_returns_btc_amount_not_contracts() -> None:
    """market_data 返回 BTC 数量（非张数），且不再错误拒绝 <0.01 的小值。"""
    service = MarketDataService(exchange=None, symbol="BTC/USDT:USDT")

    btc_amount = await service.calculate_max_contracts(
        PRICE, LEVERAGE, AsyncMock(return_value=7.295)
    )

    # $7.295×0.30×10÷85100 ≈ 0.000257 BTC（旧代码会四舍五入成 0.0003 并
    # 因 <0.01 直接返回 0.0 —— 两者都是 bug）
    expected_btc = (7.295 * USAGE * LEVERAGE) / PRICE
    assert btc_amount == pytest.approx(expected_btc)
    assert btc_amount > 0


@pytest.mark.asyncio
async def test_small_balance_converts_to_two_contracts(monkeypatch, caplog) -> None:
    """$7.295@85100 → 0.0257 张 → 截断 0.02 张（完整链路）。"""
    client = _make_client(_btc_swap_spec())
    monkeypatch.setattr(client, "get_balance", AsyncMock(return_value=7.295))

    with caplog.at_level(logging.INFO):
        contracts = await client.calculate_max_contracts(PRICE, LEVERAGE)

    assert contracts == pytest.approx(0.02)
    # 0.02 张 × 0.01 BTC × 85100 = $17.02 真实名义
    assert "17.02" in caplog.text


@pytest.mark.asyncio
async def test_below_minimum_contracts_returns_zero(monkeypatch, caplog) -> None:
    """更小余额 → 0.009 张 → 低于 minSz 0.01 → 0.0 + WARNING。"""
    client = _make_client(_btc_swap_spec())
    # balance = 0.00009 BTC × 85100 ÷ 3 = 2.553 → 0.009 张
    monkeypatch.setattr(client, "get_balance", AsyncMock(return_value=2.553))

    with caplog.at_level(logging.WARNING):
        contracts = await client.calculate_max_contracts(PRICE, LEVERAGE)

    assert contracts == 0.0
    assert "无法交易" in caplog.text


@pytest.mark.asyncio
async def test_large_balance_restores_intended_position(monkeypatch, caplog) -> None:
    """$1000 → 3.52 张，名义 ≈$2996（30%×10x 设计意图恢复）。"""
    client = _make_client(_btc_swap_spec())
    monkeypatch.setattr(client, "get_balance", AsyncMock(return_value=1000.0))

    with caplog.at_level(logging.INFO):
        contracts = await client.calculate_max_contracts(PRICE, LEVERAGE)

    assert contracts == pytest.approx(3.52)
    # 3.52 张 × 0.01 BTC × 85100 = $2995.52 真实名义
    assert "2995.52" in caplog.text


@pytest.mark.asyncio
async def test_spec_unavailable_falls_back_to_btc_amount(caplog) -> None:
    """规格不可用（RuntimeError）→ 返回旧公式值 + WARNING（保守）。"""
    client = ExchangeClient(symbol="BTC/USDT:USDT", test_mode=True)
    client._instrument_spec = None
    service = AsyncMock()
    old_value = 0.000257168
    service.calculate_max_contracts = AsyncMock(return_value=old_value)
    client._market_data_service = service

    with caplog.at_level(logging.WARNING):
        result = await client.calculate_max_contracts(PRICE, LEVERAGE)

    # 回退值逐字节一致：直接返回 service 算出的 BTC 数量，不做张数换算
    assert result == old_value
    assert "回退旧仓位公式" in caplog.text
