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

            self._initialized = True
            logger.info("初始化完成")
            return True

        except Exception as e:
            logger.error(f"初始化失败: {e}")
            return False

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

    async def _trading_cycle(self, first_run: bool = False) -> None:
        """单次交易周期"""
        # 1. 等待周期
        await self.scheduler.wait_for_next_cycle(first_run)

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
            assert position_info is not None, (
                "position_info should not be None when has_position is True"
            )
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

        # 新开仓使用亏损止损比例 (0.5%)
        stop_percent = self.config.stop_loss.stop_loss_percent
        stop_price = price * (1 - stop_percent)
        logger.info(
            f"[止损计算] 入场价={price}, 止损比例={stop_percent * 100}%(新开仓), 止损价={stop_price:.1f}"
        )

        stop_order_id = await self._exchange.create_stop_loss(
            symbol=self.config.exchange.symbol,
            side="sell",
            amount=amount,
            stop_price=stop_price,
        )
        logger.info(f"[开仓] 止损单创建成功: 止损ID={stop_order_id}")

        self.position_manager.set_stop_order(stop_order_id)
        logger.info(
            f"[开仓] 开仓完成 - 价格:{price}, 数量:{amount}张, 止损:{stop_price}"
        )

    async def _update_stop_loss(self, current_price: float) -> None:
        """更新止损订单（带容错判断，避免频繁更新）"""
        if not self.position_manager.has_position():
            return

        position = self.position_manager.position
        assert position is not None, (
            "position should not be None when has_position is True"
        )

        # 计算新止损价
        new_stop = self.position_manager.calculate_stop_price(current_price)
        self.position_manager.log_stop_loss_info(current_price, new_stop)

        # 容错判断：新止损价变化 < 容错比例时跳过更新
        tolerance = self.config.stop_loss.stop_loss_tolerance_percent
        entry_price = position.entry_price

        # 根据盈亏状态计算原止损价
        if current_price >= entry_price:
            old_stop = entry_price * (
                1 - self.config.stop_loss.stop_loss_profit_percent
            )
        else:
            old_stop = entry_price * (1 - self.config.stop_loss.stop_loss_percent)

        # 计算变化百分比
        price_diff_percent = abs(new_stop - old_stop) / old_stop if old_stop > 0 else 1

        if price_diff_percent < tolerance:
            logger.info(
                f"[止损更新] 变化率:{price_diff_percent * 100:.4f}% < 容错:{tolerance * 100}%({tolerance * current_price:.1f}美元), 跳过更新"
            )
            return

        logger.info(
            f"[止损更新] 当前价:{current_price}, 止损价:{new_stop}, 持仓数量:{position.amount}张"
        )

        # 计算新止损价
        new_stop = self.position_manager.calculate_stop_price(current_price)
        self.position_manager.log_stop_loss_info(current_price, new_stop)

        # 获取当前止损单价格
        current_stop = self.position_manager.stop_order_id

        # 容错判断
        tolerance = self.config.stop_loss.stop_loss_tolerance_percent
        if current_stop:
            # 计算容差范围
            tolerance_amount = current_price * tolerance
            diff = abs(new_stop - (current_price * (1 - tolerance)))  # 简化计算

            # 如果新旧止损价差异在容差范围内，跳过更新
            old_stop_price = position.entry_price * (
                1
                - (
                    self.config.stop_loss.stop_loss_profit_percent
                    if current_price > position.entry_price
                    else self.config.stop_loss.stop_loss_percent
                )
            )
            price_diff_percent = (
                abs(new_stop - old_stop_price) / old_stop_price
                if old_stop_price > 0
                else 1
            )

            if price_diff_percent < tolerance:
                logger.info(
                    f"[止损更新] 止损价变化({price_diff_percent * 100:.3f}%) < 容错({tolerance * 100:.3f}%), 跳过更新"
                )
                return

        logger.info(
            f"[止损更新] 当前价:{current_price}, 止损价:{new_stop}, 持仓数量:{position.amount}张"
        )

        if self.position_manager.stop_order_id:
            logger.info(
                f"[止损更新] 取消旧止损单: {self.position_manager.stop_order_id}"
            )
            await self._exchange.cancel_order(
                self.position_manager.stop_order_id, self.config.exchange.symbol
            )

        logger.info(f"[止损更新] 创建新止损单: 止损价={new_stop}")
        stop_order_id = await self._exchange.create_stop_loss(
            symbol=self.config.exchange.symbol,
            side="sell",
            amount=position.amount,
            stop_price=new_stop,
        )

        self.position_manager.set_stop_order(stop_order_id)
        logger.info(f"[止损更新] 止损单设置完成: {stop_order_id}")

    async def _close_position(self, price: float) -> None:
        """平仓"""
        if not self.position_manager.has_position():
            logger.warning("[平仓] 无持仓，跳过平仓")
            return

        position = self.position_manager.position
        assert position is not None, (
            "position should not be None when has_position is True"
        )

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
