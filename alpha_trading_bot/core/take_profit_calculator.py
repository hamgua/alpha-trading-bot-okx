"""止盈价计算模块"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class TakeProfitCalculator:
    """止盈价计算器

    止盈价统一基于入场价计算（与 PositionManager 保持一致）：
    - 做多: entry_price × (1 + percent)
    - 做空: entry_price × (1 - percent)
    """

    def __init__(self, config: Any = None):
        self._config = config
        self._take_profit_percent = 0.06
        if config and hasattr(config, "stop_loss"):
            self._take_profit_percent = config.stop_loss.take_profit_percent

    def calculate(self, entry_price: float, position_side: str) -> float:
        """计算止盈价（基于入场价）

        Args:
            entry_price: 入场价
            position_side: 持仓方向 (long/short)
        """
        percent = self._take_profit_percent
        if position_side == "short":
            take_profit_price = entry_price * (1 - percent)
            logger.info(
                f"[止盈计算-做空] 入场价={entry_price:.1f}, 止盈价={take_profit_price:.1f} "
                f"(价格下跌{percent * 100}%触发)"
            )
        else:
            take_profit_price = entry_price * (1 + percent)
            logger.info(
                f"[止盈计算-做多] 入场价={entry_price:.1f}, 止盈价={take_profit_price:.1f} "
                f"(价格上涨{percent * 100}%触发)"
            )
        return take_profit_price
