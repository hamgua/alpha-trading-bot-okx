"""实盘安全闸门测试。"""

import sys
import types

import pytest

from alpha_trading_bot.config.models import Config, TradingConfig, ExchangeConfig
from alpha_trading_bot.core.bot import TradingBot
from alpha_trading_bot.core.adaptive_bot import AdaptiveTradingBot


@pytest.mark.parametrize(
    "trading_config, expected_reason",
    [
        (
            TradingConfig(
                test_mode=True,
                real_trading_confirmed=True,
                runtime_environment="prod",
            ),
            "test_mode_enabled",
        ),
        (
            TradingConfig(
                test_mode=False,
                real_trading_confirmed=False,
                runtime_environment="prod",
            ),
            "real_trading_not_confirmed",
        ),
        (
            TradingConfig(
                test_mode=False,
                real_trading_confirmed=True,
                runtime_environment="dev",
            ),
            "runtime_environment_not_allowed",
        ),
    ],
)
def test_trading_config_live_preconditions_block(
    trading_config: TradingConfig, expected_reason: str
) -> None:
    allowed, reason = trading_config.check_live_trading_preconditions()
    assert not allowed
    assert reason == expected_reason


def _build_live_config(*, test_mode: bool, confirmed: bool, runtime_env: str) -> Config:
    return Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(
            test_mode=test_mode,
            real_trading_confirmed=confirmed,
            runtime_environment=runtime_env,
        ),
    )


class _MockConfigSource:
    def get_current_params(self):
        return {"stop_loss_percent": 0.005, "stop_loss_profit_percent": 0.002}


class _MockRiskManager:
    def calculate_trade_params(self, *args, **kwargs):
        return {
            "suggested_position": 0.01,
            "stop_loss_price": 99.0,
            "stop_loss_percent": 0.005,
            "stop_loss_profit_percent": 0.002,
        }


@pytest.mark.asyncio
async def test_standard_bot_open_position_blocked_by_live_guard() -> None:
    config = _build_live_config(test_mode=True, confirmed=True, runtime_env="prod")
    bot = TradingBot(config)

    called = {"create_order": False, "create_stop_loss": False}

    class _MockExchange:
        async def calculate_max_contracts(self, price: float, leverage: int) -> float:
            return 0.02

        async def create_order(self, **kwargs) -> str:
            called["create_order"] = True
            return "order-1"

        async def create_stop_loss(self, **kwargs) -> str:
            called["create_stop_loss"] = True
            return "stop-1"

    setattr(bot, "_exchange", _MockExchange())

    await bot._open_position(100.0)

    assert called["create_order"] is False
    assert called["create_stop_loss"] is False


@pytest.mark.asyncio
async def test_adaptive_bot_execute_trade_blocked_by_live_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _build_live_config(test_mode=True, confirmed=True, runtime_env="prod")
    bot = AdaptiveTradingBot(config)

    called = {"create_order": False}

    class _MockExchange:
        symbol = "BTC/USDT:USDT"

        async def create_order(self, **kwargs) -> str:
            called["create_order"] = True
            return "order-1"

    setattr(bot, "_exchange", _MockExchange())
    monkeypatch.setattr(bot, "param_manager", _MockConfigSource(), raising=False)
    monkeypatch.setattr(bot, "risk_manager", _MockRiskManager(), raising=False)

    await bot._execute_trade(
        action="open",
        current_price=100.0,
        has_position=False,
        position_data={},
        market_data={"technical": {}},
        selected_strategy=None,
    )

    assert called["create_order"] is False


@pytest.mark.asyncio
async def test_adaptive_bot_initialize_logs_full_exception(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = _build_live_config(test_mode=True, confirmed=True, runtime_env="prod")
    bot = AdaptiveTradingBot(config)

    class _BoomExchange:
        async def initialize(self) -> None:
            raise TypeError("boom from exchange init")

    exchange_package = types.ModuleType("alpha_trading_bot.exchange")
    exchange_package.__path__ = []
    exchange_client = types.ModuleType("alpha_trading_bot.exchange.client")
    exchange_client.ExchangeClient = lambda **kwargs: _BoomExchange()
    monkeypatch.setitem(sys.modules, "alpha_trading_bot.exchange", exchange_package)
    monkeypatch.setitem(
        sys.modules, "alpha_trading_bot.exchange.client", exchange_client
    )

    with caplog.at_level("ERROR"):
        ok = await bot.initialize()

    assert ok is False
    assert any("boom from exchange init" in record.message for record in caplog.records)
    assert any(record.exc_info is not None for record in caplog.records)
