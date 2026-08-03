"""验证止损更新成功后，position_close_audit_context 能拿到最新 algoId/价格。

修复 P1 bug：止损单每周期被取消+创建时，position_close_audit_context.stop_order_id
仅在建仓时设置一次，导致持仓意外消失时永远 algo_history_not_found。
"""

from alpha_trading_bot.config.models import Config, ExchangeConfig, TradingConfig
from alpha_trading_bot.core.adaptive_bot import AdaptiveTradingBot


def _make_bot() -> AdaptiveTradingBot:
    config = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(test_mode=True),
    )
    return AdaptiveTradingBot(config)


def _prime_audit_context(bot: AdaptiveTradingBot) -> None:
    bot._position_close_audit_context.remember(
        side="long",
        entry_price=62815.5,
        amount=0.01,
        unrealized_pnl=-0.02,
        stop_order_id="OLD_ALGO",
        stop_price=62501.4,
    )


# T13: 刷新后 audit_context 更新为最新
def test_refresh_close_audit_stop_updates_context() -> None:
    bot = _make_bot()
    _prime_audit_context(bot)

    bot._refresh_close_audit_stop("NEW_ALGO", 62510.0)

    ctx = bot._position_close_audit_context
    assert ctx.stop_order_id == "NEW_ALGO"
    assert ctx.stop_price == 62510.0
    # 其他字段保持不变
    assert ctx.entry_price == 62815.5
    assert ctx.amount == 0.01
    assert ctx.side == "long"


# T14: 空 stop_order_id 不更新
def test_refresh_close_audit_stop_skips_empty_id() -> None:
    bot = _make_bot()
    _prime_audit_context(bot)

    bot._refresh_close_audit_stop("", 62510.0)
    assert bot._position_close_audit_context.stop_order_id == "OLD_ALGO"

    bot._refresh_close_audit_stop(None, 62510.0)  # type: ignore[arg-type]
    assert bot._position_close_audit_context.stop_order_id == "OLD_ALGO"


# T15: 无持仓上下文时不更新（防止误写平仓后状态）
def test_refresh_close_audit_stop_skips_no_position() -> None:
    bot = _make_bot()
    # 不 prime，ctx 是默认空 entry_price=0 side=""
    bot._refresh_close_audit_stop("NEW_ALGO", 62510.0)
    ctx = bot._position_close_audit_context
    # 没 entry_price 时应跳过
    assert ctx.stop_order_id == ""
    assert ctx.stop_price == 0.0
