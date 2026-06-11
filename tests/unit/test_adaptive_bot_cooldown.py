"""AdaptiveTradingBot direction cooldown quality gates."""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from alpha_trading_bot.config.models import Config, ExchangeConfig, TradingConfig
from alpha_trading_bot.core.adaptive_bot import AdaptiveTradingBot


def _make_bot() -> AdaptiveTradingBot:
    config = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(test_mode=True),
    )
    return AdaptiveTradingBot(config)


def test_profitable_high_quality_reentry_uses_short_cooldown() -> None:
    """盈利平仓后，高质量同向机会使用短冷却。"""
    bot = _make_bot()
    bot._last_close_was_profitable = True

    final_signal = {"action": "open", "confidence": 0.72}
    market_data = {
        "risk_reward_ratio": 2.4,
        "is_high_risk": False,
    }

    assert bot._get_direction_cooldown_seconds(final_signal, market_data, "long") == 300


def test_loss_reentry_keeps_full_cooldown() -> None:
    """亏损平仓后，同向机会仍保持完整冷却。"""
    bot = _make_bot()
    bot._last_close_was_profitable = False

    final_signal = {"action": "open", "confidence": 0.80}
    market_data = {
        "risk_reward_ratio": 3.0,
        "is_high_risk": False,
    }

    assert (
        bot._get_direction_cooldown_seconds(final_signal, market_data, "long") == 1800
    )


def test_high_risk_long_reentry_keeps_full_cooldown() -> None:
    """BTC高位风险下，多头再入场不缩短冷却。"""
    bot = _make_bot()
    bot._last_close_was_profitable = True

    final_signal = {"action": "open", "confidence": 0.80}
    market_data = {
        "risk_reward_ratio": 3.0,
        "is_high_risk": True,
    }

    assert (
        bot._get_direction_cooldown_seconds(final_signal, market_data, "long") == 1800
    )


def test_records_position_close_audit_context() -> None:
    """开仓/轮询持仓时记录平仓审计所需上下文。"""
    bot = _make_bot()

    bot._remember_position_close_audit_context(
        side="long",
        entry_price=108250.0,
        amount=0.01,
        unrealized_pnl=-0.05,
        stop_order_id="algo-stop-1",
        stop_price=107680.0,
    )

    assert bot._last_position_side == "long"
    assert bot._last_position_entry_price == 108250.0
    assert bot._last_position_amount == 0.01
    assert bot._last_position_unrealized_pnl == -0.05
    assert bot._last_stop_order_id == "algo-stop-1"
    assert bot._last_stop_price == 107680.0


@pytest.mark.asyncio
async def test_records_profitable_close_when_position_disappears() -> None:
    """持仓消失时记录上一笔是否盈利，用于再入场冷却。"""
    bot = _make_bot()
    bot._last_position_side = "long"
    bot._last_position_unrealized_pnl = 0.05

    await bot._record_position_disappeared()

    assert bot._last_closed_side == "long"
    assert bot._last_close_was_profitable is True
    assert bot._last_position_side == ""


@pytest.mark.asyncio
async def test_logs_stop_loss_close_when_position_disappears(caplog) -> None:
    """持仓消失时查询算法单历史并记录止损触发平仓事件。"""
    bot = _make_bot()
    bot._exchange = MagicMock()
    bot._exchange.symbol = "BTC/USDT:USDT"
    bot._exchange.get_algo_order_history = AsyncMock(
        return_value=[
            {
                "id": "algo-stop-1",
                "status": "closed",
                "info": {
                    "algoId": "algo-stop-1",
                    "state": "effective",
                    "side": "sell",
                    "sz": "0.01",
                    "slTriggerPx": "107680",
                    "actualPx": "107675.2",
                    "triggerTime": "1781179923000",
                },
            }
        ]
    )
    bot._last_position_side = "long"
    bot._last_position_entry_price = 108250.0
    bot._last_position_amount = 0.01
    bot._last_position_unrealized_pnl = -0.05
    bot._last_stop_order_id = "algo-stop-1"
    bot._last_stop_price = 107680.0

    with caplog.at_level(logging.INFO):
        await bot._record_position_disappeared()

    bot._exchange.get_algo_order_history.assert_awaited_once_with(
        "BTC/USDT:USDT", algo_id="algo-stop-1", limit=20
    )
    assert "[平仓确认] 止损单触发平仓" in caplog.text
    assert "algo-stop-1" in caplog.text
    assert "exit=107675.2" in caplog.text
    assert "pnl=-0.53%" in caplog.text


@pytest.mark.asyncio
async def test_logs_inferred_close_when_algo_history_missing(caplog) -> None:
    """算法单历史暂未返回时也要留下平仓推断日志。"""
    bot = _make_bot()
    bot._exchange = MagicMock()
    bot._exchange.symbol = "BTC/USDT:USDT"
    bot._exchange.get_algo_order_history = AsyncMock(return_value=[])
    bot._last_position_side = "short"
    bot._last_position_entry_price = 108250.0
    bot._last_position_amount = 0.01
    bot._last_position_unrealized_pnl = 0.02
    bot._last_stop_order_id = "algo-stop-2"
    bot._last_stop_price = 108800.0

    with caplog.at_level(logging.INFO):
        await bot._record_position_disappeared()

    assert "[平仓推断] 持仓消失" in caplog.text
    assert "algo-stop-2" in caplog.text
    assert "reason=algo_history_not_found" in caplog.text
