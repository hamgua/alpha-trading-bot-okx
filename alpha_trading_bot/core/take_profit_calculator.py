"""止盈价计算模块"""

import logging

logger = logging.getLogger(__name__)


class TakeProfitCalculator:
    """止盈价计算器"""

    TAKE_PROFIT_PERCENT = 0.06

    @staticmethod
    def calculate(current_price: float, position_side: str) -> float:
        """计算止盈价"""
        if position_side == "short":
            take_profit_price = current_price * (
                1 - TakeProfitCalculator.TAKE_PROFIT_PERCENT
            )
            logger.info(
                f"[执行-做空] 止盈价={take_profit_price:.1f} "
                f"(价格下跌{TakeProfitCalculator.TAKE_PROFIT_PERCENT * 100}%触发)"
            )
        else:
            take_profit_price = current_price * (
                1 + TakeProfitCalculator.TAKE_PROFIT_PERCENT
            )
            logger.info(
                f"[执行-做多] 止盈价={take_profit_price:.1f} "
                f"(价格上涨{TakeProfitCalculator.TAKE_PROFIT_PERCENT * 100}%触发)"
            )
        return take_profit_price
