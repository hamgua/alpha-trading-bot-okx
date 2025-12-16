"""
交易机器人主类
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from dataclasses import dataclass

from .base import BaseComponent, BaseConfig
from .exceptions import TradingBotException
from ..utils.logging import LoggerMixin

@dataclass
class BotConfig(BaseConfig):
    """机器人配置"""
    trading_enabled: bool = True
    max_position_size: float = 0.01
    leverage: int = 10
    test_mode: bool = True
    cycle_interval: int = 15  # 分钟

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

        # 添加调试信息
        self.enhanced_logger.logger.debug("进入交易循环，等待下一个15分钟整点...")

        try:
            cycle_count = 0
            while self._running:
                cycle_count += 1
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # 使用增强型日志记录器记录交易周期开始
                self.enhanced_logger.info_cycle_start(cycle_count, current_time)

                # 执行一次交易循环
                await self._trading_cycle(cycle_count)

                # 计算等待到下一个15分钟整点的时间
                now = datetime.now()
                next_minute = ((now.minute // 15) + 1) * 15
                if next_minute >= 60:
                    next_minute = 0
                    next_hour = now.hour + 1
                    if next_hour >= 24:
                        next_hour = 0
                else:
                    next_hour = now.hour

                next_execution_time = now.replace(hour=next_hour, minute=next_minute, second=0, microsecond=0)

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
            risk_assessment = await self.risk_manager.assess_risk(signals, current_price)
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
                        result = await self.trading_engine.execute_trade(trade)
                        if result.success:
                            executed_trades += 1
                    self.enhanced_logger.logger.info(f"✅ 交易执行完成，成功执行 {executed_trades}/{len(trades)} 笔交易")
                else:
                    self.enhanced_logger.logger.info("ℹ️ 无交易信号通过风险评估")
            else:
                self.enhanced_logger.logger.info("⚠️ 风险评估不通过，跳过交易")

            # 5. 更新状态
            await self._update_status()

            # 记录周期完成信息
            execution_time = time.time() - start_time

            # 计算下次执行时间（下一个15分钟整点）
            from datetime import datetime, timedelta
            now = datetime.now()
            next_minute = ((now.minute // 15) + 1) * 15
            if next_minute >= 60:
                next_minute = 0
                next_hour = now.hour + 1
                if next_hour >= 24:
                    next_hour = 0
            else:
                next_hour = now.hour

            next_execution_time = now.replace(hour=next_hour, minute=next_minute, second=0, microsecond=0)

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