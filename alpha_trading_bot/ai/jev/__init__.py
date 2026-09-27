"""
Jev (TypeSafe System One) 快车道

- config: JevFastLaneConfig（env 配置）
- typesafe_client: TypeSafe HTTP 客户端与类型化问答
- questions: 问题集与市场状态序列化
- fast_lane: 快车道决策（置信度门控 + 风险旗标 + 熔断器）
"""

from .config import JevFastLaneConfig
from .questions import JEV_QUESTIONS, build_state
from .typesafe_client import (
    ChoiceAnswer,
    JevClient,
    NoulAnswer,
    ScoreAnswer,
    SystemOneResponse,
    TypeSafeAPIError,
    TypeSafeAuthError,
    TypeSafeError,
    TypeSafeTimeoutError,
)

__all__ = [
    "JevFastLaneConfig",
    "ChoiceAnswer",
    "JevClient",
    "NoulAnswer",
    "ScoreAnswer",
    "SystemOneResponse",
    "TypeSafeAPIError",
    "TypeSafeAuthError",
    "TypeSafeError",
    "TypeSafeTimeoutError",
    "JEV_QUESTIONS",
    "build_state",
]
