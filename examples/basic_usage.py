#!/usr/bin/env python3
"""
基础使用示例 - 展示如何使用Alpha Trading Bot OKX
"""

import asyncio
import logging
from alpha_trading_bot import (
    create_bot, start_bot, stop_bot, get_bot_status,
    setup_logging, load_config
)

async def basic_example():
    """基础使用示例"""
    # 设置日志
    setup_logging(level='INFO')

    # 加载配置
    config = load_config()
    print(f"当前配置的交易模式: {'测试模式' if config.trading.test_mode else '真实交易'}")

    # 创建机器人
    print("\n1. 创建交易机器人...")
    bot = await create_bot(
        bot_id="demo-bot",
        name="演示机器人",
        config={
            "max_position_size": 0.01,
            "leverage": 10,
            "test_mode": True,
            "cycle_interval": 15  # 15分钟一个周期
        }
    )
    print(f"机器人创建成功: {bot.config.name}")

    # 获取机器人状态
    print("\n2. 查看机器人状态...")
    status = await get_bot_status("demo-bot")
    print(f"机器人状态: {status}")

    # 启动机器人（运行一段时间后停止）
    print("\n3. 启动机器人...")
    await start_bot("demo-bot")
    print("机器人已启动，运行30秒后停止...")

    # 等待一段时间
    await asyncio.sleep(30)

    # 停止机器人
    print("\n4. 停止机器人...")
    await stop_bot("demo-bot")
    print("机器人已停止")

    print("\n演示完成！")

if __name__ == "__main__":
    # 运行异步示例
    asyncio.run(basic_example())