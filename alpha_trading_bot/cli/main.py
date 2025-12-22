#!/usr/bin/env python3
"""
Alpha Trading Bot OKX - 命令行接口
"""

import argparse
import asyncio
import sys
from pathlib import Path

# 将项目根目录添加到Python路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from alpha_trading_bot import create_bot, start_bot, stop_bot, get_bot_status
from alpha_trading_bot.config import load_config
from alpha_trading_bot.utils import setup_logging

async def run_bot(args):
    """运行交易机器人"""
    try:
        # 设置日志
        setup_logging(level=args.log_level)

        # 加载配置
        config = load_config()

        # 创建机器人
        bot_config = {
            'max_position_size': args.max_position_size,
            'leverage': args.leverage,
            'test_mode': not args.real_trading,
            'cycle_interval': args.cycle_interval,
            'random_offset_enabled': args.random_offset_enabled,
            'random_offset_range': args.random_offset_range
        }

        bot = await create_bot(
            bot_id=args.bot_id,
            name=args.name,
            config=bot_config
        )

        # 启动机器人
        await start_bot(args.bot_id)

        print(f"机器人 {args.bot_id} 正在运行...")
        print("按 Ctrl+C 停止")

        # 保持运行
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n正在停止机器人...")
            await stop_bot(args.bot_id)
            print("机器人已停止")

    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)

def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="Alpha Trading Bot OKX - 加密货币交易机器人",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 启动测试模式机器人
  python -m alpha_trading_bot run --bot-id test-bot

  # 启动真实交易机器人（谨慎使用）
  python -m alpha_trading_bot run --bot-id live-bot --real-trading

  # 自定义参数
  python -m alpha_trading_bot run --bot-id my-bot --max-position-size 0.02 --leverage 5

  # 自定义交易周期和随机偏移（规避风控检测）
  python -m alpha_trading_bot run --bot-id my-bot --cycle-interval 15 --random-offset-range 300

  # 禁用随机偏移（固定周期执行）
  python -m alpha_trading_bot run --bot-id my-bot --no-random-offset
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='可用命令')

    # run命令
    run_parser = subparsers.add_parser('run', help='运行交易机器人')
    run_parser.add_argument('--bot-id', required=True, help='机器人ID')
    run_parser.add_argument('--name', help='机器人名称')
    run_parser.add_argument('--max-position-size', type=float, default=0.01,
                           help='最大仓位大小 (默认: 0.01)')
    run_parser.add_argument('--leverage', type=int, default=10,
                           help='杠杆倍数 (默认: 10)')
    run_parser.add_argument('--cycle-interval', type=int, default=15,
                           help='交易周期（分钟）(默认: 15)')
    run_parser.add_argument('--random-offset-enabled', action='store_true', default=True,
                           help='启用随机时间偏移（默认: 开启）')
    run_parser.add_argument('--no-random-offset', dest='random_offset_enabled', action='store_false',
                           help='禁用随机时间偏移')
    run_parser.add_argument('--random-offset-range', type=int, default=180,
                           help='随机偏移范围（秒，默认: ±180秒=±3分钟）')
    run_parser.add_argument('--real-trading', action='store_true',
                           help='启用真实交易（默认: 测试模式）')
    run_parser.add_argument('--log-level', default='INFO',
                           choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                           help='日志级别 (默认: INFO)')

    # status命令
    status_parser = subparsers.add_parser('status', help='查看机器人状态')
    status_parser.add_argument('--bot-id', help='机器人ID（不指定则显示所有）')

    # stop命令
    stop_parser = subparsers.add_parser('stop', help='停止机器人')
    stop_parser.add_argument('--bot-id', required=True, help='机器人ID')

    # config命令
    config_parser = subparsers.add_parser('config', help='查看配置')
    config_parser.add_argument('--section', help='配置段')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == 'run':
            asyncio.run(run_bot(args))

        elif args.command == 'status':
            # 这里可以添加查看状态的逻辑
            print("状态功能开发中...")

        elif args.command == 'stop':
            # 这里可以添加停止机器人的逻辑
            print("停止功能开发中...")

        elif args.command == 'config':
            # 加载并显示配置
            config = load_config()
            if args.section:
                print(f"{args.section} 配置:")
                print(getattr(config, args.section).__dict__)
            else:
                print("所有配置:")
                print(config.get_all())

    except KeyboardInterrupt:
        print("\n操作被用户中断")
        sys.exit(0)
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()