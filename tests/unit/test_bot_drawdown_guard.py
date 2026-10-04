"""TradingBot × 回撤总闸集成测试（P1）"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from alpha_trading_bot.config.models import Config, ExchangeConfig, TradingConfig
from alpha_trading_bot.core.bot import TradingBot


def _make_bot(tmp_path: Path, balance: float = 1000.0) -> TradingBot:
    config = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(test_mode=True),
    )
    bot = TradingBot(config)
    bot._exchange = MagicMock()
    bot._exchange.get_balance = AsyncMock(return_value=balance)
    bot._exchange.create_order = AsyncMock(return_value="")
    bot._stop_loss_manager = None
    return bot


@pytest.mark.asyncio
async def test_buy_blocked_when_halted(tmp_path) -> None:
    bot = _make_bot(tmp_path)
    bot._drawdown_guard.check(1000.0)
    bot._drawdown_status = bot._drawdown_guard.check(700.0)  # trip
    result = await bot._execute_signal("BUY", 84000.0, has_position=False)
    assert result.action == "blocked_drawdown"
    bot._exchange.create_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_buy_allowed_when_not_halted(tmp_path) -> None:
    bot = _make_bot(tmp_path)
    bot._drawdown_guard.check(1000.0)
    bot._drawdown_status = bot._drawdown_guard.check(990.0)
    # 让开仓流程在 create_order 处止步（返回空 order_id → 正常中止）
    bot._open_position = AsyncMock()  # type: ignore[assignment]
    result = await bot._execute_signal("BUY", 84000.0, has_position=False)
    assert result.action == "open_long"
    bot._open_position.assert_awaited_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_close_and_stop_update_allowed_when_halted(tmp_path) -> None:
    # 总闸只拦新开仓：平仓/止损更新不受影响
    bot = _make_bot(tmp_path)
    bot._drawdown_guard.check(1000.0)
    bot._drawdown_status = bot._drawdown_guard.check(700.0)
    bot._close_position = AsyncMock()  # type: ignore[assignment]
    r1 = await bot._execute_signal("SELL", 84000.0, has_position=True)
    assert r1.action == "close"
    r2 = await bot._execute_signal("HOLD", 84000.0, has_position=True)
    assert r2.action == "update_stop"


@pytest.mark.asyncio
async def test_cycle_survives_balance_fetch_error(tmp_path) -> None:
    # Review Focus #1: get_balance 抛异常 → 跳过本轮总闸检查，周期继续
    bot = _make_bot(tmp_path)
    bot._exchange.get_balance = AsyncMock(side_effect=RuntimeError("api down"))
    bot._drawdown_guard.check(1000.0)  # 正常状态
    await bot._check_drawdown()
    assert bot._drawdown_status is None or not bot._drawdown_status.halted


@pytest.mark.asyncio
async def test_test_mode_fixed_balance_never_halts(tmp_path) -> None:
    # Review Focus #5: TEST_MODE 固定模拟余额 → 高水位不动，永不触发
    bot = _make_bot(tmp_path, balance=100.0)
    for _ in range(5):
        await bot._check_drawdown()
    assert not bot._drawdown_status.halted  # type: ignore[union-attr]
