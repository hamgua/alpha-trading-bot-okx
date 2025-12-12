"""
仓位管理器 - 管理交易仓位
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from ...core.base import BaseComponent, BaseConfig
from ..models import PositionInfo, TradeSide

logger = logging.getLogger(__name__)

class PositionManagerConfig(BaseConfig):
    """仓位管理器配置"""
    max_positions: int = 1
    auto_close_on_loss: bool = False
    max_loss_percentage: float = 0.05

class PositionManager(BaseComponent):
    """仓位管理器"""

    def __init__(self, config: Optional[PositionManagerConfig] = None):
        # 如果没有提供配置，创建默认配置
        if config is None:
            config = PositionManagerConfig(name="PositionManager")
        super().__init__(config)
        self.positions: Dict[str, PositionInfo] = {}
        self.closed_positions: List[PositionInfo] = []
        self.total_pnl = 0.0

    async def initialize(self) -> bool:
        """初始化仓位管理器"""
        logger.info("正在初始化仓位管理器...")
        self._initialized = True
        return True

    async def cleanup(self) -> None:
        """清理资源"""
        pass

    async def update_position(self, exchange_client, symbol: str = "BTC/USDT:USDT") -> Optional[PositionInfo]:
        """更新仓位信息"""
        try:
            # 从交易所获取仓位信息
            positions = await exchange_client.fetch_positions(symbol)

            if positions and len(positions) > 0:
                pos_data = positions[0]  # 取第一个仓位

                position = PositionInfo(
                    symbol=symbol,
                    side=TradeSide.LONG if pos_data['side'] == 'long' else TradeSide.SHORT,
                    amount=abs(pos_data['contracts']),
                    entry_price=pos_data['entryPrice'],
                    mark_price=pos_data['markPrice'],
                    liquidation_price=pos_data['liquidationPrice'],
                    unrealized_pnl=pos_data['unrealizedPnl'],
                    realized_pnl=pos_data.get('realizedPnl', 0),
                    margin=pos_data['initialMargin'],
                    leverage=pos_data['leverage']
                )

                self.positions[symbol] = position
                logger.debug(f"仓位更新: {symbol} {position.side.value} {position.amount}")
                return position
            else:
                # 没有仓位
                if symbol in self.positions:
                    # 如果之前有仓位，现在没有了，说明已平仓
                    closed_pos = self.positions.pop(symbol)
                    self.closed_positions.append(closed_pos)
                    self.total_pnl += closed_pos.realized_pnl
                    logger.info(f"仓位已平仓: {symbol}")
                return None

        except Exception as e:
            logger.error(f"更新仓位失败: {e}")
            return None

    def get_position(self, symbol: str) -> Optional[PositionInfo]:
        """获取仓位"""
        return self.positions.get(symbol)

    def get_all_positions(self) -> List[PositionInfo]:
        """获取所有仓位"""
        return list(self.positions.values())

    def has_position(self, symbol: str) -> bool:
        """是否有仓位"""
        return symbol in self.positions

    def get_position_side(self, symbol: str) -> Optional[TradeSide]:
        """获取仓位方向"""
        position = self.get_position(symbol)
        return position.side if position else None

    def get_position_amount(self, symbol: str) -> float:
        """获取仓位数量"""
        position = self.get_position(symbol)
        return position.amount if position else 0.0

    def get_unrealized_pnl(self, symbol: str) -> float:
        """获取未实现盈亏"""
        position = self.get_position(symbol)
        return position.unrealized_pnl if position else 0.0

    def get_total_unrealized_pnl(self) -> float:
        """获取总未实现盈亏"""
        return sum(pos.unrealized_pnl for pos in self.positions.values())

    def get_total_realized_pnl(self) -> float:
        """获取总已实现盈亏"""
        return self.total_pnl

    def get_total_pnl(self) -> float:
        """获取总盈亏"""
        return self.total_pnl + self.get_total_unrealized_pnl()

    async def close_position(self, exchange_client, symbol: str, amount: Optional[float] = None) -> bool:
        """平仓"""
        position = self.get_position(symbol)
        if not position:
            logger.warning(f"尝试平仓但找不到仓位: {symbol}")
            return False

        try:
            # 计算平仓数量
            close_amount = amount or position.amount

            # 确定平仓方向（与当前仓位相反）
            close_side = TradeSide.SELL if position.side == TradeSide.LONG else TradeSide.BUY

            # 创建平仓订单
            from .order_manager import MarketOrderRequest
            order_request = {
                'symbol': symbol,
                'type': 'market',
                'side': close_side.value,
                'amount': close_amount,
                'reduce_only': True
            }

            # 执行平仓
            result = await exchange_client.create_order(order_request)

            if result.success:
                logger.info(f"平仓成功: {symbol} {close_side.value} {close_amount}")
                # 更新仓位（将在下一次更新中被移除）
                return True
            else:
                logger.error(f"平仓失败: {result.error_message}")
                return False

        except Exception as e:
            logger.error(f"平仓异常: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        base_status = super().get_status()
        base_status.update({
            'active_positions': len(self.positions),
            'closed_positions': len(self.closed_positions),
            'total_unrealized_pnl': self.get_total_unrealized_pnl(),
            'total_realized_pnl': self.get_total_realized_pnl(),
            'total_pnl': self.get_total_pnl()
        })
        return base_status