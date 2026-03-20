"""止盈价计算模块"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class TakeProfitCalculator:
    """止盈价计算器"""

    def __init__(self, config: Any = None):
        self._config = config
        self._take_profit_percent = 0.06
        if config and hasattr(config, "stop_loss"):
            self._take_profit_percent = config.stop_loss.take_profit_percent

    def calculate(self, current_price: float, position_side: str) -> float:
        """计算止盈价"""
        percent = self._take_profit_percent
        if position_side == "short":
            take_profit_price = current_price * (1 - percent)
            logger.info(
                f"[执行-做空] 止盈价={take_profit_price:.1f} "
                f"(价格下跌{percent * 100}%触发)"
            )
        else:
            take_profit_price = current_price * (1 + percent)
            logger.info(
                f"[执行-做多] 止盈价={take_profit_price:.1f} "
                f"(价格上涨{percent * 100}%触发)"
            )
        return take_profit_price
