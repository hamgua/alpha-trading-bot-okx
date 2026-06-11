"""
交易周期调度器
处理周期控制、随机偏移、时间计算
"""

import asyncio
import logging
import random
from datetime import datetime
from typing import Optional

from ..config.models import Config, TradingConfig
from .cycle_timing import calculate_cycle_timing

logger = logging.getLogger(__name__)


class TradingScheduler:
    """交易周期调度器"""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config.from_env()
        self.trading_config: TradingConfig = self.config.trading

    async def wait_for_next_cycle(self, first_run: bool = False) -> None:
        """
        等待到下一个周期

        Args:
            first_run: 是否是首次运行（首次不等待）
        """
        if first_run:
            logger.info("[调度] 首次运行，立即开始交易周期")
            return

        now = datetime.now()
        cycle_minutes = self.trading_config.cycle_minutes
        offset_range = self.trading_config.random_offset_range
        random_offset = random.randint(-offset_range, offset_range)
        timing = calculate_cycle_timing(now, cycle_minutes, offset_range, random_offset)

        logger.info(
            f"[调度] 等待下一个周期: "
            f"周期={cycle_minutes}分钟, 偏移={timing.random_offset}秒, "
            f"等待={timing.wait_seconds:.0f}秒, "
            f"下次执行时间={timing.next_time.strftime('%H:%M:%S')}"
        )
        await asyncio.sleep(timing.wait_seconds)

    def get_next_cycle_seconds(self) -> float:
        """获取距离下一个周期的秒数"""
        now = datetime.now()
        cycle_minutes = self.trading_config.cycle_minutes
        offset_range = self.trading_config.random_offset_range
        random_offset = random.randint(-offset_range, offset_range)
        timing = calculate_cycle_timing(now, cycle_minutes, offset_range, random_offset)
        return timing.wait_seconds


def create_scheduler(config: Optional[Config] = None) -> TradingScheduler:
    """创建调度器实例"""
    return TradingScheduler(config)
