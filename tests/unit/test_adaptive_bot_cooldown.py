"""AdaptiveTradingBot direction cooldown quality gates."""

from unittest.mock import MagicMock

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


def test_records_profitable_close_when_position_disappears() -> None:
    """持仓消失时记录上一笔是否盈利，用于再入场冷却。"""
    bot = _make_bot()
    bot._last_position_side = "long"
    bot._last_position_unrealized_pnl = 0.05

    bot._record_position_disappeared()

    assert bot._last_closed_side == "long"
    assert bot._last_close_was_profitable is True
    assert bot._last_position_side == ""
