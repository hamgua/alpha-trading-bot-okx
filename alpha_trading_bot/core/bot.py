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
from typing import Dict, Any, Optional

from .trading_scheduler import TradingScheduler
from .signal_processor import SignalProcessor, Position
from .position_manager import PositionManager
from ..config.models import Config

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
            )
            await self._exchange.initialize()
            await self._exchange.set_leverage(self.config.exchange.leverage)

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
        position_data = await self._exchange.get_position()
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
        position_data = await self._exchange.get_position()
        if position_data:
            self.position_manager.update_from_exchange(position_data)
        else:
            self.position_manager.update_from_exchange({})
        has_position = self.position_manager.has_position()

        if has_position:
            pm = self.position_manager
            position_info = pm.position
            if position_info is None:
                logger.error("[持仓状态] 数据不一致: has_position=True 但 position 为 None")
                return
            logger.info(
                f"[持仓状态] 持仓中 - 方向:{position_info.side}, 数量:{position_info.amount}张, 入场价:{position_info.entry_price}"
            )
            unrealized_pnl = position_info.unrealized_pnl
            pnl_percent = (
                (current_price - position_info.entry_price)
                / position_info.entry_price
                * 100
                if position_info.entry_price > 0
                else 0
            )
            logger.info(
                f"[持仓状态] 未实现盈亏: {unrealized_pnl:.2f} USDT ({pnl_percent:.2f}%)"
            )
            market_data["position"] = {
                "side": position_info.side,
                "amount": position_info.amount,
                "entry_price": position_info.entry_price,
                "unrealized_pnl": unrealized_pnl,
            }
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
            f"[信号执行] 开始处理信号: {signal}, 当前价格: {current_price}, 持仓状态: {'有持仓' if has_position else '无持仓'}"
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

        elif signal == "SELL":
            if has_position:
                logger.info("[信号执行] SELL信号 + 有持仓 -> 执行平仓")
                await self._close_position(current_price)
            else:
                logger.info("[信号执行] SELL信号 + 无持仓 -> 不操作")

        else:
            logger.warning(f"[信号执行] 未知信号: {signal}")

    async def _open_position(self, price: float) -> None:
        """开仓 - 根据余额动态计算交易量"""
        logger.info(f"[开仓] 开始开仓流程, 当前价格: {price}")

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
        logger.info(f"[开仓] 订单创建成功: 订单ID={order_id}")

        self.position_manager.update_position(
            amount, price, self.config.exchange.symbol
        )

        # 统一使用 PositionManager 计算止损价
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
        logger.info(f"[开仓] 止损单创建成功: 止损ID={stop_order_id}")

        self.position_manager.set_stop_order(stop_order_id, stop_price)
        logger.info(
            f"[开仓] 开仓完成 - 价格:{price}, 数量:{amount}张, 止损:{stop_price}"
        )

    async def _get_existing_stop_order_id(self) -> Optional[str]:
        """查询交易所中现有的止损单ID（同时查询普通订单和算法订单）"""
        symbol = self.config.exchange.symbol
        
        # 优先查询算法订单（OKX 止损单是 algo 订单）
        try:
            algo_orders = await self._exchange.get_algo_orders(symbol)
            for order in algo_orders:
                info = order.get("info", {})
                algo_id = info.get("algoId")
                # 检查是否是止损单 (stop loss)
                if algo_id:
                    stop_price = info.get("slTriggerPx") or info.get("stopLossPrice")
                    if stop_price:
                        logger.info(f"[止损查询] 找到现有止损单(algo): {algo_id}, 止损价={stop_price}")
                        return str(algo_id)
        except Exception as e:
            logger.warning(f"[止损查询] 查询算法订单失败: {e}")
        
        # 备用：查询普通订单
        try:
            open_orders = await self._exchange.get_open_orders(symbol)
            for order in open_orders:
                order_type = (order.get("type") or "").lower()
                info = order.get("info", {})
                has_algo_id = bool(info.get("algoId"))
                has_stop_price = bool(info.get("slTriggerPx") or info.get("stopLossPrice"))

                is_stop_order = (
                    order_type in ["stop_loss", "stop-loss", "trigger", "stop"]
                    or has_algo_id
                    or has_stop_price
                )

                if is_stop_order:
                    stop_order_id = info.get("algoId") or order.get("id")
                    if stop_order_id:
                        logger.info(f"[止损查询] 找到现有止损单: {stop_order_id} (type={order_type})")
                        return str(stop_order_id)
        except Exception as e:
            logger.warning(f"[止损查询] 查询普通订单失败: {e}")
            
        logger.debug("[止损查询] 未找到现有止损单")
        return None

    async def _update_stop_loss(self, current_price: float) -> None:
        """更新止损订单（带容错判断，避免频繁更新）"""
        if not self.position_manager.has_position():
            return

        position = self.position_manager.position
        if position is None:
            logger.error("[止损更新] 数据不一致: has_position=True 但 position 为 None")
            return

        local_stop_order_id = self.position_manager.stop_order_id
        exchange_stop_order_id = await self._get_existing_stop_order_id()

        # 修复重复创建问题：优先信任本地记录，减少交易所查询
        # 如果本地有记录，以本地记录为准进行容错比较
        # 只有在本地没有记录时才尝试从交易所恢复
        if not local_stop_order_id and exchange_stop_order_id:
            logger.info(f"[止损更新] 发现交易所现有止损单: {exchange_stop_order_id}")
            self.position_manager.set_stop_order(exchange_stop_order_id)
            local_stop_order_id = exchange_stop_order_id

        has_existing_stop_order = local_stop_order_id is not None

        new_stop = self.position_manager.calculate_stop_price(current_price)
        self.position_manager.log_stop_loss_info(current_price, new_stop)

        if not has_existing_stop_order:
            logger.info("[止损更新] 当前无止损单，直接创建")
            logger.info(f"[止损更新] 创建新止损单: 止损价={new_stop}")
            stop_order_id = await self._create_stop_loss_with_retry(
                position.amount, new_stop, current_price
            )
            if stop_order_id:
                self.position_manager.set_stop_order(stop_order_id, new_stop)
                logger.info(f"[止损更新] 止损单设置完成: {stop_order_id}")
            else:
                logger.error("[止损更新] 止损单创建失败，已达最大重试次数")
            return

        tolerance = self.config.stop_loss.stop_loss_tolerance_percent

        # 使用上次记录的止损价进行容错比较
        old_stop = self.position_manager.last_stop_price
        
        # 无历史记录时，强制更新（不跳过）
        if old_stop <= 0:
            logger.info(f"[止损更新] 无历史止损价记录，强制创建止损单")
            old_stop = new_stop  # 临时设置为 new_stop 以避免后续计算错误
            force_update = True
        else:
            force_update = False

        price_diff_percent = abs(new_stop - old_stop) / old_stop if old_stop > 0 else 1

        if price_diff_percent < tolerance and not force_update:
            logger.info(
                f"[止损更新] 变化率:{price_diff_percent * 100:.4f}% < 容错:{tolerance * 100}%({tolerance * current_price:.1f}美元), 跳过更新"
            )
            return

        # 以交易所为主导：先查询交易所当前有效的止损单
        old_stop_order_id = self.position_manager.stop_order_id
        current_existing_id = await self._get_existing_stop_order_id()
        
        # 规则1: 交易所存在且和本地旧订单ID一致 -> 取消旧订单 -> 创建新订单
        # 规则2: 交易所不存在，本地旧订单存在 -> 无需取消，直接创建新订单
        # 规则3: 交易所存在，本地不存在 -> 取消交易所订单 -> 创建新订单
        
        # 以交易所为主导：先输出交易所查询结果
        if current_existing_id:
            # 交易所存在有效订单
            logger.info(f"[止损更新] 交易所现有止损单: {current_existing_id}")
            logger.info(f"[止损更新] 取消交易所现有止损单: {current_existing_id}")
            cancel_success = await self._exchange.cancel_order(
                str(current_existing_id), self.config.exchange.symbol
            )
            if not cancel_success:
                logger.warning(f"[止损更新] 取消止损单失败: {current_existing_id}")
        else:
            # 交易所无止损单
            logger.info("[止损更新] 交易所无现有止损单")
            if old_stop_order_id:
                # 交易所不存在，但本地有记录，说明本地记录已失效
                logger.info(f"[止损更新] 本地记录 {old_stop_order_id} 已失效")

        logger.info(f"[止损更新] 创建新止损单: 止损价={new_stop}")
        stop_order_id = await self._exchange.create_stop_loss(
            symbol=self.config.exchange.symbol,
            side="sell",
            amount=position.amount,
            stop_price=new_stop,
        )

        self.position_manager.set_stop_order(stop_order_id, new_stop)
        logger.info(f"[止损更新] 止损单设置完成: {stop_order_id}")

    async def _create_stop_loss_with_retry(
        self,
        amount: float,
        stop_price: float,
        current_price: float,
        max_retries: int = 2,
    ) -> Optional[str]:
        """
        创建止损单（带重试机制）

        如果止损价高于当前价格导致失败，自动降低止损价重试

        Args:
            amount: 合约数量
            stop_price: 初始止损价
            current_price: 当前价格
            max_retries: 最大重试次数

        Returns:
            止损单ID，失败返回None
        """
        for attempt in range(max_retries + 1):
            try:
                stop_order_id = await self._exchange.create_stop_loss(
                    symbol=self.config.exchange.symbol,
                    side="sell",
                    amount=amount,
                    stop_price=stop_price,
                )
                if stop_order_id:
                    return stop_order_id

                if attempt < max_retries:
                    stop_price = stop_price * 0.998
                    logger.warning(
                        f"[止损重试] 第{attempt + 1}次失败，尝试降低止损价至 {stop_price:.1f}"
                    )
            except Exception as e:
                error_msg = str(e)
                if "SL trigger price must be less than the last price" in error_msg:
                    if attempt < max_retries:
                        stop_price = stop_price * 0.998
                        logger.warning(
                            f"[止损重试] 止损价过高，第{attempt + 1}次重试，"
                            f"降低至 {stop_price:.1f} (当前价={current_price:.1f})"
                        )
                        continue
                logger.error(f"[止损重试] 创建止损单失败: {e}")
                break

        return None

    async def _close_position(self, price: float) -> None:
        """平仓"""
        if not self.position_manager.has_position():
            logger.warning("[平仓] 无持仓，跳过平仓")
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
        logger.info(f"[平仓] 平仓订单创建成功: 订单ID={order_id}")

        if self.position_manager.stop_order_id:
            logger.info(f"[平仓] 取消旧止损单: {self.position_manager.stop_order_id}")
            try:
                await self._exchange.cancel_order(
                    self.position_manager.stop_order_id, self.config.exchange.symbol
                )
            except Exception as e:
                logger.warning(f"[平仓] 取消止损单失败: {e}")

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
