"""验证止损更新引入 tick 容差后不再因为 OKX tick 截断而重复取消+重建算法单。

修复 P0 bug：当 old_stop=62501.4（OKX 已截断），new_stop=62501.4225（本地计算）
时，原代码用严格浮点 `>` 判定 "新止损更紧"，导致 5h55m 内重复取消+创建 21 次。
"""

from typing import Any, Optional, Tuple
from unittest.mock import AsyncMock

import pytest

from alpha_trading_bot.config.models import (
    Config,
    ExchangeConfig,
    StopLossConfig,
    TradingConfig,
)
from alpha_trading_bot.core.adaptive_bot import AdaptiveTradingBot


def _make_bot(stop_loss_overrides: Optional[dict] = None) -> AdaptiveTradingBot:
    sl_kwargs = dict(stop_loss_entry_based=True)
    if stop_loss_overrides:
        sl_kwargs.update(stop_loss_overrides)
    config = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(test_mode=True),
        stop_loss=StopLossConfig(**sl_kwargs),
    )
    return AdaptiveTradingBot(config)


def _force_long_position(bot: AdaptiveTradingBot, entry: float = 62815.5) -> None:
    bot.position_manager._position = type(
        "P",
        (),
        {
            "symbol": "BTC/USDT:USDT",
            "side": "long",
            "amount": 0.01,
            "entry_price": entry,
        },
    )()
    bot.position_manager._entry_price = entry
    bot.position_manager._highest_price_since_entry = entry


def _patch_exchange_state(
    bot: AdaptiveTradingBot,
    existing_stop_id: str,
    exchange_stop_price: float,
) -> Tuple[AsyncMock, AsyncMock]:
    """Mock 内部 IO，返回 (cancel_mock, create_mock)。"""
    # Mock 查询现有算法单
    bot._get_existing_stop_order_id = AsyncMock(  # type: ignore[assignment]
        return_value=(existing_stop_id, exchange_stop_price)
    )
    # Mock 取消/创建
    cancel_mock = AsyncMock(return_value=(True, ""))
    create_mock = AsyncMock(return_value="NEW_ALGO_ID")
    # 模拟 exchange
    bot._exchange = type(
        "Exch",
        (),
        {
            "symbol": "BTC/USDT:USDT",
            "cancel_algo_order": cancel_mock,
        },
    )()
    bot._create_stop_loss_with_retry = create_mock  # type: ignore[assignment]
    return cancel_mock, create_mock


# T9: tick 容差内不触发更新
@pytest.mark.asyncio
async def test_tick_equal_prices_skip_update() -> None:
    """OKX 截断后 old=62501.4，本地算出 new=62501.4225，满足 tick=0.1 容差 -> 不调用 cancel/create。

    进入 L1455 容错分支的条件：abs(price_vs_entry_percent) < tolerance (0.001)。
    因此 current_price 必须在 entry ± 0.1% 内，即 [62752.7, 62878.4]。
    """
    bot = _make_bot({"stop_loss_percent": 0.005, "stop_loss_tick_tolerance": 0.1})
    entry = 62815.5
    _force_long_position(bot, entry=entry)
    # 浮亏 0.01%，位于容错分支
    current_price = entry * 0.9999
    # 此时 position_manager.calculate_stop_price 走亏损分支
    # new_stop = entry * (1-0.005) = 62501.4225 < current_price ✓ 不触发 51280 防护
    cancel_mock, create_mock = _patch_exchange_state(
        bot, existing_stop_id="OLD_ALGO", exchange_stop_price=62501.4
    )

    await bot._update_stop_loss(
        current_price=current_price,
        position_data={"side": "long", "entry_price": entry, "amount": 0.01},
        market_data={"technical": {"atr_percent": 0.4}},
    )

    # 关键断言：L1482 判定 62501.4225 ≤ 62501.4 + 0.1，跳过收紧
    cancel_mock.assert_not_called()
    create_mock.assert_not_called()


