"""
信号处理器
处理AI信号解析、信号转换、决策逻辑
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """持仓信息"""

    symbol: str
    side: str
    amount: float
    entry_price: float
    unrealized_pnl: float = 0.0


class SignalProcessor:
    """信号处理器"""

    # 信号转换规则
    SELL_TO_HOLD = False  # SELL信号是否强制转为HOLD（改为False，允许SELL信号通过）

    @classmethod
    def process(cls, signal: str) -> str:
        """
        处理原始信号

        Args:
            signal: 原始信号 (buy/hold/sell)

        Returns:
            处理后的信号
        """
        signal = signal.upper()

        if signal == "SELL" and cls.SELL_TO_HOLD:
            logger.info("信号转换: SELL → HOLD")
            return "HOLD"

        return signal

    @classmethod
    def validate(cls, signal: str) -> bool:
        """
        验证信号是否有效

        Args:
            signal: 信号字符串

        Returns:
            是否有效
        """
        return signal.upper() in ["BUY", "HOLD", "SELL"]

    @classmethod
    def should_open_position(cls, signal: str, has_position: bool) -> bool:
        """
        判断是否应该开仓

        Args:
            signal: 当前信号
            has_position: 是否有持仓

        Returns:
            是否开仓
        """
        return signal == "BUY" and not has_position

    @classmethod
    def should_update_stop_loss(cls, signal: str, has_position: bool) -> bool:
        """
        判断是否应该更新止损

        Args:
            signal: 当前信号
            has_position: 是否有持仓

        Returns:
            是否更新止损
        """
        return (signal == "BUY" or signal == "HOLD") and has_position

    @classmethod
    def create_position_from_exchange(
        cls, position_data: Dict[str, Any]
    ) -> Optional[Position]:
        """
        从交易所数据创建Position对象

        Args:
            position_data: 交易所返回的持仓数据

        Returns:
            Position对象或None
        """
        if not position_data:
            return None

        return Position(
            symbol=position_data["symbol"],
            side=position_data["side"],
            amount=position_data["amount"],
            entry_price=position_data["entry_price"],
            unrealized_pnl=position_data.get("unrealized_pnl", 0),
        )


def process_signal(signal: str) -> str:
    """便捷函数：处理信号"""
    return SignalProcessor.process(signal)


def validate_signal(signal: str) -> bool:
    """便捷函数：验证信号"""
    return SignalProcessor.validate(signal)
