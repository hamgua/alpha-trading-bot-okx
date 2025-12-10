"""
API模块 - 提供对外的REST API和WebSocket接口
"""

from .client import TradingBotAPI, get_api
from .bot_api import (
    create_bot,
    start_bot,
    stop_bot,
    get_bot_status,
    list_bots,
    delete_bot
)

__all__ = [
    # API客户端
    'TradingBotAPI',
    'get_api',

    # 机器人管理API
    'create_bot',
    'start_bot',
    'stop_bot',
    'get_bot_status',
    'list_bots',
    'delete_bot'
]