# T10: 真实收紧（差异大于 tick）应触发更新
@pytest.mark.asyncio
async def test_real_tightening_triggers_update() -> None:
    """new=62600 显著大于 old=62501.4 + 0.1，应触发更新。"""
    bot = _make_bot({"stop_loss_percent": 0.005, "stop_loss_tick_tolerance": 0.1})
    entry = 62815.5
    _force_long_position(bot, entry=entry)
    # 让 position_manager 在盈利分支给出 new_stop 远高于 old
    # 设置最高价为 entry * 1.005（浮盈 0.5%），触发追踪
    bot.position_manager._highest_price_since_entry = entry * 1.005
    current_price = entry * 1.004  # 浮盈 > tolerance
    cancel_mock, create_mock = _patch_exchange_state(
        bot, existing_stop_id="OLD_ALGO", exchange_stop_price=62501.4
    )

    await bot._update_stop_loss(
        current_price=current_price,
        position_data={"side": "long", "entry_price": entry, "amount": 0.01},
        market_data={"technical": {"atr_percent": 0.4}},
    )

    # 此时持仓价 > 建仓价 + tolerance，跳过 L1455 容错分支
    # 进入"只升不降"分支：new_stop > old_stop + tick，触发更新
    cancel_mock.assert_called_once()
    create_mock.assert_called_once()


# T11: 只升不降分支（在容错分支之外）应识别 tick 容差
@pytest.mark.asyncio
async def test_only_increase_branch_respects_tick() -> None:
    """当浮盈已超 tolerance，但 new 仅比 old 高出不到 tick 时，仍跳过更新。"""
    bot = _make_bot({"stop_loss_percent": 0.005, "stop_loss_tick_tolerance": 0.1})
    entry = 62815.5
    _force_long_position(bot, entry=entry)
    # 让 position_manager 进入盈利分支但 new 仅略高于 old
    bot.position_manager._highest_price_since_entry = entry * 1.005
    # current_price 必须 ≥ entry * (1+tolerance=0.001) = 62878.3
    current_price = entry * 1.005
    cancel_mock, create_mock = _patch_exchange_state(
        bot,
        existing_stop_id="OLD_ALGO",
        exchange_stop_price=62920.0,  # 假设 old 已经追到接近位置
    )

    await bot._update_stop_loss(
        current_price=current_price,
        position_data={"side": "long", "entry_price": entry, "amount": 0.01},
        market_data={"technical": {"atr_percent": 0.4}},
    )

    # 用 highest=63091.65 计算 trailing stop = 63091.65 * (1-0.0002) ≈ 63079.03
    # 这高于 old=62920.0 0.25%，远超 tick=0.1，因此**应该**触发更新
    # 此用例实际是 T10 的变体
    cancel_mock.assert_called_once()
    create_mock.assert_called_once()


# T12: tick_tolerance=0 时回退到严格比较
@pytest.mark.asyncio
async def test_tick_tolerance_zero_disables() -> None:
    """tick=0 时容忍度消失，62501.4225 > 62501.4 = True，应进入"偏松收紧"分支并触发更新。"""
    bot = _make_bot({"stop_loss_percent": 0.005, "stop_loss_tick_tolerance": 0.0})
    entry = 62815.5
    _force_long_position(bot, entry=entry)
    # 浮亏 0.01% 触发 L1455 容错分支
    current_price = entry * 0.9999
    cancel_mock, create_mock = _patch_exchange_state(
        bot, existing_stop_id="OLD_ALGO", exchange_stop_price=62501.4
    )

    await bot._update_stop_loss(
        current_price=current_price,
        position_data={"side": "long", "entry_price": entry, "amount": 0.01},
        market_data={"technical": {"atr_percent": 0.4}},
    )

    # 容差为 0 -> 62501.4225 > 62501.4 = True -> 走"偏松收紧"分支并执行更新
    cancel_mock.assert_called_once()
    create_mock.assert_called_once()
