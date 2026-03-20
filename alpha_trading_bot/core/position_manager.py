"""
仓位管理器
处理开仓、平仓、止损止盈、仓位计算
支持状态持久化和崩溃恢复
"""

import logging
from typing import Optional
from dataclasses import dataclass
from pathlib import Path

from ..config.models import Config
from .state_persistence import StatePersistence, create_state_persistence

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """持仓信息"""

    symbol: str
    side: str
    amount: float
    entry_price: float
    unrealized_pnl: float = 0.0


class PositionManager:
    """仓位管理器（支持持久化）"""

    def __init__(
        self,
        config: Optional[Config] = None,
        data_dir: Optional[Path] = None,
    ):
        self.config = config or Config.from_env()
        self._position: Optional[Position] = None
        self._entry_price: float = 0.0
        self._stop_order_id: Optional[str] = None
        self._last_stop_price: float = 0.0  # 上次设置的止损价，用于容错比较
        self._take_profit_order_id: Optional[str] = None  # 止盈单ID
        self._last_take_profit_price: float = 0.0  # 上次设置的止盈价

        # 初始化持久化管理器
        self._persistence = create_state_persistence(data_dir)

        # 从持久化存储恢复状态
        self._restore_from_persistence()

    def _restore_from_persistence(self) -> None:
        """从持久化存储恢复状态"""
        try:
            state = self._persistence.load_state()

            if state.position:
                self._position = Position(
                    symbol=state.position.symbol,
                    side=state.position.side,
                    amount=state.position.amount,
                    entry_price=state.position.entry_price,
                    unrealized_pnl=state.position.unrealized_pnl,
                )
                self._entry_price = state.position.entry_price
                self._stop_order_id = state.position.stop_order_id
                self._last_stop_price = state.position.last_stop_price  # 恢复上次止损价

                logger.info(
                    f"[持久化恢复] 已恢复持仓: {self._position.symbol} "
                    f"{self._position.side} {self._position.amount}@{self._position.entry_price}, "
                    f"止损单: {self._stop_order_id}, 上次止损价: {self._last_stop_price}"
                )
        except Exception as e:
            logger.warning(f"[持久化恢复] 恢复状态失败: {e}")

    @property
    def position(self) -> Optional[Position]:
        """获取当前持仓"""
        return self._position

    @property
    def position_side(self) -> str:
        """获取持仓方向 (long/short/none)"""
        if self._position is None:
            return "none"
        return self._position.side

    @property
    def entry_price(self) -> float:
        """获取入场价"""
        return self._entry_price

    @property
    def stop_order_id(self) -> Optional[str]:
        """获取止损单ID"""
        return self._stop_order_id

    @property
    def last_stop_price(self) -> float:
        """获取上次设置的止损价"""
        return self._last_stop_price

    def has_position(self) -> bool:
        """是否有持仓"""
        return self._position is not None and self._entry_price > 0

    def update_from_exchange(self, position_data: dict) -> None:
        """从交易所数据更新持仓信息（并持久化）"""
        if position_data:
            self._position = Position(
                symbol=position_data["symbol"],
                side=position_data["side"],
                amount=position_data["amount"],
                entry_price=position_data["entry_price"],
            )
            self._entry_price = position_data["entry_price"]

            # 持久化保存
            self._persistence.save_position(
                symbol=position_data["symbol"],
                side=position_data["side"],
                amount=position_data["amount"],
                entry_price=position_data["entry_price"],
                stop_order_id=self._stop_order_id,
                last_stop_price=self._last_stop_price,
            )

            logger.info(
                f"[仓位更新] 从交易所更新持仓: {self._position.symbol}, "
                f"方向:{self._position.side}, 数量:{self._position.amount}, 入场价:{self._position.entry_price}"
            )
        else:
            self._position = None
            logger.info("[仓位更新] 交易所返回无持仓信息")

    def calculate_stop_price(self, current_price: float) -> float:
        """
        计算止损价 (做多仓位)

        止损逻辑:
        1. 新建仓/亏损状态: 止损价 = 当前价格 × 99.5% (确保低于当前价)
        2. 盈利状态(当前价 > 入场价): 止损价 = 当前价格 × 99.8% (追踪止损)

        Args:
            current_price: 当前价格

        Returns:
            止损价 (做多) 或 0.0 (无效)
        """
        if self._position is None or self._entry_price == 0:
            return 0.0

        # 只处理做多仓位
        if self._position.side != "long":
            return 0.0

        # 新建仓/亏损状态: 止损价 = 当前价格 × 99.5%
        # 使用当前价格而非入场价，确保止损价低于当前价格，避免OKX拒绝
        if current_price <= self._entry_price:
            stop_percent = 0.005  # 0.5% 止损 = 99.5%
            stop_price = current_price * (1 - stop_percent)
            logger.debug(
                f"[止损计算-做多] 亏损/新建仓: 当前价({current_price}) <= 入场价({self._entry_price}), "
                f"止损比例:{stop_percent * 100}%, 止损价:{stop_price}"
            )
            return stop_price
        else:
            # 盈利状态: 止损价 = 当前价格 × 99.8% (追踪止损，只升不降)
            stop_percent = 0.002  # 0.2% 止损 = 99.8%
            stop_price = current_price * (1 - stop_percent)
            logger.debug(
                f"[止损计算-做多] 盈利状态: 当前价({current_price}) > 入场价({self._entry_price}), "
                f"止损比例:{stop_percent * 100}%, 止损价:{stop_price}"
            )
            return stop_price

    def calculate_short_stop_price(self, current_price: float) -> float:
        """
        计算做空仓位的止损价 (做空仓位)

        做空止损逻辑:
        - 做空赚钱时(价格下跌)，止损价 = 当前价格 × 100.5% (高于当前价)
        - 做空亏钱时(价格上涨)，止损价 = 当前价格 × 101.0% (追高)

        Args:
            current_price: 当前价格

        Returns:
            止损价 (做空) 或 0.0 (无效)
        """
        if self._position is None or self._entry_price == 0:
            return 0.0

        # 只处理做空仓位
        if self._position.side != "short":
            return 0.0

        # 做空赚钱时(价格下跌): 止损价 = 当前价格 × 100.5%
        if current_price >= self._entry_price:
            stop_percent = 0.005  # 0.5% 止损 = 100.5%
            stop_price = current_price * (1 + stop_percent)
            logger.debug(
                f"[止损计算-做空] 盈利(价格下跌): 当前价({current_price}) >= 入场价({self._entry_price}), "
                f"止损比例:{stop_percent * 100}%, 止损价:{stop_price}"
            )
            return stop_price
        else:
            # 做空亏钱时(价格上涨): 止损价 = 当前价格 × 101.0%
            stop_percent = 0.010  # 1.0% 止损 = 101.0%
            stop_price = current_price * (1 + stop_percent)
            logger.debug(
                f"[止损计算-做空] 亏损(价格上涨): 当前价({current_price}) < 入场价({self._entry_price}), "
                f"止损比例:{stop_percent * 100}%, 止损价:{stop_price}"
            )
            return stop_price

    def calculate_take_profit_price(self, current_price: float) -> float:
        """
        计算止盈价 (做多仓位)

        止盈逻辑:
        - 盈利达到目标时自动平仓

        Args:
            current_price: 当前价格

        Returns:
            止盈价 (做多)
        """
        if self._position is None or self._entry_price == 0:
            return 0.0

        # 只处理做多仓位
        if self._position.side != "long":
            return 0.0

        # 止盈价 = 入场价 × 1.06 (6% 止盈)
        take_profit_percent = 0.06
        take_profit_price = self._entry_price * (1 + take_profit_percent)
        logger.debug(
            f"[止盈计算-做多] 入场价:{self._entry_price}, 止盈比例:{take_profit_percent * 100}%, 止盈价:{take_profit_price}"
        )
        return take_profit_price

    def calculate_short_take_profit_price(self, current_price: float) -> float:
        """
        计算做空仓位的止盈价 (做空仓位)

        做空止盈逻辑:
        - 价格下跌到目标价位时自动平仓获利
        - 止盈价 = 入场价 × 0.94 (6% 止盈，即价格下跌6%)

        Args:
            current_price: 当前价格

        Returns:
            止盈价 (做空)
        """
        if self._position is None or self._entry_price == 0:
            return 0.0

        # 只处理做空仓位
        if self._position.side != "short":
            return 0.0

        # 止盈价 = 入场价 × 0.94 (6% 止盈，即价格下跌6%)
        take_profit_percent = 0.06
        take_profit_price = self._entry_price * (1 - take_profit_percent)
        logger.debug(
            f"[止盈计算-做空] 入场价:{self._entry_price}, 止盈比例:{take_profit_percent * 100}%, 止盈价:{take_profit_price}"
        )
        return take_profit_price

    def log_stop_loss_info(self, current_price: float, new_stop: float) -> None:
        """记录止损信息（支持做多和做空）"""
        if self._position is None:
            return

        side = self._position.side

        if side == "long":
            # 做多仓位的盈亏计算
            if current_price < self._entry_price:
                pnl = (current_price - self._entry_price) / self._entry_price * 100
                logger.info(
                    f"[止损监控-做多] 亏损持仓: 当前价={current_price}, 入场价={self._entry_price}, "
                    f"亏损={pnl:.2f}%, 止损价={new_stop}"
                )
            else:
                pnl = (current_price - self._entry_price) / self._entry_price * 100
                logger.info(
                    f"[止损监控-做多] 盈利持仓: 当前价={current_price}, 入场价={self._entry_price}, "
                    f"盈利={pnl:.2f}%, 止损价={new_stop}"
                )
        elif side == "short":
            # 做空仓位的盈亏计算 (与做多相反)
            if current_price > self._entry_price:
                pnl = (self._entry_price - current_price) / self._entry_price * 100
                logger.info(
                    f"[止损监控-做空] 亏损持仓: 当前价={current_price}, 入场价={self._entry_price}, "
                    f"亏损={pnl:.2f}%, 止损价={new_stop}"
                )
            else:
                pnl = (self._entry_price - current_price) / self._entry_price * 100
                logger.info(
                    f"[止损监控-做空] 盈利持仓: 当前价={current_price}, 入场价={self._entry_price}, "
                    f"盈利={pnl:.2f}%, 止损价={new_stop}"
                )

    def set_stop_order(self, stop_order_id: str, stop_price: float = 0.0) -> None:
        """设置止损单ID（并持久化）"""
        self._stop_order_id = stop_order_id
        if stop_price > 0:
            self._last_stop_price = stop_price

        # 持久化更新（同时保存 last_stop_price）
        if self._position:
            self._persistence.save_position(
                symbol=self._position.symbol,
                side=self._position.side,
                amount=self._position.amount,
                entry_price=self._entry_price,
                stop_order_id=stop_order_id,
                last_stop_price=self._last_stop_price,
            )

        logger.debug(f"[止损单] 设置止损单ID: {stop_order_id}, 止损价: {stop_price}")

    def set_take_profit_order(
        self, take_profit_order_id: str, take_profit_price: float = 0.0
    ) -> None:
        """设置止盈单ID（并持久化）"""
        self._take_profit_order_id = take_profit_order_id
        if take_profit_price > 0:
            self._last_take_profit_price = take_profit_price

        # 持久化更新
        if self._position:
            self._persistence.save_position(
                symbol=self._position.symbol,
                side=self._position.side,
                amount=self._position.amount,
                entry_price=self._entry_price,
                take_profit_order_id=take_profit_order_id,
                last_take_profit_price=self._last_take_profit_price,
            )

        logger.debug(
            f"[止盈单] 设置止盈单ID: {take_profit_order_id}, 止盈价: {take_profit_price}"
        )

    def needs_stop_order_recovery(self) -> bool:
        """检查是否需要恢复止损单（有持仓但无止损单ID）"""
        return self.has_position() and self._stop_order_id is None

    def get_stop_order_recovery_info(self) -> dict:
        """获取止损单恢复所需信息"""
        if not self.has_position():
            return {}
        return {
            "symbol": self._position.symbol if self._position else "",
            "side": self._position.side if self._position else "",
            "amount": self._position.amount if self._position else 0,
            "entry_price": self._entry_price,
            "stop_order_id": self._stop_order_id,
        }

    def clear_position(self) -> None:
        """清空持仓信息（并持久化）"""
        logger.info(f"[清仓] 清空持仓信息，原止损单: {self._stop_order_id}")

        # 记录平仓交易
        if self._position:
            self._persistence.record_trade(
                trade_type="close",
                symbol=self._position.symbol,
                side=self._position.side,
                amount=self._position.amount,
                price=self._entry_price,
                reason="manual_close",
            )

        self._position = None
        self._entry_price = 0.0
        self._stop_order_id = None
        self._last_stop_price = 0.0

        # 持久化清空
        self._persistence.clear_position()

    def update_position(
        self, amount: float, entry_price: float, symbol: str, side: str = "long"
    ) -> None:
        """
        更新持仓信息（开仓后调用，并持久化）

        Args:
            amount: 持仓数量
            entry_price: 入场价格
            symbol: 交易对
            side: 持仓方向 (long=做多, short=做空)
        """
        # 验证 side 参数
        if side not in ["long", "short"]:
            logger.warning(f"[持仓更新] 无效的持仓方向: {side}, 默认为做多")
            side = "long"

        self._entry_price = entry_price
        self._position = Position(
            symbol=symbol,
            side=side,
            amount=amount,
            entry_price=entry_price,
        )

        # 持久化保存
        self._persistence.save_position(
            symbol=symbol,
            side=side,
            amount=amount,
            entry_price=entry_price,
            stop_order_id=self._stop_order_id,
            last_stop_price=self._last_stop_price,
        )

        # 记录开仓交易
        self._persistence.record_trade(
            trade_type="open",
            symbol=symbol,
            side=side,
            amount=amount,
            price=entry_price,
            reason="signal_open",
        )

        logger.info(
            f"[持仓更新] 开仓成功: {symbol}, 方向:{side}, 数量:{amount}, 入场价:{entry_price}"
        )


def create_position_manager(
    config: Optional[Config] = None,
    data_dir: Optional[Path] = None,
) -> PositionManager:
    """创建仓位管理器实例"""
    return PositionManager(config, data_dir)
