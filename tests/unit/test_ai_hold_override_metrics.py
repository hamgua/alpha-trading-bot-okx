"""AI-HOLD 覆盖交易结果统计测试。"""

import pytest

from alpha_trading_bot.ai.adaptive.performance_tracker import PerformanceTracker


def test_ai_hold_override_metrics_track_closed_trade_outcomes(tmp_path) -> None:
    """AI-HOLD 覆盖后的交易关闭时，应按类型统计胜负和胜率。"""
    tracker = PerformanceTracker(data_dir=str(tmp_path))

    tracker.record_trade(
        entry_time="2026-07-20T00:00:00Z",
        entry_price=100.0,
        side="buy",
        confidence=0.8,
        signal_type="buy",
        market_regime="trend",
        used_threshold=0.5,
        used_stop_loss=0.005,
        metadata={
            "ai_hold_override": True,
            "ai_hold_override_type": "structure_long",
        },
    )
    tracker.close_trade(
        exit_time="2026-07-20T01:00:00Z",
        exit_price=101.0,
        reason="take_profit",
    )

    tracker.record_trade(
        entry_time="2026-07-20T02:00:00Z",
        entry_price=100.0,
        side="sell",
        confidence=0.8,
        signal_type="sell",
        market_regime="trend",
        used_threshold=0.5,
        used_stop_loss=0.005,
        metadata={
            "ai_hold_override": True,
            "ai_hold_override_type": "structure_short",
        },
    )
    tracker.close_trade(
        exit_time="2026-07-20T03:00:00Z",
        exit_price=101.0,
        reason="stop_loss",
    )

    metrics = tracker.get_ai_hold_override_metrics()

    assert metrics["total"] == 2
    assert metrics["wins"] == 1
    assert metrics["losses"] == 1
    assert metrics["win_rate"] == pytest.approx(0.5)
    assert metrics["by_type"]["structure_long"]["wins"] == 1
    assert metrics["by_type"]["structure_short"]["losses"] == 1
