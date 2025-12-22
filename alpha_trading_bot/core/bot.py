"""
交易机器人主类
"""

import asyncio
import logging
import random
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass

from .base import BaseComponent, BaseConfig
from .exceptions import TradingBotException
from ..utils.logging import LoggerMixin
from .health_check import get_health_check
from .monitor import get_system_monitor, collect_metrics_periodically, monitor_performance

@dataclass
class BotConfig(BaseConfig):
    """机器人配置"""
    trading_enabled: bool = True
    max_position_size: float = 0.01
    leverage: int = 10
    test_mode: bool = True
    cycle_interval: int = 15  # 分钟（从配置文件中读取，默认15分钟）
    random_offset_enabled: bool = True  # 是否启用随机时间偏移
    random_offset_range: int = 180  # 随机偏移范围（秒），默认±3分钟

class TradingBot(BaseComponent):
    """交易机器人主类"""

    def __init__(self, config: Optional[BotConfig] = None):
        """初始化交易机器人"""
        super().__init__(config or BotConfig(name="AlphaTradingBot"))
        self._running = False
        self._start_time = None

    @property
    def enhanced_logger(self):
        """获取增强型日志记录器"""
        from ..utils.logging import EnhancedLogger
        # 使用完整的模块路径和类名，确保日志记录器名称一致性
        module_path = self.__class__.__module__
        class_name = self.__class__.__name__
        if module_path and module_path != '__main__':
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
                name="TradingEngine",
                test_mode=config_manager.trading.test_mode
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
                self.enhanced_logger.logger.warning(f"数据管理器初始化失败: {e}，将继续运行但不保存历史数据")
                self.data_manager = None

            # 初始化策略管理器
            from ..strategies import StrategyManager
            self.strategy_manager = StrategyManager(ai_manager=self.ai_manager)
            await self.strategy_manager.initialize()

            # 初始化风控管理器
            from ..exchange.trading import RiskManager
            self.risk_manager = RiskManager()
            await self.risk_manager.initialize()

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
                    side = TradeSide.SELL if position.side == 'long' else TradeSide.BUY

                    self.enhanced_logger.logger.info(f"正在平仓: {symbol} {position.side} {amount}")

                    # 创建平仓订单
                    close_trade = {
                        'symbol': symbol,
                        'side': side.value,
                        'amount': amount,
                        'type': 'market',
                        'reason': f'横盘清仓 - {reason}',
                        'confidence': 1.0,  # 清仓信号具有高置信度
                        'is_close_all': True,
                        'reduce_only': True
                    }

                    try:
                        result = await self.trading_engine.execute_trade(close_trade)
                        if result.success:
                            closed_count += 1
                            self.enhanced_logger.logger.info(f"✓ 平仓成功: {symbol}")
                        else:
                            failed_count += 1
                            self.enhanced_logger.logger.error(f"✗ 平仓失败: {symbol} - {result.error_message}")
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
                            self.enhanced_logger.logger.info(f"取消 {symbol} 的 {len(algo_orders)} 个算法订单")
                            for order in algo_orders:
                                try:
                                    await self.order_manager.cancel_algo_order(order['algoId'], symbol)
                                    self.enhanced_logger.logger.info(f"✓ 取消算法订单: {order['algoId']}")
                                except Exception as e:
                                    self.enhanced_logger.logger.error(f"✗ 取消算法订单失败: {order['algoId']} - {e}")
            except Exception as e:
                self.enhanced_logger.logger.error(f"清理委托单时出错: {e}")

            # 总结结果
            self.enhanced_logger.logger.warning(f"清仓操作完成: 成功 {closed_count} 个, 失败 {failed_count} 个")

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
        if hasattr(self, 'trading_engine'):
            await self.trading_engine.cleanup()
        if hasattr(self, 'strategy_manager'):
            await self.strategy_manager.cleanup()
        if hasattr(self, 'risk_manager'):
            await self.risk_manager.cleanup()
        if hasattr(self, 'ai_manager'):
            await self.ai_manager.cleanup()
        if hasattr(self, 'data_manager'):
            await self.data_manager.cleanup()

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
            self.enhanced_logger.logger.warning(f"启动监控任务失败: {e}，继续运行主程序")

        # 添加调试信息
        cycle_minutes = self.config.cycle_interval
        self.enhanced_logger.logger.debug(f"进入交易循环，等待下一个{cycle_minutes}分钟周期（含随机偏移）...")

        try:
            cycle_count = 0
            while self._running:
                cycle_count += 1
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # 使用增强型日志记录器记录交易周期开始
                self.enhanced_logger.info_cycle_start(cycle_count, current_time)

                # 执行一次交易循环
                await self._trading_cycle(cycle_count)

                # 计算等待到下一个周期的时间（使用配置中的周期 + 随机偏移）
                now = datetime.now()
                cycle_minutes = self.config.cycle_interval  # 从配置读取周期（默认15分钟）

                # 计算下一个周期的基础时间
                current_minute = now.minute
                next_minute = ((current_minute // cycle_minutes) + 1) * cycle_minutes
                if next_minute >= 60:
                    next_minute = next_minute % 60
                    next_hour = now.hour + (next_minute // 60)
                    if next_hour >= 24:
                        next_hour = next_hour % 24
                else:
                    next_hour = now.hour

                # 基础执行时间（周期整点）
                base_execution_time = now.replace(hour=next_hour, minute=next_minute, second=0, microsecond=0)

                # 添加随机时间偏移（使用配置的偏移范围）
                offset_range = self.config.random_offset_range  # 默认±180秒（±3分钟）
                random_offset = random.randint(-offset_range, offset_range)
                next_execution_time = base_execution_time + timedelta(seconds=random_offset)

                # 确保不会在过去时间执行（如果随机偏移为负数且绝对值很大）
                if next_execution_time <= now:
                    next_execution_time = base_execution_time
                    self.enhanced_logger.logger.warning(f"随机偏移导致执行时间在过去，已调整为基准时间")

                # 记录周期和随机偏移信息
                offset_minutes = random_offset / 60
                offset_range_minutes = offset_range / 60
                self.enhanced_logger.logger.info(f"⏰ 下次执行周期: {cycle_minutes}分钟 + 随机偏移: {offset_minutes:+.1f} 分钟 (范围: ±{offset_range_minutes}分钟)")

                # 计算等待时间
                wait_seconds = (next_execution_time - now).total_seconds()
                if wait_seconds < 0:
                    wait_seconds += 86400

                # 记录等待信息
                self.enhanced_logger.logger.info(f"⏰ 等待 {wait_seconds:.0f} 秒到下一个15分钟整点执行...")

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

    async def _trading_cycle(self, cycle_num: int) -> None:
        """执行一次交易循环"""
        import time
        start_time = time.time()
        total_signals = 0
        executed_trades = 0

        try:
            # 1. 获取市场数据
            self.enhanced_logger.logger.info("📊 获取市场数据...")
            market_data = await self.trading_engine.get_market_data()

            # 记录市场数据详情
            if market_data:
                current_price = market_data.get('price', 0)
                period = market_data.get('period', '15m')
                change_percent = market_data.get('change_percent', 0)
                last_kline_time = market_data.get('last_kline_time', '')

                self.enhanced_logger.info_market_data(
                    current_price, period, change_percent, last_kline_time
                )

                # 输出详细的成交量信息
                volume_24h = market_data.get('volume', 0)
                avg_volume_24h = market_data.get('avg_volume_24h', 0)

                self.enhanced_logger.logger.info("📈 市场成交量详情:")
                self.enhanced_logger.logger.info(f"  📊 交易所24h成交量: {volume_24h}")
                if avg_volume_24h > 0:
                    self.enhanced_logger.logger.info(f"  📊 计算的平均成交量: {avg_volume_24h:.2f}")

                # 如果交易所24h成交量为0但有平均成交量，说明使用了备用数据
                if volume_24h == 0 and avg_volume_24h > 0:
                    self.enhanced_logger.logger.info("  ⚠️  注意：交易所24h成交量为0，系统将使用计算的平均成交量进行评估")

                # 记录OHLCV数据获取状态
                if market_data.get('ohlcv'):
                    self.enhanced_logger.logger.info(f"✅ 成功获取 {len(market_data['ohlcv'])} 根K线数据用于技术指标计算")
                else:
                    self.enhanced_logger.logger.warning("⚠️ 未能获取OHLCV数据，技术指标将使用基础分数")

            # 2. 生成交易信号
            self.enhanced_logger.logger.info("🔍 分析市场状态...")

            # 获取AI提供商信息
            providers = self.ai_manager.providers if hasattr(self.ai_manager, 'providers') else []
            config_providers = self.ai_manager.config.primary_provider if hasattr(self.ai_manager, 'config') else 'kimi'

            # 记录AI提供商信息
            self.enhanced_logger.info_ai_providers(providers, config_providers)

            # 执行健康检查
            try:
                from alpha_trading_bot.core.health_check import get_health_check
                health_check = await get_health_check()

                # 计算执行时间（从开始到现在）
                execution_time = time.time() - start_time

                # 执行健康检查
                health_report = await health_check.perform_health_check(
                    market_data=market_data,
                    execution_time=execution_time,
                    api_response_time=0,  # TODO: 可以从exchange_client获取实际API响应时间
                    api_errors=0  # TODO: 可以从exchange_client获取实际API错误数
                )

                # 记录健康状态
                self.enhanced_logger.logger.info(f"🏥 健康检查: {health_report['overall_status'].upper()}")

                # 输出详细健康检查信息
                self.enhanced_logger.logger.info("📊 详细健康检查结果:")

                # 流动性详情
                liquidity = health_report.get('liquidity', {})
                if liquidity:
                    self.enhanced_logger.logger.info(f"  💧 流动性状态: {liquidity.get('status', 'unknown')}")
                    self.enhanced_logger.logger.info(f"  📈 流动性评分: {liquidity.get('score', 0)}")
                    if liquidity.get('issues'):
                        self.enhanced_logger.logger.info(f"  ⚠️  流动性问题: {', '.join(liquidity['issues'])}")

                    # 详细ATR信息
                    atr_info = liquidity.get('atr_info', {})
                    if atr_info:
                        self.enhanced_logger.logger.info(f"  📊 ATR详细分析:")
                        self.enhanced_logger.logger.info(f"    📈 ATR值: {atr_info.get('atr_value', 0):.2f} USDT")
                        self.enhanced_logger.logger.info(f"    📊 ATR百分比: {atr_info.get('atr_percentage', 0):.2f}%")
                        self.enhanced_logger.logger.info(f"    🎯 评估: {atr_info.get('assessment', '未知')}")

                        # 添加ATR解释
                        atr_pct = atr_info.get('atr_percentage', 0)
                        if atr_pct < 0.2:
                            self.enhanced_logger.logger.info(f"    💡 解释: ATR百分比低于0.2%，市场波动极小，价格可能处于横盘状态")
                        elif atr_pct < 0.5:
                            self.enhanced_logger.logger.info(f"    💡 解释: ATR百分比在0.2%-0.5%之间，市场波动较低")
                        else:
                            self.enhanced_logger.logger.info(f"    💡 解释: ATR百分比高于0.5%，市场波动正常")

                # 性能详情
                performance = health_report.get('performance', {})
                if performance:
                    self.enhanced_logger.logger.info(f"  ⚡ 性能状态: {performance.get('status', 'unknown')}")
                    if performance.get('execution_time'):
                        self.enhanced_logger.logger.info(f"  ⏱️  执行时间: {performance['execution_time']:.2f}s")

                # API详情
                api = health_report.get('api', {})
                if api:
                    self.enhanced_logger.logger.info(f"  🔌 API状态: {api.get('status', 'unknown')}")
                    if api.get('response_time'):
                        self.enhanced_logger.logger.info(f"  🔄 API响应时间: {api['response_time']:.2f}s")
                    if api.get('errors', 0) > 0:
                        self.enhanced_logger.logger.info(f"  ❌ API错误数: {api['errors']}")

                # 统计信息
                self.enhanced_logger.logger.info(f"  📋 统计: {health_report.get('critical_count', 0)}个严重问题, {health_report.get('warning_count', 0)}个警告")

                if health_report['overall_status'] != 'healthy':
                    self.enhanced_logger.logger.warning(f"⚠️  系统健康异常: {health_report['critical_count']}个严重问题, {health_report['warning_count']}个警告")

                    # 如果流动性严重不足，可以考虑暂停交易
                    liquidity_health = health_report.get('liquidity', {})
                    if liquidity_health.get('status') == 'critical':
                        self.enhanced_logger.logger.error("🚨 流动性严重不足，建议暂停交易")
                        # TODO: 可以在这里添加暂停交易的逻辑

            except Exception as e:
                self.enhanced_logger.logger.error(f"健康检查失败: {e}")

            # 生成AI信号
            ai_signals = await self.ai_manager.generate_signals(market_data)

            # 如果有多AI模式且多个提供商，显示详细信息
            if hasattr(self.ai_manager, 'config') and self.ai_manager.config.use_multi_ai and len(providers) > 1:
                # 检查是否是缓存的信号
                is_cached = any(signal.get('_from_cache') for signal in ai_signals)

                if is_cached:
                    # 如果是缓存信号，跳过详细分析（已经在AI manager中记录过）
                    self.enhanced_logger.logger.info("ℹ️ 使用缓存的AI信号，跳过重复分析")
                else:
                    self.enhanced_logger.info_ai_parallel_request(providers)

                    # 记录信号统计 - 修正统计逻辑
                    # 获取个体信号（非融合信号）
                    individual_signals = []
                    fusion_signals = []

                    for signal in ai_signals:
                        if signal.get('provider') == 'fusion':
                            fusion_signals.append(signal)
                        else:
                            individual_signals.append(signal)

                    # 统计个体信号的成功/失败
                    success_count = len([s for s in individual_signals if s.get('confidence', 0) >= 0.3])
                    fail_count = len([s for s in individual_signals if s.get('confidence', 0) < 0.3])

                    self.enhanced_logger.info_ai_fusion_stats(
                        success_count, fail_count, providers,
                        [s.get('provider', 'unknown') for s in individual_signals]
                    )

                # 如果有多个信号，进行融合分析
                if len(ai_signals) > 1:
                    # 计算信号多样性
                    signal_types = [s.get('signal', 'HOLD') for s in ai_signals]
                    signal_counts = {
                        'BUY': signal_types.count('BUY'),
                        'SELL': signal_types.count('SELL'),
                        'HOLD': signal_types.count('HOLD')
                    }

                    # 计算多样性分数
                    total = len(signal_types)
                    if total > 0:
                        buy_ratio = signal_counts['BUY'] / total
                        sell_ratio = signal_counts['SELL'] / total
                        hold_ratio = signal_counts['HOLD'] / total
                        diversity_score = 1 - max(buy_ratio, sell_ratio, hold_ratio)

                        # 计算平均信心
                        confidences = [s.get('confidence', 0.5) for s in ai_signals]
                        avg_confidence = sum(confidences) / len(confidences)
                        std_confidence = (sum((c - avg_confidence) ** 2 for c in confidences) / len(confidences)) ** 0.5

                        self.enhanced_logger.info_ai_signal_diversity(
                            diversity_score, signal_counts, avg_confidence, std_confidence
                        )

                    # 投票统计
                    voting_stats = signal_counts
                    self.enhanced_logger.info_ai_voting_stats(voting_stats)

                    # 信心分布
                    confidence_dist = {
                        'BUY': sum(s.get('confidence', 0) for s in ai_signals if s.get('signal') == 'BUY') / max(signal_counts['BUY'], 1),
                        'SELL': sum(s.get('confidence', 0) for s in ai_signals if s.get('signal') == 'SELL') / max(signal_counts['SELL'], 1),
                        'HOLD': sum(s.get('confidence', 0) for s in ai_signals if s.get('signal') == 'HOLD') / max(signal_counts['HOLD'], 1)
                    }

                    self.enhanced_logger.info_ai_confidence_distribution(confidence_dist)
            else:
                # 单AI模式，显示基本信息
                if ai_signals:
                    signal = ai_signals[0]
                    self.enhanced_logger.logger.info(f"✅ AI信号生成成功: {signal.get('signal', 'HOLD')} (信心: {signal.get('confidence', 0):.2f}, 提供商: {signal.get('provider', config_providers)})")
                else:
                    self.enhanced_logger.logger.info("⚠️ 未生成AI信号，使用回退模式")

            # 生成所有信号（包括策略信号）
            all_signals = await self.strategy_manager.generate_signals(market_data, ai_signals)
            total_signals = len(all_signals)  # 更新信号总数

            # 记录信号摘要
            if all_signals:
                self.enhanced_logger.logger.info(f"📊 交易信号摘要:")
                signal_summary = {}
                for signal in all_signals:
                    signal_type = signal.get('type', 'unknown').upper()
                    signal_summary[signal_type] = signal_summary.get(signal_type, 0) + 1

                for signal_type, count in signal_summary.items():
                    self.enhanced_logger.logger.info(f"  {signal_type}: {count} 个")
            else:
                self.enhanced_logger.logger.info("⚠️ 未生成任何交易信号")

            # 选择最终信号
            signals = await self._select_final_signals(all_signals)

            # 添加调试日志
            self.enhanced_logger.logger.info(f"🔍 调试：选择后的信号数量: {len(signals)}")
            for i, signal in enumerate(signals):
                self.enhanced_logger.logger.info(f"  信号 {i+1}: {signal.get('type', signal.get('signal', 'UNKNOWN'))}, 来源: {signal.get('source', 'unknown')}, 信心: {signal.get('confidence', 0):.2f}")

            # 3. 风险评估
            self.enhanced_logger.logger.info("⚠️ 进行风险评估...")
            # 获取当前价格用于风险评估
            current_price = market_data.get('price', 0)
            # 获取账户余额用于动态计算交易数量
            balance = await self.trading_engine.get_balance()
            risk_assessment = await self.risk_manager.assess_risk(signals, current_price, balance)
            risk_level = risk_assessment.get('risk_level', 'unknown')
            risk_score = risk_assessment.get('risk_score', 0)
            trades = risk_assessment.get('trades', [])  # 确保trades变量被定义

            self.enhanced_logger.logger.info(f"风险评估结果: 等级={risk_level}, 分数={risk_score:.2f}")

            # 记录风险评估详情
            if risk_assessment:
                self.enhanced_logger.logger.info(f"📋 风险评估详情:")
                self.enhanced_logger.logger.info(f"  当日亏损: ${risk_assessment.get('daily_loss', 0):.2f} USDT")
                self.enhanced_logger.logger.info(f"  连续亏损次数: {risk_assessment.get('consecutive_losses', 0)}")
                self.enhanced_logger.logger.info(f"  评估原因: {risk_assessment.get('reason', '无')}")

            # 记录交易执行情况
            if trades:
                self.enhanced_logger.logger.info(f"✅ 通过风险评估的交易 ({len(trades)} 个):")
                for i, trade in enumerate(trades, 1):
                    self.enhanced_logger.logger.info(f"  交易 {i}:")
                    self.enhanced_logger.logger.info(f"    操作: {trade.get('side', 'unknown').upper()}")
                    self.enhanced_logger.logger.info(f"    价格: ${trade.get('price', 0) or 0:,.2f}")
                    self.enhanced_logger.logger.info(f"    数量: {trade.get('amount', 0)}")
                    self.enhanced_logger.logger.info(f"    原因: {trade.get('reason', '无')}")
                    self.enhanced_logger.logger.info(f"    信心度: {trade.get('confidence', 0):.2f}")
                    self.enhanced_logger.logger.info("    " + "-" * 30)

            # 4. 执行交易
            if risk_assessment.get('can_trade', False):
                # 获取交易列表（如果有的话）
                trades = risk_assessment.get('trades', [])
                if trades:
                    self.enhanced_logger.logger.info(f"💰 准备执行 {len(trades)} 笔交易")
                    for i, trade in enumerate(trades, 1):
                        action = trade.get('side', 'unknown')
                        price = trade.get('price', 0)
                        size = trade.get('amount', 0)
                        reason = trade.get('reason', '')
                        confidence = trade.get('confidence', 0)

                        # 检查是否是横盘清仓信号
                        if trade.get('type') == 'close_all' or trade.get('is_consolidation'):
                            self.enhanced_logger.logger.warning(f"⚠️ 检测到横盘清仓信号！")
                            self.enhanced_logger.logger.warning(f"  原因: {reason}")
                            self.enhanced_logger.logger.warning(f"  置信度: {confidence:.2f}")

                            # 执行清仓操作
                            close_result = await self._execute_close_all_positions(reason)
                            if close_result:
                                executed_trades += 1
                            continue  # 跳过普通交易执行

                        # 计算止盈止损价格（基于6%止盈，2%止损）
                        tp_price = None
                        sl_price = None
                        if price > 0:
                            if action.upper() == 'BUY':
                                tp_price = price * 1.06  # 6% 止盈
                                sl_price = price * 0.98  # 2% 止损
                            elif action.upper() == 'SELL':
                                tp_price = price * 0.94  # 6% 止盈
                                sl_price = price * 1.02  # 2% 止损

                        # 显示交易编号（多笔交易时）
                        if len(trades) > 1:
                            self.enhanced_logger.logger.info(f"📊 交易 {i}/{len(trades)}:")

                        self.enhanced_logger.info_trading_decision(
                            action, price, size, reason, confidence, tp_price, sl_price
                        )

                    # 逐笔执行交易
                    for trade in trades:
                        # 跳过已经处理的清仓信号
                        if trade.get('type') == 'close_all' or trade.get('is_consolidation'):
                            continue

                        result = await self.trading_engine.execute_trade(trade)
                        if result.success:
                            executed_trades += 1
                    self.enhanced_logger.logger.info(f"✅ 交易执行完成，成功执行 {executed_trades}/{len(trades)} 笔交易")

                    # 在15分钟周期内执行标记的TP/SL更新
                    # 先更新仓位信息，确保获取最新数据
                    self.enhanced_logger.logger.info("📊 更新仓位信息...")
                    await self.trading_engine.position_manager.update_position(self.trading_engine.exchange_client, "BTC/USDT:USDT")

                    # 获取所有需要更新的持仓
                    positions = self.trading_engine.position_manager.get_all_positions()
                    if positions:
                        for position in positions:
                            if position and position.amount != 0:
                                symbol = position.symbol
                                # 检查并更新止盈止损（包括创建缺失的订单）
                                self.enhanced_logger.logger.info(f"检查 {symbol} 的止盈止损订单状态")
                                try:
                                    # 检查是否需要创建缺失的止盈止损订单
                                    await self.trading_engine.trade_executor.check_and_create_missing_tp_sl(symbol, position)

                                    # 同时更新现有止盈止损订单（实现追踪止损）
                                    self.enhanced_logger.logger.info(f"🔍 检查是否需要更新 {symbol} 的追踪止损...")
                                    if self.trading_engine.trade_executor.config.enable_tp_sl:
                                        await self.trading_engine.trade_executor._check_and_update_tp_sl(
                                            symbol,
                                            position.side,
                                            position
                                        )
                                except Exception as e:
                                    self.enhanced_logger.logger.error(f"为 {symbol} 检查止盈止损订单失败: {e}")
                    else:
                        self.enhanced_logger.logger.info("当前没有持仓，跳过15分钟周期内TP/SL更新")
                else:
                    self.enhanced_logger.logger.info("ℹ️ 无交易信号通过风险评估")

                    # 检查持仓是否需要创建缺失的止盈止损订单
                    self.enhanced_logger.logger.info("🔍 检查持仓是否需要创建止盈止损订单...")
                    # 先更新仓位信息，确保获取最新数据
                    self.enhanced_logger.logger.info("📊 更新仓位信息...")
                    await self.trading_engine.position_manager.update_position(self.trading_engine.exchange_client, "BTC/USDT:USDT")

                    positions = self.trading_engine.position_manager.get_all_positions()
                    if positions:
                        for position in positions:
                            if position and position.amount > 0:
                                symbol = position.symbol
                                try:
                                    # 检查并创建缺失的止盈止损订单
                                    await self.trading_engine.trade_executor.check_and_create_missing_tp_sl(symbol, position)

                                    # 同时更新现有止盈止损订单（实现追踪止损）
                                    self.enhanced_logger.logger.info(f"🔍 检查是否需要更新 {symbol} 的追踪止损...")
                                    if self.trading_engine.trade_executor.config.enable_tp_sl:
                                        await self.trading_engine.trade_executor._check_and_update_tp_sl(
                                            symbol,
                                            position.side,
                                            position
                                        )
                                except Exception as e:
                                    self.enhanced_logger.logger.error(f"为 {symbol} 处理止盈止损订单失败: {e}")
                    else:
                        self.enhanced_logger.logger.info("当前没有持仓，无需检查止盈止损订单")
            else:
                self.enhanced_logger.logger.info("⚠️ 风险评估不通过，跳过交易")

            # 5. 更新状态
            await self._update_status()

            # 记录周期完成信息
            execution_time = time.time() - start_time

            # 计算下次执行时间（下一个周期整点 + 随机偏移）
            now = datetime.now()

            # 从配置读取周期（默认15分钟）
            cycle_minutes = self.config.cycle_interval
            next_minute = ((now.minute // cycle_minutes) + 1) * cycle_minutes
            if next_minute >= 60:
                next_minute = next_minute % 60
                next_hour = now.hour + (next_minute // 60) + 1
                if next_hour >= 24:
                    next_hour = next_hour % 24
            else:
                next_hour = now.hour

            # 基础执行时间（周期整点）
            base_execution_time = now.replace(hour=next_hour, minute=next_minute, second=0, microsecond=0)

            # 根据配置决定是否添加随机时间偏移
            if self.config.random_offset_enabled:
                # 添加随机时间偏移（使用配置的偏移范围）
                offset_range = self.config.random_offset_range  # 默认±180秒（±3分钟）
                random_offset = random.randint(-offset_range, offset_range)
                next_execution_time = base_execution_time + timedelta(seconds=random_offset)
            else:
                # 不启用随机偏移，直接使用基准时间
                random_offset = 0
                next_execution_time = base_execution_time

            # 确保不会在过去时间执行（如果随机偏移为负数且绝对值很大）
            if next_execution_time <= now:
                next_execution_time = base_execution_time
                self.enhanced_logger.logger.warning(f"随机偏移导致执行时间在过去，已调整为基准时间")

            # 记录随机偏移信息
            if self.config.random_offset_enabled:
                offset_minutes = random_offset / 60
                self.enhanced_logger.logger.info(f"⏰ 下次执行时间偏移: {offset_minutes:+.1f} 分钟 (随机范围: ±{self.config.random_offset_range/60:.0f}分钟，周期: {cycle_minutes}分钟)")
            else:
                self.enhanced_logger.logger.info(f"⏰ 下次执行时间: {next_execution_time.strftime('%Y-%m-%d %H:%M:%S')} (无随机偏移，周期: {cycle_minutes}分钟)")

            # 计算等待时间
            wait_seconds = (next_execution_time - now).total_seconds()
            if wait_seconds < 0:
                wait_seconds += 86400  # 如果跨越午夜，加24小时

            wait_minutes = int(wait_seconds // 60)
            wait_seconds_remainder = int(wait_seconds % 60)
            wait_time = f"{wait_minutes}分{wait_seconds_remainder}秒"

            # 记录周期完成
            self.enhanced_logger.info_cycle_complete(
                cycle_num, execution_time, total_signals, executed_trades,
                next_execution_time.strftime("%Y-%m-%d %H:%M:%S"), wait_time
            )

        except Exception as e:
            self.enhanced_logger.logger.error(f"交易循环执行失败: {e}")
            import traceback
            self.enhanced_logger.logger.error(f"详细错误: {traceback.format_exc()}")

    async def _select_final_signals(self, all_signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """从所有信号中选择最终要执行的信号"""
        try:
            if not all_signals:
                return []

            # 按信号来源分组
            ai_signals = [s for s in all_signals if s.get('source') == 'ai']
            strategy_signals = [s for s in all_signals if s.get('source') in ['conservative_strategy', 'moderate_strategy', 'aggressive_strategy']]

            self.enhanced_logger.logger.info("🔍 选择最终交易信号:")

            # 优先选择AI信号（如果有）
            if ai_signals:
                # 如果有多个AI信号，选择置信度最高的
                if len(ai_signals) > 1:
                    best_ai_signal = max(ai_signals, key=lambda x: x.get('confidence', 0))
                    self.enhanced_logger.logger.info(f"  选择AI信号（置信度最高: {best_ai_signal.get('confidence', 0):.2f}）")
                    return [best_ai_signal]
                else:
                    self.enhanced_logger.logger.info(f"  选择AI信号: {ai_signals[0].get('type', 'UNKNOWN').upper()}")
                    return ai_signals

            # 如果没有AI信号，选择策略信号
            elif strategy_signals:
                # 按投资类型优先级选择
                from ..config import load_config
                config = load_config()
                investment_type = config.strategies.investment_type

                # 根据投资类型选择对应的策略信号
                priority_signals = [s for s in strategy_signals if investment_type in s.get('source', '')]

                if priority_signals:
                    # 选择置信度最高的优先策略信号
                    best_strategy_signal = max(priority_signals, key=lambda x: x.get('confidence', 0))
                    self.enhanced_logger.logger.info(f"  选择{investment_type}策略信号（置信度: {best_strategy_signal.get('confidence', 0):.2f}）")
                    return [best_strategy_signal]
                else:
                    # 如果没有匹配的策略信号，选择置信度最高的策略信号
                    best_strategy_signal = max(strategy_signals, key=lambda x: x.get('confidence', 0))
                    self.enhanced_logger.logger.info(f"  选择置信度最高的策略信号: {best_strategy_signal.get('confidence', 0):.2f}")
                    return [best_strategy_signal]

            # 如果都没有，返回空列表
            self.enhanced_logger.logger.info("  没有合适的信号，返回空")
            return []

        except Exception as e:
            self.enhanced_logger.logger.error(f"选择最终信号失败: {e}")
            # 出错时返回置信度最高的信号
            if all_signals:
                return [max(all_signals, key=lambda x: x.get('confidence', 0))]
            return []

    async def _update_status(self) -> None:
        """更新机器人状态"""
        # 这里可以添加状态更新逻辑
        pass

    def get_status(self) -> Dict[str, Any]:
        """获取机器人状态"""
        status = super().get_status()
        status.update({
            'running': self._running,
            'start_time': self._start_time.isoformat() if self._start_time else None,
            'uptime': self.get_uptime(),
            'trades_executed': getattr(self, 'trade_count', 0),
            'profit_loss': getattr(self, 'total_pnl', 0.0)
        })
        return status