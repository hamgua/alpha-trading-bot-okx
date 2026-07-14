"""
订单数据模型
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class OrderStatus(Enum):
    """订单状态"""

    OPEN = "open"
    CLOSED = "closed"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class OrderIntent(Enum):
    """订单意图。"""

    OPEN = "open"
    CLOSE = "close"
    REDUCE = "reduce"


@dataclass
class OrderResult:
    """订单执行结果"""

    order_id: str
    status: OrderStatus
    symbol: str
    side: str
    order_type: str

    # 成交信息
    requested_amount: float
    filled_amount: float
    remaining_amount: float
    average_price: float

    # 错误信息
    error_message: Optional[str] = None
    error_code: Optional[str] = None

    @property
    def is_fully_filled(self) -> bool:
        """是否完全成交"""
        return self.remaining_amount == 0

    @property
    def is_partially_filled(self) -> bool:
        """是否部分成交"""
        return (
            self.filled_amount > 0
            and self.remaining_amount > 0
            and self.filled_amount < self.requested_amount
        )

    @property
    def has_fill(self) -> bool:
        """是否至少成交。"""
        return self.filled_amount > 0

    @property
    def is_terminal(self) -> bool:
        """订单是否已进入终态。"""
        return self.status in {
            OrderStatus.CLOSED,
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        }

    @property
    def is_rejected(self) -> bool:
        """是否被拒绝"""
        return self.status == OrderStatus.REJECTED

    @property
    def is_success(self) -> bool:
        """是否成功（至少部分成交）"""
        return self.filled_amount > 0 and self.status not in [
            OrderStatus.REJECTED,
            OrderStatus.CANCELED,
        ]


@dataclass
class StopOrderResult:
    """止损单执行结果"""

    order_id: str
    stop_price: float
    amount: float
    status: OrderStatus
    error_message: Optional[str] = None

    @property
    def is_success(self) -> bool:
        """是否成功创建"""
        return self.status == OrderStatus.OPEN and self.order_id != ""
