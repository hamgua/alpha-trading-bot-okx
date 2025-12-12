#!/usr/bin/env python3
"""
Alpha Trading Bot 启动脚本
用于启动和管理交易机器人
"""

import asyncio
import argparse
import logging
import sys
from pathlib import Path

# 设置日志配置
def setup_logging(log_level=logging.INFO):
    """配置日志系统"""
    logging.basicConfig(
        level=log_level,
        format='[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('trading_bot.log', encoding='utf-8')
        ]
    )
    return logging.getLogger(__name__)


async def main_async(config_path=None, strategy_name=None):
    """异步主函数"""
    from alpha_trading_bot import create_bot, start_bot, stop_bot, load_config

    # 获取当前模块的logger
    logger = logging.getLogger(__name__)

    bot = None

    try:
        # 加载配置（如果有配置文件路径）
        if config_path:
            logger.info(f"使用配置文件: {config_path}")
            # 这里可以添加从配置文件加载特定配置的逻辑

        # 创建交易机器人实例（使用默认ID和配置）
        bot = await create_bot("main_bot", name="AlphaTradingBot")

        # 启动交易机器人
        await start_bot("main_bot")

    except KeyboardInterrupt:
        logger.info("\n用户中断程序，正在安全退出...")
        if bot:
            await stop_bot("main_bot")
        raise
    except Exception as e:
        logger.error(f"启动交易机器人失败: {e}")
        if bot:
            try:
                await stop_bot("main_bot")
            except:
                pass
        raise


def main():
    """主入口函数"""
    # 创建命令行参数解析器
    parser = argparse.ArgumentParser(
        description='Alpha Trading Bot - 智能量化交易机器人',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
    python main.py                          # 使用默认配置启动
    python main.py -c config.json           # 使用指定配置文件
    python main.py -s sma                   # 使用指定策略
    python main.py -d                       # 调试模式运行
    python main.py --help                   # 显示帮助信息
        """
    )

    # 添加命令行参数
    parser.add_argument(
        '-c', '--config',
        type=str,
        default=None,
        help='配置文件路径 (默认: 使用内置配置)'
    )

    parser.add_argument(
        '-s', '--strategy',
        type=str,
        default=None,
        help='指定要使用的策略名称'
    )

    parser.add_argument(
        '-d', '--debug',
        action='store_true',
        help='启用调试模式 (显示详细日志)'
    )

    parser.add_argument(
        '--version',
        action='version',
        version='Alpha Trading Bot v3.0.0'
    )

    # 解析命令行参数
    args = parser.parse_args()

    # 设置日志级别
    log_level = logging.DEBUG if args.debug else logging.INFO
    logger = setup_logging(log_level)

    try:
        logger.info("=" * 50)
        logger.info("Alpha Trading Bot 启动中...")
        logger.info("版本: v3.0.0")
        logger.info("=" * 50)

        # 检查配置文件是否存在
        if args.config and not Path(args.config).exists():
            logger.error(f"配置文件不存在: {args.config}")
            sys.exit(1)

        # 运行异步主函数
        asyncio.run(main_async(
            config_path=args.config,
            strategy_name=args.strategy
        ))

    except KeyboardInterrupt:
        logger.info("\n用户中断程序，正在安全退出...")
        # 清理已经在 main_async 中处理
        sys.exit(0)
    except Exception as e:
        logger.error(f"程序运行错误: {e}")
        if args.debug:
            logger.exception("详细错误信息:")
        sys.exit(1)


if __name__ == '__main__':
    main()