"""止损保护测试 - 止损创建失败时自动平仓 + TEST_MODE 安全"""

import pytest
from alpha_trading_bot.core.bot import TradingBot
from alpha_trading_bot.config.models import (
    Config, TradingConfig, ExchangeConfig, StopLossConfig,
)


def _make_live_config() -> Config:
    return Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(
            test_mode=False,
            real_trading_confirmed=True,
            runtime_environment="prod",
        ),
        stop_loss=StopLossConfig(
            stop_loss_percent=0.015,
            stop_loss_profit_percent=0.008,
        ),
    )


@pytest.mark.asyncio
async def test_open_position_closes_when_stop_loss_fails():
    """止损单创建失败时，应立即市价平仓"""
    config = _make_live_config()
    bot = TradingBot(config)

    order_created = {"open": False, "close": False, "stop": False}

    class MockExchange:
        symbol = "BTC/USDT:USDT"

        async def calculate_max_contracts(self, price, leverage):
            return 0.01

        async def create_order(self, symbol, side, amount, price=None, order_type="market"):
            if side == "buy":
                order_created["open"] = True
                return "open-order-1"
            elif side == "sell":
                order_created["close"] = True
                return "close-order-1"
            return ""

        async def create_stop_loss(self, symbol, side, amount, stop_price):
            order_created["stop"] = True
            return ""

        async def cancel_algo_order(self, algo_id, symbol):
            return (True, "success")

    bot._exchange = MockExchange()

    await bot._open_position(100000.0)

    assert order_created["open"] is True
    assert order_created["stop"] is True
    assert order_created["close"] is True


@pytest.mark.asyncio
async def test_open_position_succeeds_with_stop_loss():
    """止损创建成功时不应平仓"""
    config = _make_live_config()
    bot = TradingBot(config)

    order_created = {"open": False, "close": False, "stop": False}

    class MockExchange:
        symbol = "BTC/USDT:USDT"

        async def calculate_max_contracts(self, price, leverage):
            return 0.01

        async def create_order(self, symbol, side, amount, price=None, order_type="market"):
            if side == "buy":
                order_created["open"] = True
                return "open-order-1"
            elif side == "sell":
                order_created["close"] = True
                return "close-order-1"
            return ""

        async def create_stop_loss(self, symbol, side, amount, stop_price):
            order_created["stop"] = True
            return "stop-order-1"

        async def cancel_algo_order(self, algo_id, symbol):
            return (True, "success")

    bot._exchange = MockExchange()

    await bot._open_position(100000.0)

    assert order_created["open"] is True
    assert order_created["stop"] is True
    assert order_created["close"] is False


@pytest.mark.asyncio
async def test_open_position_skips_state_for_simulated_order():
    """TEST_MODE 下开仓应跳过本地状态更新"""
    import tempfile
    config = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(
            test_mode=False,
            real_trading_confirmed=True,
            runtime_environment="prod",
        ),
    )
    bot = TradingBot(config)
    # 使用临时目录避免持久化干扰
    from alpha_trading_bot.core.position_manager import PositionManager
    bot.position_manager = PositionManager(config, data_dir=tempfile.mkdtemp())

    class MockExchange:
        symbol = "BTC/USDT:USDT"

        async def calculate_max_contracts(self, price, leverage):
            return 0.01

        async def create_order(self, symbol, side, amount, price=None, order_type="market"):
            return "SIMULATED_ORDER_BUY_123"

        async def create_stop_loss(self, symbol, side, amount, stop_price):
            return "SIMULATED_STOP_123"

        async def cancel_algo_order(self, algo_id, symbol):
            return (True, "success")

    bot._exchange = MockExchange()

    await bot._open_position(100000.0)

    assert not bot.position_manager.has_position()


def test_is_simulated_order():
    """ExchangeClient.is_simulated_order 应正确识别模拟订单"""
    from alpha_trading_bot.exchange.client import ExchangeClient

    assert ExchangeClient.is_simulated_order("SIMULATED_ORDER_BUY_123") is True
    assert ExchangeClient.is_simulated_order("SIMULATED_STOP_456") is True
    assert ExchangeClient.is_simulated_order("real-order-789") is False
    assert ExchangeClient.is_simulated_order("") is False