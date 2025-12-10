"""
Alpha Trading Bot OKX - 重构版统一API

基于模块化架构的OKX自动交易系统，提供简洁的顶层接口。
"""

__version__ = "3.0.0"
__author__ = "Alpha Trading Team"

# 简化API导出 - 只暴露最常用的接口
from .core import (
    BaseConfig,
    BaseComponent,
    SignalData,
    MarketData,
    TradingResult,
    TradingBot,
    BotConfig
)

from .api import (
    create_bot,
    start_bot,
    stop_bot,
    get_bot_status,
    TradingBotAPI
)

# 配置管理
from .config import ConfigManager, load_config

# 工具函数
from .utils import setup_logging, get_logger

__all__ = [
    # 核心类
    'BaseConfig',
    'BaseComponent',
    'SignalData',
    'MarketData',
    'TradingResult',
    'TradingBot',
    'BotConfig',

    # API接口
    'create_bot',
    'start_bot',
    'stop_bot',
    'get_bot_status',
    'TradingBotAPI',

    # 配置管理
    'ConfigManager',
    'load_config',

    # 工具函数
    'setup_logging',
    'get_logger',

    # 版本信息
    '__version__',
    '__author__'
]