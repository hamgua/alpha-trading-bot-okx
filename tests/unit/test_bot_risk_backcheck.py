"""开仓单笔风险反查测试（P1：止损触发预期亏损 ≤ 账户 10%）"""

import logging
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from alpha_trading_bot.config.models import (
    Config,
    ExchangeConfig,
    StopLossConfig,
    TradingConfig,
)
from alpha_trading_bot.core.bot import TradingBot
from alpha_trading_bot.exchange.models.instruments import InstrumentSpec

# 真实 OKX BTC-USDT-SWAP 规格：1 张 = 0.01 BTC，lotSz/minSz = 0.01 张
BTC_SPEC = InstrumentSpec(
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


def _spec_exchange(balance: float) -> MagicMock:
    """构造 _exchange mock：名义/截断走真实 InstrumentSpec 语义（不 mock 数学）。"""
    exchange = MagicMock()
    exchange.get_balance = AsyncMock(return_value=balance)
    exchange.calculate_notional_usdt = MagicMock(
        side_effect=lambda amount, price: BTC_SPEC.notional_usdt(amount, price)
    )
    exchange.normalize_order_size = MagicMock(
        side_effect=lambda amount: BTC_SPEC.normalize_size(amount)
    )
    return exchange


def _make_bot(tmp_path: Path) -> TradingBot:
    config = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(test_mode=True),
        stop_loss=StopLossConfig(),
    )
    bot = TradingBot(config)
    bot._exchange = _spec_exchange(1000.0)
    return bot


@pytest.mark.asyncio
async def test_normal_path_unchanged(tmp_path) -> None:
    """默认止损 0.05% 下反查几乎不触发（护栏语义，正常路径零行为变化）。"""
    bot = _make_bot(tmp_path)
    bot._exchange.get_balance = AsyncMock(return_value=1000.0)
    # 真实名义 = 0.03×0.01×84000 = 25.2 USDT → 预期亏损 25.2×0.0005 = 0.0126 << 100
    assert await bot._apply_risk_backcheck(84000.0, 0.03) == 0.03


@pytest.mark.asyncio
async def test_shrinks_on_wide_stop(tmp_path) -> None:
    """宽止损（未来 ATR 化后可能出现）时按真实名义缩仓到风险上限。

    $100 / 0.10 张 / d=0.5 / price=85100：名义 = 0.10×0.01×85100 = $85.1，
    预期亏损 = 85.1×0.5 = $42.55 > $10 → shrunk = 10/(851×0.5) = 0.0235 张。
    """
    bot = _make_bot(tmp_path)
    bot.config.stop_loss.stop_loss_percent = 0.5  # 50% 宽止损
    bot._exchange.get_balance = AsyncMock(return_value=100.0)
    amt = await bot._apply_risk_backcheck(85100.0, 0.10)
    assert amt == pytest.approx(0.0235, abs=1e-4)


@pytest.mark.asyncio
async def test_invalid_balance_skips_backcheck(tmp_path) -> None:
    """余额获取失败（0.0）→ 跳过反查，保持原仓位（与总闸"跳过"语义一致）。"""
    bot = _make_bot(tmp_path)
    bot._exchange.get_balance = AsyncMock(return_value=0.0)
    assert await bot._apply_risk_backcheck(84000.0, 0.03) == 0.03


@pytest.mark.asyncio
async def test_balance_fetch_error_skips_backcheck(tmp_path) -> None:
    bot = _make_bot(tmp_path)
    bot._exchange.get_balance = AsyncMock(side_effect=RuntimeError("down"))
    assert await bot._apply_risk_backcheck(84000.0, 0.03) == 0.03


def _make_live_bot(tmp_path: Path, exchange: MagicMock = None) -> TradingBot:
    config = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(
            test_mode=False,
            real_trading_confirmed=True,
            runtime_environment="prod",
            decision_journal_enabled=False,
        ),
        stop_loss=StopLossConfig(stop_loss_percent=0.5),
    )
    bot = TradingBot(config)
    bot._exchange = exchange if exchange is not None else MagicMock()
    return bot


