#!/usr/bin/env python3
"""
Alpha Trading Bot - 精简版入口

核心逻辑：
1. 15分钟周期执行（随机偏移±3分钟）
2. 调用AI获取信号（buy/hold/sell）
3. 信号处理与止损管理
"""

import asyncio
import logging
import os
from datetime import datetime
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# 创建logs目录
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)

# 日志文件名（日期格式）
log_file = os.path.join(
    log_dir, f"alpha-trading-bot-okx-{datetime.now().strftime('%Y%m%d')}.log"
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(),  # 控制台输出
        logging.FileHandler(log_file, encoding="utf-8"),  # 文件输出
    ],
)

logger = logging.getLogger(__name__)


async def main():
    """主入口"""
    from alpha_trading_bot import TradingBot

    print("=" * 60)
    print("Alpha Trading Bot - AI人工智能驱动的加密货币交易系统")
    print("=" * 60)
    print("系统能力:")
    print("  • 多源AI信号: Kimi, DeepSeek, Qwen, OpenAI 智能融合")
    print("  • 高级融合策略: 加权平均/共识决策/多数表决")
    print("  • 15分钟交易周期 + 随机偏移 (防风控检测)")
    print("  • 智能仓位管理 + 动态止损止盈")
    print("  • 实时风控 + 组合资产保护")
    print("交易流程:")
    print("  1. 市场分析: 价格/RSI/ATR/趋势/波动率多维指标")
    print("  2. AI决策: 多模型信号生成 (Buy/Hold/Sell + 置信度)")
    print("  3. 执行引擎: 智能开仓/平仓 + 止损订单管理")
    print("=" * 60)

    bot = TradingBot()
    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\n收到停止信号，正在退出...")
        await bot.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序退出")
