"""
API模块单元测试
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from alpha_trading_bot.api import create_bot, start_bot, stop_bot, get_bot_status, list_bots, delete_bot
from alpha_trading_bot.core import TradingBot

@pytest.mark.asyncio
class TestBotAPI:
    """测试机器人API"""

    async def test_create_bot_success(self):
        """测试成功创建机器人"""
        # 模拟TradingBot的初始化方法
        with patch.object(TradingBot, 'initialize', return_value=True):
            bot = await create_bot(
                bot_id="test-bot",
                name="Test Bot",
                config={
                    "max_position_size": 0.01,
                    "leverage": 10,
                    "test_mode": True
                }
            )
            assert isinstance(bot, TradingBot)
            assert bot.config.name == "Test Bot"

    async def test_create_bot_duplicate(self):
        """测试重复创建机器人"""
        with patch.object(TradingBot, 'initialize', return_value=True):
            # 创建第一个机器人
            await create_bot(bot_id="duplicate-bot")

            # 尝试创建相同ID的机器人
            with pytest.raises(ValueError, match="机器人 duplicate-bot 已存在"):
                await create_bot(bot_id="duplicate-bot")

    async def test_create_bot_init_failure(self):
        """测试机器人初始化失败"""
        with patch.object(TradingBot, 'initialize', return_value=False):
            with pytest.raises(RuntimeError, match="机器人初始化失败"):
                await create_bot(bot_id="fail-bot")

    async def test_start_bot_success(self):
        """测试成功启动机器人"""
        with patch.object(TradingBot, 'initialize', return_value=True):
            # 创建机器人
            bot = await create_bot(bot_id="start-test-bot")

            # 模拟start方法
            with patch.object(bot, 'start', new_callable=AsyncMock):
                # 启动机器人
                await start_bot("start-test-bot")
                bot.start.assert_called_once()

    async def test_start_bot_not_exists(self):
        """测试启动不存在的机器人"""
        with pytest.raises(ValueError, match="机器人 not-exist-bot 不存在"):
            await start_bot("not-exist-bot")

    async def test_stop_bot_success(self):
        """测试成功停止机器人"""
        with patch.object(TradingBot, 'initialize', return_value=True):
            # 创建机器人
            bot = await create_bot(bot_id="stop-test-bot")

            # 模拟stop方法
            with patch.object(bot, 'stop', new_callable=AsyncMock):
                # 停止机器人
                await stop_bot("stop-test-bot")
                bot.stop.assert_called_once()

    async def test_stop_bot_not_exists(self):
        """测试停止不存在的机器人"""
        with pytest.raises(ValueError, match="机器人 not-exist-bot 不存在"):
            await stop_bot("not-exist-bot")

    async def test_get_bot_status(self):
        """测试获取机器人状态"""
        with patch.object(TradingBot, 'initialize', return_value=True):
            # 创建机器人
            bot = await create_bot(bot_id="status-test-bot")

            # 获取状态
            status = await get_bot_status("status-test-bot")
            assert 'name' in status
            assert 'initialized' in status
            assert 'uptime' in status
            assert status['name'] == "status-test-bot"

    async def test_get_bot_status_not_exists(self):
        """测试获取不存在机器人的状态"""
        with pytest.raises(ValueError, match="机器人 not-exist-bot 不存在"):
            await get_bot_status("not-exist-bot")

    async def test_list_bots_empty(self):
        """测试空机器人列表"""
        bots = await list_bots()
        assert bots == []

    async def test_list_bots_with_bots(self):
        """测试有机器人的列表"""
        with patch.object(TradingBot, 'initialize', return_value=True):
            # 创建多个机器人
            await create_bot(bot_id="bot1", name="Bot 1")
            await create_bot(bot_id="bot2", name="Bot 2")

            # 获取列表
            bots = await list_bots()
            assert len(bots) == 2
            assert any(bot['bot_id'] == 'bot1' for bot in bots)
            assert any(bot['bot_id'] == 'bot2' for bot in bots)

    async def test_delete_bot_success(self):
        """测试成功删除机器人"""
        with patch.object(TradingBot, 'initialize', return_value=True):
            # 创建机器人
            bot = await create_bot(bot_id="delete-test-bot")

            # 模拟cleanup方法
            with patch.object(bot, 'cleanup', new_callable=AsyncMock):
                # 删除机器人
                await delete_bot("delete-test-bot")
                bot.cleanup.assert_called_once()

                # 验证机器人已被删除
                with pytest.raises(ValueError):
                    await get_bot_status("delete-test-bot")

    async def test_delete_bot_not_exists(self):
        """测试删除不存在的机器人"""
        with pytest.raises(ValueError, match="机器人 not-exist-bot 不存在"):
            await delete_bot("not-exist-bot")

    async def test_delete_bot_running(self):
        """测试删除运行中的机器人"""
        with patch.object(TradingBot, 'initialize', return_value=True):
            # 创建机器人
            bot = await create_bot(bot_id="delete-running-bot")

            # 模拟运行状态
            bot._running = True

            # 模拟stop和cleanup方法
            with patch.object(bot, 'stop', new_callable=AsyncMock):
                with patch.object(bot, 'cleanup', new_callable=AsyncMock):
                    # 删除机器人
                    await delete_bot("delete-running-bot")
                    bot.stop.assert_called_once()
                    bot.cleanup.assert_called_once()

class TestSyncWrapperFunctions:
    """测试同步包装函数"""

    def test_create_bot_sync(self):
        """测试同步创建机器人"""
        with patch.object(TradingBot, 'initialize', return_value=True):
            # 注意：这里使用同步版本的函数
            # 由于我们是在测试环境中，需要使用不同的导入方式
            from alpha_trading_bot.api.bot_api import create_bot_sync
            bot = create_bot_sync(
                bot_id="sync-test-bot",
                name="Sync Test Bot"
            )
            assert isinstance(bot, TradingBot)

    def test_get_bot_status_sync(self):
        """测试同步获取状态"""
        # 先创建机器人
        with patch.object(TradingBot, 'initialize', return_value=True):
            from alpha_trading_bot.api.bot_api import create_bot_sync, get_bot_status_sync
            create_bot_sync(bot_id="sync-status-bot")

            # 获取状态
            status = get_bot_status_sync("sync-status-bot")
            assert 'name' in status
            assert status['name'] == "sync-status-bot"