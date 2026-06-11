"""交易周期时间计算。

该模块只负责计算下一轮等待时间，不触碰调度副作用，便于回归测试锁定
15 分钟周期、随机偏移和最小等待时间的既有行为。
"""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class CycleTiming:
    """下一轮交易周期时间信息。"""

    next_time: datetime
    wait_seconds: float
    random_offset: int


def calculate_cycle_timing(
    now: datetime,
    cycle_minutes: int,
    offset_range: int,
    random_offset: int,
) -> CycleTiming:
    """计算下一轮执行时间，保持 TradingScheduler 原有行为。"""
    min_wait = max(30, cycle_minutes * 20)

    current_minute = now.minute
    current_second = now.second
    minutes_to_next = cycle_minutes - (current_minute % cycle_minutes)
    if minutes_to_next == cycle_minutes:
        minutes_to_next = cycle_minutes

    seconds_to_next = minutes_to_next * 60 - current_second
    base_time = now + timedelta(seconds=seconds_to_next)

    next_time = base_time + timedelta(seconds=random_offset)

    if next_time <= now:
        next_time = base_time + timedelta(seconds=offset_range)
        random_offset = offset_range

    wait_seconds = (next_time - now).total_seconds()

    if wait_seconds < min_wait:
        next_time = base_time + timedelta(seconds=min_wait)
        wait_seconds = min_wait
        random_offset = min_wait - seconds_to_next

    return CycleTiming(
        next_time=next_time,
        wait_seconds=wait_seconds,
        random_offset=random_offset,
    )
