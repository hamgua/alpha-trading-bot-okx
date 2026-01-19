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

    async def update_position(
        self, exchange_client, symbol: str = "BTC/USDT:USDT"
    ) -> Optional[PositionInfo]:
        """更新仓位信息"""
        try:
            # 验证exchange_client参数
            if exchange_client is None or not hasattr(exchange_client, "is_test_mode"):
                logger.warning(
                    f"无效的exchange_client参数，假设为测试模式: {type(exchange_client)}"
                )
                exchange_client = type("obj", (object,), {"is_test_mode": True})()

            # 检查是否为测试模式
            if exchange_client.is_test_mode:
                logger.info(f"测试模式：返回模拟仓位信息: {symbol}")
                # 测试模式下，如果没有缓存的仓位，返回None（表示无持仓）
                if symbol not in self.positions:
                    logger.info(f"测试模式：无持仓: {symbol}")
                    return None
                # 如果有缓存的仓位，返回缓存的信息
                position = self.positions[symbol]
                logger.info(
                    f"测试模式：返回缓存仓位 - 数量: {position.amount}, 方向: {position.side.value}"
                )
                return position

            # 从交易所获取仓位信息（非测试模式）
            logger.info(f"开始更新仓位信息: {symbol}")
            positions = await exchange_client.fetch_positions(symbol)

            if positions and len(positions) > 0:
                pos_data = positions[0]  # 取第一个仓位

                # 检查是否真的没有仓位（合约数量为0或side为None）
                contracts = pos_data.get("contracts", 0) or 0
                side = pos_data.get("side")

                if contracts == 0 or side is None:
                    # 没有实际仓位，清理缓存
                    if symbol in self.positions:
                        closed_pos = self.positions.pop(symbol)
                        self.closed_positions.append(closed_pos)
                        self.total_pnl += closed_pos.realized_pnl
                        logger.info(f"仓位已平仓: {symbol}")
                    logger.info(f"检测到无持仓: {symbol}")
                    return None

                # 有实际仓位，处理仓位信息
                entry_price = pos_data.get("entryPrice", 0) or 0
                unrealized_pnl = pos_data.get("unrealizedPnl", 0) or 0
                percentage = pos_data.get("percentage", 0) or 0

                logger.info(
                    f"检测到仓位: {symbol} {side} {contracts} 张, "
                    f"均价: ${entry_price:.2f}, 浮盈: ${unrealized_pnl:.4f} ({percentage:.2f}%)"
                )

                position = PositionInfo(
                    symbol=symbol,
                    side=TradeSide.LONG if side == "long" else TradeSide.SHORT,
                    amount=abs(contracts),
                    entry_price=pos_data.get("entryPrice", 0),
                    mark_price=pos_data.get("markPrice", 0),
                    liquidation_price=pos_data.get("liquidationPrice", 0),
                    unrealized_pnl=pos_data.get("unrealizedPnl", 0),
                    realized_pnl=pos_data.get("realizedPnl", 0),
                    margin=pos_data.get("initialMargin", 0),
                    leverage=pos_data.get("leverage", 0),
                )

                self.positions[symbol] = position
                logger.info(
                    f"仓位更新成功: {symbol} {position.side.value} {position.amount}"
                )
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

    async def partial_close_position(
        self, exchange_client, symbol: str, amount: float, tp_level: int = None
    ) -> bool:
        """部分平仓并更新止盈级别信息"""
        position = self.get_position(symbol)
        if not position:
            logger.warning(f"尝试部分平仓但找不到仓位: {symbol}")
            return False

        try:
            # 检查剩余数量是否足够
            if amount >= position.amount:
                logger.info(
                    f"部分平仓数量 {amount} >= 当前仓位 {position.amount}，执行全部平仓"
                )
                return await self.close_position(exchange_client, symbol)

            # 执行部分平仓
            close_side = (
                TradeSide.SELL if position.side == TradeSide.LONG else TradeSide.BUY
            )
            order_request = {
                "symbol": symbol,
                "type": "market",
                "side": close_side.value,
                "amount": amount,
                "reduce_only": True,
            }

            result = await exchange_client.create_order(order_request)

            if result.get("success"):
                logger.info(f"部分平仓成功: {symbol} {close_side.value} {amount} 张")

                # 更新仓位数量
                position.amount -= amount

                # 如果指定了止盈级别，记录已触发的级别
                if tp_level is not None:
                    position.tp_levels_hit.append(tp_level)
                    logger.info(
                        f"记录止盈级别 {tp_level} 已触发，已触发级别: {position.tp_levels_hit}"
                    )

                # 更新已实现盈亏
                if "realizedPnl" in result:
                    realized_pnl = float(result["realizedPnl"])
                    position.realized_pnl += realized_pnl
                    self.total_pnl += realized_pnl

                return True
            else:
                logger.error(f"部分平仓失败: {result.get('error', 'Unknown error')}")
                return False

        except Exception as e:
            logger.error(f"部分平仓异常: {e}")
            import traceback

            logger.error(f"详细错误: {traceback.format_exc()}")
            return False

    async def close_position(
        self, exchange_client, symbol: str, amount: Optional[float] = None
    ) -> bool:
        """平仓"""
        position = self.get_position(symbol)
        if not position:
            logger.warning(f"尝试平仓但找不到仓位: {symbol}")
            return False

        try:
            # 计算平仓数量
            close_amount = amount or position.amount

            # 确定平仓方向（与当前仓位相反）
            close_side = (
                TradeSide.SELL if position.side == TradeSide.LONG else TradeSide.BUY
            )

            # 创建平仓订单
            from .order_manager import MarketOrderRequest

            order_request = {
                "symbol": symbol,
                "type": "market",
                "side": close_side.value,
                "amount": close_amount,
                "reduce_only": True,
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
        base_status.update(
            {
                "active_positions": len(self.positions),
                "closed_positions": len(self.closed_positions),
                "total_unrealized_pnl": self.get_total_unrealized_pnl(),
                "total_realized_pnl": self.get_total_realized_pnl(),
                "total_pnl": self.get_total_pnl(),
            }
        )
        return base_status
