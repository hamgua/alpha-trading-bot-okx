"""
持续下跌检测器单元测试
"""

from alpha_trading_bot.ai.sustained_decline_detector import SustainedDeclineDetector


def test_decline_metrics_count_recent_consecutive_down_periods_from_old_to_new_changes():
    """小时变化按旧到新传入时，应统计最近连续下跌周期。"""
    detector = SustainedDeclineDetector()

    metrics = detector._calculate_decline_metrics(
        current_price=96.0,
        start_price=100.0,
        start_time=None,
        hourly_changes=[0.002, 0.001, -0.002, -0.003, -0.004],
        recent_change=-0.4,
        daily_change=-4.0,
    )

    assert metrics.consecutive_down_periods == 3
    assert metrics.down_ratio == 3 / 5


def test_decline_metrics_use_recent_window_for_down_ratio():
    """下跌周期占比应基于最近最多12个周期，而不是被更早历史稀释。"""
    detector = SustainedDeclineDetector()

    metrics = detector._calculate_decline_metrics(
        current_price=96.0,
        start_price=100.0,
        start_time=None,
        hourly_changes=([0.001] * 20) + ([-0.002] * 9) + ([0.001] * 3),
        recent_change=0.1,
        daily_change=-4.0,
    )

    assert metrics.total_periods == 32
    assert metrics.consecutive_down_periods == 0
    assert metrics.down_ratio == 9 / 12
