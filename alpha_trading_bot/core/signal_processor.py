"""
信号处理器
处理AI信号解析、信号转换、决策逻辑
"""

import logging
from typing import Dict, Any, Optional, Tuple

from .position_manager import Position

logger = logging.getLogger(__name__)


class SignalProcessor:
    """信号处理器"""

    SELL_TO_HOLD = False

    VALID_SIGNALS = ["BUY", "HOLD", "SELL", "SHORT"]

    @classmethod
    def process(cls, signal: str) -> str:
        """处理原始信号"""
        signal = signal.upper()

        if signal == "SELL" and cls.SELL_TO_HOLD:
            logger.info("信号转换: SELL → HOLD")
            return "HOLD"

        if signal == "SHORT":
            logger.debug(f"信号处理: SHORT (趋势下跌苗头)")

        return signal

    @classmethod
    def validate(cls, signal: str) -> bool:
        """验证信号是否有效"""
        return signal.upper() in cls.VALID_SIGNALS

    @classmethod
    def should_open_long(cls, signal: str, has_position: bool) -> bool:
        """判断是否应该做多开仓"""
        return signal == "BUY" and not has_position

    @classmethod
    def should_open_short(
        cls, signal: str, has_position: bool, allow_short: bool = False
    ) -> bool:
        """判断是否应该做空开仓"""
        return signal == "SHORT" and not has_position and allow_short

    @classmethod
    def should_close_position(cls, signal: str, has_position: bool) -> bool:
        """判断是否应该平仓（SELL 信号专用）"""
        return signal == "SELL" and has_position

    @classmethod
    def should_reverse_position(
        cls, signal: str, position_side: str
    ) -> Tuple[bool, str]:
        """判断是否需要反向操作（先平仓再反向开仓）

        业务逻辑:
        - 做多仓位(long) + SHORT信号 → 建议先平仓
        - 做空仓位(short) + BUY信号 → 建议先平仓
        - 其他情况 → 不需要反向操作

        Returns:
            (should_reverse, reason)
        """
        if signal == "SHORT" and position_side == "long":
            return True, "做多仓位收到SHORT信号，建议先平仓"
        if signal == "BUY" and position_side == "short":
            return True, "做空仓位收到BUY信号，建议先平仓"
        return False, ""

    @classmethod
    def resolve_signal_with_position(
        cls, signal: str, has_position: bool, position_side: str = "none"
    ) -> Tuple[str, bool]:
        """根据持仓状态解析最终信号动作

        Returns:
            (resolved_signal, should_close_first)
        """
        signal = signal.upper()
        if not has_position:
            return signal, False

        if signal == "SELL":
            return "SELL", True

        should_reverse, reason = cls.should_reverse_position(signal, position_side)
        if should_reverse:
            logger.info(f"[信号解析] {reason}")
            return "SELL", True

        return signal, False

    @classmethod
    def should_open_position(cls, signal: str, has_position: bool) -> bool:
        """判断是否应该开仓（兼容旧接口）"""
        return signal in ["BUY", "SHORT"] and not has_position

    @classmethod
    def should_update_stop_loss(cls, signal: str, has_position: bool) -> bool:
        """判断是否应该更新止损"""
        return signal in ["BUY", "HOLD", "SHORT"] and has_position

    @classmethod
    def create_position_from_exchange(
        cls, position_data: Dict[str, Any]
    ) -> Optional[Position]:
        """从交易所数据创建Position对象"""
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
