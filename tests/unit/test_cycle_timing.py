"""交易周期时间计算单元测试

覆盖路径:
- 正常偏移路径
- min_wait 重置路径下 random_offset 钳位到 offset_range
- next_time <= now 修正路径
- 边界与不变量验证
"""

from datetime import datetime, timedelta

from alpha_trading_bot.core.cycle_timing import (
    CycleTiming,
    calculate_cycle_timing,
)


class TestCalculateCycleTiming:

    def test_normal_path_with_positive_offset(self) -> None:
        now = datetime(2026, 6, 18, 14, 7, 30)
        timing = calculate_cycle_timing(
            now=now,
            cycle_minutes=15,
            offset_range=180,
            random_offset=120,
        )

        assert timing.next_time == datetime(2026, 6, 18, 14, 17, 0)
        assert timing.wait_seconds == 570.0
        assert timing.random_offset == 120

    def test_normal_path_with_negative_offset(self) -> None:
        now = datetime(2026, 6, 18, 14, 7, 30)
        timing = calculate_cycle_timing(
            now=now,
            cycle_minutes=15,
            offset_range=180,
            random_offset=-95,
        )

        assert timing.next_time == datetime(2026, 6, 18, 14, 13, 25)
        assert timing.wait_seconds == 355.0
        assert timing.random_offset == -95

    def test_next_time_past_now_resets_to_positive_offset(self) -> None:
        now = datetime(2026, 6, 18, 14, 7, 30)
        timing = calculate_cycle_timing(
            now=now,
            cycle_minutes=15,
            offset_range=180,
            random_offset=-180,
        )

        assert timing.random_offset == -150
        assert timing.wait_seconds == 300.0
        assert timing.next_time == datetime(2026, 6, 18, 14, 12, 30)

    def test_min_wait_reset_clamps_offset_to_offset_range(self) -> None:
        now = datetime(2026, 6, 18, 9, 44, 41)
        timing = calculate_cycle_timing(
            now=now,
            cycle_minutes=15,
            offset_range=180,
            random_offset=-180,
        )

        assert timing.random_offset == 180
        assert timing.next_time == datetime(2026, 6, 18, 9, 48, 0)
        assert timing.wait_seconds == 199.0

    def test_min_wait_reset_does_not_invert_wait_below_min_wait(self) -> None:
        now = datetime(2026, 6, 18, 14, 0, 30)
        timing = calculate_cycle_timing(
            now=now,
            cycle_minutes=15,
            offset_range=180,
            random_offset=-150,
        )

        assert timing.wait_seconds >= 300.0
        assert timing.random_offset == -150
        assert timing.next_time == now + timedelta(seconds=timing.wait_seconds)

    def test_min_wait_reset_when_offset_not_past_now(self) -> None:
        now = datetime(2026, 6, 18, 14, 7, 30)
        timing = calculate_cycle_timing(
            now=now,
            cycle_minutes=15,
            offset_range=180,
            random_offset=-120,
        )

        assert timing.next_time == datetime(2026, 6, 18, 14, 13, 0)
        assert timing.wait_seconds == 330.0
        assert timing.random_offset == -120

    def test_seconds_to_next_zero_at_boundary(self) -> None:
        now = datetime(2026, 6, 18, 14, 15, 0)
        timing = calculate_cycle_timing(
            now=now,
            cycle_minutes=15,
            offset_range=180,
            random_offset=0,
        )

        assert timing.next_time == datetime(2026, 6, 18, 14, 30, 0)
        assert timing.wait_seconds == 900.0
        assert timing.random_offset == 0

    def test_base_time_invariant_across_paths(self) -> None:
        scenarios = [
            (datetime(2026, 6, 18, 14, 7, 30), 120),
            (datetime(2026, 6, 18, 14, 7, 30), -95),
            (datetime(2026, 6, 18, 9, 44, 41), -180),
            (datetime(2026, 6, 18, 14, 0, 0), 180),
            (datetime(2026, 6, 18, 14, 14, 59), -180),
        ]

        for now, offset in scenarios:
            timing = calculate_cycle_timing(
                now=now,
                cycle_minutes=15,
                offset_range=180,
                random_offset=offset,
            )
            current_minute = now.minute
            current_second = now.second
            minutes_to_next = 15 - (current_minute % 15)
            seconds_to_next = minutes_to_next * 60 - current_second
            base_time = now + timedelta(seconds=seconds_to_next)
            expected_next = base_time + timedelta(seconds=timing.random_offset)
            assert timing.next_time == expected_next, (
                f"next_time 与 base_time 基准不一致: now={now}, offset={offset}, "
                f"next_time={timing.next_time}, expected={expected_next}"
            )

    def test_real_log_scenario_clamps_offset(self) -> None:
        now = datetime(2026, 6, 18, 9, 44, 41)
        timing = calculate_cycle_timing(
            now=now,
            cycle_minutes=15,
            offset_range=180,
            random_offset=-180,
        )

        assert timing.random_offset == 180
        assert timing.next_time == datetime(2026, 6, 18, 9, 48, 0)


class TestCycleTimingDataclass:

    def test_cycle_timing_is_frozen(self) -> None:
        timing = CycleTiming(
            next_time=datetime(2026, 6, 18, 14, 17, 0),
            wait_seconds=570.0,
            random_offset=120,
        )

        try:
            timing.wait_seconds = 600  # type: ignore[misc]
            assert False, "应抛 FrozenInstanceError"
        except Exception:
            pass