@pytest.mark.asyncio
async def test_open_position_aborts_below_min_contracts(tmp_path, caplog) -> None:
    """张数截断后低于最小张数（ValueError）→ 取消开仓：不下单 + WARNING + 不抛异常。"""
    bot = _make_live_bot(tmp_path, _spec_exchange(100.0))
    bot._exchange.calculate_max_contracts = AsyncMock(return_value=0.009)
    bot._exchange.create_order = AsyncMock(return_value="order-1")

    with caplog.at_level(logging.WARNING):
        await bot._open_position(84000.0)

    bot._exchange.create_order.assert_not_awaited()
    assert "张数截断后低于最小张数" in caplog.text


@pytest.mark.asyncio
async def test_open_position_truncates_to_lot_size(tmp_path) -> None:
    """0.0257 张 → ROUND_FLOOR 截断 0.02 张，create_order 收到截断后张数。"""
    bot = _make_live_bot(tmp_path, _spec_exchange(1000.0))
    bot._exchange.calculate_max_contracts = AsyncMock(return_value=0.0257)
    bot._exchange.create_order = AsyncMock(return_value="order-1")
    bot._exchange.create_stop_loss = AsyncMock(return_value="stop-1")

    await bot._open_position(85100.0)

    bot._exchange.create_order.assert_awaited_once()
    assert bot._exchange.create_order.call_args.kwargs["amount"] == 0.02


@pytest.mark.asyncio
async def test_open_position_spec_unavailable_keeps_legacy_flow(
    tmp_path, caplog
) -> None:
    """截断规格不可用（RuntimeError）→ 跳过截断保持修正前流程（回退不改行为）。

    amount=0.0257 ≥ 0.01 → 继续 create_order（原值，不放大仓位）+ WARNING。
    """
    bot = _make_live_bot(tmp_path, _spec_exchange(1000.0))
    bot._exchange.calculate_max_contracts = AsyncMock(return_value=0.0257)
    bot._exchange.normalize_order_size = MagicMock(side_effect=RuntimeError("未初始化"))
    bot._exchange.create_order = AsyncMock(return_value="order-1")
    bot._exchange.create_stop_loss = AsyncMock(return_value="stop-1")

    with caplog.at_level(logging.WARNING):
        await bot._open_position(85100.0)

    bot._exchange.create_order.assert_awaited_once()
    assert bot._exchange.create_order.call_args.kwargs["amount"] == 0.0257
    assert "跳过张数截断" in caplog.text


@pytest.mark.asyncio
async def test_small_balance_passes_with_real_notional(tmp_path) -> None:
    """$7.295 / 0.02 张 / 5bp 止损：真实名义 $17.02 → 预期亏损 $0.00851 ≤ $0.7295。

    通过不缩仓。旧公式（张数当 BTC 数量）会算出 $0.851 > $0.7295 → 误缩到
    0.0017 张 → <0.01 放弃开仓；本测试钉死名义修正。
    """
    bot = _make_bot(tmp_path)
    bot._exchange.get_balance = AsyncMock(return_value=7.295)
    # 名义 = 0.02×0.01×85100 = 17.02；预期亏损 = 17.02×0.0005 = 0.00851
    # max_loss = 7.295×0.10 = 0.7295
    assert await bot._apply_risk_backcheck(85100.0, 0.02) == 0.02


@pytest.mark.asyncio
async def test_spec_unavailable_falls_back_conservative(tmp_path, caplog) -> None:
    """规格不可用（RuntimeError）→ 回退旧公式（张数当 BTC 数量，高估亏损=保守）。

    旧公式：0.03×84000×0.05 = 126 > 100 → 缩至 100/(84000×0.05) = 0.0238 + WARNING。
    """
    bot = _make_bot(tmp_path)
    bot.config.stop_loss.stop_loss_percent = 0.05  # 5% 宽止损
    bot._exchange.get_balance = AsyncMock(return_value=1000.0)
    bot._exchange.calculate_notional_usdt = MagicMock(
        side_effect=RuntimeError("未初始化")
    )

    with caplog.at_level(logging.WARNING):
        amt = await bot._apply_risk_backcheck(84000.0, 0.03)

    assert amt == pytest.approx(0.0238, abs=1e-4)
    assert "规格不可用" in caplog.text
