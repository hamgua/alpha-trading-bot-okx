#!/usr/bin/env python3
"""
Alpha Trading Bot - 统一入口

支持两种运行模式:
  --mode standard   标准模式 (TradingBot v1，生产默认)
  --mode adaptive   自适应模式 (AdaptiveTradingBot v2，含 ML 学习)

环境变量:
  BOT_MODE=standard|adaptive  等价于 --mode

示例:
  python main.py                     # 默认 standard 模式
  python main.py --mode adaptive     # 自适应模式
  BOT_MODE=adaptive python main.py   # 通过环境变量切换
"""

import argparse
import asyncio
import logging
import os
import re
import sys
import traceback
from logging.handlers import TimedRotatingFileHandler

from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# 创建logs目录
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)

log_file = os.path.join(log_dir, "alpha-trading-bot-okx.log")

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(),  # 控制台输出
        TimedRotatingFileHandler(
            log_file,
            when="midnight",
            interval=1,
            backupCount=30,  # 保留30天日志
            encoding="utf-8",
        ),
    ],
)

logger = logging.getLogger(__name__)


def _redact_sensitive_text(text: str) -> str:
    """对异常输出进行敏感信息脱敏。"""
    redacted = text
    patterns = [
        re.compile(r"(bearer\s+)[a-z0-9._\-]+", re.IGNORECASE),
        re.compile(r"(api[_-]?key\s*[:=]\s*)[a-z0-9._\-]+", re.IGNORECASE),
        re.compile(r"(google[_-]?api[_-]?key\s*[:=]\s*)[a-z0-9._\-]+", re.IGNORECASE),
        re.compile(r"(gemini[_-]?api[_-]?key\s*[:=]\s*)[a-z0-9._\-]+", re.IGNORECASE),
    ]
    for pattern in patterns:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    return redacted


# 全局异常处理器 - 捕获所有未处理的异常
def global_exception_handler(exc_type, exc_value, exc_traceback) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    sanitized_trace = _redact_sensitive_text(
        "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    )
    sanitized_message = _redact_sensitive_text(str(exc_value))
    logger.critical(
        f"未捕获的致命异常: {exc_type.__name__}: {sanitized_message}\n"
        + sanitized_trace
    )


sys.excepthook = global_exception_handler

VALID_MODES = ["standard", "adaptive"]


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Alpha Trading Bot - AI驱动的加密货币交易系统"
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=VALID_MODES,
        default=None,
        help="运行模式: standard (v1, 默认) 或 adaptive (v2, 含 ML 学习)",
    )
    parser.add_argument("--symbol", type=str, help="交易品种 (例如: BTC/USDT:USDT)")
    parser.add_argument(
        "--real-trading",
        action="store_true",
        help="显式确认实盘交易（将 TEST_MODE=false 且 REAL_TRADING_CONFIRMED=true）",
    )
    return parser.parse_args()


def get_bot_mode(args: argparse.Namespace) -> str:
    """确定运行模式: 命令行参数 > 环境变量 > 默认值"""
    if args.mode:
        return args.mode
    return os.getenv("BOT_MODE", "standard").lower()


async def main() -> None:
    """统一主入口"""
    args = parse_args()
    mode = get_bot_mode(args)

    if mode not in VALID_MODES:
        logger.error(f"无效的运行模式: {mode}, 可选: {VALID_MODES}")
        return

    print("=" * 60)
    print("Alpha Trading Bot - AI驱动的加密货币交易系统")
    print("=" * 60)

    if mode == "standard":
        print("[模式] standard (标准模式 v1)")
        print("系统能力:")
        print("  - 多源AI信号: Kimi, DeepSeek, Qwen, OpenAI, Gemini 智能融合")
        print("  - 高级融合策略: 加权平均/共识决策/多数表决")
        print("  - 15分钟交易周期 + 随机偏移 (防风控检测)")
        print("  - 智能仓位管理 + 动态止损止盈")
        print("  - 实时风控 + 组合资产保护")
    else:
        print("[模式] adaptive (自适应模式 v2)")
        print("核心特性:")
        print("  - 市场环境感知 - 实时检测8种市场状态")
        print("  - 策略自动选择 - 根据市场状态动态切换策略")
        print("  - 风险边界控制 - 5%硬止损 + 动态熔断")
        print("  - 自适应学习 - 基于交易结果自动优化策略权重")
        print("  - 后台优化 - 每6h贝叶斯参数优化 + ML 回测学习")

    print("=" * 60)

    from alpha_trading_bot.config.models import Config

    config = Config.from_env()

    if args.real_trading:
        config.trading.test_mode = False
        config.trading.real_trading_confirmed = True
        if config.trading.runtime_environment not in ["prod", "production"]:
            config.trading.runtime_environment = "prod"
        logger.warning("[实盘确认] 已启用 --real-trading，系统将按实盘前置条件执行")

    # 覆盖交易品种
    if args.symbol:
        config.exchange.symbol = args.symbol
        print(f"[交易对] {args.symbol}")

    # 根据模式创建 bot
    if mode == "standard":
        from alpha_trading_bot.core.bot import TradingBot

        bot = TradingBot(config)
    else:
        from alpha_trading_bot.core.adaptive_bot import AdaptiveTradingBot

        bot = AdaptiveTradingBot(config)

    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\n收到停止信号，正在退出...")
        if mode == "standard":
            await bot.stop()
        else:
            bot._running = False
            await bot.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序退出")
