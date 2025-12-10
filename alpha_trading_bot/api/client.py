"""
API客户端 - 提供REST API接口
"""

import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..core import TradingBot, BotConfig
from ..config import load_config
from ..utils import get_logger

logger = get_logger(__name__)

class TradingBotAPI:
    """交易机器人API客户端"""

    def __init__(self):
        self.bots: Dict[str, TradingBot] = {}
        self.logger = logger

    async def create_bot(self, bot_id: str, name: Optional[str] = None, config: Optional[Dict[str, Any]] = None) -> TradingBot:
        """创建交易机器人"""
        if bot_id in self.bots:
            raise ValueError(f"机器人 {bot_id} 已存在")

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

        # 保存到字典
        self.bots[bot_id] = bot

        self.logger.info(f"机器人 {bot_id} 创建成功")
        return bot

    async def start_bot(self, bot_id: str) -> None:
        """启动机器人"""
        if bot_id not in self.bots:
            raise ValueError(f"机器人 {bot_id} 不存在")

        bot = self.bots[bot_id]
        if bot.is_initialized() and not getattr(bot, '_running', False):
            await bot.start()
            self.logger.info(f"机器人 {bot_id} 已启动")
        else:
            raise RuntimeError("机器人无法启动")

    async def stop_bot(self, bot_id: str) -> None:
        """停止机器人"""
        if bot_id not in self.bots:
            raise ValueError(f"机器人 {bot_id} 不存在")

        bot = self.bots[bot_id]
        if getattr(bot, '_running', False):
            await bot.stop()
            self.logger.info(f"机器人 {bot_id} 已停止")

    async def get_bot_status(self, bot_id: str) -> Dict[str, Any]:
        """获取机器人状态"""
        if bot_id not in self.bots:
            raise ValueError(f"机器人 {bot_id} 不存在")

        bot = self.bots[bot_id]
        return bot.get_status()

    def list_bots(self) -> List[Dict[str, Any]]:
        """列出所有机器人"""
        bots = []
        for bot_id, bot in self.bots.items():
            status = bot.get_status()
            bots.append({
                'bot_id': bot_id,
                'name': status['name'],
                'running': status.get('running', False),
                'initialized': status['initialized'],
                'uptime': status['uptime']
            })
        return bots

    async def delete_bot(self, bot_id: str) -> None:
        """删除机器人"""
        if bot_id not in self.bots:
            raise ValueError(f"机器人 {bot_id} 不存在")

        bot = self.bots[bot_id]

        # 停止机器人
        if getattr(bot, '_running', False):
            await bot.stop()

        # 清理资源
        await bot.cleanup()

        # 从字典中移除
        del self.bots[bot_id]

        self.logger.info(f"机器人 {bot_id} 已删除")

# 创建全局API实例
_api_instance = None

async def get_api() -> TradingBotAPI:
    """获取API实例（单例）"""
    global _api_instance
    if _api_instance is None:
        _api_instance = TradingBotAPI()
    return _api_instance