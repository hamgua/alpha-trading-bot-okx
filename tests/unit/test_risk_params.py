"""风控参数测试 - 仓位限制和杠杆"""

import pytest
from unittest.mock import AsyncMock
from alpha_trading_bot.exchange.market_data import MarketDataService
from alpha_trading_bot.config.models import ExchangeConfig


def test_exchange_config_default_leverage_is_safe():
    """默认杠杆应为5倍"""
    config = ExchangeConfig()
    assert config.leverage == 5


def test_exchange_config_max_position_usage():
    """默认仓位使用比例应为30%"""
    config = ExchangeConfig()
    assert config.max_position_usage == 0.30


@pytest.mark.asyncio
async def test_calculate_max_contracts_limits_position():
    """仓位计算应限制在余额的 max_position_usage 比例内"""
    service = MarketDataService(exchange=None, symbol="BTC/USDT:USDT")

    mock_balance = AsyncMock(return_value=1000.0)
    contracts = await service.calculate_max_contracts(100000.0, 5, mock_balance)

    max_expected = (1000.0 * 0.30 * 5) / 100000.0
    assert contracts <= max_expected + 0.001


@pytest.mark.asyncio
async def test_calculate_max_contracts_zero_balance():
    """余额为0时应返回0"""
    service = MarketDataService(exchange=None, symbol="BTC/USDT:USDT")
    mock_balance = AsyncMock(return_value=0.0)
    contracts = await service.calculate_max_contracts(100000.0, 5, mock_balance)
    assert contracts == 0.0


@pytest.mark.asyncio
async def test_calculate_max_contracts_custom_usage():
    """自定义 max_position_usage 应生效"""
    service = MarketDataService(exchange=None, symbol="BTC/USDT:USDT")

    mock_balance = AsyncMock(return_value=1000.0)
    contracts = await service.calculate_max_contracts(
        100000.0, 5, mock_balance, max_position_usage=0.50
    )
    max_expected = (1000.0 * 0.50 * 5) / 100000.0
    assert contracts <= max_expected + 0.001


# === Task 2: 止损参数测试 ===

from alpha_trading_bot.config.models import StopLossConfig
from alpha_trading_bot.core.position_manager import PositionManager, Position


def test_stop_loss_defaults_are_safe():
    """智能止损模式下，止损比例基于建仓价计算，值更小但以建仓价为基准"""
    config = StopLossConfig()
    assert config.stop_loss_percent > 0
    assert config.stop_loss_profit_percent > 0
    assert config.stop_loss_entry_based is True


def test_stop_loss_profit_ratio_reasonable():
    """追踪止损不应远小于亏损止损"""
    config = StopLossConfig()
    ratio = config.stop_loss_profit_percent / config.stop_loss_percent
    assert ratio >= 0.4


def test_position_manager_long_stop_price():
    """做多止损价应给出足够噪音缓冲（传统模式）"""
    from alpha_trading_bot.config.models import Config, ExchangeConfig, TradingConfig, AIConfig, StopLossConfig

    config = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        stop_loss=StopLossConfig(
            stop_loss_percent=0.015,
            stop_loss_profit_percent=0.008,
            stop_loss_entry_based=False,
        ),
    )

    pm = PositionManager(config)
    pm._position = Position(
        symbol="BTC/USDT:USDT", side="long", amount=0.01, entry_price=100000.0
    )
    pm._entry_price = 100000.0

    stop_price = pm.calculate_stop_price(100000.0)
    assert stop_price <= 98500.0

    stop_price_profit = pm.calculate_stop_price(102000.0)
    assert stop_price_profit <= 101184.0


def test_position_manager_short_stop_price_uses_loss_percent():
    """做空亏损时应使用亏损止损比例而非 profit_percent*2"""
    from alpha_trading_bot.config.models import Config, ExchangeConfig, StopLossConfig

    config = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        stop_loss=StopLossConfig(stop_loss_percent=0.015, stop_loss_profit_percent=0.008),
    )

    pm = PositionManager(config)
    pm._position = Position(
        symbol="BTC/USDT:USDT", side="short", amount=0.01, entry_price=100000.0
    )
    pm._entry_price = 100000.0

    stop_price = pm.calculate_short_stop_price(101000.0)
    expected = 101000.0 * (1 + 0.015)
    assert abs(stop_price - expected) < 1.0


def test_unified_stop_price_long():
    """统一止损入口应正确路由做多（传统模式）"""
    from alpha_trading_bot.config.models import Config, ExchangeConfig, StopLossConfig

    config = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        stop_loss=StopLossConfig(
            stop_loss_percent=0.015,
            stop_loss_profit_percent=0.008,
            stop_loss_entry_based=False,
        ),
    )

    pm = PositionManager(config)
    pm._position = Position(
        symbol="BTC/USDT:USDT", side="long", amount=0.01, entry_price=100000.0
    )
    pm._entry_price = 100000.0

    unified = pm.calculate_stop_price_unified(100000.0)
    direct = pm.calculate_stop_price(100000.0)
    assert unified == direct


def test_unified_stop_price_short():
    """统一止损入口应正确路由做空"""
    from alpha_trading_bot.config.models import Config, ExchangeConfig, StopLossConfig

    config = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        stop_loss=StopLossConfig(stop_loss_percent=0.015, stop_loss_profit_percent=0.008),
    )

    pm = PositionManager(config)
    pm._position = Position(
        symbol="BTC/USDT:USDT", side="short", amount=0.01, entry_price=100000.0
    )
    pm._entry_price = 100000.0

    unified = pm.calculate_stop_price_unified(101000.0)
    direct = pm.calculate_short_stop_price(101000.0)
    assert unified == direct