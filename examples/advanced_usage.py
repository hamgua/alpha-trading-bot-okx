#!/usr/bin/env python3
"""
高级使用示例 - 展示更复杂的功能
"""

import asyncio
import logging
from datetime import datetime
from alpha_trading_bot import (
    create_bot, start_bot, stop_bot, list_bots,
    setup_logging, load_config, TradingBotAPI
)
from alpha_trading_bot.config import ConfigManager
from alpha_trading_bot.core import BotConfig

class BotManager:
    """机器人管理器示例"""

    def __init__(self):
        self.bots = {}
        self.logger = logging.getLogger(__name__)

    async def create_strategy_bots(self):
        """创建不同策略的机器人"""
        print("\n1. 创建不同策略的机器人...")

        # 保守型策略机器人
        conservative_bot = await create_bot(
            bot_id="conservative-bot",
            name="保守型策略机器人",
            config={
                "max_position_size": 0.005,
                "leverage": 5,
                "test_mode": True,
                "cycle_interval": 15
            }
        )
        self.bots["conservative"] = conservative_bot
        print("✓ 保守型策略机器人创建完成")

        # 中等型策略机器人
        moderate_bot = await create_bot(
            bot_id="moderate-bot",
            name="中等型策略机器人",
            config={
                "max_position_size": 0.01,
                "leverage": 10,
                "test_mode": True,
                "cycle_interval": 10
            }
        )
        self.bots["moderate"] = moderate_bot
        print("✓ 中等型策略机器人创建完成")

        # 激进型策略机器人
        aggressive_bot = await create_bot(
            bot_id="aggressive-bot",
            name="激进型策略机器人",
            config={
                "max_position_size": 0.02,
                "leverage": 15,
                "test_mode": True,
                "cycle_interval": 5
            }
        )
        self.bots["aggressive"] = aggressive_bot
        print("✓ 激进型策略机器人创建完成")

    async def start_all_bots(self):
        """启动所有机器人"""
        print("\n2. 启动所有机器人...")
        tasks = []

        for bot_id in ["conservative-bot", "moderate-bot", "aggressive-bot"]:
            task = asyncio.create_task(start_bot(bot_id))
            tasks.append(task)

        await asyncio.gather(*tasks)
        print("✓ 所有机器人启动完成")

    async def monitor_bots(self, duration: int = 60):
        """监控机器人状态"""
        print(f"\n3. 监控机器人状态（{duration}秒）...")
        start_time = datetime.now()

        while (datetime.now() - start_time).seconds < duration:
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 机器人状态:")

            # 获取所有机器人列表
            bots = await list_bots()

            for bot_info in bots:
                bot_id = bot_info['bot_id']
                status = await get_bot_status(bot_id)

                print(f"  📊 {bot_info['name']}:")
                print(f"     运行状态: {'🟢 运行中' if status.get('running') else '🔴 已停止'}")
                print(f"     运行时间: {status['uptime']:.1f} 秒")
                print(f"     交易次数: {status.get('trades_executed', 0)}")
                print(f"     盈亏: {status.get('profit_loss', 0):.4f} USDT")

            # 每10秒更新一次
            await asyncio.sleep(10)

    async def stop_all_bots(self):
        """停止所有机器人"""
        print("\n4. 停止所有机器人...")
        tasks = []

        for bot_id in ["conservative-bot", "moderate-bot", "aggressive-bot"]:
            task = asyncio.create_task(stop_bot(bot_id))
            tasks.append(task)

        await asyncio.gather(*tasks)
        print("✓ 所有机器人已停止")

    async def performance_analysis(self):
        """性能分析"""
        print("\n5. 性能分析...")

        total_trades = 0
        total_pnl = 0.0
        bot_stats = []

        for bot_id in ["conservative-bot", "moderate-bot", "aggressive-bot"]:
            status = await get_bot_status(bot_id)
            trades = status.get('trades_executed', 0)
            pnl = status.get('profit_loss', 0.0)

            total_trades += trades
            total_pnl += pnl

            bot_stats.append({
                'name': status['name'],
                'trades': trades,
                'pnl': pnl,
                'avg_pnl_per_trade': pnl / trades if trades > 0 else 0
            })

        print(f"\n📈 总体统计:")
        print(f"   总交易次数: {total_trades}")
        print(f"   总盈亏: {total_pnl:.4f} USDT")
        print(f"   平均每笔盈亏: {total_pnl / total_trades if total_trades > 0 else 0:.4f} USDT")

        print(f"\n📊 各机器人表现:")
        for stat in bot_stats:
            print(f"   {stat['name']}:")
            print(f"     交易次数: {stat['trades']}")
            print(f"     盈亏: {stat['pnl']:.4f} USDT")
            print(f"     平均每笔: {stat['avg_pnl_per_trade']:.4f} USDT")

async def advanced_example():
    """高级使用示例"""
    # 设置日志
    setup_logging(level='INFO')

    # 创建机器人管理器
    manager = BotManager()

    try:
        # 1. 创建多个策略机器人
        await manager.create_strategy_bots()

        # 2. 启动所有机器人
        await manager.start_all_bots()

        # 3. 监控机器人（60秒）
        await manager.monitor_bots(duration=60)

        # 4. 停止所有机器人
        await manager.stop_all_bots()

        # 5. 性能分析
        await manager.performance_analysis()

        print("\n✅ 高级示例完成！")

    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        # 确保机器人被正确停止
        await manager.stop_all_bots()

if __name__ == "__main__":
    # 运行高级示例
    asyncio.run(advanced_example())