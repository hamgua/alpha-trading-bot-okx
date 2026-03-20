"""
Core模块 - 交易机器人核心组件
"""

from .bot import TradingBot, main
from .trading_scheduler import TradingScheduler, create_scheduler
from .signal_processor import SignalProcessor, process_signal, validate_signal
from .position_manager import Position
from .position_manager import PositionManager, create_position_manager

__version__ = "1.0.0"

__all__ = [
    # 主类
    "TradingBot",
    "main",
    # 调度器
    "TradingScheduler",
    "create_scheduler",
    # 信号处理器
    "SignalProcessor",
    "Position",
    "process_signal",
    "validate_signal",
    # 仓位管理器
    "PositionManager",
    "create_position_manager",
]
