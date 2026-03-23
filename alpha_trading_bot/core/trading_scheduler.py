"""
交易周期调度器
处理周期控制、随机偏移、时间计算
"""

import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Optional

from ..config.models import Config, TradingConfig

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
        min_wait = max(30, cycle_minutes * 30)

        current_minute = now.minute
        current_second = now.second
        minutes_to_next = cycle_minutes - (current_minute % cycle_minutes)
        if minutes_to_next == cycle_minutes:
            minutes_to_next = cycle_minutes

        seconds_to_next = minutes_to_next * 60 - current_second
        base_time = now + timedelta(seconds=seconds_to_next)

        random_offset = random.randint(-offset_range, offset_range)
        next_time = base_time + timedelta(seconds=random_offset)

        if next_time <= now:
            next_time = base_time + timedelta(seconds=offset_range)
            random_offset = offset_range

        wait_seconds = (next_time - now).total_seconds()

        if wait_seconds < min_wait:
            next_time = base_time + timedelta(seconds=min_wait)
            wait_seconds = min_wait
            random_offset = min_wait - seconds_to_next

        logger.info(
            f"[调度] 等待下一个周期: "
            f"周期={cycle_minutes}分钟, 偏移={random_offset}秒, 等待={wait_seconds:.0f}秒, "
            f"下次执行时间={next_time.strftime('%H:%M:%S')}"
        )
        await asyncio.sleep(wait_seconds)

    def get_next_cycle_seconds(self) -> float:
        """获取距离下一个周期的秒数"""
        now = datetime.now()
        cycle_minutes = self.trading_config.cycle_minutes
        offset_range = self.trading_config.random_offset_range
        min_wait = max(30, cycle_minutes * 30)

        current_minute = now.minute
        current_second = now.second
        minutes_to_next = cycle_minutes - (current_minute % cycle_minutes)
        if minutes_to_next == cycle_minutes:
            minutes_to_next = cycle_minutes

        seconds_to_next = minutes_to_next * 60 - current_second
        base_time = now + timedelta(seconds=seconds_to_next)

        random_offset = random.randint(-offset_range, offset_range)
        next_time = base_time + timedelta(seconds=random_offset)

        if next_time <= now:
            next_time = base_time + timedelta(seconds=offset_range)

        wait_seconds = (next_time - now).total_seconds()

        if wait_seconds < min_wait:
            next_time = base_time + timedelta(seconds=min_wait)
            wait_seconds = min_wait

        return wait_seconds


def create_scheduler(config: Optional[Config] = None) -> TradingScheduler:
    """创建调度器实例"""
    return TradingScheduler(config)
