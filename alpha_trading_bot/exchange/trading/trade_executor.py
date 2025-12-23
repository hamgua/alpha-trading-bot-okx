"""
交易执行器 - 执行交易请求
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, List
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
    leverage: int = 10  # 杠杆倍数（用户要求10倍）
    allow_short_selling: bool = False  # 是否允许做空

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

                    # 严格检查仓位数量，避免对0仓位进行操作
                    if current_position.amount <= 0:
                        logger.warning(f"检测到仓位数量为 {current_position.amount}，视为无有效持仓，执行新开仓")
                        # 清理无效仓位缓存
                        if self.position_manager.has_position(symbol):
                            logger.info(f"清理无效仓位缓存: {symbol}")
                        # 继续执行新开仓逻辑，不进入持仓处理分支
                    else:
                        # 正常的持仓处理逻辑
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
                    logger.info("当前无持仓，执行开仓操作")

            # 1. 检查是否有足够的余额
            try:
                balance = await self.exchange_client.fetch_balance()
                current_price = price or await self._get_current_price(symbol)

                # 合约交易使用杠杆，计算所需保证金
                if self.config.use_leverage:
                    # 获取合约大小（每张合约代表的标的资产数量）
                    contract_size = 0.01  # BTC/USDT:USDT 默认合约大小为0.01 BTC
                    if symbol in self.exchange_client.exchange.markets:
                        market = self.exchange_client.exchange.markets[symbol]
                        contract_size = market.get('contractSize', 0.01)

                    # 计算实际的名义价值 = 数量 × 合约大小 × 价格
                    actual_amount = amount * contract_size
                    notional_value = actual_amount * current_price
                    required_margin = notional_value / self.config.leverage

                    # 对于合约交易，检查是否有足够的可用资金
                    # 考虑到可能存在其他持仓占用的保证金
                    available_for_trade = balance.free

                    logger.info(f"合约交易 - 合约大小: {contract_size} BTC/张, 数量: {amount} 张 = {actual_amount:.6f} BTC")
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

                # 添加余额不足的特殊处理提示
                if balance.free < required_margin and balance.total >= required_margin:
                    logger.warning("⚠️ 注意：虽然余额检查通过，但可用余额不足。系统仍会尝试提交订单，由交易所决定是否接受")
                    logger.warning(f"建议：增加账户USDT余额至至少 {required_margin * 1.1:.2f} USDT 以确保正常交易")
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

        # 检查是否使用多级止盈策略
        if config.strategies.profit_taking_strategy == 'multi_level' and config.strategies.profit_taking_levels:
            # 多级止盈模式：返回第一级作为基础止盈
            take_profit_pct = config.strategies.profit_taking_levels[0]  # 使用第一级作为基础
            logger.info(f"使用多级止盈策略，第一级止盈: {take_profit_pct*100:.1f}%")
        else:
            # 传统单一止盈模式
            take_profit_pct = config.strategies.take_profit_percent

        stop_loss_pct = config.strategies.stop_loss_percent

        logger.info(f"使用止盈止损配置: 止盈={take_profit_pct*100:.1f}%, 止损={stop_loss_pct*100:.1f}%")

        return take_profit_pct, stop_loss_pct

    def _get_multi_level_take_profit_prices(self, entry_price: float, current_price: float, position_side: TradeSide) -> List[Dict[str, Any]]:
        """获取多级止盈价格配置"""
        from ...config import load_config
        config = load_config()

        # 检查是否启用多级止盈
        if config.strategies.profit_taking_strategy != 'multi_level' or not config.strategies.profit_taking_levels:
            return []

        levels = config.strategies.profit_taking_levels
        ratios = config.strategies.profit_taking_ratios

        if len(levels) != len(ratios):
            logger.warning(f"多级止盈级别数量({len(levels)})与比例数量({len(ratios)})不匹配")
            return []

        # 验证比例总和
        if abs(sum(ratios) - 1.0) > 0.001:
            logger.warning(f"多级止盈比例总和不为1.0: {sum(ratios)}")
            return []

        multi_level_prices = []
        for i, (level, ratio) in enumerate(zip(levels, ratios)):
            if position_side == TradeSide.LONG:
                tp_price = entry_price * (1 + level)
            else:  # SHORT
                tp_price = entry_price * (1 - level)

            multi_level_prices.append({
                'level': i + 1,
                'price': tp_price,
                'ratio': ratio,
                'profit_pct': level * 100,
                'description': f"第{i+1}级止盈: {level*100:.0f}%"
            })

        # 构建配置信息字符串
        config_info = []
        for p in multi_level_prices:
            profit_pct = f"{p['profit_pct']:.0f}%"
            ratio_pct = f"{p['ratio']*100:.0f}%"
            config_info.append((profit_pct, ratio_pct))
        logger.info(f"多级止盈配置: {config_info}")
        logger.info(f"返回 {len(multi_level_prices)} 个止盈级别")
        return multi_level_prices

    def __init__(self, exchange_client, order_manager, position_manager, risk_manager, config=None):
        super().__init__(config)
        self.exchange_client = exchange_client
        self.order_manager = order_manager
        self.position_manager = position_manager
        self.risk_manager = risk_manager
        # 添加多级止盈订单创建冷却时间跟踪
        self._last_tp_creation_time = {}  # symbol -> timestamp

    async def _check_and_create_multi_level_tp_sl(self, symbol: str, current_position: PositionInfo, existing_orders: List) -> None:
        """检查并创建多级止盈订单 - 为缺失的级别补充创建"""
        try:
            # 检查冷却时间，避免频繁创建
            current_time = time.time()
            last_creation = self._last_tp_creation_time.get(symbol, 0)
            if current_time - last_creation < 5:  # 5秒内不重复创建
                logger.info(f"多级止盈创建冷却中，跳过检查: {symbol}")
                return

            # 获取当前价格
            current_price = await self._get_current_price(symbol)

            # 计算多级止盈价格
            multi_level_tps = self._get_multi_level_take_profit_prices(
                current_position.entry_price, current_price, current_position.side
            )

            if not multi_level_tps:
                logger.warning("未获取到多级止盈配置，使用传统单级止盈")
                return

            logger.info(f"多级止盈检查: 配置 {len(multi_level_tps)} 个级别，现有 {len(existing_orders)} 个算法订单")

            # 优化策略：如果已有足够的止盈订单且价格匹配，跳过完整识别
            quick_check_passed = False
            if current_position.tp_orders_info and len(current_position.tp_orders_info) >= len(multi_level_tps):
                # 快速检查：验证缓存的订单是否仍然存在且价格匹配
                matched_count = 0
                for cached_order_id, cached_info in list(current_position.tp_orders_info.items()):
                    for order in existing_orders:
                        if order.order_id == cached_order_id:
                            # 验证价格是否匹配（使用较大容差）
                            price_diff = abs(order.price - cached_info['price'])
                            if price_diff <= 0.5:  # 0.5 USDT 容差
                                matched_count += 1
                                break
                            else:
                                logger.info(f"  缓存订单价格变化: ID={cached_order_id}, 缓存价={cached_info['price']}, 现价={order.price}")
                                break

                if matched_count >= len(multi_level_tps):
                    logger.info(f"快速检查通过：已匹配 {matched_count}/{len(multi_level_tps)} 个止盈订单，跳过完整识别")
                    quick_check_passed = True
                    # 直接使用已识别的订单
                    tp_orders = [o for o in existing_orders if o.order_id in current_position.tp_orders_info]
                    logger.info(f"其中识别为止盈订单的有 {len(tp_orders)} 个（快速识别）")
                else:
                    logger.info(f"快速检查失败：仅匹配 {matched_count}/{len(multi_level_tps)} 个订单，重新识别")

            if not quick_check_passed:
                # 由于订单信息不持久化，重新构建
                current_position.tp_orders_info = {}

                # 统计订单类型 - 使用优化后的识别逻辑
                tp_orders = []
                sl_orders = []

                for order in existing_orders:
                    # 对于多头仓位：
                    if current_position.side == TradeSide.LONG and order.side == TradeSide.SELL:
                        # 计算与入场价的距离，避免误判
                        price_diff_from_entry = (order.price - current_position.entry_price) / current_position.entry_price

                        if order.price > current_price and price_diff_from_entry > 0.005:  # 价格高于入场价0.5%以上
                            tp_orders.append(order)
                        elif order.price < current_position.entry_price * 1.001:  # 价格接近或低于入场价
                            sl_orders.append(order)

                logger.info(f"统计结果 - 止盈订单: {len(tp_orders)} 个, 止损订单: {len(sl_orders)} 个")
                for i, order in enumerate(tp_orders):
                    logger.info(f"  止盈订单 {i+1}: ID={order.order_id}, 价格=${order.price:.4f}, 数量={getattr(order, 'amount', 0)}")

            # 获取已存在的止盈订单价格和总数量（按价格分组）
            existing_tp_orders = {}  # {price: total_amount}

            # 只处理止盈订单（基于价格和方向判断）
            for order in existing_orders:
                # 检查订单方向是否与仓位方向相反（止盈订单应该与仓位方向相反）
                if ((current_position.side == TradeSide.LONG and order.side == TradeSide.SELL and order.price > current_price) or
                    (current_position.side == TradeSide.SHORT and order.side == TradeSide.BUY and order.price < current_price)):
                    # 使用原始价格作为键，不进行四舍五入
                    price_key = order.price
                    if price_key not in existing_tp_orders:
                        existing_tp_orders[price_key] = 0
                    existing_tp_orders[price_key] += getattr(order, 'amount', 0) or 0

            logger.info(f"已存在的止盈订单（按价格汇总）: {existing_tp_orders}")

            # 检查每个止盈级别 - 添加级别跟踪避免重复
            created_count = 0
            processed_levels = set()  # 跟踪已处理的级别
            for tp_level in multi_level_tps:
                # 检查是否已经处理过这个级别
                if tp_level['level'] in processed_levels:
                    logger.info(f"级别 {tp_level['level']} 已处理过，跳过")
                    continue
                expected_price = tp_level['price']
                expected_amount = current_position.amount * tp_level['ratio']
                expected_amount = round(expected_amount, 2)

                # 使用更严格的价格容差匹配（0.01），更好识别不同级别的订单
                price_tolerance = 0.01  # 严格容差，更好区分不同级别
                existing_amount = 0
                matched_price = None

                # 查找最接近的价格
                logger.info(f"第{tp_level['level']}级止盈检查 - 期望价格: ${expected_price:.4f}, 容差: ±{price_tolerance}")
                for existing_price, existing_amt in existing_tp_orders.items():
                    price_diff = abs(existing_price - expected_price)
                    logger.info(f"  对比现有价格: ${existing_price:.4f}, 差异: ${price_diff:.4f}")
                    if price_diff <= price_tolerance:
                        existing_amount = existing_amt
                        matched_price = existing_price
                        logger.info(f"  ✓ 找到匹配价格: ${matched_price:.4f}")
                        break

                # 检查是否已存在足够数量的止盈订单
                if existing_amount >= expected_amount:
                    logger.info(f"第{tp_level['level']}级止盈订单已存在且数量足够，价格: ${expected_price:.2f} (匹配价格: ${matched_price:.2f}), 数量: {existing_amount}/{expected_amount}")
                    # 记录订单信息到仓位
                    for order in tp_orders:
                        if abs(order.price - matched_price) <= price_tolerance:
                            current_position.tp_orders_info[order.order_id] = {
                                'level': tp_level['level'],
                                'amount': existing_amount,
                                'price': matched_price,
                                'ratio': tp_level['ratio'],
                                'profit_pct': tp_level['profit_pct']
                            }
                            break
                    continue
                elif existing_amount > 0:
                    logger.info(f"第{tp_level['level']}级止盈订单存在但数量不足，价格: ${expected_price:.2f} (匹配价格: ${matched_price:.2f}), 现有: {existing_amount}, 需要: {expected_amount}")
                    # 计算需要补充的数量
                    needed_amount = expected_amount - existing_amount
                    tp_amount = needed_amount
                else:
                    logger.info(f"第{tp_level['level']}级止盈订单不存在，需要创建: {expected_amount} 张 @ ${expected_price:.2f}")
                    tp_amount = expected_amount

                # 确定订单方向
                tp_side = TradeSide.SELL if current_position.side == TradeSide.LONG else TradeSide.BUY

                logger.info(f"创建第{tp_level['level']}级止盈订单: {tp_amount} 张 @ ${expected_price:.2f} ({tp_level['profit_pct']:.0f}%)")

                try:
                    tp_result = await self.order_manager.create_take_profit_order(
                        symbol=symbol,
                        side=tp_side,
                        amount=tp_amount,
                        take_profit_price=expected_price,
                        reduce_only=True
                    )

                    if tp_result.success:
                        logger.info(f"✓ 第{tp_level['level']}级止盈订单创建成功: ID={tp_result.order_id}")
                        created_count += 1
                        processed_levels.add(tp_level['level'])  # 标记级别已处理

                        # 更新冷却时间
                        self._last_tp_creation_time[symbol] = time.time()

                        # 存储订单信息
                        current_position.tp_orders_info[tp_result.order_id] = {
                            'level': tp_level['level'],
                            'amount': tp_amount,
                            'price': tp_level['price'],
                            'ratio': tp_level['ratio'],
                            'profit_pct': tp_level['profit_pct']
                        }
                    else:
                        logger.error(f"✗ 第{tp_level['level']}级止盈订单创建失败: {tp_result.error_message}")

                except Exception as e:
                    logger.error(f"创建第{tp_level['level']}级止盈订单异常: {e}")

            logger.info(f"多级止盈补充创建完成: 成功创建 {created_count} 个新订单")
            logger.info(f"已处理的止盈级别: {sorted(processed_levels)}")
            logger.info(f"更新后的仓位订单信息: {current_position.tp_orders_info}")

            # 如果创建了新订单，等待一段时间避免立即重复检查
            if created_count > 0:
                logger.info(f"等待2秒让新订单被系统确认...")
                await asyncio.sleep(2)

        except Exception as e:
            logger.error(f"多级止盈检查失败: {e}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")

            # 获取当前价格
            current_price = await self._get_current_price(symbol)

            # 计算多级止盈价格
            multi_level_tps = self._get_multi_level_take_profit_prices(
                current_position.entry_price, current_price, current_position.side
            )

            if not multi_level_tps:
                logger.warning("未获取到多级止盈配置，使用传统单级止盈")
                return

            logger.info(f"多级止盈检查: 配置 {len(multi_level_tps)} 个级别，现有 {len(existing_orders)} 个算法订单")
            logger.info(f"仓位订单信息: {current_position.tp_orders_info}")

            # 统计订单类型
            tp_orders = []
            for order in existing_orders:
                if ((current_position.side == TradeSide.LONG and order.side == TradeSide.SELL and order.price > current_price) or
                    (current_position.side == TradeSide.SHORT and order.side == TradeSide.BUY and order.price < current_price)):
                    tp_orders.append(order)
            logger.info(f"其中识别为止盈订单的有 {len(tp_orders)} 个")
            for i, order in enumerate(tp_orders):
                logger.info(f"  止盈订单 {i+1}: ID={order.order_id}, 价格=${order.price:.4f}, 数量={getattr(order, 'amount', 0)}")

            # 确保tp_orders_info已初始化
            if not current_position.tp_orders_info:
                current_position.tp_orders_info = {}

            # 获取已存在的止盈订单价格和总数量（按价格分组）
            existing_tp_orders = {}  # {price: total_amount}

            # 只处理止盈订单（基于价格和方向判断）
            for order in existing_orders:
                # 检查订单方向是否与仓位方向相反（止盈订单应该与仓位方向相反）
                if ((current_position.side == TradeSide.LONG and order.side == TradeSide.SELL and order.price > current_price) or
                    (current_position.side == TradeSide.SHORT and order.side == TradeSide.BUY and order.price < current_price)):
                    # 使用原始价格作为键，不进行四舍五入
                    price_key = order.price
                    if price_key not in existing_tp_orders:
                        existing_tp_orders[price_key] = 0
                    existing_tp_orders[price_key] += getattr(order, 'amount', 0) or 0

            logger.info(f"已存在的止盈订单（按价格汇总）: {existing_tp_orders}")

            # 检查每个止盈级别 - 添加级别跟踪避免重复
            created_count = 0
            processed_levels = set()  # 跟踪已处理的级别
            for tp_level in multi_level_tps:
                # 检查是否已经处理过这个级别
                if tp_level['level'] in processed_levels:
                    logger.info(f"级别 {tp_level['level']} 已处理过，跳过")
                    continue
                expected_price = tp_level['price']
                expected_amount = current_position.amount * tp_level['ratio']
                expected_amount = round(expected_amount, 2)

                # 使用更严格的价格容差匹配（0.01），更好识别不同级别的订单
                price_tolerance = 0.01  # 严格容差，更好区分不同级别
                existing_amount = 0
                matched_price = None

                # 查找最接近的价格
                logger.info(f"第{tp_level['level']}级止盈检查 - 期望价格: ${expected_price:.4f}, 容差: ±{price_tolerance}")
                for existing_price, existing_amt in existing_tp_orders.items():
                    price_diff = abs(existing_price - expected_price)
                    logger.info(f"  对比现有价格: ${existing_price:.4f}, 差异: ${price_diff:.4f}")
                    if price_diff <= price_tolerance:
                        existing_amount = existing_amt
                        matched_price = existing_price
                        logger.info(f"  ✓ 找到匹配价格: ${matched_price:.4f}")
                        break

                # 检查是否已存在足够数量的止盈订单
                if existing_amount >= expected_amount:
                    logger.info(f"第{tp_level['level']}级止盈订单已存在且数量足够，价格: ${expected_price:.2f} (匹配价格: ${matched_price:.2f}), 数量: {existing_amount}/{expected_amount}")
                    # 确保订单信息已记录
                    if matched_price and str(matched_price) not in current_position.tp_orders_info:
                        # 查找匹配的订单ID
                        for order in tp_orders:
                            if abs(order.price - matched_price) <= price_tolerance:
                                current_position.tp_orders_info[order.order_id] = {
                                    'level': tp_level['level'],
                                    'amount': existing_amount,
                                    'price': matched_price,
                                    'ratio': tp_level['ratio'],
                                    'profit_pct': tp_level['profit_pct']
                                }
                                break
                    continue
                elif existing_amount > 0:
                    logger.info(f"第{tp_level['level']}级止盈订单存在但数量不足，价格: ${expected_price:.2f} (匹配价格: ${matched_price:.2f}), 现有: {existing_amount}, 需要: {expected_amount}")
                    # 计算需要补充的数量
                    needed_amount = expected_amount - existing_amount
                    tp_amount = needed_amount
                else:
                    logger.info(f"第{tp_level['level']}级止盈订单不存在，需要创建: {expected_amount} 张 @ ${expected_price:.2f}")
                    tp_amount = expected_amount

                # 确定订单方向
                tp_side = TradeSide.SELL if current_position.side == TradeSide.LONG else TradeSide.BUY

                logger.info(f"创建第{tp_level['level']}级止盈订单: {tp_amount} 张 @ ${expected_price:.2f} ({tp_level['profit_pct']:.0f}%)")

                try:
                    tp_result = await self.order_manager.create_take_profit_order(
                        symbol=symbol,
                        side=tp_side,
                        amount=tp_amount,
                        take_profit_price=expected_price,
                        reduce_only=True
                    )

                    if tp_result.success:
                        logger.info(f"✓ 第{tp_level['level']}级止盈订单创建成功: ID={tp_result.order_id}")
                        created_count += 1
                        processed_levels.add(tp_level['level'])  # 标记级别已处理

                        # 更新冷却时间
                        self._last_tp_creation_time[symbol] = time.time()

                        # 存储订单信息
                        current_position.tp_orders_info[tp_result.order_id] = {
                            'level': tp_level['level'],
                            'amount': tp_amount,
                            'price': tp_level['price'],
                            'ratio': tp_level['ratio'],
                            'profit_pct': tp_level['profit_pct']
                        }
                    else:
                        logger.error(f"✗ 第{tp_level['level']}级止盈订单创建失败: {tp_result.error_message}")

                except Exception as e:
                    logger.error(f"创建第{tp_level['level']}级止盈订单异常: {e}")

            logger.info(f"多级止盈补充创建完成: 成功创建 {created_count} 个新订单")
            logger.info(f"已处理的止盈级别: {sorted(processed_levels)}")
            logger.info(f"更新后的仓位订单信息: {current_position.tp_orders_info}")

            # 如果创建了新订单，等待一段时间避免立即重复检查
            if created_count > 0:
                logger.info(f"等待2秒让新订单被系统确认...")
                await asyncio.sleep(2)

        except Exception as e:
            logger.error(f"多级止盈检查失败: {e}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")

    async def monitor_filled_tp_orders(self, symbol: str) -> None:
        """监控已成交的止盈订单，处理多级止盈逻辑"""
        try:
            position = self.position_manager.get_position(symbol)
            if not position or not position.tp_orders_info:
                return

            # 获取所有算法订单
            algo_orders = await self.order_manager.fetch_algo_orders(symbol)

            # 检查每个止盈订单的状态
            for order_id, tp_info in list(position.tp_orders_info.items()):
                # 在现有订单中查找该订单
                order_exists = any(order.order_id == order_id for order in algo_orders)

                if not order_exists:
                    # 订单不存在，可能是已成交或被取消
                    logger.info(f"检测到止盈订单 {order_id} 已不存在，可能是已成交")

                    # 检查是否已记录此级别
                    if tp_info['level'] not in position.tp_levels_hit:
                        # 执行部分平仓
                        logger.info(f"执行第{tp_info['level']}级止盈部分平仓: {tp_info['amount']} 张")
                        success = await self.position_manager.partial_close_position(
                            self.exchange_client,
                            symbol,
                            tp_info['amount'],
                            tp_level=tp_info['level']
                        )

                        if success:
                            logger.info(f"✓ 第{tp_info['level']}级止盈部分平仓成功")
                            # 从订单信息中移除已处理的订单
                            del position.tp_orders_info[order_id]
                        else:
                            logger.error(f"✗ 第{tp_info['level']}级止盈部分平仓失败")

            # 检查是否所有止盈级别都已触发
            from ...config import load_config
            config = load_config()
            if config.strategies.profit_taking_strategy == 'multi_level' and config.strategies.profit_taking_levels:
                total_levels = len(config.strategies.profit_taking_levels)
                hit_levels = len(position.tp_levels_hit)
                logger.info(f"多级止盈进度: {hit_levels}/{total_levels} 个级别已触发")

                if hit_levels >= total_levels:
                    logger.info(f"所有 {total_levels} 个止盈级别均已触发，仓位剩余: {position.amount} 张")
                    # 可以选择关闭剩余的止损订单

        except Exception as e:
            logger.error(f"监控止盈订单失败: {e}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")

    async def check_and_create_missing_tp_sl(self, symbol: str, current_position: PositionInfo) -> None:
        """检查并为没有止盈止损订单的持仓创建订单 - 支持多级止盈"""
        try:
            if not current_position or current_position.amount <= 0:
                return

            # 获取现有的算法订单
            existing_orders = await self.order_manager.fetch_algo_orders(symbol)
            logger.info(f"检查持仓 {symbol} 的止盈止损订单状态，找到 {len(existing_orders)} 个现有算法订单")

            # 检查是否启用多级止盈策略
            from ...config import load_config
            config = load_config()

            if config.strategies.profit_taking_strategy == 'multi_level':
                # 多级止盈策略：检查需要补充创建的止盈订单
                await self._check_and_create_multi_level_tp_sl(symbol, current_position, existing_orders)
                return

            # 传统单级止盈策略（原有逻辑）
            # 检查是否有止盈或止损订单
            has_tp = False
            has_sl = False

            for order in existing_orders:
                if current_position.side == TradeSide.LONG:
                    if order.price > current_position.mark_price:
                        has_tp = True
                    elif order.price < current_position.mark_price:
                        has_sl = True
                else:  # SHORT
                    if order.price < current_position.mark_price:
                        has_tp = True
                    elif order.price > current_position.mark_price:
                        has_sl = True

            # 如果没有止盈或止损订单，创建它们
            if not has_tp or not has_sl:
                logger.warning(f"持仓 {symbol} 缺少止盈止损订单（TP: {has_tp}, SL: {has_sl}），正在创建...")

                # 获取当前价格
                current_price = await self._get_current_price(symbol)

                # 计算止盈止损价格
                take_profit_pct, stop_loss_pct = self._get_tp_sl_percentages()

                if current_position.side == TradeSide.LONG:
                    new_take_profit = current_price * (1 + take_profit_pct)
                    new_stop_loss = current_position.entry_price * (1 - stop_loss_pct)
                    tp_side = TradeSide.SELL
                    sl_side = TradeSide.SELL
                else:  # SHORT
                    new_take_profit = current_price * (1 - take_profit_pct)
                    new_stop_loss = current_position.entry_price * (1 + stop_loss_pct)
                    tp_side = TradeSide.BUY
                    sl_side = TradeSide.BUY

                # 创建缺失的订单
                created_count = 0

                if not has_tp:
                    logger.info(f"创建止盈订单: {symbol} {tp_side.value} {current_position.amount} @ ${new_take_profit:.2f}")
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
                        processed_levels.add(tp_level['level'])  # 标记级别已处理
                    else:
                        logger.error(f"✗ 止盈订单创建失败: {tp_result.error_message}")

                if not has_sl:
                    logger.info(f"创建止损订单: {symbol} {sl_side.value} {current_position.amount} @ ${new_stop_loss:.2f}")
                    sl_result = await self.order_manager.create_stop_order(
                        symbol=symbol,
                        side=sl_side,
                        amount=current_position.amount,
                        stop_price=new_stop_loss,
                        reduce_only=True
                    )
                    if sl_result.success:
                        logger.info(f"✓ 止损订单创建成功: ID={sl_result.order_id}")
                        created_count += 1
                        processed_levels.add(tp_level['level'])  # 标记级别已处理
                    else:
                        logger.error(f"✗ 止损订单创建失败: {sl_result.error_message}")

                logger.info(f"止盈止损订单创建完成: 创建了 {created_count} 个新订单")

        except Exception as e:
            logger.error(f"检查并创建缺失的止盈止损订单失败: {e}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")

    async def _check_and_update_tp_sl(self, symbol: str, side: TradeSide, current_position: PositionInfo, min_price_change_pct: float = 0.01) -> None:
        """检查并更新止盈止损 - 实现追踪止损逻辑"""
        try:
            # 确保属性存在
            if not hasattr(self, '_last_tp_update_time'):
                self._last_tp_update_time: Dict[str, datetime] = {}

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

            # 检查是否启用了多级止盈策略
            is_multi_level = self._get_multi_level_take_profit_prices(current_position.entry_price, current_price, current_position.side)

            # 追踪止损策略：根据价格变动动态调整止损
            if current_position.side == TradeSide.LONG:
                if is_multi_level:
                    # 多级止盈：使用固定价格，不随当前价格变动
                    new_take_profit = current_position.entry_price * (1 + take_profit_pct)  # 基于入场价（固定）
                else:
                    # 单级止盈：基于当前价格（动态）
                    new_take_profit = current_price * (1 + take_profit_pct)  # 止盈：基于当前价（动态）

                # 追踪止损逻辑
                if current_price > entry_price:
                    # 价格上涨超过入场价：止损同步上涨
                    # 止损价 = 当前价 × (1 - 止损百分比)
                    new_stop_loss = current_price * (1 - stop_loss_pct)
                    logger.info(f"价格上涨超过入场价，止损同步上涨至: ${new_stop_loss:.2f}")
                else:
                    # 价格未超过入场价：保持入场时的固定止损
                    new_stop_loss = entry_price * (1 - stop_loss_pct)
                    logger.info(f"价格未超过入场价，保持固定止损: ${new_stop_loss:.2f}")

                tp_side = TradeSide.SELL
                sl_side = TradeSide.SELL

            else:  # SHORT
                if is_multi_level:
                    # 多级止盈：使用固定价格，不随当前价格变动
                    new_take_profit = current_position.entry_price * (1 - take_profit_pct)  # 基于入场价（固定）
                else:
                    # 单级止盈：基于当前价格（动态）
                    new_take_profit = current_price * (1 - take_profit_pct)  # 止盈：基于当前价（动态）

                # 追踪止损逻辑
                if current_price < entry_price:
                    # 价格下跌低于入场价：止损同步下跌
                    # 止损价 = 当前价 × (1 + 止损百分比)
                    new_stop_loss = current_price * (1 + stop_loss_pct)
                    logger.info(f"价格下跌低于入场价，止损同步下跌至: ${new_stop_loss:.2f}")
                else:
                    # 价格未低于入场价：保持入场时的固定止损
                    new_stop_loss = entry_price * (1 + stop_loss_pct)
                    logger.info(f"价格未低于入场价，保持固定止损: ${new_stop_loss:.2f}")

                tp_side = TradeSide.BUY
                sl_side = TradeSide.BUY

            logger.info(f"当前持仓: {symbol} {current_position.side.value} {current_position.amount} 张")
            logger.info(f"追踪止损策略 - 持仓均价: ${entry_price:.2f}, 当前价格: ${current_price:.2f}")
            if is_multi_level:
                logger.info(f"- 多级止盈策略：固定价格，不随价格变动")
            else:
                logger.info(f"- 止盈: ${new_take_profit:.2f} (基于当前价 +{take_profit_pct*100:.0f}%) - 动态更新")
            logger.info(f"- 止损: ${new_stop_loss:.2f} (追踪止损 -{stop_loss_pct*100:.0f}%) - 动态调整")

            # 获取现有的算法订单
            existing_orders = await self.order_manager.fetch_algo_orders(symbol)
            logger.info(f"找到 {len(existing_orders)} 个现有算法订单")

            # 分离止盈和止损订单
            current_tp_price = None
            current_sl_price = None

            for order in existing_orders:
                # 通过触发价格与当前价格的关系来判断是止盈还是止损订单
                if current_position.side == TradeSide.LONG:
                    if order.price > current_price:
                        current_tp_price = order.price
                    elif order.price < current_price:
                        current_sl_price = order.price
                else:  # SHORT
                    if order.price < current_price:
                        current_tp_price = order.price
                    elif order.price > current_price:
                        current_sl_price = order.price

            # 检查止盈价格变动是否达到阈值
            if current_tp_price:
                price_change_pct = abs(current_price - current_tp_price) / current_tp_price
                if price_change_pct < min_price_change_pct:
                    logger.info(f"价格变动 {price_change_pct*100:.2f}% 小于阈值 {min_price_change_pct*100:.2f}%，跳过止盈更新")
                    return
                else:
                    logger.info(f"价格变动 {price_change_pct*100:.2f}% 达到阈值 {min_price_change_pct*100:.2f}%，需要更新止盈")

            # 检查是否需要更新止损（追踪止损逻辑）
            if current_sl_price:
                # 计算当前价格与入场价的关系
                price_vs_entry_pct = (current_price - entry_price) / entry_price

                if current_position.side == TradeSide.LONG:
                    # 多头：价格上涨超过入场价时追踪止损
                    if current_price > entry_price:
                        # 计算当前止损与入场价的关系
                        current_sl_vs_entry_pct = (current_sl_price - entry_price) / entry_price

                        # 如果当前止损仍低于入场价，需要更新
                        if current_sl_price < entry_price * (1 - stop_loss_pct):
                            logger.info(f"价格已上涨，需要更新追踪止损")
                        else:
                            logger.info(f"当前止损已追踪上涨，无需更新")
                    else:
                        logger.info(f"价格未超过入场价，保持固定止损")
                else:  # SHORT
                    # 空头：价格下跌低于入场价时追踪止损
                    if current_price < entry_price:
                        # 计算当前止损与入场价的关系
                        current_sl_vs_entry_pct = (current_sl_price - entry_price) / entry_price

                        # 如果当前止损仍高于入场价，需要更新
                        if current_sl_price > entry_price * (1 + stop_loss_pct):
                            logger.info(f"价格已下跌，需要更新追踪止损")
                        else:
                            logger.info(f"当前止损已追踪下跌，无需更新")
                    else:
                        logger.info(f"价格未低于入场价，保持固定止损")

            # 打印订单详情以便调试
            for i, order in enumerate(existing_orders):
                logger.info(f"订单 {i+1}: ID={order.order_id}, 价格={order.price}, 方向={order.side.value}")

            # 检查是否启用了多级止盈策略
            is_multi_level = self._get_multi_level_take_profit_prices(current_position.entry_price, current_price, current_position.side)

            # 如果是多级止盈策略，不清理订单
            if is_multi_level:
                logger.info("检测到多级止盈策略，跳过订单清理")
            else:
                # 传统单级止盈策略的清理逻辑
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
                    logger.warning(f"检测到 {len(tp_orders)} 个单级止盈订单，将清理重复订单")
                    # 按订单ID排序（假设ID越大越新）
                    tp_orders.sort(key=lambda x: x.order_id, reverse=True)
                    # 保留第一个（最新的），取消其余的
                    for order in tp_orders[1:]:
                        logger.info(f"取消重复的止盈订单: {order.order_id}")
                        await self.order_manager.cancel_algo_order(order.order_id, symbol)
                        # 从现有订单列表中移除
                        existing_orders = [o for o in existing_orders if o.order_id != order.order_id]

            # 初始化变量，避免未定义错误
            current_tp = None
            current_sl = None

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

            # 检查是否启用了多级止盈策略
            is_multi_level = self._get_multi_level_take_profit_prices(current_position.entry_price, current_price, current_position.side)

            if is_multi_level:
                # 多级止盈策略：固定价格，不随价格变动更新
                logger.info("多级止盈策略：固定价格，不随价格变动更新")
                tp_needs_update = False
                sl_needs_update = False  # 多级策略下不更新止损

                # 只在首次或确实缺失订单时补充创建
                # 优化：通过实际检测到的止盈订单数量来判断是否需要补充
                actual_tp_orders = []
                for order in existing_orders:
                    # 精确识别止盈订单
                    if current_position.side == TradeSide.LONG:
                        if order.side == TradeSide.SELL and order.price > current_price:
                            # 进一步验证是否为止盈订单（价格应显著高于入场价）
                            price_diff_from_entry = (order.price - current_position.entry_price) / current_position.entry_price
                            if price_diff_from_entry > 0.005:  # 高于入场价0.5%以上
                                actual_tp_orders.append(order)
                    else:  # SHORT
                        if order.side == TradeSide.BUY and order.price < current_price:
                            price_diff_from_entry = (current_position.entry_price - order.price) / current_position.entry_price
                            if price_diff_from_entry > 0.005:
                                actual_tp_orders.append(order)

                if len(actual_tp_orders) < len(is_multi_level):
                    logger.info(f"多级止盈缺失订单：已检测到 {len(actual_tp_orders)} 个止盈订单，需要 {len(is_multi_level)} 个")
                    # 调用补充创建逻辑
                    await self._check_and_create_multi_level_tp_sl(symbol, current_position, existing_orders)
                else:
                    logger.info(f"多级止盈订单完整：已检测到 {len(actual_tp_orders)} 个止盈订单，无需补充创建")
            else:
                # 单级止盈策略：追踪止损逻辑
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

            # 检查现有止损订单（追踪止损逻辑）
            if current_sl:
                # 追踪止损逻辑：检查是否需要更新止损价格
                current_sl_price = current_sl['triggerPx']

                if current_position.side == TradeSide.LONG:
                    # 多头：价格上涨超过入场价时追踪止损
                    if current_price > entry_price:
                        # 计算新的追踪止损价格（基于当前价格）
                        expected_sl_price = current_price * (1 - stop_loss_pct)

                        # 真正的追踪止损：只上升不下降
                        # 只有当新的止损价高于当前止损价时才更新
                        if expected_sl_price > current_sl_price:
                            # 检查价格差异是否超过阈值（0.1%）
                            price_diff_pct = (expected_sl_price - current_sl_price) / current_sl_price
                            if price_diff_pct > 0.001:  # 0.1% 阈值
                                sl_needs_update = True
                                logger.info(f"价格上涨，追踪止损上移: 当前=${current_sl_price:.2f} → 新=${expected_sl_price:.2f}")
                            else:
                                logger.info(f"价格上涨幅度太小，追踪止损保持: ${current_sl_price:.2f}")
                        else:
                            # 新的追踪止损价低于当前止损价，不更新（保持只升不降原则）
                            logger.info(f"价格回调，追踪止损保持不动: ${current_sl_price:.2f} (新计算价=${expected_sl_price:.2f})")
                    else:
                        logger.info(f"价格未超过入场价，保持固定止损: ${current_sl_price:.2f}")
                else:  # SHORT
                    # 空头：价格下跌低于入场价时追踪止损
                    if current_price < entry_price:
                        # 计算新的追踪止损价格（基于当前价格）
                        expected_sl_price = current_price * (1 + stop_loss_pct)

                        # 真正的追踪止损：只下降不上升（空头逻辑相反）
                        # 只有当新的止损价低于当前止损价时才更新
                        if expected_sl_price < current_sl_price:
                            # 检查价格差异是否超过阈值（0.1%）
                            price_diff_pct = (current_sl_price - expected_sl_price) / current_sl_price
                            if price_diff_pct > 0.001:  # 0.1% 阈值
                                sl_needs_update = True
                                logger.info(f"价格下跌，追踪止损下移: 当前=${current_sl_price:.2f} → 新=${expected_sl_price:.2f}")
                            else:
                                logger.info(f"价格下跌幅度太小，追踪止损保持: ${current_sl_price:.2f}")
                        else:
                            # 新的追踪止损价高于当前止损价，不更新（保持只降不升原则）
                            logger.info(f"价格反弹，追踪止损保持不动: ${current_sl_price:.2f} (新计算价=${expected_sl_price:.2f})")
                    else:
                        logger.info(f"价格未低于入场价，保持固定止损: ${current_sl_price:.2f}")
            else:
                # 没有现有止损订单，需要创建
                sl_needs_update = True
                logger.info("没有找到现有止损订单，需要创建")

            # 更新止盈和止损订单（追踪止损实现）
            created_count = 0
            updated_count = 0

            # 更新止盈订单
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

            # 更新止损订单（追踪止损逻辑）
            if sl_needs_update:
                if current_sl:
                    # 取消现有止损订单
                    logger.info(f"取消现有止损订单: {current_sl['algoId']}")
                    await self.order_manager.cancel_algo_order(current_sl['algoId'], symbol)

                # 创建新的止损订单
                logger.info(f"创建新止损订单: {symbol} {sl_side.value} {current_position.amount} @ ${new_stop_loss:.2f}")
                sl_result = await self.order_manager.create_stop_order(
                    symbol=symbol,
                    side=sl_side,
                    amount=current_position.amount,
                    stop_price=new_stop_loss,
                    reduce_only=True
                )

                if sl_result.success:
                    logger.info(f"✓ 止损订单创建成功: ID={sl_result.order_id}")
                    updated_count += 1
                else:
                    logger.error(f"✗ 止损订单创建失败: {sl_result.error_message}")

            logger.info(f"止盈止损更新完成: {created_count} 个新止盈订单, {updated_count} 个新止损订单已创建")

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

            # 检查是否启用多级止盈策略
            multi_level_tps = self._get_multi_level_take_profit_prices(entry_price, current_price, side)

            logger.info(f"多级止盈计算结果: {len(multi_level_tps)} 个级别")
            for i, tp in enumerate(multi_level_tps):
                logger.info(f"  级别 {i+1}: 价格=${tp['price']:.2f}, 比例={tp['ratio']}, 盈利={tp['profit_pct']:.1f}%")

            if multi_level_tps:
                # 使用多级止盈策略
                logger.info(f"创建新仓位的多级止盈止损订单: {symbol}")
                logger.info(f"多级止盈策略 - 入场价: ${entry_price:.2f}, 当前价: ${current_price:.2f}")

                # 创建多级止盈订单
                created_tp_count = 0
                logger.info(f"开始创建 {len(multi_level_tps)} 个多级止盈订单...")

                for tp_level in multi_level_tps:
                # 检查是否已经处理过这个级别
                if tp_level['level'] in processed_levels:
                    logger.info(f"级别 {tp_level['level']} 已处理过，跳过")
                    continue
                    tp_amount = order_result.filled_amount * tp_level['ratio']
                    # 确保数量精度符合交易所要求
                    tp_amount = round(tp_amount, 2)  # 保留2位小数，OKX精度为0.01

                    logger.info(f"创建第{tp_level['level']}级止盈订单: {tp_amount} 张 @ ${tp_level['price']:.2f} ({tp_level['profit_pct']:.0f}%)")

                    tp_side = TradeSide.SELL if side == TradeSide.BUY else TradeSide.BUY

                    try:
                        tp_result = await self.order_manager.create_take_profit_order(
                            symbol=symbol,
                            side=tp_side,
                            amount=tp_amount,
                            take_profit_price=tp_level['price'],
                            reduce_only=True
                        )

                        if tp_result.success:
                            logger.info(f"✓ 第{tp_level['level']}级止盈订单创建成功: ID={tp_result.order_id}")
                            created_tp_count += 1

                            # 存储止盈订单信息到仓位
                            current_position = self.position_manager.get_position(symbol)
                            if current_position:
                                current_position.tp_orders_info[tp_result.order_id] = {
                                    'level': tp_level['level'],
                                    'amount': tp_amount,
                                    'price': tp_level['price'],
                                    'ratio': tp_level['ratio'],
                                    'profit_pct': tp_level['profit_pct']
                                }
                                logger.info(f"已存储第{tp_level['level']}级止盈订单信息到仓位追踪")
                        else:
                            logger.error(f"✗ 第{tp_level['level']}级止盈订单创建失败: {tp_result.error_message}")
                    except Exception as e:
                        logger.error(f"创建第{tp_level['level']}级止盈订单时发生异常: {e}")
                        import traceback
                        logger.error(f"详细错误: {traceback.format_exc()}")

                logger.info(f"多级止盈订单创建完成: 成功创建 {created_tp_count}/{len(multi_level_tps)} 个订单")

            else:
                # 使用传统单级止盈策略
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

            # 创建止损订单（无论使用哪种止盈策略，止损都是单一的）
            if side == TradeSide.BUY:
                stop_loss = entry_price * (1 - stop_loss_pct)
                sl_side = TradeSide.SELL
            else:
                stop_loss = entry_price * (1 + stop_loss_pct)
                sl_side = TradeSide.BUY

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
async def create_trade_executor(exchange_client, order_manager, position_manager, risk_manager, config=None) -> TradeExecutor:
    """创建交易执行器实例"""
    executor = TradeExecutor(exchange_client, order_manager, position_manager, risk_manager, config)
    await executor.initialize()
    return executor