"""
交易执行器 - 执行交易请求
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from ...core.base import BaseComponent, BaseConfig
from ..models import TradeResult, OrderResult, TradeSide, TPSLRequest

logger = logging.getLogger(__name__)

class TradeExecutorConfig(BaseConfig):
    """交易执行器配置"""
    enable_tp_sl: bool = True
    tp_sl_timeout: int = 30
    partial_close_ratio: float = 0.5
    retry_on_failure: bool = True
    max_retries: int = 3
    enable_position_check: bool = True
    max_position_amount: float = 0.1  # 最大持仓量（BTC）
    enable_add_position: bool = False  # 是否允许加仓
    add_position_ratio: float = 0.5  # 加仓比例（相对于初始仓位）

class TradeExecutor(BaseComponent):
    """交易执行器"""

    def __init__(
        self,
        exchange_client,
        order_manager,
        position_manager,
        risk_manager,
        config: Optional[TradeExecutorConfig] = None
    ):
        # 如果没有提供配置，创建默认配置
        if config is None:
            config = TradeExecutorConfig(name="TradeExecutor")
        super().__init__(config)
        self.exchange_client = exchange_client
        self.order_manager = order_manager
        self.position_manager = position_manager
        self.risk_manager = risk_manager

    async def initialize(self) -> bool:
        """初始化交易执行器"""
        logger.info("正在初始化交易执行器...")
        self._initialized = True
        return True

    async def cleanup(self) -> None:
        """清理资源"""
        pass

    async def execute_trade(self, trade_request: Dict[str, Any]) -> TradeResult:
        """执行交易"""
        try:
            symbol = trade_request['symbol']
            side = TradeSide(trade_request['side'])
            amount = trade_request['amount']
            order_type = trade_request.get('type', 'market')
            price = trade_request.get('price')
            reason = trade_request.get('reason', 'normal')

            logger.info(f"执行交易: {symbol} {side.value} {amount} @ {price or 'market'} - {reason}")

            # 0. 检查现有持仓状态（如果启用）
            current_position = None
            if self.config.enable_position_check:
                current_position = self.position_manager.get_position(symbol)
                if current_position:
                    logger.info(f"检测到现有持仓: {symbol} {current_position.side.value} {current_position.amount}")

                    # 检查信号方向是否与持仓一致
                    if (side == TradeSide.BUY and current_position.side == TradeSide.LONG) or \
                       (side == TradeSide.SELL and current_position.side == TradeSide.SHORT):
                        logger.info("信号方向与现有持仓一致，考虑加仓操作")

                        # 检查是否允许加仓
                        if not self.config.enable_add_position:
                            logger.info("加仓功能已禁用，跳过此次交易")
                            return TradeResult(
                                success=False,
                                error_message="加仓功能已禁用"
                            )

                        # 检查是否超过最大仓位限制
                        new_total_amount = current_position.amount + amount
                        if new_total_amount > self.config.max_position_amount:
                            logger.info(f"加仓后总仓位 {new_total_amount} 超过最大限制 {self.config.max_position_amount}，调整加仓量")
                            amount = self.config.max_position_amount - current_position.amount
                            if amount <= 0:
                                logger.info("已达到最大仓位限制，无法继续加仓")
                                return TradeResult(
                                    success=False,
                                    error_message="已达到最大仓位限制"
                                )

                        # 按比例调整加仓量
                        amount = amount * self.config.add_position_ratio
                        logger.info(f"调整后的加仓量: {amount}")

                    else:
                        logger.info("信号方向与现有持仓相反，执行平仓操作")
                        # 先平仓当前持仓
                        close_result = await self._close_position(symbol)
                        if not close_result.success:
                            return close_result

                        # 记录平仓成功，但继续执行反向开仓
                        logger.info("平仓完成，准备执行反向开仓")
                else:
                    logger.info("当前无持仓，执行开仓操作")

            # 1. 检查是否有足够的余额
            try:
                balance = await self.exchange_client.fetch_balance()
                current_price = price or await self._get_current_price(symbol)
                required_amount = amount * current_price

                logger.info(f"余额检查 - 可用: {balance.free}, 需要: {required_amount}, 价格: {current_price}")

                if balance.free < required_amount:
                    return TradeResult(
                        success=False,
                        error_message=f"余额不足 - 可用: {balance.free:.4f}, 需要: {required_amount:.4f}"
                    )
            except Exception as e:
                logger.error(f"余额检查失败: {e}")
                return TradeResult(
                    success=False,
                    error_message=f"余额检查异常: {str(e)}"
                )

            # 2. 创建主订单
            if order_type == 'limit' and price:
                order_result = await self.order_manager.create_limit_order(
                    symbol, side, amount, price
                )
            else:
                order_result = await self.order_manager.create_market_order(
                    symbol, side, amount
                )

            if not order_result.success:
                return TradeResult(
                    success=False,
                    error_message=f"订单创建失败: {order_result.error_message}"
                )

            # 3. 等待订单成交
            filled_order = await self._wait_for_order_fill(order_result)
            if not filled_order:
                return TradeResult(
                    success=False,
                    error_message="订单成交超时"
                )

            # 4. 设置止盈止损（仅在新开仓时）
            if self.config.enable_tp_sl and not current_position:
                await self._set_tp_sl(symbol, side, filled_order)
            elif self.config.enable_tp_sl and current_position:
                # 如果是加仓，检查并更新止盈止损
                await self._check_and_update_tp_sl(symbol, side, current_position)

            # 5. 更新仓位信息
            await self.position_manager.update_position(self.exchange_client, symbol)

            # 6. 记录交易结果
            trade_result = TradeResult(
                success=True,
                order_id=filled_order.order_id,
                filled_amount=filled_order.filled_amount,
                average_price=filled_order.average_price,
                fee=filled_order.fee
            )

            # 7. 更新风险统计
            await self.risk_manager.update_trade_result({
                'pnl': 0,  # 初始PNL为0，将在后续更新
                'timestamp': datetime.now()
            })

            logger.info(f"交易执行成功: {symbol} {filled_order.filled_amount} @ {filled_order.average_price}")
            return trade_result

        except Exception as e:
            logger.error(f"交易执行失败: {e}")
            import traceback
            logger.error(f"详细错误堆栈: {traceback.format_exc()}")
            return TradeResult(
                success=False,
                error_message=f"交易执行异常: {str(e)}"
            )

    async def _wait_for_order_fill(self, order_result: OrderResult, timeout: int = 30) -> Optional[OrderResult]:
        """等待订单成交"""
        try:
            start_time = datetime.now()
            order_id = order_result.order_id
            symbol = order_result.symbol

            while (datetime.now() - start_time).seconds < timeout:
                # 更新订单状态
                updated_order = await self.exchange_client.fetch_order(order_id, symbol)

                if updated_order.success:
                    if updated_order.status == 'closed':
                        logger.info(f"订单已成交: {order_id}")
                        return updated_order
                    elif updated_order.status in ['canceled', 'rejected', 'expired']:
                        logger.warning(f"订单已终止: {order_id} - {updated_order.status}")
                        return None

                # 等待1秒后重试
                await asyncio.sleep(1)

            logger.warning(f"订单成交超时: {order_id}")
            return None

        except Exception as e:
            logger.error(f"等待订单成交异常: {e}")
            return None

    async def _close_position(self, symbol: str) -> TradeResult:
        """平仓当前持仓"""
        try:
            current_position = self.position_manager.get_position(symbol)
            if not current_position:
                return TradeResult(
                    success=True,
                    error_message="无持仓可平"
                )

            logger.info(f"正在平仓: {symbol} {current_position.side.value} {current_position.amount}")

            # 创建反向订单以平仓
            close_side = TradeSide.SELL if current_position.side == TradeSide.LONG else TradeSide.BUY
            close_amount = current_position.amount

            # 使用市价单平仓
            order_result = await self.order_manager.create_market_order(symbol, close_side, close_amount)

            if not order_result.success:
                return TradeResult(
                    success=False,
                    error_message=f"平仓订单创建失败: {order_result.error_message}"
                )

            # 等待订单成交
            filled_order = await self._wait_for_order_fill(order_result)
            if not filled_order:
                return TradeResult(
                    success=False,
                    error_message="平仓订单成交超时"
                )

            # 更新仓位信息
            await self.position_manager.update_position(self.exchange_client, symbol)

            logger.info(f"平仓成功: {symbol} {filled_order.filled_amount} @ {filled_order.average_price}")
            return TradeResult(
                success=True,
                order_id=filled_order.order_id,
                filled_amount=filled_order.filled_amount,
                average_price=filled_order.average_price,
                fee=filled_order.fee
            )

        except Exception as e:
            logger.error(f"平仓失败: {e}")
            return TradeResult(
                success=False,
                error_message=f"平仓异常: {str(e)}"
            )

    async def _check_and_update_tp_sl(self, symbol: str, side: TradeSide, current_position: PositionInfo) -> None:
        """检查并更新止盈止损"""
        try:
            # 获取当前价格
            current_price = await self._get_current_price(symbol)
            entry_price = current_position.average_price

            # 计算新的止盈止损价格
            if current_position.side == TradeSide.LONG:
                # 多头：止盈在上方，止损在下方
                new_take_profit = entry_price * 1.06  # 6% 止盈
                new_stop_loss = entry_price * 0.98    # 2% 止损
            else:
                # 空头：止盈在下方，止损在上方
                new_take_profit = entry_price * 0.94  # 6% 止盈
                new_stop_loss = entry_price * 1.02    # 2% 止损

            # 这里应该实现更新现有止盈止损订单的逻辑
            # 简化实现：记录日志
            logger.info(f"更新止盈止损: {symbol} 新TP={new_take_profit:.2f} 新SL={new_stop_loss:.2f}")

        except Exception as e:
            logger.error(f"更新止盈止损失败: {e}")

    async def _set_tp_sl(self, symbol: str, side: TradeSide, order_result: OrderResult) -> None:
        """设置止盈止损"""
        try:
            # 获取当前价格
            current_price = await self._get_current_price(symbol)
            entry_price = order_result.average_price

            # 计算止盈止损价格
            if side == TradeSide.BUY:
                # 多头：止盈在上方，止损在下方
                take_profit = entry_price * 1.06  # 6% 止盈
                stop_loss = entry_price * 0.98    # 2% 止损
            else:
                # 空头：止盈在下方，止损在上方
                take_profit = entry_price * 0.94  # 6% 止盈
                stop_loss = entry_price * 1.02    # 2% 止损

            # 创建止盈止损订单
            tp_sl_request = {
                'symbol': symbol,
                'take_profit': take_profit,
                'stop_loss': stop_loss
            }

            # 这里应该实现具体的TP/SL逻辑
            # 简化实现：记录日志
            logger.info(f"设置止盈止损: {symbol} TP={take_profit:.2f} SL={stop_loss:.2f}")

        except Exception as e:
            logger.error(f"设置止盈止损失败: {e}")

    async def _get_current_price(self, symbol: str) -> float:
        """获取当前价格"""
        try:
            ticker = await self.exchange_client.fetch_ticker(symbol)
            return ticker.last
        except Exception as e:
            logger.error(f"获取当前价格失败: {e}")
            return 0.0

    async def close_position(self, symbol: str, amount: Optional[float] = None) -> TradeResult:
        """平仓"""
        try:
            # 获取当前仓位
            position = self.position_manager.get_position(symbol)
            if not position:
                return TradeResult(
                    success=False,
                    error_message="没有找到仓位"
                )

            # 计算平仓数量
            close_amount = amount or position.amount

            # 确定平仓方向
            close_side = TradeSide.SELL if position.side == TradeSide.LONG else TradeSide.BUY

            # 创建平仓交易请求
            close_request = {
                'symbol': symbol,
                'side': close_side.value,
                'amount': close_amount,
                'type': 'market',
                'reason': 'close_position',
                'reduce_only': True
            }

            # 执行平仓
            return await self.execute_trade(close_request)

        except Exception as e:
            logger.error(f"平仓失败: {e}")
            return TradeResult(
                success=False,
                error_message=str(e)
            )

    async def partial_close(self, symbol: str, ratio: float = 0.5) -> TradeResult:
        """部分平仓"""
        try:
            position = self.position_manager.get_position(symbol)
            if not position:
                return TradeResult(
                    success=False,
                    error_message="没有找到仓位"
                )

            # 计算部分平仓数量
            close_amount = position.amount * ratio

            return await self.close_position(symbol, close_amount)

        except Exception as e:
            logger.error(f"部分平仓失败: {e}")
            return TradeResult(
                success=False,
                error_message=str(e)
            )

    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        base_status = super().get_status()
        base_status.update({
            'total_executed_trades': len([t for t in self.position_manager.trade_history if t.get('executed')]),
            'enable_tp_sl': self.config.enable_tp_sl
        })
        return base_status

# 创建交易执行器的工厂函数
async def create_trade_executor(exchange_client, order_manager, position_manager, risk_manager) -> TradeExecutor:
    """创建交易执行器实例"""
    executor = TradeExecutor(exchange_client, order_manager, position_manager, risk_manager)
    await executor.initialize()
    return executor