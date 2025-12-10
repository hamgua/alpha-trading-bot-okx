"""
交易所模块 - 处理与交易所的交互
"""

from .engine import TradingEngine, create_trading_engine
from .models import (
    ExchangeConfig, OrderResult, PositionInfo, TradeResult,
    RiskAssessmentResult, TickerData, OrderBookData, BalanceData,
    MarketOrderRequest, LimitOrderRequest, TPSLRequest
)
from .client import ExchangeClient
from .trading import (
    OrderManager,
    PositionManager,
    RiskManager,
    TradeExecutor
)

__all__ = [
    # 交易引擎
    'TradingEngine',
    'create_trading_engine',

    # 数据模型
    'ExchangeConfig',
    'OrderResult',
    'PositionInfo',
    'TradeResult',
    'RiskAssessmentResult',
    'TickerData',
    'OrderBookData',
    'BalanceData',
    'MarketOrderRequest',
    'LimitOrderRequest',
    'TPSLRequest',

    # 客户端
    'ExchangeClient',

    # 交易管理
    'OrderManager',
    'PositionManager',
    'RiskManager',
    'TradeExecutor'
]