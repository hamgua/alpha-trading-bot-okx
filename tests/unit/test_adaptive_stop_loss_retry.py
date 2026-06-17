"""Stop-loss retry 算法测试 (2026-06-17 fix-sl-trigger-price)

回归测试 OKX 止损单触发价约束：
- 做多(LONG)止损 = sell 单：触发价必须 < 当前价 (code 51280)
- 做空(SHORT)止损 = buy 单：触发价必须 > 当前价 (code 51278)

修复内容：
- 重试时优先基于 current_price 重算安全止损价（不再用绝对价格递减）
- 安全裕度 = max(current_price * 0.001, 1.0 USDT)
- 兜底：current_price 无效时回退到原百分比调整逻辑
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from alpha_trading_bot.core.adaptive_stop_loss import AdaptiveStopLossManager


def _make_exchange():
    """构造最小可用的 mock exchange"""
    exchange = MagicMock()
    exchange.symbol = "BTC/USDT:USDT"
    exchange.create_stop_loss = AsyncMock()
    return exchange


@pytest.mark.asyncio
async def test_long_retry_with_safe_price():
    """做多：首次止损价(基于建仓价)高于当前价 → 重试时使用安全价"""
    exchange = _make_exchange()
    exchange.create_stop_loss.side_effect = [
        "",
        "stop-123",
    ]

    manager = AdaptiveStopLossManager(exchange)

    stop_order_id = await manager.create_stop_loss_with_retry(
        amount=0.01,
        stop_price=65660.7,
        current_price=64868.2,
        max_retries=3,
        position_side="long",
    )

    assert stop_order_id == "stop-123"
    second_call = exchange.create_stop_loss.call_args_list[1]
    used_stop_price = second_call.kwargs["stop_price"]
    assert used_stop_price < 64868.2


@pytest.mark.asyncio
async def test_short_retry_with_safe_price():
    """做空：首次止损价(基于建仓价)低于当前价 → 重试时使用安全价"""
    exchange = _make_exchange()
    exchange.create_stop_loss.side_effect = [
        "",
        "stop-456",
    ]

    manager = AdaptiveStopLossManager(exchange)

    stop_order_id = await manager.create_stop_loss_with_retry(
        amount=0.01,
        stop_price=66990.0,
        current_price=67100.0,
        max_retries=3,
        position_side="short",
    )

    assert stop_order_id == "stop-456"
    second_call = exchange.create_stop_loss.call_args_list[1]
    used_stop_price = second_call.kwargs["stop_price"]
    assert used_stop_price > 67100.0


@pytest.mark.asyncio
async def test_safety_margin_at_least_1_usdt():
    """安全裕度必须至少 0.1% 或 1 USDT（取较大者）"""
    exchange = _make_exchange()
    exchange.create_stop_loss.side_effect = [
        Exception("okx SL trigger price must be less than the last price"),
        "stop-789",
    ]

    manager = AdaptiveStopLossManager(exchange)

    await manager.create_stop_loss_with_retry(
        amount=0.01,
        stop_price=200.0,
        current_price=100.0,
        max_retries=3,
        position_side="long",
    )

    second_call = exchange.create_stop_loss.call_args_list[1]
    used_stop_price = second_call.kwargs["stop_price"]
    assert (100.0 - used_stop_price) >= 1.0


@pytest.mark.asyncio
async def test_real_world_scenario_3pct_drop():
    """真实场景：建仓价 65990.7，当前价 64868.2，跌幅 1.7%"""
    exchange = _make_exchange()
    exchange.create_stop_loss.side_effect = [
        "",
        "",
        "stop-abc",
    ]

    manager = AdaptiveStopLossManager(exchange)

    stop_order_id = await manager.create_stop_loss_with_retry(
        amount=0.01,
        stop_price=65660.7,
        current_price=64868.2,
        max_retries=3,
        position_side="long",
    )

    assert stop_order_id == "stop-abc"
    third_call = exchange.create_stop_loss.call_args_list[2]
    used_stop_price = third_call.kwargs["stop_price"]
    assert used_stop_price < 64868.2


@pytest.mark.asyncio
async def test_all_retries_fail_returns_none():
    """异常路径：重试全部失败返回 None"""
    exchange = _make_exchange()
    exchange.create_stop_loss.return_value = ""

    manager = AdaptiveStopLossManager(exchange)

    result = await manager.create_stop_loss_with_retry(
        amount=0.01,
        stop_price=65660.7,
        current_price=64868.2,
        max_retries=3,
        position_side="long",
    )

    assert result is None
    assert exchange.create_stop_loss.call_count == 4


@pytest.mark.asyncio
async def test_non_sl_trigger_error_breaks_loop():
    """异常路径：非 SL trigger 错误立即退出"""
    exchange = _make_exchange()
    exchange.create_stop_loss.side_effect = Exception("okx sCode=51000")

    manager = AdaptiveStopLossManager(exchange)

    result = await manager.create_stop_loss_with_retry(
        amount=0.01,
        stop_price=65660.7,
        current_price=64868.2,
        max_retries=3,
        position_side="long",
    )

    assert result is None
    assert exchange.create_stop_loss.call_count == 1


@pytest.mark.asyncio
async def test_zero_current_price_falls_back():
    """边界条件：current_price 为 0 时，使用百分比调整作为 fallback"""
    exchange = _make_exchange()
    exchange.create_stop_loss.side_effect = [
        Exception("okx SL trigger price must be less than the last price"),
        "stop-xyz",
    ]

    manager = AdaptiveStopLossManager(exchange)

    result = await manager.create_stop_loss_with_retry(
        amount=0.01,
        stop_price=65660.7,
        current_price=0.0,
        max_retries=3,
        position_side="long",
    )

    assert result == "stop-xyz"
    second_call = exchange.create_stop_loss.call_args_list[1]
    used_stop_price = second_call.kwargs["stop_price"]
    assert abs(used_stop_price - 65332.4) < 0.5


@pytest.mark.asyncio
async def test_short_direction_increases_price():
    """做空方向：止损价必须递增（高于当前价）"""
    exchange = _make_exchange()
    exchange.create_stop_loss.side_effect = [
        Exception("okx SL trigger price must be greater than the last price"),
        "stop-short",
    ]

    manager = AdaptiveStopLossManager(exchange)

    await manager.create_stop_loss_with_retry(
        amount=0.01,
        stop_price=66000.0,
        current_price=67000.0,
        max_retries=3,
        position_side="short",
    )

    second_call = exchange.create_stop_loss.call_args_list[1]
    used_stop_price = second_call.kwargs["stop_price"]
    assert used_stop_price > 67000.0


@pytest.mark.asyncio
async def test_first_attempt_succeeds():
    """正常路径：首次创建即成功（不进入重试分支）"""
    exchange = _make_exchange()
    exchange.create_stop_loss.return_value = "stop-first"

    manager = AdaptiveStopLossManager(exchange)

    result = await manager.create_stop_loss_with_retry(
        amount=0.01,
        stop_price=65600.0,
        current_price=64868.2,
        max_retries=3,
        position_side="long",
    )

    assert result == "stop-first"
    assert exchange.create_stop_loss.call_count == 1


@pytest.mark.asyncio
async def test_safety_margin_pct_used_for_high_price():
    """高单价场景：使用 0.1% 比例裕度"""
    exchange = _make_exchange()
    exchange.create_stop_loss.side_effect = [
        "",
        "stop-high",
    ]

    manager = AdaptiveStopLossManager(exchange)

    await manager.create_stop_loss_with_retry(
        amount=0.01,
        stop_price=70000.0,
        current_price=64868.2,
        max_retries=3,
        position_side="long",
    )

    second_call = exchange.create_stop_loss.call_args_list[1]
    used_stop_price = second_call.kwargs["stop_price"]
    margin = 64868.2 - used_stop_price
    assert margin >= 64.8
    assert margin <= 65.0
