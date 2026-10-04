"""开仓单笔风险反查测试（P1：止损触发预期亏损 ≤ 账户 10%）"""

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


def _make_bot(tmp_path: Path) -> TradingBot:
    config = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(test_mode=True),
        stop_loss=StopLossConfig(),
    )
    bot = TradingBot(config)
    bot._exchange = MagicMock()
    return bot


@pytest.mark.asyncio
async def test_normal_path_unchanged(tmp_path) -> None:
    """默认止损 0.05% 下反查几乎不触发（护栏语义，正常路径零行为变化）。"""
    bot = _make_bot(tmp_path)
    bot._exchange.get_balance = AsyncMock(return_value=1000.0)
    # 0.03 张 × 84000 × 0.0005 = 1.26 USDT << 1000 × 10%
    assert await bot._apply_risk_backcheck(84000.0, 0.03) == 0.03


@pytest.mark.asyncio
async def test_shrinks_on_wide_stop(tmp_path) -> None:
    """宽止损（未来 ATR 化后可能出现）时按比例缩仓到风险上限。"""
    bot = _make_bot(tmp_path)
    bot.config.stop_loss.stop_loss_percent = 0.05  # 5% 宽止损
    bot._exchange.get_balance = AsyncMock(return_value=1000.0)
    # 0.03×84000×0.05 = 126 > 100 → 缩至 100/(84000×0.05) = 0.0238
    amt = await bot._apply_risk_backcheck(84000.0, 0.03)
    assert amt == pytest.approx(0.0238, abs=1e-4)


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
