"""
交易所数据模型
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional, List

class OrderStatus(Enum):
    """订单状态"""
    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REJECTED = "rejected"

class TradeSide(Enum):
    """交易方向"""
    BUY = "buy"
    SELL = "sell"
    LONG = "long"
    SHORT = "short"

@dataclass
class ExchangeConfig:
    """交易所配置"""
    exchange: str = "okx"
    api_key: str = ""
    secret: str = ""
    password: str = ""
    sandbox: bool = True
    symbol: str = "BTC/USDT:USDT"
    leverage: int = 10
    margin_mode: str = "cross"
    timeout: int = 30
    rate_limit: int = 100
    enable_rate_limit: bool = True

@dataclass
class MarketOrderRequest:
    """市价单请求"""
    symbol: str
    side: TradeSide
    amount: float
    reduce_only: bool = False
    client_order_id: Optional[str] = None

@dataclass
class LimitOrderRequest:
    """限价单请求"""
    symbol: str
    side: TradeSide
    amount: float
    price: float
    reduce_only: bool = False
    post_only: bool = False
    time_in_force: str = "GTC"  # Good Till Cancel
    client_order_id: Optional[str] = None

@dataclass
class TPSLRequest:
    """止盈止损请求"""
    symbol: str
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    trailing_stop: Optional[float] = None

@dataclass
class OrderResult:
    """订单结果"""
    success: bool
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    symbol: Optional[str] = None
    side: Optional[TradeSide] = None
    amount: float = 0.0
    price: float = 0.0
    filled_amount: float = 0.0
    average_price: float = 0.0
    status: Optional[OrderStatus] = None
    error_message: Optional[str] = None
    timestamp: datetime = None
    fee: float = 0.0

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

@dataclass
class PositionInfo:
    """仓位信息"""
    symbol: str
    side: TradeSide
    amount: float
    entry_price: float
    mark_price: float
    liquidation_price: float
    unrealized_pnl: float
    realized_pnl: float
    margin: float
    leverage: float
    timestamp: datetime = None
    # 多级止盈相关字段
    tp_levels_hit: List[int] = None  # 已触发的止盈级别列表
    tp_orders_info: Dict[str, Any] = None  # 止盈订单信息 {order_id: {level: int, amount: float, price: float}}
    original_amount: float = 0.0  # 原始仓位数量（用于计算部分平仓比例）

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.tp_levels_hit is None:
            self.tp_levels_hit = []
        if self.tp_orders_info is None:
            self.tp_orders_info = {}
        if self.original_amount == 0.0:
            self.original_amount = self.amount

@dataclass
class TradeResult:
    """交易结果"""
    success: bool
    order_id: Optional[str] = None
    error_message: Optional[str] = None
    filled_amount: float = 0.0
    average_price: float = 0.0
    fee: float = 0.0
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

@dataclass
class RiskAssessmentResult:
    """风险评估结果"""
    can_execute: bool
    reason: str
    risk_score: float = 0.0
    daily_loss: float = 0.0
    position_risk: float = 0.0
    market_risk: float = 0.0
    ai_confidence: float = 0.0

@dataclass
class TickerData:
    """行情数据"""
    symbol: str
    bid: float
    ask: float
    last: float
    high: float
    low: float
    volume: float
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

@dataclass
class OrderBookData:
    """订单簿数据"""
    symbol: str
    bids: List[List[float]]  # [[price, amount], ...]
    asks: List[List[float]]  # [[price, amount], ...]
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

@dataclass
class BalanceData:
    """余额数据"""
    total: float
    free: float
    used: float
    currency: str
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()