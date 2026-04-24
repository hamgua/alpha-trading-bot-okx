"""轻量级运行时观测指标。"""

from dataclasses import dataclass, asdict
from threading import Lock
from typing import Dict


@dataclass
class RuntimeMetrics:
    """核心运行时指标。"""

    gemini_requests_total: int = 0
    gemini_success_total: int = 0
    gemini_failure_total: int = 0
    fallback_invocations_total: int = 0
    live_guard_block_total: int = 0


_METRICS = RuntimeMetrics()
_LOCK = Lock()


def record_gemini_request(success: bool) -> None:
    """记录 Gemini 请求结果。"""
    with _LOCK:
        _METRICS.gemini_requests_total += 1
        if success:
            _METRICS.gemini_success_total += 1
        else:
            _METRICS.gemini_failure_total += 1


def record_fallback_invocation() -> None:
    """记录 fallback 调用次数。"""
    with _LOCK:
        _METRICS.fallback_invocations_total += 1


def record_live_guard_block() -> None:
    """记录实盘闸门拦截次数。"""
    with _LOCK:
        _METRICS.live_guard_block_total += 1


def get_runtime_metrics() -> Dict[str, int]:
    """返回当前指标快照。"""
    with _LOCK:
        return asdict(_METRICS)


def get_runtime_slo_snapshot() -> Dict[str, float]:
    """返回 SLO 相关快照指标。"""
    with _LOCK:
        requests = float(_METRICS.gemini_requests_total)
        success_rate = (
            _METRICS.gemini_success_total / requests if requests > 0 else 1.0
        )
        fallback_rate = (
            _METRICS.fallback_invocations_total / requests if requests > 0 else 0.0
        )

        return {
            "gemini_success_rate": success_rate,
            "gemini_fallback_rate": fallback_rate,
            "live_guard_block_total": float(_METRICS.live_guard_block_total),
        }
