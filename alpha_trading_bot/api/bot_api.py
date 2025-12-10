"""
机器人管理API - 提供简洁的机器人管理接口
"""

import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime

from ..core import TradingBot, BotConfig
from ..config import load_config
from ..utils import get_logger

logger = get_logger(__name__)

# 全局机器人数组
_bots: Dict[str, TradingBot] = {}

async def create_bot(
    bot_id: str,
    name: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None
) -> TradingBot:
    """
    创建交易机器人

    Args:
        bot_id: 机器人ID
        name: 机器人名称
        config: 配置字典

    Returns:
        TradingBot: 交易机器人实例
    """
    if bot_id in _bots:
        raise ValueError(f"机器人 {bot_id} 已存在")

    # 加载配置
    config_manager = load_config()

    # 创建机器人配置
    bot_config = BotConfig(
        name=name or f"Bot-{bot_id}",
        trading_enabled=True,
        max_position_size=config.get('max_position_size', 0.01) if config else 0.01,
        leverage=config.get('leverage', 10) if config else 10,
        test_mode=config.get('test_mode', True) if config else True,
        cycle_interval=config.get('cycle_interval', 15) if config else 15
    )

    # 创建机器人
    bot = TradingBot(bot_config)

    # 初始化
    success = await bot.initialize()
    if not success:
        raise RuntimeError("机器人初始化失败")

    # 保存到全局数组
    _bots[bot_id] = bot

    logger.info(f"机器人 {bot_id} 创建成功")
    return bot

async def start_bot(bot_id: str) -> None:
    """
    启动机器人

    Args:
        bot_id: 机器人ID
    """
    if bot_id not in _bots:
        raise ValueError(f"机器人 {bot_id} 不存在")

    bot = _bots[bot_id]
    if bot.is_initialized() and not getattr(bot, '_running', False):
        await bot.start()
        logger.info(f"机器人 {bot_id} 已启动")
    else:
        raise RuntimeError("机器人无法启动")

async def stop_bot(bot_id: str) -> None:
    """
    停止机器人

    Args:
        bot_id: 机器人ID
    """
    if bot_id not in _bots:
        raise ValueError(f"机器人 {bot_id} 不存在")

    bot = _bots[bot_id]
    if getattr(bot, '_running', False):
        await bot.stop()
        logger.info(f"机器人 {bot_id} 已停止")

async def get_bot_status(bot_id: str) -> Dict[str, Any]:
    """
    获取机器人状态

    Args:
        bot_id: 机器人ID

    Returns:
        Dict[str, Any]: 机器人状态
    """
    if bot_id not in _bots:
        raise ValueError(f"机器人 {bot_id} 不存在")

    bot = _bots[bot_id]
    return bot.get_status()

async def list_bots() -> List[Dict[str, Any]]:
    """
    列出所有机器人

    Returns:
        List[Dict[str, Any]]: 机器人列表
    """
    bots = []
    for bot_id, bot in _bots.items():
        status = bot.get_status()
        bots.append({
            'bot_id': bot_id,
            'name': status['name'],
            'running': status.get('running', False),
            'initialized': status['initialized'],
            'uptime': status['uptime']
        })
    return bots

async def delete_bot(bot_id: str) -> None:
    """
    删除机器人

    Args:
        bot_id: 机器人ID
    """
    if bot_id not in _bots:
        raise ValueError(f"机器人 {bot_id} 不存在")

    bot = _bots[bot_id]

    # 停止机器人
    if getattr(bot, '_running', False):
        await bot.stop()

    # 清理资源
    await bot.cleanup()

    # 从数组中移除
    del _bots[bot_id]

    logger.info(f"机器人 {bot_id} 已删除")

# 同步包装函数（便于非async环境使用）
def create_bot_sync(*args, **kwargs) -> TradingBot:
    """同步版本的create_bot"""
    return asyncio.run(create_bot(*args, **kwargs))

def start_bot_sync(bot_id: str) -> None:
    """同步版本的start_bot"""
    asyncio.run(start_bot(bot_id))

def stop_bot_sync(bot_id: str) -> None:
    """同步版本的stop_bot"""
    asyncio.run(stop_bot(bot_id))

def get_bot_status_sync(bot_id: str) -> Dict[str, Any]:
    """同步版本的get_bot_status"""
    return asyncio.run(get_bot_status(bot_id))

def list_bots_sync() -> List[Dict[str, Any]]:
    """同步版本的list_bots"""
    return asyncio.run(list_bots())

def delete_bot_sync(bot_id: str) -> None:
    """同步版本的delete_bot"""
    asyncio.run(delete_bot(bot_id))