"""
交易执行器 - 执行交易请求
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from ...core.base import BaseComponent, BaseConfig
from ..models import TradeResult, OrderResult, TradeSide, TPSLRequest, PositionInfo

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
    tp_update_threshold_pct: float = 0.01  # 止盈更新阈值（价格变动百分比）
    tp_update_min_interval: int = 300  # 止盈更新最小间隔（秒，5分钟）
    use_leverage: bool = True  # 是否使用杠杆（合约交易）
    leverage: int = 10  # 杠杆倍数

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

        # 记录每个币种的最后一次止盈更新时间
        self._last_tp_update_time: Dict[str, datetime] = {}

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

            # 检查是否允许做空（新增检查）
            if side == TradeSide.SELL and not self.config.allow_short_selling:
                # 检查是否有现有持仓
                await self.position_manager.update_position(self.exchange_client, symbol)
                current_position = self.position_manager.get_position(symbol)

                if not current_position or current_position.side == TradeSide.LONG:
                    logger.warning(f"做空被禁用(allow_short_selling={self.config.allow_short_selling})，跳过SELL信号 - {symbol}")
                    return TradeResult(
                        success=False,
                        error_message="做空功能已禁用"
                    )
                else:
                    logger.info(f"已有空头持仓，允许继续做空操作 - {symbol}")

            # 0. 检查现有持仓状态（如果启用）
            current_position = None
            if self.config.enable_position_check:
                logger.info(f"开始检查持仓状态: {symbol}")
                # 先更新仓位信息，确保获取最新数据
                await self.position_manager.update_position(self.exchange_client, symbol)
                current_position = self.position_manager.get_position(symbol)
                if current_position:
                    logger.info(f"检测到现有持仓: {symbol} {current_position.side.value} {current_position.amount}")

                    # 检查信号方向是否与持仓一致
                    if (side == TradeSide.BUY and current_position.side == TradeSide.LONG) or \
                       (side == TradeSide.SELL and current_position.side == TradeSide.SHORT):
                        logger.info("信号方向与现有持仓一致")

                        # 有持仓时更新止盈止损（与加仓功能无关）
                        if self.config.enable_tp_sl:
                            logger.info(f"检测到同向信号，更新现有持仓止盈止损: {symbol}")
                            await self._check_and_update_tp_sl(symbol, side, current_position)
                            logger.info(f"止盈止损更新完成")
                        else:
                            logger.info(f"止盈止损功能已禁用，跳过更新: {symbol}")

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

                        # 检查是否真的需要反向开仓
                        if current_position.amount <= 0:
                            logger.info(f"当前仓位数量为 {current_position.amount}，无需反向开仓，直接执行新开仓")
                        else:
                            logger.info("平仓完成，准备执行反向开仓")
                else:
                    logger.info("当前无持仓，执行开仓操作")

            # 1. 检查是否有足够的余额
            try:
                balance = await self.exchange_client.fetch_balance()
                current_price = price or await self._get_current_price(symbol)

                # 合约交易使用杠杆，计算所需保证金
                if self.config.use_leverage:
                    # 所需保证金 = 名义价值 / 杠杆倍数
                    notional_value = amount * current_price
                    required_margin = notional_value / self.config.leverage

                    # 对于合约交易，检查是否有足够的可用资金
                    # 考虑到可能存在其他持仓占用的保证金
                    available_for_trade = balance.free

                    logger.info(f"合约交易 - 名义价值: {notional_value:.4f} USDT, 杠杆: {self.config.leverage}x, 所需保证金: {required_margin:.4f} USDT")
                    logger.info(f"账户余额 - 总余额: {balance.total:.4f} USDT, 已用: {balance.used:.4f} USDT, 可用: {balance.free:.4f} USDT")

                    # 如果可用余额不足但总额足够，给出更友好的提示
                    if available_for_trade < required_margin and balance.total >= required_margin:
                        logger.warning(f"可用余额不足，但账户总额足够。建议检查是否有其他持仓占用保证金")
                        # 仍然允许交易，由交易所决定是否接受
                    elif balance.total < required_margin:
                        return TradeResult(
                            success=False,
                            error_message=f"账户总余额不足 - 总余额: {balance.total:.4f} USDT, 需要保证金: {required_margin:.4f} USDT"
                        )
                else:
                    # 现货交易需要全额资金
                    required_margin = amount * current_price
                    logger.info(f"现货交易 - 所需资金: {required_margin:.4f} USDT")

                    if balance.free < required_margin:
                        return TradeResult(
                            success=False,
                            error_message=f"余额不足 - 可用: {balance.free:.4f} USDT, 需要: {required_margin:.4f} USDT"
                        )

                logger.info(f"余额检查通过 - 可用: {balance.free:.4f} USDT, 需要保证金: {required_margin:.4f} USDT")
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

            # 4. 设置止盈止损
            if self.config.enable_tp_sl:
                if not current_position:
                    # 新仓位，创建止盈止损
                    logger.info(f"新仓位创建止盈止损: {symbol}")
                    await self._set_tp_sl(symbol, side, filled_order)
                else:
                    # 已有仓位，更新止盈止损（与加仓功能无关）
                    if (side == TradeSide.BUY and current_position.side == TradeSide.LONG) or \
                       (side == TradeSide.SELL and current_position.side == TradeSide.SHORT):
                        logger.info(f"同向信号，更新现有持仓止盈止损: {symbol}")
                        await self._check_and_update_tp_sl(symbol, side, current_position)
                    else:
                        # 方向相反，说明是平仓后反向开仓，创建新的止盈止损
                        logger.info(f"反向开仓，创建新止盈止损: {symbol}")
                        await self._set_tp_sl(symbol, side, filled_order)

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

            # 记录交易到策略管理器（如果可用）
            try:
                from alpha_trading_bot.strategies import get_strategy_manager
                strategy_manager = await get_strategy_manager()
                strategy_manager.record_trade()
                logger.debug("已记录交易到策略管理器")
            except Exception as e:
                logger.debug(f"记录交易失败（非关键）: {e}")

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

            # 检查仓位数量，如果为0则不需要平仓
            if current_position.amount <= 0:
                logger.warning(f"仓位数量为 {current_position.amount}，无需平仓: {symbol}")
                return TradeResult(
                    success=True,
                    error_message=f"仓位数量为 {current_position.amount}，无需平仓"
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

    def _get_tp_sl_percentages(self) -> tuple[float, float]:
        """获取止盈止损百分比配置"""
        # 从配置管理器获取策略配置
        from ...config import load_config
        config = load_config()

        take_profit_pct = config.strategies.take_profit_percent
        stop_loss_pct = config.strategies.stop_loss_percent

        logger.info(f"使用止盈止损配置: 止盈={take_profit_pct*100:.1f}%, 止损={stop_loss_pct*100:.1f}%")

        return take_profit_pct, stop_loss_pct

    async def _check_and_update_tp_sl(self, symbol: str, side: TradeSide, current_position: PositionInfo, min_price_change_pct: float = 0.01) -> None:
        """检查并更新止盈 - 只更新止盈不更新止损"""
        try:
            # 检查更新间隔
            now = datetime.now()
            last_update = self._last_tp_update_time.get(symbol)
            if last_update:
                time_since_last_update = (now - last_update).total_seconds()
                if time_since_last_update < self.config.tp_update_min_interval:
                    logger.info(f"距离上次止盈更新仅 {time_since_last_update:.0f} 秒，小于最小间隔 {self.config.tp_update_min_interval} 秒，跳过更新")
                    return

            # 获取当前价格
            current_price = await self._get_current_price(symbol)
            entry_price = current_position.entry_price

            # 获取止盈止损百分比配置
            take_profit_pct, stop_loss_pct = self._get_tp_sl_percentages()

            # 新策略：只更新止盈，止损保持固定（基于入场价）
            if current_position.side == TradeSide.LONG:
                # 多头：止盈在上方
                new_take_profit = current_price * (1 + take_profit_pct)  # 止盈：基于当前价（动态）
                # 止损：基于持仓均价（固定），不更新
                fixed_stop_loss = entry_price * (1 - stop_loss_pct)
                tp_side = TradeSide.SELL
            else:
                # 空头：止盈在下方
                new_take_profit = current_price * (1 - take_profit_pct)  # 止盈：基于当前价（动态）
                # 止损：基于持仓均价（固定），不更新
                fixed_stop_loss = entry_price * (1 + stop_loss_pct)
                tp_side = TradeSide.BUY

            logger.info(f"当前持仓: {symbol} {current_position.side.value} {current_position.amount} 张")
            logger.info(f"新策略设置 - 持仓均价: ${entry_price:.2f}, 当前价格: ${current_price:.2f}")
            logger.info(f"- 止盈: ${new_take_profit:.2f} (基于当前价 +{take_profit_pct*100:.0f}%) - 动态更新")
            logger.info(f"- 止损: ${fixed_stop_loss:.2f} (基于持仓均价 -{stop_loss_pct*100:.0f}%) - 固定不变")

            # 获取现有的算法订单
            existing_orders = await self.order_manager.fetch_algo_orders(symbol)
            logger.info(f"找到 {len(existing_orders)} 个现有算法订单")

            # 检查是否有现有止盈订单，并计算价格变动
            current_tp_price = None
            for order in existing_orders:
                # 通过触发价格与当前价格的关系来判断是止盈还是止损订单
                if current_position.side == TradeSide.LONG:
                    if order.price > current_price:
                        current_tp_price = order.price
                        break
                else:  # SHORT
                    if order.price < current_price:
                        current_tp_price = order.price
                        break

            # 检查价格变动是否达到阈值
            if current_tp_price:
                price_change_pct = abs(current_price - current_tp_price) / current_tp_price
                if price_change_pct < min_price_change_pct:
                    logger.info(f"价格变动 {price_change_pct*100:.2f}% 小于阈值 {min_price_change_pct*100:.2f}%，跳过止盈更新")
                    return
                else:
                    logger.info(f"价格变动 {price_change_pct*100:.2f}% 达到阈值 {min_price_change_pct*100:.2f}%，需要更新止盈")

            # 打印订单详情以便调试
            for i, order in enumerate(existing_orders):
                logger.info(f"订单 {i+1}: ID={order.order_id}, 价格={order.price}, 方向={order.side.value}")

            # 清理重复的止盈订单（保留最新的一个）
            tp_orders = []
            for order in existing_orders:
                if current_position.side == TradeSide.LONG:
                    if order.price > current_price:
                        tp_orders.append(order)
                else:  # SHORT
                    if order.price < current_price:
                        tp_orders.append(order)

            # 如果有多个止盈订单，保留最新的一个，取消其他的
            if len(tp_orders) > 1:
                logger.warning(f"检测到 {len(tp_orders)} 个止盈订单，将清理重复订单")
                # 按订单ID排序（假设ID越大越新）
                tp_orders.sort(key=lambda x: x.order_id, reverse=True)
                # 保留第一个（最新的），取消其余的
                for order in tp_orders[1:]:
                    logger.info(f"取消重复的止盈订单: {order.order_id}")
                    await self.order_manager.cancel_algo_order(order.order_id, symbol)
                    # 从现有订单列表中移除
                    existing_orders = [o for o in existing_orders if o.order_id != order.order_id]

            for order in existing_orders:
                # OrderResult 对象的处理方式
                algo_id = order.order_id
                trigger_price = order.price

                # 通过触发价格与当前价格的关系来判断是止盈还是止损订单
                if current_position.side == TradeSide.LONG:
                    if trigger_price > current_price:
                        current_tp = {'algoId': algo_id, 'triggerPx': trigger_price}
                    elif trigger_price < current_price:
                        current_sl = {'algoId': algo_id, 'triggerPx': trigger_price}
                else:  # SHORT
                    if trigger_price < current_price:
                        current_tp = {'algoId': algo_id, 'triggerPx': trigger_price}
                    elif trigger_price > current_price:
                        current_sl = {'algoId': algo_id, 'triggerPx': trigger_price}

            # 只检查和处理止盈订单
            tp_needs_update = False

            if current_tp:
                tp_price_diff = abs(current_tp['triggerPx'] - new_take_profit)
                tp_needs_update = tp_price_diff > (current_price * 0.001)  # 价格差异超过0.1%才更新
                if tp_needs_update:
                    logger.info(f"止盈需要更新: 当前=${current_tp['triggerPx']:.2f} → 新=${new_take_profit:.2f}")
                else:
                    logger.info(f"止盈无需更新: 当前价格接近目标")
            else:
                tp_needs_update = True  # 没有现有止盈订单，需要创建
                logger.info("没有找到现有止盈订单，需要创建")

            # 检查现有止损订单（只检查，不更新）
            if current_sl:
                logger.info(f"检测到现有止损订单: {current_sl['algoId']} @ ${current_sl['triggerPx']:.2f} - 保持固定，不更新")
            else:
                logger.warning(f"未检测到止损订单 - 建议检查仓位安全")

            # 只更新止盈订单
            created_count = 0

            if tp_needs_update:
                if current_tp:
                    # 取消现有止盈订单
                    logger.info(f"取消现有止盈订单: {current_tp['algoId']}")
                    await self.order_manager.cancel_algo_order(current_tp['algoId'], symbol)

                # 创建新的止盈订单
                logger.info(f"创建新止盈订单: {symbol} {tp_side.value} {current_position.amount} @ ${new_take_profit:.2f}")
                tp_result = await self.order_manager.create_take_profit_order(
                    symbol=symbol,
                    side=tp_side,
                    amount=current_position.amount,
                    take_profit_price=new_take_profit,
                    reduce_only=True
                )

                if tp_result.success:
                    logger.info(f"✓ 止盈订单创建成功: ID={tp_result.order_id}")
                    created_count += 1
                else:
                    logger.error(f"✗ 止盈订单创建失败: {tp_result.error_message}")

            logger.info(f"止盈更新完成: {created_count} 个新止盈订单已创建")
            logger.info(f"止损订单保持不变: 固定止损 @ ${fixed_stop_loss:.2f}")

            # 记录更新时间
            if created_count > 0:
                self._last_tp_update_time[symbol] = datetime.now()
                logger.info(f"已更新 {symbol} 的止盈更新时间记录")

        except Exception as e:
            logger.error(f"更新止盈失败: {e}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")

    async def _set_tp_sl(self, symbol: str, side: TradeSide, order_result: OrderResult) -> None:
        """设置止盈止损"""
        try:
            # 获取当前价格
            current_price = await self._get_current_price(symbol)
            entry_price = order_result.average_price

            # 获取止盈止损百分比配置
            take_profit_pct, stop_loss_pct = self._get_tp_sl_percentages()

            # 新仓位策略：止盈基于当前价（动态），止损基于入场价（固定）
            # 记录入场价格作为固定止损基准
            entry_price = order_result.average_price

            if side == TradeSide.BUY:
                # 多头：止盈在上方，止损在下方
                take_profit = current_price * (1 + take_profit_pct)  # 止盈：基于当前价（动态）
                stop_loss = entry_price * (1 - stop_loss_pct)      # 止损：基于入场价（固定）
                # 止盈止损订单方向
                tp_side = TradeSide.SELL
                sl_side = TradeSide.SELL
            else:
                # 空头：止盈在下方，止损在上方
                take_profit = current_price * (1 - take_profit_pct)  # 止盈：基于当前价（动态）
                stop_loss = entry_price * (1 + stop_loss_pct)      # 止损：基于入场价（固定）
                # 止盈止损订单方向
                tp_side = TradeSide.BUY
                sl_side = TradeSide.BUY

            # 实际创建止盈止损订单
            logger.info(f"创建新仓位的止盈止损订单: {symbol}")
            logger.info(f"混合策略 - 入场价: ${entry_price:.2f}, 当前价: ${current_price:.2f}")
            logger.info(f"- 止盈: ${take_profit:.2f} (基于当前价 +{take_profit_pct*100:.0f}%)")
            logger.info(f"- 止损: ${stop_loss:.2f} (基于入场价 -{stop_loss_pct*100:.0f}%)")

            # 创建止盈订单
            tp_result = await self.order_manager.create_take_profit_order(
                symbol=symbol,
                side=tp_side,
                amount=order_result.filled_amount,  # 对新仓位设置止盈
                take_profit_price=take_profit,
                reduce_only=True
            )

            if tp_result.success:
                logger.info(f"新仓位止盈订单创建成功: {tp_result.order_id}")
            else:
                logger.error(f"新仓位止盈订单创建失败: {tp_result.error_message}")

            # 创建止损订单
            sl_result = await self.order_manager.create_stop_order(
                symbol=symbol,
                side=sl_side,
                amount=order_result.filled_amount,  # 对新仓位设置止损
                stop_price=stop_loss,
                reduce_only=True
            )

            if sl_result.success:
                logger.info(f"新仓位止损订单创建成功: {sl_result.order_id}")
            else:
                logger.error(f"新仓位止损订单创建失败: {sl_result.error_message}")

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