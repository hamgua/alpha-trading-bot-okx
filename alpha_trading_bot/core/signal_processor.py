"""
信号处理器
处理AI信号解析、信号转换、决策逻辑
"""

import logging
from typing import Dict, Any, Optional

from .position_manager import Position

logger = logging.getLogger(__name__)


class SignalProcessor:
    """信号处理器"""

    # 信号转换规则
    SELL_TO_HOLD = False  # SELL信号是否强制转为HOLD（改为False，允许SELL信号通过）

    # 信号定义
    VALID_SIGNALS = ["BUY", "HOLD", "SELL", "SHORT"]

    @classmethod
    def process(cls, signal: str) -> str:
        """
        处理原始信号

        Args:
            signal: 原始信号 (buy/hold/sell/short)

        Returns:
            处理后的信号
        """
        signal = signal.upper()

        # SELL 信号专用于平仓，不做转换
        if signal == "SELL" and cls.SELL_TO_HOLD:
            logger.info("信号转换: SELL → HOLD")
            return "HOLD"

        # SHORT 信号需要检查是否允许做空
        if signal == "SHORT":
            logger.debug(f"信号处理: SHORT (趋势下跌苗头)")

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
        return signal.upper() in cls.VALID_SIGNALS

    @classmethod
    def should_open_long(cls, signal: str, has_position: bool) -> bool:
        """
        判断是否应该做多开仓（BUY 信号）

        Args:
            signal: 当前信号
            has_position: 是否有持仓

        Returns:
            是否做多开仓
        """
        return signal == "BUY" and not has_position

    @classmethod
    def should_open_short(
        cls, signal: str, has_position: bool, allow_short: bool = False
    ) -> bool:
        """
        判断是否应该做空开仓（SHORT 信号）

        Args:
            signal: 当前信号
            has_position: 是否有持仓
            allow_short: 是否允许做空

        Returns:
            是否做空开仓
        """
        return signal == "SHORT" and not has_position and allow_short

    @classmethod
    def should_close_position(cls, signal: str, has_position: bool) -> bool:
        """
        判断是否应该平仓（SELL 信号专用）

        Args:
            signal: 当前信号
            has_position: 是否有持仓

        Returns:
            是否平仓
        """
        return signal == "SELL" and has_position

    @classmethod
    def should_open_position(cls, signal: str, has_position: bool) -> bool:
        """
        判断是否应该开仓（兼容旧接口）

        Args:
            signal: 当前信号
            has_position: 是否有持仓

        Returns:
            是否开仓（做多或做空）
        """
        # BUY 或 SHORT 都可以开仓
        return signal in ["BUY", "SHORT"] and not has_position

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
        # 有持仓时，BUY/HOLD/SHORT 都可以更新止损
        return signal in ["BUY", "HOLD", "SHORT"] and has_position

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
