"""
Jev 快车道：熔断器 + 决策矩阵

- _CircuitBreaker: Jev 账户故障（欠费/封停）或瞬态网络故障 → 自动关闭快车道，
  全量流量回落现有 LLM 路径；故障恢复后自动探测恢复
- JevFastLane.decide(): 置信度门控级联决策（adopt / escalate）（Task 6 追加）
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple

from .config import JevFastLaneConfig
from .questions import JEV_QUESTIONS, build_state
from .typesafe_client import (
    ChoiceAnswer,
    JevClient,
    NoulAnswer,
    SystemOneResponse,
    TypeSafeAPIError,
    TypeSafeAuthError,
    TypeSafeTimeoutError,
)

logger = logging.getLogger(__name__)


class _CircuitBreaker:
    """快车道熔断器。

    状态机: CLOSED --(失败达阈值)--> OPEN --(冷却到期)-->
    HALF-OPEN(放行单次探测) --成功--> CLOSED / --失败--> OPEN(新冷却)

    故障分类:
    - TypeSafeAuthError (401/402 欠费/Key 无效/封停): 单次即 OPEN，长冷却
    - Timeout/APIError (瞬态): 连续 N 次后 OPEN，短冷却

    冷却到期由 is_open() 自动转 half_open 并返回 False（放行探测）；
    探测结果通过 record_success/record_failure 反馈。
    内存态：进程重启即全量重置（bot 进程干净重启，可接受）。
    """

    def __init__(
        self,
        config: JevFastLaneConfig,
        now: Optional[Callable[[], float]] = None,
    ) -> None:
        self._failure_threshold = config.failure_threshold
        self._cooldown = config.cooldown_seconds
        self._auth_cooldown = config.auth_cooldown_seconds
        self._now = now or time.monotonic

        self._state = "closed"  # closed / open / half_open
        self._consecutive_failures = 0
        self._open_until = 0.0
        self._last_reason = ""

    def is_open(self) -> bool:
        """快车道是否应被跳过。

        注意副作用：冷却到期时 open 自动转 half_open（返回 False 放行探测）。
        """
        if self._state == "open" and self._now() >= self._open_until:
            self._state = "half_open"
            logger.info(
                "[Jev熔断] HALF-OPEN: 冷却结束(上次原因: %s)，放行探测",
                self._last_reason[:80],
            )
        return self._state == "open"

    def record_success(self) -> None:
        """探测/正常调用成功：关闭熔断并重置连续失败计数。"""
        if self._state != "closed":
            logger.info("[Jev熔断] CLOSED: 调用成功，快车道恢复")
        self._state = "closed"
        self._consecutive_failures = 0

    def record_failure(self, error: Exception) -> None:
        """记录一次失败并驱动状态机（任何快车道调用失败都调用）。"""
        if isinstance(error, TypeSafeAuthError):
            # 欠费/封停：高频重试无意义 → 立即 OPEN + 长冷却
            self._open(auth_cooldown=True, reason=str(error))
            return
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold:
            self._open(auth_cooldown=False, reason=str(error))

    def _open(self, auth_cooldown: bool, reason: str) -> None:
        cooldown = self._auth_cooldown if auth_cooldown else self._cooldown
        kind = "欠费/鉴权失败" if auth_cooldown else "瞬态故障"
        self._state = "open"
        self._open_until = self._now() + cooldown
        self._last_reason = reason
        if auth_cooldown:
            self._consecutive_failures = 0
        logger.warning(
            "[Jev熔断] OPEN: %s，冷却 %ds，原因=%s",
            kind,
            cooldown,
            reason[:120],
        )

    @property
    def state(self) -> str:
        """当前状态（closed/open/half_open），供测试与监控。"""
        return self._state

    def get_stats(self) -> Dict[str, Any]:
        return {
            "circuit_state": self._state,
            "consecutive_failures": self._consecutive_failures,
        }
