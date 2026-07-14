"""
精简版交易机器人主类
核心逻辑：
1. 15分钟周期执行（随机偏移±3分钟）
2. 调用AI获取信号（buy/hold/sell）
3. 信号处理
4. 止损订单管理
"""

import asyncio
import logging
from typing import Optional

from .trading_scheduler import TradingScheduler
from .signal_processor import SignalProcessor
from .position_manager import PositionManager
from .stop_loss_manager import StopLossManager
from ..config.models import Config
from ..utils.observability import record_live_guard_block

logger = logging.getLogger(__name__)


class TradingBot:
    """精简版交易机器人"""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config.from_env()
        self._running = False
        self._initialized = False

        # 使用独立的组件
        self.scheduler = TradingScheduler(config)
        self.position_manager = PositionManager(config)
        self._stop_loss_manager: Optional[StopLossManager] = None

    @property
    def exchange(self):
        """获取交易所客户端（延迟初始化）"""
        return getattr(self, "_exchange", None)

    @property
    def ai_client(self):
        """获取AI客户端（延迟初始化）"""
        return getattr(self, "_ai_client", None)

    async def initialize(self) -> bool:
        """初始化交易所和AI客户端"""
        try:
            logger.info("初始化交易机器人...")

            from ..exchange.client import ExchangeClient

            self._exchange = ExchangeClient(
                api_key=self.config.exchange.api_key,
                secret=self.config.exchange.secret,
                password=self.config.exchange.password,
                symbol=self.config.exchange.symbol,
                allow_short_selling=self.config.trading.allow_short_selling,
                test_mode=self.config.trading.test_mode,
                max_position_usage=self.config.exchange.max_position_usage,
                order_confirm_timeout_seconds=(
                    self.config.trading.order_confirm_timeout_seconds
                ),
                order_confirm_poll_interval_seconds=(
                    self.config.trading.order_confirm_poll_interval_seconds
                ),
            )
            await self._exchange.initialize()
            await self._exchange.set_leverage(self.config.exchange.leverage)

            self._stop_loss_manager = StopLossManager(
                self._exchange, self.config, self.position_manager
            )

            from ..ai.client import AIClient

            self._ai_client = AIClient(
                config=self.config.ai, api_keys=self.config.ai.api_keys
            )

            # 检查止损单恢复
            await self._check_stop_order_recovery()

            self._initialized = True
            logger.info("初始化完成")
            return True

        except Exception as e:
            logger.error(f"初始化失败: {e}")
            return False

    async def _check_stop_order_recovery(self) -> None:
        """检查并恢复止损单"""
        # 从交易所获取最新持仓状态
        try:
            position_data = await self._exchange.get_position()
        except Exception as e:
            logger.error(f"[止损恢复] 获取持仓失败: {e}")
            return
        if position_data:
            self.position_manager.update_from_exchange(position_data)

        # 检查是否需要恢复止损单
        if not self.position_manager.has_position():
            return

        # 查找交易所现有的止损单
        exchange_stop_order_id = await self._get_existing_stop_order_id()

        if exchange_stop_order_id:
            logger.info(f"[止损恢复] 发现交易所止损单: {exchange_stop_order_id}")
            self.position_manager.set_stop_order(exchange_stop_order_id)
        elif self.position_manager.needs_stop_order_recovery():
            logger.warning("[止损恢复] 有持仓但无止损单，需要重建止损单")
            await self._recreate_stop_order()

    async def _recreate_stop_order(self) -> None:
        """重建止损单"""
        position = self.position_manager.position
        if not position:
            return

        # 获取当前价格
        market_data = await self._exchange.get_market_data()
        current_price = market_data.get("price", 0)

        if current_price <= 0:
            logger.error("[止损恢复] 无法获取当前价格")
            return

        # 计算止损价
        stop_price = self.position_manager.calculate_stop_price(current_price)

        logger.info(
            f"[止损恢复] 创建止损单: 止损价={stop_price}, 数量={position.amount}"
        )

        try:
            stop_order_id = await self._exchange.create_stop_loss(
                symbol=self.config.exchange.symbol,
                side="sell",
                amount=position.amount,
                stop_price=stop_price,
            )
            self.position_manager.set_stop_order(stop_order_id)
            logger.info(f"[止损恢复] 止损单重建成功: {stop_order_id}")
        except Exception as e:
            logger.error(f"[止损恢复] 止损单重建失败: {e}")

    async def run(self) -> None:
        """主循环"""
        if not self._initialized:
            if not await self.initialize():
                raise RuntimeError("初始化失败")

        self._running = True
        logger.info("交易机器人启动")

        try:
            first_run = True
            while self._running:
                await self._trading_cycle(first_run=first_run)
                first_run = False

        except asyncio.CancelledError:
            logger.info("收到停止信号")
        finally:
            await self.cleanup()

    # 交易周期全局超时（秒）- 防止 AI 调用或交易所调用挂起导致整个 bot 阻塞
    TRADING_CYCLE_TIMEOUT = 300  # 5分钟

    async def _trading_cycle(self, first_run: bool = False) -> None:
        """单次交易周期（带全局超时保护）"""
        # 1. 等待周期
        await self.scheduler.wait_for_next_cycle(first_run)

        try:
            await asyncio.wait_for(
                self._execute_trading_cycle(),
                timeout=self.TRADING_CYCLE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.error(
                f"[交易周期] 交易周期超时 ({self.TRADING_CYCLE_TIMEOUT}秒)，强制结束本周期"
            )
        except Exception as e:
            logger.error(f"[交易周期] 交易周期异常: {e}")
            logger.exception("详细错误:")

    async def _execute_trading_cycle(self) -> None:
        """执行交易周期的核心逻辑"""

        logger.info("=" * 60)
        logger.info("开始新的交易周期")
        logger.info("=" * 60)

        # 2. 获取市场数据
        market_data = await self._exchange.get_market_data()
        current_price = market_data.get("price", 0)
        change_percent = market_data.get("change_percent", 0)
        recent_drop = market_data.get("recent_drop_percent", 0)
        technical = market_data.get("technical", {})
        rsi = technical.get("rsi") if technical else None
        atr = technical.get("atr") if technical else None

        # 格式化显示
        change_str = f"{change_percent:.2f}%" if change_percent else "N/A"
        recent_drop_str = f"{recent_drop * 100:.2f}%" if recent_drop else "N/A"
        rsi_str = f"{rsi:.2f}" if rsi is not None else "N/A"
        atr_str = f"{atr:.2f}" if atr is not None else "N/A"

        logger.info(f"[市场数据] 当前价格: {current_price}")
        logger.info(f"[市场数据] 24h涨跌幅: {change_str}")
        logger.info(f"[市场数据] 1h涨跌幅: {recent_drop_str}")
        logger.info(f"[市场数据] RSI: {rsi_str}")
        logger.info(f"[市场数据] ATR: {atr_str}")

        # 3. 检查当前持仓状态
        try:
            position_data = await self._exchange.get_position()
            api_query_failed = False
        except Exception as e:
            logger.error(f"[持仓状态] 获取持仓失败: {e}")
            position_data = None
            api_query_failed = True
        if position_data:
            self.position_manager.update_from_exchange(position_data)
        elif api_query_failed:
            logger.warning(
                "[持仓对账] API查询持仓失败，保留本地持仓状态不清理，"
                "等待下一周期重试"
            )
        else:
            if self.position_manager.has_position():
                logger.warning(
                    "[持仓对账] API返回无持仓，但本地PositionManager仍有持仓状态，"
                    f"清理本地缓存。本地持仓: "
                    f"方向={self.position_manager.position.side if self.position_manager.position else 'N/A'}, "
                    f"入场价={self.position_manager.entry_price}"
                )
            self.position_manager.update_from_exchange({})
        has_position = self.position_manager.has_position()

        if has_position:
            pm = self.position_manager
            position_info = pm.position
            if position_info is None:
                logger.error(
                    "[持仓状态] 数据不一致: has_position=True 但 position 为 None"
                )
                return
            logger.info(
                "[持仓状态] 持仓中 - "
                f"方向:{position_info.side}, 数量:{position_info.amount}张, "
                f"入场价:{position_info.entry_price}"
            )
            position_context = pm.get_position_context(current_price)
            unrealized_pnl = position_info.unrealized_pnl
            pnl_percent = position_context.get("pnl_percent", 0)
            duration_hours = position_context.get("duration_hours", 0)
            health = position_context.get("health", "unknown")
            logger.info(
                f"[持仓状态] 未实现盈亏: {unrealized_pnl:.2f} USDT ({pnl_percent:.2f}%), "
                f"持仓时长: {duration_hours:.1f}小时, 健康度: {health}"
            )
            market_data["position"] = position_context
        else:
            logger.info("[持仓状态] 无持仓")
            market_data["position"] = {}

        logger.info(f"[交易决策] 当前价格: {current_price}")

        # 4. 获取AI信号
        try:
            logger.info("[AI信号] 正在获取交易信号...")
            signal = await self._ai_client.get_signal(market_data)
            signal = SignalProcessor.process(signal)
            logger.info(f"[AI信号] 原始信号: {signal}")

            # 5. 处理信号
            await self._execute_signal(signal, current_price, has_position)
        except Exception as e:
            logger.error(f"[交易周期] 获取/处理AI信号时出错: {e}")
            logger.exception("详细错误:")
            return  # 直接返回，跳过后续处理

        logger.info("交易周期完成")
        logger.info("=" * 60)

    async def _execute_signal(
        self, signal: str, current_price: float, has_position: bool
    ) -> None:
        """执行信号"""
        logger.info(
            f"[信号执行] 开始处理信号: {signal}, 当前价格: {current_price}, "
            f"持仓状态: {'有持仓' if has_position else '无持仓'}"
        )

        if signal == "BUY":
            if not has_position:
                logger.info("[信号执行] BUY信号 + 无持仓 -> 执行开仓")
                await self._open_position(current_price)
            else:
                logger.info("[信号执行] BUY信号 + 有持仓 -> 更新止损")
                await self._update_stop_loss(current_price)

        elif signal == "HOLD":
            if has_position:
                logger.info("[信号执行] HOLD信号 + 有持仓 -> 更新止损")
                await self._update_stop_loss(current_price)
            else:
                logger.info("[信号执行] HOLD信号 + 无持仓 -> 不操作")
                logger.info(
                    "[机会评估] 当前为HOLD信号，系统持续监控中。"
                    "如需更多交易机会，可考虑: 1)缩短CYCLE_MINUTES 2)切换AI_FUSION模式 3)调整INVESTMENT_TYPE=aggressive"
                )

        elif signal == "SELL":
            if has_position:
                logger.info("[信号执行] SELL信号 + 有持仓 -> 执行平仓")
                await self._close_position(current_price)
            else:
                logger.info("[信号执行] SELL信号 + 无持仓 -> 不操作")

        else:
            logger.warning(f"[信号执行] 未知信号: {signal}")

    async def _open_position(self, price: float) -> None:
        """开仓 - 根据余额动态计算交易量

        止损保护：如果止损单创建失败，立即市价平仓，不允许无止损持仓。
        """
        logger.info(f"[开仓] 开始开仓流程, 当前价格: {price}")

        live_allowed, reason = self.config.check_live_trading_preconditions()
        if not live_allowed:
            logger.warning(f"[实盘闸门] 拒绝开仓: {reason}")
            record_live_guard_block()
            return

        amount = await self._exchange.calculate_max_contracts(
            price, self.config.exchange.leverage
        )

        if amount <= 0:
            logger.warning("[开仓] 无法计算有效交易量，取消开仓")
            return

        logger.info(
            f"[开仓] 计算可开合约数: {amount} 张 (杠杆: {self.config.exchange.leverage}x)"
        )

        order_id = await self._exchange.create_order(
            symbol=self.config.exchange.symbol,
            side="buy",
            amount=amount,
            price=None,
        )

        if not order_id:
            logger.error("[开仓] 开仓订单创建失败，取消后续操作")
            return

        # TEST_MODE 模拟订单检测
        from ..exchange.client import ExchangeClient

        if ExchangeClient.is_simulated_order(order_id):
            logger.info(
                f"[模拟交易] ✅ TEST_MODE模拟开仓成功: "
                f"价格={price}, 数量={amount}张, 杠杆={self.config.exchange.leverage}x, "
                f"模拟订单ID={order_id}"
            )
            logger.info(
                f"[模拟交易] 提示: 切换实盘需设置 TEST_MODE=false + "
                f"REAL_TRADING_CONFIRMED=true + RUNTIME_ENVIRONMENT=prod"
            )
            return

        logger.info(f"[开仓] 订单创建成功: 订单ID={order_id}")

        self.position_manager.update_position(
            amount, price, self.config.exchange.symbol
        )

        stop_price = self.position_manager.calculate_stop_price(price)
        logger.info(
            f"[止损计算] 入场价={price}, 止损价={stop_price:.1f} (由PositionManager统一计算)"
        )

        stop_order_id = await self._exchange.create_stop_loss(
            symbol=self.config.exchange.symbol,
            side="sell",
            amount=amount,
            stop_price=stop_price,
        )

        if stop_order_id:
            self.position_manager.set_stop_order(stop_order_id, stop_price)
            logger.info(
                f"[开仓] 开仓完成 - 价格:{price}, 数量:{amount}张, 止损:{stop_price}"
            )
        else:
            logger.critical(
                f"[止损保护] 止损单创建失败！立即市价平仓保护资金安全。"
                f"开仓订单={order_id}, 数量={amount}张"
            )
            try:
                close_order_id = await self._exchange.create_order(
                    symbol=self.config.exchange.symbol,
                    side="sell",
                    amount=amount,
                    price=None,
                )
                if close_order_id:
                    logger.info(f"[止损保护] 紧急平仓成功: {close_order_id}")
                else:
                    logger.critical(
                        "[止损保护] 紧急平仓也失败！需要人工介入检查持仓状态！"
                    )
            except Exception as e:
                logger.critical(
                    f"[止损保护] 紧急平仓异常: {e}！需要人工介入检查持仓状态！"
                )
            finally:
                self.position_manager.clear_position()

    async def _get_existing_stop_order_id(self) -> Optional[str]:
        """查询交易所中现有的止损单ID（委托给StopLossManager）"""
        if self._stop_loss_manager is None:
            return None
        return await self._stop_loss_manager.get_existing_stop_order_id()

    async def _update_stop_loss(self, current_price: float) -> None:
        """更新止损订单（委托给StopLossManager）"""
        if self._stop_loss_manager is None:
            return
        await self._stop_loss_manager.update_stop_loss(current_price)

    async def _create_stop_loss_with_retry(
        self,
        amount: float,
        stop_price: float,
        current_price: float,
        max_retries: int = 2,
    ) -> Optional[str]:
        """创建止损单（委托给StopLossManager）"""
        if self._stop_loss_manager is None:
            return None
        return await self._stop_loss_manager.create_stop_loss_with_retry(
            amount, stop_price, current_price, max_retries
        )

    async def _close_position(self, price: float) -> None:
        """平仓"""
        if not self.position_manager.has_position():
            logger.warning("[平仓] 无持仓，跳过平仓")
            return

        live_allowed, reason = self.config.check_live_trading_preconditions()
        if not live_allowed:
            logger.warning(f"[实盘闸门] 拒绝平仓: {reason}")
            record_live_guard_block()
            return

        position = self.position_manager.position
        if position is None:
            logger.error("[平仓] 数据不一致: has_position=True 但 position 为 None")
            return

        amount = position.amount
        logger.info(f"[平仓] 开始平仓流程, 当前价格: {price}, 数量: {amount}张")

        order_id = await self._exchange.create_order(
            symbol=self.config.exchange.symbol,
            side="sell",
            amount=amount,
            price=None,
        )

        from ..exchange.client import ExchangeClient

        if ExchangeClient.is_simulated_order(order_id):
            logger.info(f"[平仓] TEST_MODE 模拟平仓: ID={order_id}, 跳过状态清理")
            return

        logger.info(f"[平仓] 平仓订单创建成功: 订单ID={order_id}")

        if self.position_manager.stop_order_id:
            logger.info(f"[平仓] 取消旧止损单: {self.position_manager.stop_order_id}")
            try:
                cancel_result = await self._exchange.cancel_algo_order(
                    self.position_manager.stop_order_id, self.config.exchange.symbol
                )
                cancel_success, cancel_reason = cancel_result
                if cancel_success:
                    logger.info("[平仓] 止损单取消成功")
                elif cancel_reason == "already_gone":
                    logger.info("[平仓] 止损单已不存在(可能已触发)")
                else:
                    logger.warning("[平仓] 取消止损单失败")
            except Exception as e:
                logger.warning(f"[平仓] 取消止损单异常: {e}")

        self.position_manager.clear_position()
        logger.info(f"[平仓] 平仓完成 - 价格:{price}, 数量:{amount}张")

    async def cleanup(self) -> None:
        """清理资源"""
        logger.info("清理资源...")
        if hasattr(self, "_exchange"):
            await self._exchange.cleanup()

    async def stop(self) -> None:
        """停止机器人"""
        self._running = False
        logger.info("交易机器人停止")


async def main():
    """入口"""
    import logging

    logging.basicConfig(level=logging.INFO)

    bot = TradingBot()
    try:
        await bot.run()
    except KeyboardInterrupt:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
