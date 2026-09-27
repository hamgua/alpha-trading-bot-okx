"""
Jev (TypeSafe System One) 快车道

- config: JevFastLaneConfig（env 配置）
- typesafe_client: TypeSafe HTTP 客户端与类型化问答
- questions: 问题集与市场状态序列化
- fast_lane: 快车道决策（置信度门控 + 风险旗标 + 熔断器）
"""

from .config import JevFastLaneConfig

__all__ = [
    "JevFastLaneConfig",
]
