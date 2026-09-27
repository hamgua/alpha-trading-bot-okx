"""
Jev 熔断器单元测试（注入时钟驱动）
"""

from alpha_trading_bot.ai.jev.config import JevFastLaneConfig
from alpha_trading_bot.ai.jev.fast_lane import _CircuitBreaker
from alpha_trading_bot.ai.jev.typesafe_client import (
    TypeSafeAPIError,
    TypeSafeAuthError,
    TypeSafeTimeoutError,
)


class _Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def make_breaker(clock: _Clock) -> _CircuitBreaker:
    return _CircuitBreaker(
        JevFastLaneConfig(
            failure_threshold=3,
            cooldown_seconds=600,
            auth_cooldown_seconds=21600,
        ),
        now=clock,
    )


def test_starts_closed() -> None:
    breaker = make_breaker(_Clock())
    assert breaker.is_open() is False
    assert breaker.state == "closed"


def test_transient_failures_open_after_threshold() -> None:
    clock = _Clock()
    breaker = make_breaker(clock)
    breaker.record_failure(TypeSafeTimeoutError("t"))
    breaker.record_failure(TypeSafeAPIError("500"))
    assert breaker.is_open() is False  # 2 次失败未达阈值
    breaker.record_failure(TypeSafeAPIError("500"))
    assert breaker.is_open() is True  # 连续 3 次 → OPEN
    assert breaker.state == "open"


def test_transient_cooldown_duration() -> None:
    clock = _Clock(1000.0)
    breaker = make_breaker(clock)
    for _ in range(3):
        breaker.record_failure(TypeSafeAPIError("500"))
    clock.t = 1599.9
    assert breaker.is_open() is True  # 冷却期内
    clock.t = 1600.0
    assert breaker.is_open() is False  # 冷却到期 → half_open 放行探测
    assert breaker.state == "half_open"


def test_auth_failure_opens_immediately_with_long_cooldown() -> None:
    """欠费/封停（AuthError）：单次即 OPEN，长冷却 6h。"""
    clock = _Clock(1000.0)
    breaker = make_breaker(clock)
    breaker.record_failure(TypeSafeAuthError("402 payment required"))
    assert breaker.is_open() is True
    clock.t = 1000.0 + 600 + 600  # 远超瞬态冷却，但远短于 6h
    assert breaker.is_open() is True
    clock.t = 1000.0 + 21600
    assert breaker.is_open() is False  # 6h 后才放行探测
    assert breaker.state == "half_open"


def test_half_open_success_closes_and_resets() -> None:
    clock = _Clock(1000.0)
    breaker = make_breaker(clock)
    for _ in range(3):
        breaker.record_failure(TypeSafeAPIError("500"))
    clock.t = 1600.0
    assert breaker.is_open() is False  # → half_open
    breaker.record_success()
    assert breaker.state == "closed"
    # 重置后需再连续 3 次瞬态失败才重新 OPEN
    breaker.record_failure(TypeSafeAPIError("500"))
    assert breaker.is_open() is False


def test_half_open_transient_failure_reopens() -> None:
    """探测失败（瞬态）→ 重新 OPEN 新冷却，不能卡死在 half_open。
    Review Focus #5。"""
    clock = _Clock(1000.0)
    breaker = make_breaker(clock)
    for _ in range(3):
        breaker.record_failure(TypeSafeAPIError("500"))
    clock.t = 1600.0
    assert breaker.is_open() is False  # → half_open
    breaker.record_failure(TypeSafeTimeoutError("timeout"))
    assert breaker.state == "open"
    # 冷却从探测失败时刻重新计算
    clock.t = 1600.0 + 599.9
    assert breaker.is_open() is True
    clock.t = 1600.0 + 600.0
    assert breaker.is_open() is False
