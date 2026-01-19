"""
交易机器人主类
"""

import asyncio
import logging
import random
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass

from .base import BaseComponent, BaseConfig
from .exceptions import TradingBotException
from ..utils.logging import LoggerMixin
from .health_check import get_health_check
from .monitor import (
    get_system_monitor,
    collect_metrics_periodically,
    monitor_performance,
)
from ..utils.price_calculator import PriceCalculator


@dataclass
class BotConfig(BaseConfig):
    """机器人配置"""

    trading_enabled: bool = True
    max_position_size: float = 0.01
    leverage: int = 10
    test_mode: bool = True
    cycle_minutes: int = 15  # 分钟（从配置文件中读取，默认15分钟）
    random_offset_enabled: bool = True  # 是否启用随机时间偏移
    random_offset_range: int = 180  # 随机偏移范围（秒），默认±3分钟


class TradingBot(BaseComponent):
    """交易机器人主类"""

    # 常量定义 - 置信度阈值
    CONFIDENCE_THRESHOLD_LOW = 0.3
    CONFIDENCE_THRESHOLD_MEDIUM = 0.5
    CONFIDENCE_THRESHOLD_HIGH = 0.8

    # ATR百分比阈值
    ATR_PERCENTAGE_LOW = 0.2
    ATR_PERCENTAGE_MEDIUM = 0.5

    # 止盈止损百分比
    TAKE_PROFIT_PERCENTAGE = 0.06  # 6%
    STOP_LOSS_PERCENTAGE = 0.02  # 2%

    # 价格变化显示阈值
    PRICE_CHANGE_DISPLAY_THRESHOLD = 0.001

    def __init__(self, config: Optional[BotConfig] = None):
        # 如果没有提供配置，创建默认配置
        if config is None:
            config = BotConfig(name="AlphaTradingBot")
        super().__init__(config)
        self._running = False
        self._start_time = None
        self._last_random_offset = 0  # 存储上一次使用的随机偏移
        self._next_execution_time = None  # 存储下次执行时间
        self._tp_sl_managed_this_cycle = False  # 标记当前周期是否已管理止盈止损
        self._managed_positions = set()  # 记录本周期已管理的仓位
        self._tp_sl_lock = asyncio.Lock()  # 止盈止损操作锁，避免并发冲突

    @property
    def enhanced_logger(self):
        """获取增强型日志记录器"""
        from ..utils.logging import EnhancedLogger

        # 使用完整的模块路径和类名，确保日志记录器名称一致性
        module_path = self.__class__.__module__
        class_name = self.__class__.__name__
        if module_path and module_path != "__main__":
            logger_name = f"{module_path}.{class_name}"
        else:
            logger_name = class_name
        return EnhancedLogger(logger_name)

    async def initialize(self) -> bool:
        """初始化机器人"""
        try:
            self.enhanced_logger.logger.info("正在初始化交易机器人...")

            # 初始化交易引擎
            from ..exchange import TradingEngine, TradingEngineConfig

            # 获取配置管理器
            from ..config import load_config

            config_manager = load_config()

            # 创建交易引擎配置，启用测试模式
            engine_config = TradingEngineConfig(
                name="TradingEngine", test_mode=config_manager.trading.test_mode
            )
            self.trading_engine = TradingEngine(engine_config)
            await self.trading_engine.initialize()

            # 初始化AI管理器 - 使用全局实例
            from ..ai import get_ai_manager

            try:
                self.ai_manager = await get_ai_manager()
            except RuntimeError:
                # 如果全局实例不存在，创建它
                from ..ai import create_ai_manager

                self.ai_manager = await create_ai_manager()

            # 初始化数据管理器（移到策略管理器之前）
            try:
                from ..data import create_data_manager

                self.data_manager = await create_data_manager()
                self.enhanced_logger.logger.info("数据管理器初始化成功")
            except Exception as e:
                self.enhanced_logger.logger.warning(
                    f"数据管理器初始化失败: {e}，将继续运行但不保存历史数据"
                )
                self.data_manager = None

            # 初始化策略管理器
            from ..strategies import StrategyManager

            self.strategy_manager = StrategyManager(ai_manager=self.ai_manager)
            await self.strategy_manager.initialize()

            # 初始化风控管理器
            from ..exchange.trading import RiskManager

            self.risk_manager = RiskManager(
                exchange_client=self.trading_engine.exchange_client
            )
            await self.risk_manager.initialize()

            # 初始化价格监控器（第一阶段：记录触发信号）
            from ..realtime_monitor import price_monitor

            self.price_monitor = price_monitor
            await self.price_monitor.initialize()
            await self.price_monitor.start_monitoring()

            # 初始化AlphaPulse引擎（代号：阿尔法脉冲）
            from ..alphapulse import AlphaPulseEngine

            self.alphapulse_engine = AlphaPulseEngine(
                exchange_client=self.trading_engine.exchange_client,
                config=None,  # 从环境变量加载
                trade_executor=self.trading_engine.trade_executor,
                ai_manager=self.ai_manager,
                on_signal=self._on_alphapulse_signal,
            )
            await self.alphapulse_engine.start()

            self._initialized = True
            self.enhanced_logger.logger.info("交易机器人初始化成功")
            return True

        except Exception as e:
            self.enhanced_logger.logger.error(f"初始化失败: {e}")
            import traceback

            self.enhanced_logger.logger.error(f"详细错误: {traceback.format_exc()}")
            return False

    async def _execute_close_all_positions(self, reason: str) -> bool:
        """执行清仓操作并清理所有委托单"""
        try:
            self.enhanced_logger.logger.warning(f"🚨 开始执行清仓操作: {reason}")

            # 获取当前所有持仓
            positions = await self.trading_engine.get_positions()
            if not positions:
                self.enhanced_logger.logger.info("当前没有持仓，无需清仓")
                return True

            closed_count = 0
            failed_count = 0

            # 遍历所有持仓进行平仓
            for position in positions:
                if position and position.amount != 0:  # 有实际持仓
                    symbol = position.symbol
                    amount = abs(position.amount)
                    side = TradeSide.SELL if position.side == "long" else TradeSide.BUY

                    self.enhanced_logger.logger.info(
                        f"正在平仓: {symbol} {position.side} {amount}"
                    )

                    # 创建平仓订单
                    close_trade = {
                        "symbol": symbol,
                        "side": side.value,
                        "amount": amount,
                        "type": "market",
                        "reason": f"横盘清仓 - {reason}",
                        "confidence": 1.0,  # 清仓信号具有高置信度
                        "is_close_all": True,
                        "reduce_only": True,
                    }

                    try:
                        result = await self.trading_engine.execute_trade(close_trade)
                        if result.success:
                            closed_count += 1
                            self.enhanced_logger.logger.info(f"✓ 平仓成功: {symbol}")
                        else:
                            failed_count += 1
                            self.enhanced_logger.logger.error(
                                f"✗ 平仓失败: {symbol} - {result.error_message}"
                            )
                    except Exception as e:
                        failed_count += 1
                        self.enhanced_logger.logger.error(f"✗ 平仓异常: {symbol} - {e}")

            # 清理所有委托单（包括止盈止损等算法订单）
            self.enhanced_logger.logger.warning("正在清理所有委托单...")
            try:
                # 获取所有算法订单
                for position in positions:
                    if position and position.symbol:
                        symbol = position.symbol
                        algo_orders = await self.order_manager.fetch_algo_orders(symbol)

                        if algo_orders:
                            self.enhanced_logger.logger.info(
                                f"取消 {symbol} 的 {len(algo_orders)} 个算法订单"
                            )
                            for order in algo_orders:
                                try:
                                    await self.order_manager.cancel_algo_order(
                                        order["algoId"], symbol
                                    )
                                    self.enhanced_logger.logger.info(
                                        f"✓ 取消算法订单: {order['algoId']}"
                                    )
                                except Exception as e:
                                    self.enhanced_logger.logger.error(
                                        f"✗ 取消算法订单失败: {order['algoId']} - {e}"
                                    )
            except Exception as e:
                self.enhanced_logger.logger.error(f"清理委托单时出错: {e}")

            # 总结结果
            self.enhanced_logger.logger.warning(
                f"清仓操作完成: 成功 {closed_count} 个, 失败 {failed_count} 个"
            )

            if closed_count > 0:
                self.enhanced_logger.logger.warning("✅ 清仓操作执行成功")
                return True
            else:
                self.enhanced_logger.logger.error("❌ 清仓操作执行失败")
                return False

        except Exception as e:
            self.enhanced_logger.logger.error(f"清仓操作异常: {e}")
            import traceback

            self.enhanced_logger.logger.error(f"详细错误: {traceback.format_exc()}")
            return False

    async def cleanup(self) -> None:
        """清理资源"""
        if hasattr(self, "alphapulse_engine") and self.alphapulse_engine:
            await self.alphapulse_engine.stop()
        if hasattr(self, "trading_engine"):
            await self.trading_engine.cleanup()
        if hasattr(self, "strategy_manager"):
            await self.strategy_manager.cleanup()
        if hasattr(self, "risk_manager"):
            await self.risk_manager.cleanup()
        if hasattr(self, "ai_manager"):
            await self.ai_manager.cleanup()
        if hasattr(self, "data_manager"):
            await self.data_manager.cleanup()
        if hasattr(self, "price_monitor"):
            await self.price_monitor.cleanup()

    def _on_alphapulse_signal(self, signal):
        """AlphaPulse信号回调"""
        self.enhanced_logger.logger.info(
            f"📡 AlphaPulse信号: {signal.signal_type.upper()} {signal.symbol} "
            f"(置信度: {signal.confidence:.2f})"
        )

    async def start(self) -> None:
        """启动机器人"""
        if not self._initialized:
            raise TradingBotException("机器人未初始化")

        self._running = True
        self._start_time = datetime.now()
        self.enhanced_logger.logger.info("交易机器人已启动")

        # 启动监控任务
        try:
            # 启动系统指标收集
            asyncio.create_task(collect_metrics_periodically(interval=60))
            # 启动性能监控
            asyncio.create_task(monitor_performance())
            self.enhanced_logger.logger.info("监控任务已启动")
        except Exception as e:
            self.enhanced_logger.logger.warning(
                f"启动监控任务失败: {e}，继续运行主程序"
            )

        # 添加调试信息
        cycle_minutes = self.config.cycle_minutes
        self.enhanced_logger.logger.debug(
            f"进入交易循环，等待下一个{cycle_minutes}分钟周期（含随机偏移）..."
        )

        try:
            cycle_count = 0
            while self._running:
                cycle_count += 1
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # 计算下次执行时间（在交易循环之前）
                now = datetime.now()
                cycle_minutes = (
                    self.config.cycle_minutes
                )  # 从配置读取周期（默认15分钟）

                # 计算下一个周期的基础时间（更可靠的方法）
                # 计算当前时间距离下一个周期整点的秒数
                current_minute = now.minute
                current_second = now.second
                cycle_seconds = cycle_minutes * 60

                # 计算距离下一个周期整点的秒数
                minutes_to_next_cycle = cycle_minutes - (current_minute % cycle_minutes)
                if minutes_to_next_cycle == cycle_minutes:  # 恰好在整点
                    minutes_to_next_cycle = cycle_minutes

                seconds_to_next_cycle = minutes_to_next_cycle * 60 - current_second

                # 基础执行时间 = 当前时间 + 距离下一个周期的秒数
                base_execution_time = now + timedelta(seconds=seconds_to_next_cycle)

                # 添加随机时间偏移（使用配置的偏移范围）
                offset_range = self.config.random_offset_range  # 默认±180秒（±3分钟）
                if self._last_random_offset != 0:
                    # 使用上一次保存的随机偏移（确保一致性）
                    random_offset = self._last_random_offset
                    self._last_random_offset = 0  # 重置，下次将生成新的
                else:
                    # 首次执行或没有保存的偏移时生成新的
                    random_offset = random.randint(-offset_range, offset_range)
                next_execution_time = base_execution_time + timedelta(
                    seconds=random_offset
                )

                # 优化：确保不会在过去时间执行 - 使用更智能的调整策略
                if next_execution_time <= now:
                    # 计算需要的最小正向偏移
                    min_positive_offset = max(
                        30, int((now - base_execution_time).total_seconds()) + 30
                    )
                    # 生成新的正向偏移，确保在未来执行
                    new_offset = random.randint(
                        min_positive_offset, min_positive_offset + offset_range
                    )
                    next_execution_time = base_execution_time + timedelta(
                        seconds=new_offset
                    )
                    self.enhanced_logger.logger.warning(
                        f"随机偏移导致执行时间在过去，已调整为正向偏移 {new_offset}秒"
                    )
                    # 不保存这个调整后的偏移，下次重新生成随机偏移

                # 存储下次执行时间供周期完成日志使用
                self._next_execution_time = next_execution_time

                # 保存随机偏移供下次使用（确保自然偏移被保存，而非调整后的偏移）
                if self.config.random_offset_enabled and next_execution_time > now:
                    # 只有自然生成的偏移才保存，不保存因时间修正产生的偏移
                    self._last_random_offset = random_offset

                # 记录周期和随机偏移信息
                offset_minutes = random_offset / 60
                offset_range_minutes = offset_range / 60
                self.enhanced_logger.logger.info(
                    f"⏰ 等待执行 - 周期: {cycle_minutes}分钟，随机偏移: {offset_minutes:+.1f} 分钟 (范围: ±{offset_range_minutes}分钟)"
                )

                # 计算等待时间（使用更精确的时间）
                now_precise = datetime.now()
                wait_seconds = (next_execution_time - now_precise).total_seconds()
                if wait_seconds < 0:
                    wait_seconds += 86400

                # 使用增强型日志记录器记录交易周期开始
                self.enhanced_logger.info_cycle_start(cycle_count, current_time)

                # 执行一次交易循环
                await self._trading_cycle(cycle_count)

                # 记录等待信息
                wait_minutes = wait_seconds / 60
                if self.config.random_offset_enabled:
                    self.enhanced_logger.logger.info(
                        f"⏰ 等待 {wait_seconds:.0f} 秒 ({wait_minutes:.1f} 分钟) 到下一个周期执行..."
                    )
                else:
                    self.enhanced_logger.logger.info(
                        f"⏰ 等待 {wait_seconds:.0f} 秒 ({wait_minutes:.1f} 分钟) 到下一个{cycle_minutes}分钟整点执行..."
                    )

                # 存储下次执行时间供周期完成日志使用
                self._next_execution_time = next_execution_time

                # 等待到下一个整点
                await asyncio.sleep(wait_seconds)

        except Exception as e:
            self.enhanced_logger.logger.error(f"交易循环异常: {e}")
            raise

    async def stop(self) -> None:
        """停止机器人"""
        self._running = False
        self.enhanced_logger.logger.info("交易机器人已停止")

        # 清理资源
        try:
            await self.cleanup()
            self.enhanced_logger.logger.info("交易机器人资源已清理")
        except Exception as e:
            self.enhanced_logger.logger.error(f"清理机器人资源失败: {e}")

    async def _process_market_data(self) -> Dict[str, Any]:
        """处理市场数据获取和日志记录"""
        self.enhanced_logger.logger.info("📊 获取市场数据...")
        market_data = await self.trading_engine.get_market_data()

        if market_data:
            current_price = market_data.get("price", 0)
            period = market_data.get("period", "15m")
            change_percent = market_data.get("change_percent", 0)
            last_kline_time = market_data.get("last_kline_time", "")

            self.enhanced_logger.info_market_data(
                current_price, period, change_percent, last_kline_time
            )

            # 记录K线详情
            self._log_kline_details(market_data, current_price)

            # 记录价格区间
            self._log_price_ranges(market_data, current_price)

            # 记录成交量信息
            self._log_volume_info(market_data)

        return market_data

    def _log_kline_details(
        self, market_data: Dict[str, Any], current_price: float
    ) -> None:
        """记录K线数据详情"""
        close_prices = market_data.get("close_prices", [])
        if len(close_prices) >= 2:
            previous_price = close_prices[-2]
            current_kline_price = close_prices[-1]
            self.enhanced_logger.logger.info(f"📊 K线数据详情:")
            self.enhanced_logger.logger.info(
                f"  ⏰ 当前K线收盘价: ${current_kline_price:,.2f}"
            )
            self.enhanced_logger.logger.info(
                f"  ⏰ 前一根K线收盘价: ${previous_price:,.2f}"
            )
            self.enhanced_logger.logger.info(
                f"  📏 价格差值: ${current_kline_price - previous_price:+.2f}"
            )

            # 计算并显示更精确的变化
            actual_change = (
                ((current_kline_price - previous_price) / previous_price * 100)
                if previous_price > 0
                else 0
            )
            if abs(actual_change) >= 0.001:  # 只显示有意义的变化
                self.enhanced_logger.logger.info(
                    f"  🔍 实际变化率: {actual_change:+.4f}%"
                )

    def _log_price_ranges(
        self, market_data: Dict[str, Any], current_price: float
    ) -> None:
        """记录价格区间信息"""
        # 24h价格区间
        if "high" in market_data and "low" in market_data:
            high = market_data.get("high", 0)
            low = market_data.get("low", 0)
            self.enhanced_logger.logger.info(f"📈 24h价格区间:")
            self.enhanced_logger.logger.info(f"  🔺 最高价: ${high:,.2f}")
            self.enhanced_logger.logger.info(f"  🔻 最低价: ${low:,.2f}")
            self.enhanced_logger.logger.info(f"  📊 价格区间: ${high - low:,.2f}")

            if high > low:
                # 使用统一的价格位置计算器
                price_position_result = PriceCalculator.calculate_price_position(
                    current_price=current_price, daily_high=high, daily_low=low
                )
                price_position = price_position_result.daily_position
                self.enhanced_logger.logger.info(
                    f"  📍 当前价格在24h区间位置: {price_position:.1f}%"
                )

        # 7天价格区间
        if "high_7d" in market_data and "low_7d" in market_data:
            high_7d = market_data.get("high_7d", 0)
            low_7d = market_data.get("low_7d", 0)
            self.enhanced_logger.logger.info(f"📈 7天价格区间:")
            self.enhanced_logger.logger.info(f"  🔺 最高价: ${high_7d:,.2f}")
            self.enhanced_logger.logger.info(f"  🔻 最低价: ${low_7d:,.2f}")
            self.enhanced_logger.logger.info(f"  📊 价格区间: ${high_7d - low_7d:,.2f}")

            if high_7d > low_7d:
                # 使用统一的价格位置计算器
                price_position_result_7d = PriceCalculator.calculate_price_position(
                    current_price=current_price, daily_high=high_7d, daily_low=low_7d
                )
                price_position_7d = price_position_result_7d.daily_position
                self.enhanced_logger.logger.info(
                    f"  📍 当前价格在7天区间位置: {price_position_7d:.1f}%"
                )
        else:
            self.enhanced_logger.logger.info(
                f"⚠️ 7天价格数据缺失 - high_7d: {'high_7d' in market_data}, low_7d: {'low_7d' in market_data}"
            )

    def _log_volume_info(self, market_data: Dict[str, Any]) -> None:
        """记录成交量信息"""
        volume_24h = market_data.get("volume", 0)
        avg_volume_24h = market_data.get("avg_volume_24h", 0)

        self.enhanced_logger.logger.info("📈 市场成交量详情:")
        self.enhanced_logger.logger.info(f"  📊 交易所24h成交量: {volume_24h}")
        if avg_volume_24h > 0:
            self.enhanced_logger.logger.info(
                f"  📊 计算的平均成交量: {avg_volume_24h:.2f}"
            )

        if volume_24h == 0 and avg_volume_24h > 0:
            self.enhanced_logger.logger.info(
                "  ⚠️  注意：交易所24h成交量为0，系统将使用计算的平均成交量进行评估"
            )

        # 记录OHLCV数据获取状态
        if market_data.get("ohlcv"):
            self.enhanced_logger.logger.info(
                f"✅ 成功获取 {len(market_data['ohlcv'])} 根K线数据用于技术指标计算"
            )
        else:
            self.enhanced_logger.logger.warning(
                "⚠️ 未能获取OHLCV数据，技术指标将使用基础分数"
            )

    async def _generate_trading_signals(
        self, market_data: Dict[str, Any], execution_time: float
    ) -> tuple[List[Dict[str, Any]], int]:
        """生成交易信号并返回信号列表和总数"""
        self.enhanced_logger.logger.info("🔍 分析市场状态...")

        # 获取AI提供商信息
        providers = (
            self.ai_manager.providers if hasattr(self.ai_manager, "providers") else []
        )
        config_providers = (
            self.ai_manager.config.primary_provider
            if hasattr(self.ai_manager, "config")
            else "kimi"
        )

        # 记录AI提供商信息
        self.enhanced_logger.info_ai_providers(providers, config_providers)

        # 计算技术指标
        await self._calculate_technical_indicators(market_data)

        # 执行健康检查
        await self._perform_health_check(market_data, execution_time)

        # 生成AI信号 - 使用实例缓存确保不重复调用
        if getattr(self, "_ai_signals_cache_valid", False):
            self.enhanced_logger.logger.warning(
                "⚠️ 检测到重复的AI信号获取请求，使用已生成的信号"
            )
            ai_signals = getattr(self, "_cached_ai_signals", [])
            # 为缓存的信号添加标志，以便日志处理
            for signal in ai_signals:
                signal["_from_cache"] = True
        else:
            self.enhanced_logger.logger.debug("开始生成AI信号...")
            ai_signals = await self.ai_manager.generate_signals(market_data)
            self.enhanced_logger.logger.debug(
                f"AI信号生成完成，数量: {len(ai_signals)}"
            )

            # 缓存信号并设置标志
            self._ai_signals_cache_valid = True
            self._cached_ai_signals = ai_signals

        # 记录AI信号详情
        self._log_ai_signals(ai_signals, providers, config_providers)

        # 🆕 集成智能信号过滤器 - 过滤和优化信号质量
        try:
            from ..strategies.intelligent_signal_filter import IntelligentSignalFilter

            if not hasattr(self, "_signal_filter"):
                self._signal_filter = IntelligentSignalFilter()

            # 为每个AI信号创建完整的信号对象用于过滤
            filtered_signals = []
            for ai_signal in ai_signals:
                signal = {
                    "signal": ai_signal.get("signal", ai_signal.get("type", "HOLD")),
                    "type": ai_signal.get("signal", ai_signal.get("type", "HOLD")),
                    "confidence": ai_signal.get("confidence", 0.5),
                    "sources": [ai_signal],  # AI信号作为单一来源
                    "timestamp": datetime.now(),
                }

                # 应用信号过滤
                filter_result = self._signal_filter.analyze_signal_quality(
                    signal, market_data
                )

                if filter_result.passed:
                    # 添加过滤结果信息
                    signal.update(
                        {
                            "filter_score": filter_result.score,
                            "filter_confidence": filter_result.confidence_level,
                            "filter_reasons": filter_result.reasons,
                        }
                    )
                    filtered_signals.append(signal)
                    self.enhanced_logger.logger.info(
                        f"✅ 信号通过过滤: {signal['signal']} (评分: {filter_result.score:.1f})"
                    )
                else:
                    # 🆕 特殊处理HOLD信号：HOLD信号只要置信度 > 0.40就应该通过
                    original_signal_type = signal.get("signal", "").upper()
                    is_hold_signal = original_signal_type == "HOLD"
                    hold_confidence = signal.get("confidence", 0)

                    if is_hold_signal and hold_confidence > 0.40:
                        # HOLD信号直接通过，不经过过滤器
                        filtered_signals.append(signal)
                        self.enhanced_logger.logger.info(
                            f"✅ HOLD信号直接通过: 置信度={hold_confidence:.2f}"
                        )
                    elif original_signal_type in ["BUY", "SELL", "LONG", "SHORT"]:
                        # 只有BUY/SELL/LONG/SHORT才检查是否应该降级
                        should_downgrade = (
                            filter_result.score >= 40  # 基础质量OK，可以降级保留
                            and filter_result.passed is False  # 但未通过严格过滤
                        )

                        if should_downgrade:
                            # 降级为HOLD，保留信号用于止损更新
                            original_signal = signal["signal"]
                            signal["signal"] = "HOLD"
                            signal["type"] = "HOLD"
                            signal["downgraded_from"] = original_signal
                            signal["filter_score"] = filter_result.score
                            signal["filter_confidence"] = filter_result.confidence_level
                            signal["filter_reasons"] = filter_result.reasons
                            signal["is_downgraded"] = True
                            filtered_signals.append(signal)
                            self.enhanced_logger.logger.info(
                                f"🔄 信号降级: {original_signal} → HOLD (评分: {filter_result.score:.1f}) - "
                                f"将执行持仓止损更新，但不会执行新交易"
                            )
                        else:
                            # 真正过滤掉的信号
                            rejection_reasons = [
                                r for r in filter_result.reasons if r.startswith("❌")
                            ]
                            reason_text = (
                                rejection_reasons[0]
                                if rejection_reasons
                                else "未通过质量过滤"
                            )
                            self.enhanced_logger.logger.info(
                                f"❌ 信号被过滤: {signal['signal']} - {reason_text}"
                            )
                    else:
                        # 其他类型信号（如未知类型）按原逻辑处理
                        rejection_reasons = [
                            r for r in filter_result.reasons if r.startswith("❌")
                        ]
                        reason_text = (
                            rejection_reasons[0]
                            if rejection_reasons
                            else "未通过质量过滤"
                        )
                        self.enhanced_logger.logger.info(
                            f"❌ 信号被过滤: {signal['signal']} - {reason_text}"
                        )

            ai_signals = filtered_signals

        except ImportError as e:
            self.enhanced_logger.logger.warning(
                f"智能信号过滤器未找到，使用原信号: {e}"
            )
        except Exception as e:
            self.enhanced_logger.logger.error(f"信号过滤异常，使用原信号: {e}")

        # 🆕 集成动态冷却管理器 - 检查交易频率限制
        try:
            from ..trading_optimizers.dynamic_trade_cooling import (
                DynamicTradeCoolingManager,
            )

            if not hasattr(self, "_cooling_manager"):
                self._cooling_manager = DynamicTradeCoolingManager()

            # 检查是否有买入信号
            buy_signals = [
                s for s in ai_signals if s.get("signal", "").upper() in ["BUY", "LONG"]
            ]
            sell_signals = [
                s
                for s in ai_signals
                if s.get("signal", "").upper() in ["SELL", "SHORT"]
            ]

            # 检查买入冷却
            if buy_signals:
                can_buy, buy_reason, buy_cooldown = self._cooling_manager.can_trade(
                    "buy", market_data
                )
                if not can_buy:
                    self.enhanced_logger.logger.warning(
                        f"🚫 买入信号被冷却管理器阻止: {buy_reason} (冷却: {buy_cooldown}秒)"
                    )
                    # 移除所有买入信号
                    ai_signals = [
                        s
                        for s in ai_signals
                        if s.get("signal", "").upper() not in ["BUY", "LONG"]
                    ]

            # 检查卖出冷却
            if sell_signals:
                can_sell, sell_reason, sell_cooldown = self._cooling_manager.can_trade(
                    "sell", market_data
                )
                if not can_sell:
                    self.enhanced_logger.logger.warning(
                        f"🚫 卖出信号被冷却管理器阻止: {sell_reason} (冷却: {sell_cooldown}秒)"
                    )
                    # 移除所有卖出信号
                    ai_signals = [
                        s
                        for s in ai_signals
                        if s.get("signal", "").upper() not in ["SELL", "SHORT"]
                    ]

        except ImportError as e:
            self.enhanced_logger.logger.warning(
                f"动态冷却管理器未找到，跳过冷却检查: {e}"
            )
        except Exception as e:
            self.enhanced_logger.logger.error(f"冷却管理器异常，跳过冷却检查: {e}")

        # 生成所有信号（包括策略信号）
        all_signals = await self.strategy_manager.generate_signals(
            market_data, ai_signals
        )
        total_signals = len(all_signals)

        # 记录信号摘要
        self._log_signal_summary(all_signals)

        # 选择最终信号
        signals = await self._select_final_signals(all_signals)

        return signals, total_signals

    async def _calculate_technical_indicators(
        self, market_data: Dict[str, Any]
    ) -> None:
        """计算技术指标并添加到市场数据"""
        try:
            from ..utils.technical import TechnicalIndicators

            technical_data = TechnicalIndicators.calculate_all_indicators(market_data)
            market_data["technical_data"] = technical_data

            # 记录技术指标信息
            if technical_data:
                rsi = technical_data.get("rsi", 0)
                macd_hist = technical_data.get("macd_histogram", 0)
                adx = technical_data.get("adx", 0)
                bb_position = technical_data.get("price_position", 0)

                self.enhanced_logger.logger.info("📊 技术指标详情:")
                self.enhanced_logger.logger.info(f"  📈 RSI: {rsi:.2f}")
                self.enhanced_logger.logger.info(f"  📊 MACD柱状图: {macd_hist:.4f}")
                self.enhanced_logger.logger.info(f"  🎯 ADX: {adx:.2f}")
                self.enhanced_logger.logger.info(f"  📍 布林带位置: {bb_position:.2f}")

                # 计算ATR百分比用于动态缓存
                atr_value = technical_data.get("atr", 0)
                current_price = market_data.get("price", 0)
                # 使用统一的ATR百分比计算器
                atr_percentage = PriceCalculator.calculate_atr_percentage(
                    atr_value, current_price
                )
                market_data["atr_percentage"] = atr_percentage

                self.enhanced_logger.logger.info(
                    f"  📊 ATR百分比: {atr_percentage:.2f}%"
                )

        except Exception as e:
            self.enhanced_logger.logger.error(f"计算技术指标失败: {e}")
            market_data["technical_data"] = {}
            market_data["atr_percentage"] = 0

    async def _perform_health_check(
        self, market_data: Dict[str, Any], execution_time: float
    ) -> None:
        """执行健康检查"""
        try:
            from alpha_trading_bot.core.health_check import get_health_check

            health_check = await get_health_check()

            # 执行健康检查
            health_report = await health_check.perform_health_check(
                market_data=market_data,
                execution_time=execution_time,
                api_response_time=0,  # TODO: 可以从exchange_client获取实际API响应时间
                api_errors=0,  # TODO: 可以从exchange_client获取实际API错误数
            )

            # 记录健康状态
            self.enhanced_logger.logger.info(
                f"🏥 健康检查: {health_report['overall_status'].upper()}"
            )

            # 输出详细健康检查信息
            self._log_health_check_details(health_report)

        except (ConnectionError, TimeoutError, ValueError) as e:
            self.enhanced_logger.logger.error(f"健康检查失败: {e}")
        except Exception as e:
            self.enhanced_logger.logger.error(f"健康检查未知错误: {e}")

    def _log_health_check_details(self, health_report: Dict[str, Any]) -> None:
        """记录健康检查详情"""
        self.enhanced_logger.logger.info("📊 详细健康检查结果:")

        # 流动性详情
        liquidity = health_report.get("liquidity", {})
        if liquidity:
            self.enhanced_logger.logger.info(
                f"  💧 流动性状态: {liquidity.get('status', 'unknown')}"
            )
            self.enhanced_logger.logger.info(
                f"  📈 流动性评分: {liquidity.get('score', 0)}"
            )
            if liquidity.get("issues"):
                self.enhanced_logger.logger.info(
                    f"  ⚠️  流动性问题: {', '.join(liquidity['issues'])}"
                )

            # 详细ATR信息
            atr_info = liquidity.get("atr_info", {})
            if atr_info:
                self.enhanced_logger.logger.info(f"  📊 ATR详细分析:")
                self.enhanced_logger.logger.info(
                    f"    📈 ATR值: {atr_info.get('atr_value', 0):.2f} USDT"
                )
                self.enhanced_logger.logger.info(
                    f"    📊 ATR百分比: {atr_info.get('atr_percentage', 0):.2f}%"
                )
                self.enhanced_logger.logger.info(
                    f"    🎯 评估: {atr_info.get('assessment', '未知')}"
                )

                # 添加ATR解释
                atr_pct = atr_info.get("atr_percentage", 0)
                if atr_pct < 0.2:
                    self.enhanced_logger.logger.info(
                        "    💡 解释: ATR百分比低于0.2%，市场波动极小，价格可能处于横盘状态"
                    )
                elif atr_pct < 0.5:
                    self.enhanced_logger.logger.info(
                        "    💡 解释: ATR百分比在0.2%-0.5%之间，市场波动较低"
                    )
                else:
                    self.enhanced_logger.logger.info(
                        "    💡 解释: ATR百分比高于0.5%，市场波动正常"
                    )

        # 性能详情
        performance = health_report.get("performance", {})
        if performance:
            self.enhanced_logger.logger.info(
                f"  ⚡ 性能状态: {performance.get('status', 'unknown')}"
            )
            if performance.get("execution_time"):
                self.enhanced_logger.logger.info(
                    f"  ⏱️  执行时间: {performance['execution_time']:.2f}s"
                )

        # API详情
        api = health_report.get("api", {})
        if api:
            self.enhanced_logger.logger.info(
                f"  🔌 API状态: {api.get('status', 'unknown')}"
            )
            if api.get("response_time"):
                self.enhanced_logger.logger.info(
                    f"  🔄 API响应时间: {api['response_time']:.2f}s"
                )
            if api.get("errors", 0) > 0:
                self.enhanced_logger.logger.info(f"  ❌ API错误数: {api['errors']}")

        # 统计信息
        self.enhanced_logger.logger.info(
            f"  📋 统计: {health_report.get('critical_count', 0)}个严重问题, {health_report.get('warning_count', 0)}个警告"
        )

        if health_report["overall_status"] != "healthy":
            self.enhanced_logger.logger.warning(
                f"⚠️  系统健康异常: {health_report['critical_count']}个严重问题, {health_report['warning_count']}个警告"
            )

            # 如果流动性严重不足，可以考虑暂停交易
            liquidity_health = health_report.get("liquidity", {})
            if liquidity_health.get("status") == "critical":
                self.enhanced_logger.logger.error("🚨 流动性严重不足，建议暂停交易")
                # TODO: 可以在这里添加暂停交易的逻辑

    def _log_ai_signals(
        self,
        ai_signals: List[Dict[str, Any]],
        providers: List[str],
        config_providers: str,
    ) -> None:
        """记录AI信号详情"""
        if (
            hasattr(self.ai_manager, "config")
            and self.ai_manager.config.use_multi_ai
            and len(providers) > 1
        ):
            # 检查是否是缓存的信号
            is_cached = any(signal.get("_from_cache") for signal in ai_signals)

            if is_cached:
                self.enhanced_logger.logger.info("ℹ️ 使用缓存的AI信号，跳过重复分析")
                # 缓存信号显示简化的统计信息
                individual_signals = [
                    s for s in ai_signals if s.get("provider") != "fusion"
                ]
                if individual_signals:
                    self.enhanced_logger.logger.info(
                        f"🔄 缓存融合统计 - 原始提供商: {providers}, 信号数量: {len(individual_signals)}"
                    )
            else:
                self.enhanced_logger.info_ai_parallel_request(providers)

                # 记录融合后的信号统计（ai_signals只包含融合信号）
                # 检查是否有融合信号
                fusion_signals = [
                    s for s in ai_signals if s.get("provider") == "fusion"
                ]

                if fusion_signals:
                    # 有融合信号，显示融合结果
                    fusion_signal = fusion_signals[0]
                    self.enhanced_logger.logger.info(
                        f"🔮 融合结果: {fusion_signal.get('signal', 'HOLD')} (置信度: {fusion_signal.get('confidence', 0):.2f})"
                    )
                    self.enhanced_logger.logger.info(
                        f"📊 融合信号来源: {providers}, 融合策略: {fusion_signal.get('fusion_strategy', 'unknown')}"
                    )
                else:
                    # 无融合信号（异常情况），显示原始信号统计
                    individual_signals = [
                        s for s in ai_signals if s.get("provider") != "fusion"
                    ]
                    if individual_signals:
                        success_count = len(
                            [
                                s
                                for s in individual_signals
                                if s.get("confidence", 0)
                                >= self.CONFIDENCE_THRESHOLD_LOW
                            ]
                        )
                        fail_count = len(
                            [
                                s
                                for s in individual_signals
                                if s.get("confidence", 0)
                                < self.CONFIDENCE_THRESHOLD_LOW
                            ]
                        )
                        self.enhanced_logger.info_ai_fusion_stats(
                            success_count,
                            fail_count,
                            providers,
                            [s.get("provider", "unknown") for s in individual_signals],
                        )

            # 如果有多个信号，进行融合分析（缓存信号也需要分析）
            if len(ai_signals) > 1:
                self._log_signal_fusion_analysis(ai_signals)
        else:
            # 单AI模式，显示基本信息
            if ai_signals:
                signal = ai_signals[0]
                self.enhanced_logger.logger.info(
                    f"✅ AI信号生成成功: {signal.get('signal', 'HOLD')} (信心: {signal.get('confidence', 0):.2f}, 提供商: {signal.get('provider', config_providers)})"
                )
            else:
                self.enhanced_logger.logger.info("⚠️ 未生成AI信号，使用回退模式")

    def _log_signal_fusion_analysis(self, ai_signals: List[Dict[str, Any]]) -> None:
        """记录信号融合分析"""
        # 计算信号多样性
        signal_types = [s.get("signal", "HOLD") for s in ai_signals]
        signal_counts = {
            "BUY": signal_types.count("BUY"),
            "SELL": signal_types.count("SELL"),
            "HOLD": signal_types.count("HOLD"),
        }

        # 计算多样性分数
        total = len(signal_types)
        if total > 0:
            buy_ratio = signal_counts["BUY"] / total
            sell_ratio = signal_counts["SELL"] / total
            hold_ratio = signal_counts["HOLD"] / total
            diversity_score = 1 - max(buy_ratio, sell_ratio, hold_ratio)

            # 计算平均信心
            confidences = [s.get("confidence", 0.5) for s in ai_signals]
            avg_confidence = sum(confidences) / len(confidences)
            std_confidence = (
                sum((c - avg_confidence) ** 2 for c in confidences) / len(confidences)
            ) ** 0.5

            self.enhanced_logger.info_ai_signal_diversity(
                diversity_score, signal_counts, avg_confidence, std_confidence
            )

        # 投票统计
        voting_stats = signal_counts
        self.enhanced_logger.info_ai_voting_stats(voting_stats)

        # 信心分布
        confidence_dist = {
            "BUY": sum(
                s.get("confidence", 0) for s in ai_signals if s.get("signal") == "BUY"
            )
            / max(signal_counts["BUY"], 1),
            "SELL": sum(
                s.get("confidence", 0) for s in ai_signals if s.get("signal") == "SELL"
            )
            / max(signal_counts["SELL"], 1),
            "HOLD": sum(
                s.get("confidence", 0) for s in ai_signals if s.get("signal") == "HOLD"
            )
            / max(signal_counts["HOLD"], 1),
        }

        self.enhanced_logger.info_ai_confidence_distribution(confidence_dist)

    def _log_signal_summary(self, all_signals: List[Dict[str, Any]]) -> None:
        """记录信号摘要"""
        if all_signals:
            self.enhanced_logger.logger.info("📊 交易信号摘要:")
            signal_summary = {}
            for signal in all_signals:
                signal_type = signal.get("type", "unknown").upper()
                signal_summary[signal_type] = signal_summary.get(signal_type, 0) + 1

            for signal_type, count in signal_summary.items():
                self.enhanced_logger.logger.info(f"  {signal_type}: {count} 个")
        else:
            self.enhanced_logger.logger.info("⚠️ 未生成任何交易信号")

    async def _assess_risk_and_execute_trades(
        self, signals: List[Dict[str, Any]], market_data: Dict[str, Any]
    ) -> int:
        """风险评估和执行交易，返回执行的交易数量"""
        executed_trades = 0

        self.enhanced_logger.logger.info("⚠️ 进行风险评估...")
        # 获取当前价格用于风险评估
        current_price = market_data.get("price", 0)
        # 获取账户余额用于动态计算交易数量
        balance = await self.trading_engine.get_balance()
        risk_assessment = await self.risk_manager.assess_risk(
            signals, current_price, balance, market_data
        )
        risk_level = risk_assessment.get("risk_level", "unknown")
        risk_score = risk_assessment.get("risk_score", 0)
        trades = risk_assessment.get("trades", [])  # 确保trades变量被定义

        self.enhanced_logger.logger.info(
            f"风险评估结果: 等级={risk_level}, 分数={risk_score:.2f}"
        )

        # 记录风险评估详情
        if risk_assessment:
            self.enhanced_logger.logger.info(f"📋 风险评估详情:")
            self.enhanced_logger.logger.info(
                f"  当日亏损: ${risk_assessment.get('daily_loss', 0):.2f} USDT"
            )
            self.enhanced_logger.logger.info(
                f"  连续亏损次数: {risk_assessment.get('consecutive_losses', 0)}"
            )
            self.enhanced_logger.logger.info(
                f"  评估原因: {risk_assessment.get('reason', '无')}"
            )

        # 记录交易执行情况
        if trades:
            self.enhanced_logger.logger.info(
                f"✅ 通过风险评估的交易 ({len(trades)} 个):"
            )
            for i, trade in enumerate(trades, 1):
                self.enhanced_logger.logger.info(f"  交易 {i}:")
                self.enhanced_logger.logger.info(
                    f"    操作: {trade.get('side', 'unknown').upper()}"
                )
                self.enhanced_logger.logger.info(
                    f"    价格: ${trade.get('price', 0) or 0:,.2f}"
                )
                self.enhanced_logger.logger.info(f"    数量: {trade.get('amount', 0)}")
                self.enhanced_logger.logger.info(
                    f"    原因: {trade.get('reason', '无')}"
                )
                self.enhanced_logger.logger.info(
                    f"    信心度: {trade.get('confidence', 0):.2f}"
                )
                self.enhanced_logger.logger.info("    " + "-" * 30)

        # 执行交易
        if risk_assessment.get("can_trade", False):
            executed_trades = await self._execute_trades(trades)
        else:
            self.enhanced_logger.logger.info("⚠️ 风险评估不通过，跳过交易")

        # 统一止盈止损管理入口 - 根据信号类型进行区分处理
        await self._unified_tp_sl_management(signals, market_data, executed_trades)

        return executed_trades

    async def _unified_tp_sl_management(
        self,
        signals: List[Dict[str, Any]],
        market_data: Dict[str, Any],
        executed_trades: int,
    ) -> None:
        """统一的止盈止损管理入口 - 根据信号类型进行区分处理

        Args:
            signals: 当前周期生成的信号列表
            market_data: 市场数据
            executed_trades: 本周期执行的交易数量
        """
        # 使用锁保护，避免并发冲突
        async with self._tp_sl_lock:
            # 检查是否有HOLD信号
            has_hold_signal = any(
                signal.get("signal", "").upper() == "HOLD"
                or signal.get("type", "").upper() == "HOLD"
                for signal in signals
            )

            # 检查是否有BUY信号且执行了交易
            has_buy_signal_executed = executed_trades > 0 and any(
                signal.get("signal", "").upper() == "BUY" for signal in signals
            )

            # 根据信号类型进行不同的处理
            if has_hold_signal:
                # HOLD信号：执行独立的止损管理
                self.enhanced_logger.logger.info("🎯 HOLD信号：执行独立止损管理")
                await self._handle_hold_signal_position_management(signals, market_data)

            elif has_buy_signal_executed:
                # BUY信号已执行：跳过止盈止损管理（已在execute_trade中处理）
                self.enhanced_logger.logger.info(
                    "🎯 BUY信号已执行：跳过周期性止盈止损管理"
                )
                self._tp_sl_managed_this_cycle = True

            else:
                # 其他情况：执行常规的止盈止损管理
                if not self._tp_sl_managed_this_cycle:
                    self.enhanced_logger.logger.info(
                        "🎯 常规情况：执行周期性止盈止损管理"
                    )
                    await self._manage_tp_sl_orders()
                else:
                    self.enhanced_logger.logger.info(
                        "🎯 当前周期已管理过止盈止损，跳过重复管理"
                    )

    async def _handle_hold_signal_position_management(
        self, signals: List[Dict[str, Any]], market_data: Dict[str, Any]
    ) -> bool:
        """处理HOLD信号的仓位管理和止损调整"""
        # 检查是否有HOLD信号
        has_hold_signal = any(
            signal.get("signal", "").upper() == "HOLD"
            or signal.get("type", "").upper() == "HOLD"
            for signal in signals
        )

        if not has_hold_signal:
            return False

        self.enhanced_logger.logger.info("🔄 HOLD信号：检查当前持仓和止损订单...")

        try:
            # 更新仓位信息
            await self.trading_engine.position_manager.update_position(
                self.trading_engine.exchange_client, "BTC/USDT:USDT"
            )

            # 获取当前持仓
            positions = self.trading_engine.position_manager.get_all_positions()
            self.enhanced_logger.logger.info(
                f"📊 HOLD信号检查到 {len(positions)} 个仓位"
            )
            if not positions:
                self.enhanced_logger.logger.info("📊 当前无持仓，HOLD信号无需操作")
                return True

            current_price = market_data.get("price", 0)
            if current_price <= 0:
                self.enhanced_logger.logger.warning(
                    "⚠️ 无法获取当前价格，跳过HOLD仓位管理"
                )
                return True

            # 遍历所有持仓
            for position in positions:
                self.enhanced_logger.logger.info(
                    f"📊 检查仓位: {position.symbol} {position.side.value} {position.amount} 张, 入场价: ${position.entry_price:.2f}"
                )
                if position and position.amount != 0:  # 有实际持仓
                    await self._adjust_stop_loss_for_hold(position, current_price)
                    self._tp_sl_managed_this_cycle = True  # 标记已管理
                else:
                    self.enhanced_logger.logger.info(
                        f"📊 跳过空仓位: {position.symbol}"
                    )

        except Exception as e:
            self.enhanced_logger.logger.error(f"HOLD信号仓位管理异常: {e}")
            return False

        return has_hold_signal

    async def _adjust_stop_loss_for_hold(
        self, position: Any, current_price: float
    ) -> None:
        """为HOLD信号调整止损订单"""
        symbol = position.symbol
        side = position.side
        entry_price = position.entry_price
        amount = abs(position.amount)

        # 检查是否已经为这个仓位管理过止损
        position_key = f"{symbol}_{side.value}"
        if (
            hasattr(self, "_managed_positions")
            and position_key in self._managed_positions
        ):
            self.enhanced_logger.logger.info(
                f"📊 {symbol} 已在本次周期管理过止损，跳过重复操作"
            )
            return

        self.enhanced_logger.logger.info(
            f"📊 检查 {symbol} 持仓止损 - 入场价: ${entry_price:.2f}, 当前价: ${current_price:.2f}"
        )

        try:
            # 获取现有的算法订单（包括止损订单）
            algo_orders = await self.trading_engine.order_manager.fetch_algo_orders(
                symbol
            )
            existing_sl_order = None

            # 收集所有止损订单
            stop_loss_orders = []
            for order in algo_orders:
                # 检查是否为止损订单（通过价格判断，止损订单有触发价格）
                if hasattr(order, "price") and order.price > 0:
                    stop_loss_orders.append(order)

            if stop_loss_orders:
                # 有现有止损订单
                self.enhanced_logger.logger.info(
                    f"📊 发现 {len(stop_loss_orders)} 个现有止损订单"
                )

                # 如果有多个止损订单，先清理所有订单
                if len(stop_loss_orders) > 1:
                    self.enhanced_logger.logger.warning(
                        f"⚠️ 检测到多个止损订单 ({len(stop_loss_orders)}个)，将清理后重新创建"
                    )
                    for order in stop_loss_orders:
                        if hasattr(order, "order_id") and order.order_id:
                            try:
                                await (
                                    self.trading_engine.order_manager.cancel_algo_order(
                                        order.order_id, symbol
                                    )
                                )
                                self.enhanced_logger.logger.info(
                                    f"✅ 已取消重复止损订单: {order.order_id}"
                                )
                            except Exception as e:
                                self.enhanced_logger.logger.error(
                                    f"❌ 取消止损订单失败 {order.order_id}: {e}"
                                )

                    # 清理后重新获取订单状态
                    await asyncio.sleep(1.0)  # 等待订单状态同步
                    algo_orders = (
                        await self.trading_engine.order_manager.fetch_algo_orders(
                            symbol
                        )
                    )
                    stop_loss_orders = [
                        order
                        for order in algo_orders
                        if hasattr(order, "price") and order.price > 0
                    ]

                # 使用最新的止损订单（现在应该只剩一个或零个）
                if stop_loss_orders:
                    current_sl_price = stop_loss_orders[0].price
                    self.enhanced_logger.logger.info(
                        f"📊 当前止损价: ${current_sl_price:.2f}"
                    )

                    # 计算新的止损价格
                    new_sl_price = self._calculate_hold_stop_loss_price(
                        side.value, entry_price, current_price, current_sl_price
                    )

                    if (
                        new_sl_price
                        and new_sl_price > current_sl_price
                        and abs(new_sl_price - current_sl_price) > 0.01
                    ):  # 只在止损价格上升且变化超过0.01时调整
                        self.enhanced_logger.logger.info(
                            f"🔄 调整止损价格: ${current_sl_price:.2f} → ${new_sl_price:.2f}"
                        )

                        # 取消现有止损订单
                        if stop_loss_orders[0].order_id:
                            await self.trading_engine.order_manager.cancel_algo_order(
                                stop_loss_orders[0].order_id, symbol
                            )

                        # 创建新的止损订单
                        await self._create_hold_stop_loss_order(
                            symbol, side.value, amount, new_sl_price
                        )
                        # 标记该仓位已管理，避免重复操作
                        self._managed_positions.add(position_key)

                        # 添加短暂延迟，确保订单状态同步
                        await asyncio.sleep(0.5)
                    else:
                        self.enhanced_logger.logger.info(
                            f"✅ {symbol} 止损价格无需调整"
                        )
                        # 即使不调整，也标记为已管理
                        self._managed_positions.add(position_key)
                else:
                    # 清理后没有订单了，需要创建新的
                    self.enhanced_logger.logger.info(
                        f"📊 清理后无现有止损订单，将创建新的止损订单"
                    )
                    default_current_sl_price = 0  # 没有现有订单时，使用0作为基准
                    new_sl_price = self._calculate_hold_stop_loss_price(
                        side.value, entry_price, current_price, default_current_sl_price
                    )

                    if new_sl_price:
                        self.enhanced_logger.logger.info(
                            f"🆕 创建新的止损订单: ${new_sl_price:.2f}"
                        )

                        # 创建新的止损订单
                        await self._create_hold_stop_loss_order(
                            symbol, side.value, amount, new_sl_price
                        )
                        # 标记该仓位已管理
                        self._managed_positions.add(position_key)

                        # 添加短暂延迟，确保订单状态同步
                        await asyncio.sleep(0.5)
                    else:
                        self.enhanced_logger.logger.warning(
                            f"⚠️ 无法计算 {symbol} 的止损价格"
                        )
            else:
                # 没有现有止损订单，直接创建新的
                self.enhanced_logger.logger.info(
                    f"📊 {symbol} 没有现有的止损订单，将创建新的止损订单"
                )

                # 计算止损价格（使用一个默认的当前止损价格来计算）
                default_current_sl_price = 0  # 没有现有订单时，使用0作为基准
                new_sl_price = self._calculate_hold_stop_loss_price(
                    side.value, entry_price, current_price, default_current_sl_price
                )

                if new_sl_price:
                    self.enhanced_logger.logger.info(
                        f"🆕 创建新的止损订单: ${new_sl_price:.2f}"
                    )

                    # 创建新的止损订单
                    await self._create_hold_stop_loss_order(
                        symbol, side.value, amount, new_sl_price
                    )
                    # 标记该仓位已管理
                    self._managed_positions.add(position_key)
                else:
                    self.enhanced_logger.logger.warning(
                        f"⚠️ 无法计算 {symbol} 的止损价格"
                    )

        except Exception as e:
            self.enhanced_logger.logger.error(f"调整 {symbol} 止损订单失败: {e}")

    def _calculate_hold_stop_loss_price(
        self,
        side: str,
        entry_price: float,
        current_price: float,
        current_sl_price: float,
    ) -> float | None:
        """计算HOLD信号的止损价格"""
        if side.lower() == "long":
            # 多头持仓
            if current_price > entry_price:
                # 盈利状态：止损为当前价的99.8% (0.2%)
                return current_price * 0.998
            else:
                # 亏损状态：止损为入仓价的99.5% (0.5%)
                return entry_price * 0.995
        elif side.lower() == "short":
            # 空头持仓
            if current_price < entry_price:
                # 盈利状态：止损为当前价的100.2% (0.2%)
                return current_price * 1.002
            else:
                # 亏损状态：止损为入仓价的100.5% (0.5%)
                return entry_price * 1.005

        return None

    async def _create_hold_stop_loss_order(
        self, symbol: str, side: str, amount: float, stop_price: float
    ) -> None:
        """创建HOLD信号的止损订单"""
        try:
            # 根据持仓方向确定止损订单方向
            if side.lower() == "long":
                sl_side = "sell"  # 多头止损卖出
            else:
                sl_side = "buy"  # 空头止损买入

            # 直接使用订单管理器创建止损订单，避免做空检查
            from ..exchange.models import TradeSide

            sl_side_enum = TradeSide.BUY if sl_side.lower() == "buy" else TradeSide.SELL

            result = await self.trading_engine.order_manager.create_stop_order(
                symbol=symbol,
                side=sl_side_enum,
                amount=amount,
                stop_price=stop_price,
                reduce_only=True,
            )

            if result.success:
                self.enhanced_logger.logger.info(
                    f"✅ 创建HOLD止损订单成功: {symbol} {sl_side.upper()} @ ${stop_price:.2f}"
                )
            else:
                self.enhanced_logger.logger.error(
                    f"❌ 创建HOLD止损订单失败: {result.error_message}"
                )

        except Exception as e:
            self.enhanced_logger.logger.error(f"创建HOLD止损订单异常: {e}")

    async def _execute_trades(self, trades: List[Dict[str, Any]]) -> int:
        """执行交易列表，返回成功执行的交易数量"""
        executed_trades = 0

        if not trades:
            return executed_trades

        self.enhanced_logger.logger.info(f"💰 准备执行 {len(trades)} 笔交易")

        # 处理每笔交易
        for i, trade in enumerate(trades, 1):
            action = trade.get("side", "unknown")
            price = trade.get("price", 0)
            size = trade.get("amount", 0)
            reason = trade.get("reason", "")
            confidence = trade.get("confidence", 0)

            # 检查是否是横盘清仓信号
            if trade.get("type") == "close_all" or trade.get("is_consolidation"):
                self.enhanced_logger.logger.warning(f"⚠️ 检测到横盘清仓信号！")
                self.enhanced_logger.logger.warning(f"  原因: {reason}")
                self.enhanced_logger.logger.warning(f"  置信度: {confidence:.2f}")

                # 执行清仓操作
                close_result = await self._execute_close_all_positions(reason)
                if close_result:
                    executed_trades += 1
                continue  # 跳过普通交易执行

            # 计算止盈止损价格（基于6%止盈，2%止损）
            tp_price, sl_price = self._calculate_tp_sl_prices(action, price)

            # 显示交易编号（多笔交易时）
            if len(trades) > 1:
                self.enhanced_logger.logger.info(f"📊 交易 {i}/{len(trades)}:")

            self.enhanced_logger.info_trading_decision(
                action, price, size, reason, confidence, tp_price, sl_price
            )

        # 逐笔执行交易
        for trade in trades:
            # 跳过已经处理的清仓信号
            if trade.get("type") == "close_all" or trade.get("is_consolidation"):
                continue

            result = await self.trading_engine.execute_trade(trade)
            if result.success:
                executed_trades += 1

        self.enhanced_logger.logger.info(
            f"✅ 交易执行完成，成功执行 {executed_trades}/{len(trades)} 笔交易"
        )

        # 统一处理止盈止损（如果没有HOLD信号管理）
        await self._manage_tp_sl_orders()

        return executed_trades

    def _calculate_tp_sl_prices(
        self, action: str, price: float
    ) -> tuple[float | None, float | None]:
        """计算止盈止损价格"""
        tp_price = None
        sl_price = None
        if price > 0:
            if action.upper() == "BUY":
                tp_price = price * (1 + self.TAKE_PROFIT_PERCENTAGE)  # 6% 止盈
                sl_price = price * (1 - self.STOP_LOSS_PERCENTAGE)  # 2% 止损
            elif action.upper() == "SELL":
                tp_price = price * (1 - self.TAKE_PROFIT_PERCENTAGE)  # 6% 止盈
                sl_price = price * (1 + self.STOP_LOSS_PERCENTAGE)  # 2% 止损
        return tp_price, sl_price

    async def _manage_tp_sl_orders(self, force: bool = False) -> None:
        """统一处理止盈止损订单"""
        # 检查当前周期是否已经管理过止盈止损（HOLD信号处理后跳过）
        if self._tp_sl_managed_this_cycle and not force:
            self.enhanced_logger.logger.info(
                "📊 当前周期已管理过止盈止损（由HOLD信号处理），跳过重复检查"
            )
            return

        self.enhanced_logger.logger.info("📊 更新仓位信息...")
        await self.trading_engine.position_manager.update_position(
            self.trading_engine.exchange_client, "BTC/USDT:USDT"
        )

        # 获取所有需要更新的持仓
        positions = self.trading_engine.position_manager.get_all_positions()
        if positions:
            for position in positions:
                if position and position.amount != 0:
                    symbol = position.symbol

                    # 统一使用manage_tp_sl_orders处理所有止盈止损需求
                    self.enhanced_logger.logger.info(
                        f"统一检查 {symbol} 的止盈止损订单状态"
                    )
                    try:
                        await self.trading_engine.trade_executor.manage_tp_sl_orders(
                            symbol, position
                        )
                        self._tp_sl_managed_this_cycle = True  # 标记已管理
                    except Exception as e:
                        self.enhanced_logger.logger.error(
                            f"为 {symbol} 检查止盈止损订单失败: {e}"
                        )
        else:
            self.enhanced_logger.logger.info("当前没有持仓，跳过止盈止损检查")

    async def _update_cycle_status(
        self,
        cycle_num: int,
        start_time: float,
        total_signals: int,
        executed_trades: int,
    ) -> None:
        """更新状态和记录周期完成信息"""
        # 5. 更新状态
        await self._update_status()

        # 记录周期完成信息
        execution_time = time.time() - start_time

        # 获取下次执行时间（从主循环存储的变量）
        next_exec_time = self._next_execution_time
        if next_exec_time:
            next_exec_time_str = next_exec_time.strftime("%Y-%m-%d %H:%M:%S")
            # 计算等待时间（使用精确时间）
            now_precise = datetime.now()
            wait_seconds = (next_exec_time - now_precise).total_seconds()
            if wait_seconds < 0:
                wait_seconds += 86400  # 如果跨越午夜，加24小时

            wait_minutes = int(wait_seconds // 60)
            wait_seconds_remainder = int(wait_seconds % 60)
            wait_time = f"{wait_minutes}分{wait_seconds_remainder}秒"

            # 记录周期完成和偏移信息
            if self.config.random_offset_enabled:
                # 计算当前偏移（相对于15分钟整点）
                current_minute = now_precise.minute
                cycle_minutes = self.config.cycle_minutes
                current_base_minute = (current_minute // cycle_minutes) * cycle_minutes
                next_base_minute = current_base_minute + cycle_minutes
                if next_base_minute >= 60:
                    next_base_minute = 0

                base_time = now_precise.replace(
                    minute=next_base_minute, second=0, microsecond=0
                )
                if next_base_minute == 0:
                    base_time = base_time.replace(hour=(now_precise.hour + 1) % 24)

                offset_seconds = (next_exec_time - base_time).total_seconds()
                offset_minutes = offset_seconds / 60

                self.enhanced_logger.logger.info(
                    f"⏰ 周期完成 - 下次执行偏移: {offset_minutes:+.1f} 分钟 (随机范围: ±{self.config.random_offset_range / 60:.0f}分钟，周期: {cycle_minutes}分钟)"
                )

                # 重置AI信号缓存标志，为下个周期做准备
                self._ai_signals_cache_valid = False
                self._cached_ai_signals = []

                # 🆕 重置优化组件状态，为下个周期做准备
                try:
                    # 重置信号过滤器历史
                    if hasattr(self, "_signal_filter") and self._signal_filter:
                        self._signal_filter.reset_history()

                    # 重置冷却管理器（新的一天重置）
                    if hasattr(self, "_cooling_manager") and self._cooling_manager:
                        # 检查是否是新的一天
                        now = datetime.now()
                        if now.hour == 0 and now.minute < 5:  # 凌晨0点附近
                            self._cooling_manager.reset_for_new_day()
                            self.enhanced_logger.logger.info(
                                "冷却管理器已重置为新的一天"
                            )

                except Exception as e:
                    self.enhanced_logger.logger.warning(f"优化组件重置异常: {e}")
        else:
            next_exec_time_str = "未知"
            wait_time = "未知"

        # 记录周期完成
        self.enhanced_logger.info_cycle_complete(
            cycle_num,
            execution_time,
            total_signals,
            executed_trades,
            next_exec_time_str,
            wait_time,
        )

    async def _trading_cycle(self, cycle_num: int) -> None:
        """执行一次交易循环"""
        import time

        start_time = time.time()
        total_signals = 0
        executed_trades = 0
        alphapulse_signals = []
        self._tp_sl_managed_this_cycle = False  # 重置周期标志
        self._managed_positions.clear()  # 重置已管理仓位集合

        try:
            # 1. 获取和处理市场数据
            market_data = await self._process_market_data()

            # 1.5. AlphaPulse信号处理（如果启用）
            skip_rest_cycle = False  # 标记是否跳过后续分析
            if hasattr(self, "alphapulse_engine") and self.alphapulse_engine:
                from ..alphapulse.config import AlphaPulseConfig

                config = AlphaPulseConfig.from_env()
                if config.enabled:
                    # 检查是否使用后备模式
                    if config.fallback_cron_enabled:
                        # 后备模式：手动触发AlphaPulse处理
                        alphapulse_signal = await self.alphapulse_engine.process_cycle()

                        # 如果AlphaPulse没有返回有效信号，跳过整个交易周期
                        if not alphapulse_signal or alphapulse_signal.signal_type in [
                            "hold",
                            None,
                        ]:
                            self.enhanced_logger.logger.info(
                                f"💤 AlphaPulse未检测到有效信号 (hold/none)，跳过后续分析"
                            )
                            skip_rest_cycle = True
                        elif alphapulse_signal.signal_type in ["buy", "sell"]:
                            alphapulse_signals.append(
                                {
                                    "type": alphapulse_signal.signal_type,
                                    "symbol": alphapulse_signal.symbol,
                                    "source": "alphapulse",
                                    "confidence": alphapulse_signal.confidence,
                                    "reason": alphapulse_signal.reasoning,
                                    "execution_params": alphapulse_signal.execution_params,
                                    "ai_result": alphapulse_signal.ai_result,
                                }
                            )
                            self.enhanced_logger.logger.info(
                                f"📡 AlphaPulse后备模式信号: {alphapulse_signal.signal_type.upper()} "
                                f"{alphapulse_signal.symbol} (置信度: {alphapulse_signal.confidence:.2f})"
                            )

            # 如果跳过后续分析，直接进入周期完成阶段
            if skip_rest_cycle:
                self.enhanced_logger.logger.info(
                    f"⏭️ 跳过第 {cycle_num} 轮交易周期（AlphaPulse过滤）"
                )
                await self._update_cycle_status(cycle_num, start_time, 0, 0)
                return

            # 将AlphaPulse结果放入market_data，供AI分析参考
            if alphapulse_signal and alphapulse_signal.signal_type in ["buy", "sell"]:
                # 从market_data中提取技术指标
                indicator_data = alphapulse_signal.market_data.get("indicators", {})
                market_data["alphapulse_signal"] = {
                    "signal_type": alphapulse_signal.signal_type,
                    "confidence": alphapulse_signal.confidence,
                    "reasoning": alphapulse_signal.reasoning,
                    "indicator_result": {
                        "rsi": indicator_data.get("rsi"),
                        "macd": indicator_data.get("macd"),
                        "adx": indicator_data.get("adx"),
                        "bb_position": indicator_data.get("bb_position"),
                        "price_position_24h": indicator_data.get("price_position_24h"),
                        "price_position_7d": indicator_data.get("price_position_7d"),
                        "trend_direction": indicator_data.get("trend_direction"),
                        "atr_percent": indicator_data.get("atr_percent"),
                    },
                }
                self.enhanced_logger.logger.info(
                    f"📊 AlphaPulse结果已传递给AI: {alphapulse_signal.signal_type.upper()} "
                    f"(置信度: {alphapulse_signal.confidence:.2f})"
                )

            # 2. 生成交易信号
            signals, total_signals = await self._generate_trading_signals(
                market_data, time.time() - start_time
            )

            # 添加调试日志
            self.enhanced_logger.logger.info(
                f"🔍 调试：选择后的信号数量: {len(signals)}"
            )
            for i, signal in enumerate(signals):
                self.enhanced_logger.logger.info(
                    f"  信号 {i + 1}: {signal.get('type', signal.get('signal', 'UNKNOWN'))}, 来源: {signal.get('source', 'unknown')}, 信心: {signal.get('confidence', 0):.2f}"
                )

            # 3. 风险评估和交易执行
            executed_trades = await self._assess_risk_and_execute_trades(
                signals, market_data
            )

            # 4. 更新状态和记录周期完成
            await self._update_cycle_status(
                cycle_num, start_time, total_signals, executed_trades
            )

        except Exception as e:
            self.enhanced_logger.logger.error(f"交易循环执行失败: {e}")
            import traceback

            self.enhanced_logger.logger.error(f"详细错误: {traceback.format_exc()}")

    async def _select_final_signals(
        self, all_signals: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """从所有信号中选择最终要执行的信号"""
        try:
            if not all_signals:
                return []

            # 按信号来源分组
            alphapulse_signals = [
                s for s in all_signals if s.get("source") == "alphapulse"
            ]
            ai_signals = [s for s in all_signals if s.get("source") == "ai"]
            strategy_signals = [
                s
                for s in all_signals
                if s.get("source")
                in ["conservative_strategy", "moderate_strategy", "aggressive_strategy"]
            ]

            self.enhanced_logger.logger.info("🔍 选择最终交易信号:")

            # 优先选择AlphaPulse信号（最高优先级，因为它是技术指标+AI双重验证的结果）
            if alphapulse_signals:
                best_alphapulse_signal = max(
                    alphapulse_signals, key=lambda x: x.get("confidence", 0)
                )
                self.enhanced_logger.logger.info(
                    f"  ⭐ 选择AlphaPulse信号（置信度: {best_alphapulse_signal.get('confidence', 0):.2f}）"
                    f" - {best_alphapulse_signal.get('type', 'UNKNOWN').upper()}"
                )
                return [best_alphapulse_signal]

            # 其次选择AI信号
            if ai_signals:
                # 如果有多个AI信号，选择置信度最高的
                if len(ai_signals) > 1:
                    best_ai_signal = max(
                        ai_signals, key=lambda x: x.get("confidence", 0)
                    )
                    self.enhanced_logger.logger.info(
                        f"  选择AI信号（置信度最高: {best_ai_signal.get('confidence', 0):.2f}）"
                    )
                    return [best_ai_signal]
                else:
                    self.enhanced_logger.logger.info(
                        f"  选择AI信号: {ai_signals[0].get('type', 'UNKNOWN').upper()}"
                    )
                    return ai_signals

            # 如果没有AI信号，选择策略信号
            elif strategy_signals:
                # 按投资类型优先级选择
                from ..config import load_config

                config = load_config()
                investment_type = config.strategies.investment_type

                # 根据投资类型选择对应的策略信号
                priority_signals = [
                    s
                    for s in strategy_signals
                    if investment_type in s.get("source", "")
                ]

                if priority_signals:
                    # 选择置信度最高的优先策略信号
                    best_strategy_signal = max(
                        priority_signals, key=lambda x: x.get("confidence", 0)
                    )
                    self.enhanced_logger.logger.info(
                        f"  选择{investment_type}策略信号（置信度: {best_strategy_signal.get('confidence', 0):.2f}）"
                    )
                    return [best_strategy_signal]
                else:
                    # 如果没有匹配的策略信号，选择置信度最高的策略信号
                    best_strategy_signal = max(
                        strategy_signals, key=lambda x: x.get("confidence", 0)
                    )
                    self.enhanced_logger.logger.info(
                        f"  选择置信度最高的策略信号: {best_strategy_signal.get('confidence', 0):.2f}"
                    )
                    return [best_strategy_signal]

            # 如果都没有，返回空列表
            self.enhanced_logger.logger.info("  没有合适的信号，返回空")
            return []

        except Exception as e:
            self.enhanced_logger.logger.error(f"选择最终信号失败: {e}")
            # 出错时返回置信度最高的信号
            if all_signals:
                return [max(all_signals, key=lambda x: x.get("confidence", 0))]
            return []

    async def _update_status(self) -> None:
        """更新机器人状态"""
        # 这里可以添加状态更新逻辑
        pass

    def get_status(self) -> Dict[str, Any]:
        """获取机器人状态"""
        status = super().get_status()
        status.update(
            {
                "running": self._running,
                "start_time": self._start_time.isoformat()
                if self._start_time
                else None,
                "uptime": self.get_uptime(),
                "trades_executed": getattr(self, "trade_count", 0),
                "profit_loss": getattr(self, "total_pnl", 0.0),
            }
        )
        return status
