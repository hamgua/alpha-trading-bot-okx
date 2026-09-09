"""C2: 学习闭环补记（dream 2026-09-09-okx-loss-optimization）。

覆盖 task-card AC-2.1..AC-2.5。
"""

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from alpha_trading_bot.ai.adaptive.performance_tracker import (
    PerformanceTracker,
    TradeOutcome,
)
from alpha_trading_bot.config.models import (
    Config,
    ExchangeConfig,
    StopLossConfig,
    TradingConfig,
)
from alpha_trading_bot.core.adaptive_bot import AdaptiveTradingBot
from alpha_trading_bot.core.position_close_audit import (
    PositionCloseAuditContext,
    PositionCloseAuditor,
)


def _live_config() -> Config:
    return Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(
            test_mode=False,
            real_trading_confirmed=True,
            runtime_environment="prod",
            allow_short_selling=True,
        ),
        stop_loss=StopLossConfig(),
    )


class _Exchange:
    def __init__(self, history: List[Dict[str, Any]]) -> None:
        self.history = history
        self.calls: List[tuple] = []

    async def get_algo_order_history(
        self,
        symbol: str,
        algo_id: Optional[str] = None,
        limit: int = 20,
        ord_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        self.calls.append((symbol, algo_id, tuple(ord_types or ())))
        return self.history


def _confirmed_history() -> List[Dict[str, Any]]:
    return [
        {
            "id": "sl-1",
            "info": {
                "algoId": "sl-1",
                "slTriggerPx": "99.0",
                "actualPx": "98.9",
                "sz": "0.01",
            },
        }
    ]


def _fuzzy_confirmed_history() -> List[Dict[str, Any]]:
    return [
        {
            "id": "other",
            "info": {
                "algoId": "other",
                "slTriggerPx": "99.0",
                "actualPx": "98.95",
                "sz": "0.01",
            },
        }
    ]


class _FakeTracker:
    def __init__(self, closed: Any = None, raise_exc: Optional[Exception] = None) -> None:
        self.closed = closed
        self.raise_exc = raise_exc
        self.calls: List[Dict[str, Any]] = []

    def close_trade(
        self, exit_time: str, exit_price: float, reason: str = "signal"
    ) -> Any:
        self.calls.append(
            {"exit_time": exit_time, "exit_price": exit_price, "reason": reason}
        )
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.closed


class _FakeWeightManager:
    def __init__(self) -> None:
        self.calls: List[Any] = []

    def update_strategy_weights(self, trade: Any) -> None:
        self.calls.append(trade)


# ---- auditor 层 ----


@pytest.mark.asyncio
async def test_c2_a01_auditor_confirmed() -> None:
    """AC-2.1: 算法单实际成交 → confirmed 结果。"""
    ctx = PositionCloseAuditContext(
        side="long",
        entry_price=100.0,
        amount=0.01,
        stop_order_id="sl-1",
        stop_price=99.0,
    )
    ex = _Exchange(_confirmed_history())
    r = await PositionCloseAuditor(ctx).log_disappeared_position_close_event(
        ex, "BTC/USDT:USDT"
    )
    assert r["handled"] is True
    assert r["close_type"] == "confirmed"
    assert r["quality"] == "confirmed_algo"
    assert r["side"] == "long"
    assert r["exit_price"] == pytest.approx(98.9)
    assert r["pnl_percent"] == pytest.approx(-1.1)
    assert ex.calls[0] == (
        "BTC/USDT:USDT",
        "sl-1",
        ("conditional", "trigger", "move_order_stop"),
    )
    assert r["match_strategy"] == "exact_algo_id"


@pytest.mark.asyncio
async def test_c2_a07_auditor_fuzzy_confirmed() -> None:
    """安全加固: 模糊价格匹配返回 confirmed + match_strategy=fuzzy_price。"""
    ctx = PositionCloseAuditContext(
        side="long",
        entry_price=100.0,
        amount=0.01,
        stop_order_id="sl-1",
        stop_price=99.0,
    )
    ex = _Exchange(_fuzzy_confirmed_history())
    r = await PositionCloseAuditor(ctx).log_disappeared_position_close_event(
        ex, "BTC/USDT:USDT"
    )
    assert r["handled"] is True
    assert r["close_type"] == "confirmed"
    assert r["quality"] == "confirmed_algo"
    assert r["match_strategy"] == "fuzzy_price"
    assert r["exit_price"] == pytest.approx(98.95)


@pytest.mark.asyncio
async def test_c2_a02_auditor_estimated() -> None:
    """AC-2.3: 无算法单历史但 stop_price>0 → estimated 结果。"""
    ctx = PositionCloseAuditContext(
        side="long",
        entry_price=100.0,
        amount=0.01,
        stop_order_id="sl-1",
        stop_price=99.0,
    )
    ex = _Exchange([])
    r = await PositionCloseAuditor(ctx).log_disappeared_position_close_event(
        ex, "BTC/USDT:USDT"
    )
    assert r["handled"] is True
    assert r["close_type"] == "estimated"
    assert r["quality"] == "estimated_last_stop"
    assert r["exit_price"] == pytest.approx(99.0)
    assert r["pnl_percent"] == pytest.approx(-1.0)


@pytest.mark.asyncio
async def test_c2_a03_active_close_short_circuit() -> None:
    """AC-2.2: 主动平仓已确认 → 不查询、不补记。"""
    ctx = PositionCloseAuditContext(
        side="long",
        entry_price=100.0,
        amount=0.01,
        stop_order_id="sl-1",
        stop_price=99.0,
    )
    ctx.mark_active_close("close-1")

    class _BoomExchange(_Exchange):
        async def get_algo_order_history(self, *a: Any, **k: Any):
            raise AssertionError("should not query when active close confirmed")

    ex = _BoomExchange(_confirmed_history())
    r = await PositionCloseAuditor(ctx).log_disappeared_position_close_event(
        ex, "BTC/USDT:USDT"
    )
    assert r == {
        "handled": False,
        "reason": "active_close_confirmed",
        "match_strategy": "none",
    }
    assert ex.calls == []


@pytest.mark.asyncio
async def test_c2_a04_exchange_none() -> None:
    """AC-2.2: exchange=None → exchange_not_initialized。"""
    ctx = PositionCloseAuditContext(
        side="long", entry_price=100.0, amount=0.01, stop_order_id="sl-1"
    )
    r = await PositionCloseAuditor(ctx).log_disappeared_position_close_event(
        None, "BTC/USDT:USDT"
    )
    assert r == {
        "handled": False,
        "reason": "exchange_not_initialized",
        "match_strategy": "none",
    }


@pytest.mark.asyncio
async def test_c2_a05_no_exit_price() -> None:
    """AC-2.2: 无离场价（无 stop_price/order）→ no_exit_price。"""
    ctx = PositionCloseAuditContext(side="long", entry_price=100.0, amount=0.01)
    ex = _Exchange([])
    r = await PositionCloseAuditor(ctx).log_disappeared_position_close_event(
        ex, "BTC/USDT:USDT"
    )
    assert r == {
        "handled": False,
        "reason": "no_exit_price",
        "match_strategy": "none",
    }


@pytest.mark.asyncio
async def test_c2_a06_short_pnl_sign() -> None:
    """AC-2.1 边界: short pnl 符号正确。"""
    ctx = PositionCloseAuditContext(
        side="short",
        entry_price=100.0,
        amount=0.01,
        stop_order_id="sl-1",
        stop_price=101.0,
    )
    history = [
        {
            "id": "sl-1",
            "info": {
                "algoId": "sl-1",
                "slTriggerPx": "101.0",
                "actualPx": "101.1",
                "sz": "0.01",
            },
        }
    ]
    r = await PositionCloseAuditor(ctx).log_disappeared_position_close_event(
        _Exchange(history), "BTC/USDT:USDT"
    )
    assert r["exit_price"] == pytest.approx(101.1)
    assert r["pnl_percent"] == pytest.approx(-1.1)


# ---- bot 层 _backfill_close_in_tracker ----


def _bot_with_fakes(tracker: _FakeTracker, weights: _FakeWeightManager) -> AdaptiveTradingBot:
    bot = AdaptiveTradingBot(_live_config())
    bot.performance_tracker = tracker
    bot._strategy_weight_manager = weights
    bot._last_close_pnl_percent = 0.05
    bot._last_close_was_profitable = True
    return bot


def test_c2_b01_backfill_updates_pnl_and_weights() -> None:
    """AC-2.4: confirmed 补记成功 → 覆盖 pnl 快照并触发权重更新。"""
    tracker = _FakeTracker(closed=SimpleNamespace(pnl_percent=-0.011))
    weights = _FakeWeightManager()
    bot = _bot_with_fakes(tracker, weights)

    bot._backfill_close_in_tracker(
        {
            "handled": True,
            "close_type": "confirmed",
            "quality": "confirmed_algo",
            "side": "long",
            "exit_price": 98.9,
            "pnl_percent": -1.1,
        }
    )

    assert tracker.calls[0]["reason"] == "disappeared_confirmed"
    assert tracker.calls[0]["exit_price"] == pytest.approx(98.9)
    assert bot._last_close_pnl_percent == pytest.approx(-0.011)
    assert bot._last_close_was_profitable is False
    assert len(weights.calls) == 1


def test_c2_b02_backfill_profit_overrides() -> None:
    """AC-2.4: 盈利覆盖。"""
    tracker = _FakeTracker(closed=SimpleNamespace(pnl_percent=0.01))
    weights = _FakeWeightManager()
    bot = _bot_with_fakes(tracker, weights)

    bot._backfill_close_in_tracker(
        {
            "handled": True,
            "close_type": "confirmed",
            "side": "long",
            "exit_price": 101.0,
            "pnl_percent": 1.0,
        }
    )

    assert bot._last_close_pnl_percent == pytest.approx(0.01)
    assert bot._last_close_was_profitable is True
    assert len(weights.calls) == 1


def test_c2_b03_backfill_estimated_reason() -> None:
    """AC-2.3: estimated reason 命名。"""
    tracker = _FakeTracker(closed=SimpleNamespace(pnl_percent=-0.01))
    weights = _FakeWeightManager()
    bot = _bot_with_fakes(tracker, weights)

    bot._backfill_close_in_tracker(
        {
            "handled": True,
            "close_type": "estimated",
            "quality": "estimated_last_stop",
            "side": "long",
            "exit_price": 99.0,
            "pnl_percent": -1.0,
        }
    )

    assert tracker.calls[0]["reason"] == "disappeared_estimated"


def test_c2_b04_no_open_position() -> None:
    """AC-2.5: close_trade 返回 None（无 open）→ 不崩溃、不更新。"""
    tracker = _FakeTracker(closed=None)
    weights = _FakeWeightManager()
    bot = _bot_with_fakes(tracker, weights)

    bot._backfill_close_in_tracker(
        {
            "handled": True,
            "close_type": "confirmed",
            "side": "long",
            "exit_price": 98.9,
            "pnl_percent": -1.1,
        }
    )

    assert len(tracker.calls) == 1
    assert weights.calls == []
    assert bot._last_close_pnl_percent == pytest.approx(0.05)


def test_c2_b05_close_trade_exception_swallowed() -> None:
    """AC-2.5: close_trade 抛异常 → 被捕获，不影响主流程。"""
    tracker = _FakeTracker(raise_exc=RuntimeError("db down"))
    weights = _FakeWeightManager()
    bot = _bot_with_fakes(tracker, weights)

    bot._backfill_close_in_tracker(
        {
            "handled": True,
            "close_type": "confirmed",
            "side": "long",
            "exit_price": 98.9,
            "pnl_percent": -1.1,
        }
    )

    assert weights.calls == []
    assert bot._last_close_pnl_percent == pytest.approx(0.05)


def test_c2_b06_invalid_exit_price() -> None:
    """AC-2.5 边界: exit_price 无效 → 不调用 tracker。"""
    tracker = _FakeTracker(closed=SimpleNamespace(pnl_percent=-0.011))
    weights = _FakeWeightManager()
    bot = _bot_with_fakes(tracker, weights)

    bot._backfill_close_in_tracker(
        {"handled": True, "close_type": "confirmed", "exit_price": 0.0}
    )

    assert tracker.calls == []


def test_c2_b07_pnl_percent_none_guard() -> None:
    """AC-2.5 边界: closed.pnl_percent=None → 不更新、不触发权重。"""
    tracker = _FakeTracker(closed=SimpleNamespace(pnl_percent=None))
    weights = _FakeWeightManager()
    bot = _bot_with_fakes(tracker, weights)

    bot._backfill_close_in_tracker(
        {
            "handled": True,
            "close_type": "confirmed",
            "side": "long",
            "exit_price": 98.9,
        }
    )

    assert bot._last_close_pnl_percent == pytest.approx(0.05)
    assert weights.calls == []


# ---- bot 层 _record_position_disappeared 端到端 ----


@pytest.mark.asyncio
async def test_c2_r01_record_disappeared_confirmed() -> None:
    """AC-2.1/2.4: confirmed 全流程 → 补记 + 覆盖 pnl + 复位冷却。"""
    tracker = _FakeTracker(closed=SimpleNamespace(pnl_percent=-0.011))
    weights = _FakeWeightManager()
    bot = AdaptiveTradingBot(_live_config())
    bot.performance_tracker = tracker
    bot._strategy_weight_manager = weights
    bot._last_position_side = "long"
    bot._last_position_unrealized_pnl = -1.0
    bot._position_close_audit_context.remember(
        side="long",
        entry_price=100.0,
        amount=0.01,
        stop_order_id="sl-1",
        stop_price=99.0,
    )
    bot._exchange = _Exchange(_confirmed_history())

    await bot._record_position_disappeared()

    assert tracker.calls[0]["exit_price"] == pytest.approx(98.9)
    assert tracker.calls[0]["reason"] == "disappeared_confirmed"
    assert bot._last_closed_side == "long"
    assert bot._last_close_pnl_percent == pytest.approx(-0.011)
    assert bot._last_close_was_profitable is False
    assert len(weights.calls) == 1
    assert bot._last_position_side == ""


@pytest.mark.asyncio
async def test_c2_r02_record_disappeared_estimated() -> None:
    """AC-2.3: estimated 全流程。"""
    tracker = _FakeTracker(closed=SimpleNamespace(pnl_percent=-0.01))
    weights = _FakeWeightManager()
    bot = AdaptiveTradingBot(_live_config())
    bot.performance_tracker = tracker
    bot._strategy_weight_manager = weights
    bot._last_position_side = "long"
    bot._position_close_audit_context.remember(
        side="long", entry_price=100.0, amount=0.01, stop_order_id="sl-1", stop_price=99.0
    )
    bot._exchange = _Exchange([])

    await bot._record_position_disappeared()

    assert tracker.calls[0]["exit_price"] == pytest.approx(99.0)
    assert tracker.calls[0]["reason"] == "disappeared_estimated"


@pytest.mark.asyncio
async def test_c2_r03_record_disappeared_active_close() -> None:
    """AC-2.2: 主动平仓 → 不补记。"""
    tracker = _FakeTracker(closed=SimpleNamespace(pnl_percent=-0.011))
    weights = _FakeWeightManager()
    bot = AdaptiveTradingBot(_live_config())
    bot.performance_tracker = tracker
    bot._strategy_weight_manager = weights
    bot._last_position_side = "long"
    bot._position_close_audit_context.remember(
        side="long", entry_price=100.0, amount=0.01, stop_order_id="sl-1", stop_price=99.0
    )
    bot._position_close_audit_context.mark_active_close("close-1")
    bot._exchange = _Exchange(_confirmed_history())

    await bot._record_position_disappeared()

    assert tracker.calls == []
    assert weights.calls == []
    assert bot._last_position_side == ""


@pytest.mark.asyncio
async def test_c2_r04_record_disappeared_exchange_none() -> None:
    """AC-2.2: exchange=None → 不补记、不报错。"""
    tracker = _FakeTracker(closed=SimpleNamespace(pnl_percent=-0.011))
    weights = _FakeWeightManager()
    bot = AdaptiveTradingBot(_live_config())
    bot.performance_tracker = tracker
    bot._strategy_weight_manager = weights
    bot._last_position_side = "long"
    bot._position_close_audit_context.remember(
        side="long", entry_price=100.0, amount=0.01, stop_order_id="sl-1", stop_price=99.0
    )
    bot._exchange = None

    await bot._record_position_disappeared()

    assert tracker.calls == []


@pytest.mark.asyncio
async def test_c2_r05_record_disappeared_no_exit_price() -> None:
    """AC-2.2: 无离场价 → 不补记。"""
    tracker = _FakeTracker(closed=SimpleNamespace(pnl_percent=-0.011))
    weights = _FakeWeightManager()
    bot = AdaptiveTradingBot(_live_config())
    bot.performance_tracker = tracker
    bot._strategy_weight_manager = weights
    bot._last_position_side = "long"
    bot._position_close_audit_context.remember(
        side="long", entry_price=100.0, amount=0.01
    )
    bot._exchange = _Exchange([])

    await bot._record_position_disappeared()

    assert tracker.calls == []


@pytest.mark.asyncio
async def test_c2_r06_record_disappeared_query_failed_estimated_skips() -> None:
    """M-1 守卫：持仓查询失败 + estimated → 不补记，避免污染学习数据。"""
    tracker = _FakeTracker(closed=SimpleNamespace(pnl_percent=-0.01))
    weights = _FakeWeightManager()
    bot = AdaptiveTradingBot(_live_config())
    bot.performance_tracker = tracker
    bot._strategy_weight_manager = weights
    bot._last_position_side = "long"
    bot._position_close_audit_context.remember(
        side="long", entry_price=100.0, amount=0.01, stop_order_id="sl-1", stop_price=99.0
    )
    ex = _Exchange([])
    ex.last_query_failed = True
    bot._exchange = ex

    await bot._record_position_disappeared()

    assert tracker.calls == []
    assert weights.calls == []
    assert bot._last_position_side == ""


@pytest.mark.asyncio
async def test_c2_r07_record_disappeared_query_failed_exact_confirmed_backfills() -> None:
    """M-1/安全加固：持仓查询失败 + exact_algo_id confirmed → 仍补记真实离场。"""
    tracker = _FakeTracker(closed=SimpleNamespace(pnl_percent=-0.011))
    weights = _FakeWeightManager()
    bot = AdaptiveTradingBot(_live_config())
    bot.performance_tracker = tracker
    bot._strategy_weight_manager = weights
    bot._last_position_side = "long"
    bot._last_position_unrealized_pnl = -1.0
    bot._position_close_audit_context.remember(
        side="long", entry_price=100.0, amount=0.01, stop_order_id="sl-1", stop_price=99.0
    )
    ex = _Exchange(_confirmed_history())
    ex.last_query_failed = True
    bot._exchange = ex

    await bot._record_position_disappeared()

    assert tracker.calls[0]["exit_price"] == pytest.approx(98.9)
    assert tracker.calls[0]["reason"] == "disappeared_confirmed"
    assert bot._last_close_pnl_percent == pytest.approx(-0.011)
    assert len(weights.calls) == 1
    assert bot._last_position_side == ""


@pytest.mark.asyncio
async def test_c2_r08_record_disappeared_query_failed_fuzzy_confirmed_skips() -> None:
    """安全加固：持仓查询失败 + fuzzy_price confirmed → 不补记，避免误匹配污染。"""
    tracker = _FakeTracker(closed=SimpleNamespace(pnl_percent=-0.011))
    weights = _FakeWeightManager()
    bot = AdaptiveTradingBot(_live_config())
    bot.performance_tracker = tracker
    bot._strategy_weight_manager = weights
    bot._last_position_side = "long"
    bot._last_position_unrealized_pnl = -1.0
    bot._position_close_audit_context.remember(
        side="long", entry_price=100.0, amount=0.01, stop_order_id="sl-1", stop_price=99.0
    )
    ex = _Exchange(_fuzzy_confirmed_history())
    ex.last_query_failed = True
    bot._exchange = ex

    await bot._record_position_disappeared()

    assert tracker.calls == []
    assert weights.calls == []
    assert bot._last_position_side == ""


# ---- PerformanceTracker.close_trade 契约核对 ----


def test_c2_t01_close_trade_long_loss(tmp_path: Any) -> None:
    """AC-2.1: 真实 close_trade 用 side=buy 算 pnl，LOSS 阈值，二次返回 None。"""
    tracker = PerformanceTracker(data_dir=str(tmp_path / "perf"))
    tracker.record_trade(
        entry_time="t0",
        entry_price=100.0,
        side="buy",
        confidence=0.7,
        signal_type="buy",
        market_regime="trend",
        used_threshold=0.5,
        used_stop_loss=0.01,
    )
    closed = tracker.close_trade(
        exit_time="t1", exit_price=98.9, reason="disappeared_confirmed"
    )
    assert closed is not None
    assert closed.pnl_percent == pytest.approx(-0.011)
    assert closed.outcome == TradeOutcome.LOSS
    assert (
        tracker.close_trade(exit_time="t2", exit_price=98.9, reason="x") is None
    )


def test_c2_t02_close_trade_short_win(tmp_path: Any) -> None:
    """AC-2.1: short(side=sell) 盈利 → WIN。"""
    tracker = PerformanceTracker(data_dir=str(tmp_path / "perf2"))
    tracker.record_trade(
        entry_time="t0",
        entry_price=100.0,
        side="sell",
        confidence=0.7,
        signal_type="sell",
        market_regime="trend",
        used_threshold=0.5,
        used_stop_loss=0.01,
    )
    closed = tracker.close_trade(exit_time="t1", exit_price=98.9, reason="disappeared")
    assert closed is not None
    assert closed.pnl_percent == pytest.approx(0.011)
    assert closed.outcome == TradeOutcome.WIN
