"""
Alpha Trading Bot - 精简版
"""

from .config.models import (
    Config,
    ExchangeConfig,
    TradingConfig,
    AIConfig,
    StopLossConfig,
)
from .core.bot import TradingBot, main

__version__ = "4.0.0"
__all__ = [
    "Config",
    "ExchangeConfig",
    "TradingConfig",
    "AIConfig",
    "StopLossConfig",
    "TradingBot",
    "main",
]
