"""只读交易状态机视图。

第一阶段仅提供状态枚举和推导函数，不参与交易决策，不改变风控、订单或
持久化结构。后续可以用它治理日志和监控里的状态表达。
"""

from enum import Enum
from typing import Optional


class TradingLifecycleState(str, Enum):
    """交易生命周期状态。"""

    NO_POSITION = "no_position"
    OPEN = "open"
    STOP_PROTECTED = "stop_protected"
    TAKE_PROFIT_PROTECTED = "take_profit_protected"
    FULLY_PROTECTED = "fully_protected"


def derive_lifecycle_state(
    has_position: bool,
    stop_order_id: Optional[str] = None,
    take_profit_order_id: Optional[str] = None,
) -> TradingLifecycleState:
    """根据现有内存状态推导生命周期状态。"""
    if not has_position:
        return TradingLifecycleState.NO_POSITION
    if stop_order_id and take_profit_order_id:
        return TradingLifecycleState.FULLY_PROTECTED
    if stop_order_id:
        return TradingLifecycleState.STOP_PROTECTED
    if take_profit_order_id:
        return TradingLifecycleState.TAKE_PROFIT_PROTECTED
    return TradingLifecycleState.OPEN
