"""
自适应交易机器人主类 v2.0

核心特性：
1. 实时市场环境感知
2. 多策略动态选择
3. 硬止损 + 熔断保护
4. 自适应参数调整
5. 贝叶斯优化（后台）
6. 配置热更新
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from .trading_scheduler import TradingScheduler
from .signal_processor import SignalProcessor
from .position_manager import PositionManager
from ..config.models import Config

logger = logging.getLogger(__name__)


class AdaptiveTradingBot:
    """
    自适应交易机器人

    集成市场感知、策略选择、风险控制的完整交易系统
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config.from_env()
        self._running = False
        self._initialized = False

        # 交易所和AI客户端（初始化为None，在initialize方法中设置）
        self._exchange: Optional[Any] = None
        self._ai_client: Optional[Any] = None

        # 核心组件
        self.scheduler = TradingScheduler(config)
        self.position_manager = PositionManager(config)

        # === 新增：自适应组件 ===
        self._init_adaptive_components()

    def _init_adaptive_components(self) -> None:
        """初始化自适应组件"""
        # 导入自适应模块
        from ..ai.adaptive import (
            AdaptiveParameterManager,
            MarketRegimeDetector,
            PerformanceTracker,
            AdaptiveRulesEngine,
        )
        from ..ai.adaptive.strategy_library import StrategyLibrary
        from ..ai.adaptive.strategy_selector import AdaptiveStrategyManager
        from ..ai.adaptive.risk_manager import RiskControlManager, RiskConfig
        from ..ai.optimizer import ConfigUpdater

        # === ML 学习模块 ===
        from ..ai.ml.ml_data_manager import MLDataManager, get_ml_data_manager
        from ..ai.ml.adaptive_weight_optimizer import (
            AdaptiveWeightOptimizer,
            get_weight_optimizer,
        )
        from ..ai.ml.learning_integrator import (
            MLLearningIntegrator,
            SimpleLearningLoop,
            get_learning_integrator,
        )

        # 参数自适应
        self.param_manager = AdaptiveParameterManager()

        # 市场环境检测
        self.regime_detector = MarketRegimeDetector()

        # 表现追踪
        self.performance_tracker = PerformanceTracker()

        # 规则引擎
        self.rules_engine = AdaptiveRulesEngine()

        # 策略库和选择器
        self.strategy_library = StrategyLibrary()
        self.strategy_manager = AdaptiveStrategyManager()

        # 风险控制
        risk_config = RiskConfig(
            hard_stop_loss_percent=0.05,  # 5% 硬止损
            max_position_percent=0.1,  # 最大10%仓位
            circuit_breaker_threshold=0.03,  # 3%熔断
        )
        self.risk_manager = RiskControlManager(risk_config)

        # 配置管理
        self.config_updater = ConfigUpdater()

        # === ML 学习组件 ===
        # ML 数据管理器
        self.ml_data_manager = get_ml_data_manager()

        # 权重优化器
        self.weight_optimizer = get_weight_optimizer()

        # 回测学习器（无需真实交易也能学习）
        from ..ai.ml.signal_backtest import get_backtest_learner

        self.backtest_learner = get_backtest_learner()

        # 学习集成器（简化版）
        self.simple_learning = SimpleLearningLoop()

        logger.info("[自适应] 所有组件初始化完成（含ML学习模块 + 回测学习）")

    @property
    def exchange(self):
        """获取交易所客户端"""
        return getattr(self, "_exchange", None)

    @property
    def ai_client(self):
        """获取AI客户端"""
        return getattr(self, "_ai_client", None)

    async def initialize(self) -> bool:
        """初始化"""
        try:
            logger.info("初始化自适应交易机器人...")

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
        logger.info("=" * 60)
        logger.info("自适应交易机器人 v2.0 启动")
        logger.info("=" * 60)

        # 启动后台优化任务
        asyncio.create_task(self._background_optimization_task())

        try:
            first_run = True
            while self._running:
                await self._adaptive_trading_cycle(first_run=first_run)
                first_run = False

        except asyncio.CancelledError:
            logger.info("收到停止信号")
        finally:
            await self.cleanup()

    async def _adaptive_trading_cycle(self, first_run: bool = False) -> None:
        """
        自适应交易周期

        流程：
        1. 等待周期
        2. 获取市场数据
        3. 市场环境检测
        4. 风险状态评估
        5. 策略选择
        6. AI信号生成
        7. 信号融合
        8. 风险控制检查
        9. 执行交易
        """
        # 1. 等待周期
        await self.scheduler.wait_for_next_cycle(first_run)

        logger.info("=" * 60)
        logger.info("开始新的自适应交易周期")
        logger.info("=" * 60)

        try:
            # 类型断言：确保交易所和AI客户端已初始化
            assert self._exchange is not None, "Exchange client not initialized"
            assert self._ai_client is not None, "AI client not initialized"

            # 2. 获取市场数据
            market_data = await self._exchange.get_market_data()
            current_price = market_data.get("price", 0)

            logger.info(f"[市场] 当前价格: {current_price}")
            logger.info(f"[市场] 24h涨跌: {market_data.get('change_percent', 0):.2f}%")
            logger.info(
                f"[市场] RSI: {market_data.get('technical', {}).get('rsi', 50):.2f}"
            )
            logger.info(
                f"[市场] ATR%: {market_data.get('technical', {}).get('atr_percent', 0.02):.2%}"
            )

            # 3. 市场环境检测
            market_state = self.regime_detector.detect(market_data)
            logger.info(
                f"[环境] 市场状态: {market_state.regime.value}, "
                f"置信度: {market_state.confidence:.0%}, "
                f"趋势: {market_state.trend_strength:.2f}"
            )


            # === P1: 自适应参数调整（基于市场环境和绩效） ===
            # 分析市场环境并自动调整交易参数
            adjusted_config = self.param_manager.analyze_and_adjust(
                market_data=market_data,
                recent_performance=None
            )
            current_params = self.param_manager.get_current_params()

            # 应用调整后的参数到主配置（使AI客户端可以使用）
            if current_params.get('fusion_threshold'):
                self.config.ai.fusion_threshold = current_params['fusion_threshold']
            if current_params.get('stop_loss_percent'):
                self.config.ai.stop_loss_percent = current_params['stop_loss_percent']
            if current_params.get('position_multiplier'):
                self.config.ai.position_multiplier = current_params['position_multiplier']
            # 应用参数到 AI 集成器（adaptive_buy_condition 和 signal_optimizer）
            if self._ai_client:
                self._ai_client.update_integrator_config(current_params)

            logger.info(
                f"[自适应] 参数已调整: "
                f"阈值={current_params.get('fusion_threshold', 0):.2f}, "
                f"止损={current_params.get('stop_loss_percent', 0):.2%}, "
                f"仓位乘数={current_params.get('position_multiplier', 1):.2f}"
            )

            # 4. 获取持仓状态
            position_data = await self._exchange.get_position() or {}
            has_position = bool(position_data.get("amount", 0) > 0)

            if has_position:
                entry_price = position_data.get("entry_price", 0)
                logger.info(f"[持仓] 有持仓: {entry_price}")
            else:
                logger.info("[持仓] 无持仓")

            # 5. 风险状态评估
            risk_state = self.risk_manager.assess_risk(market_data, position_data)
            logger.info(
                f"[风险] 等级: {risk_state.risk_level.value}, "
                f"回撤: {risk_state.current_drawdown:.2%}, "
                f"熔断: {'是' if risk_state.circuit_breaker_active else '否'}"
            )

            # 检查熔断
            if risk_state.circuit_breaker_active:
                logger.warning(f"[风险] 熔断中: {risk_state.circuit_breaker_reason}")
                logger.info("跳过后续交易，等待下一个周期")
                return

            # 6. 获取所有策略信号
            strategy_signals = self.strategy_library.get_all_signals(market_data)
            logger.info(f"[策略] {len(strategy_signals)} 个策略产生信号")

            # 7. 获取AI信号
            logger.info("[AI] 获取融合信号...")
            ai_signal = await self._ai_client.get_signal(market_data)
            ai_signal = SignalProcessor.process(ai_signal)
            logger.info(f"[AI] 原始信号: {ai_signal}")

            # 8. 策略选择
            selected = self.strategy_manager.analyze_and_select(
                market_data, position_data
            )
            logger.info(
                f"[选择] {selected.strategy_type}: {selected.signal} "
                f"(置信度: {selected.confidence:.0%})"
            )
            for reason in selected.reasons:
                logger.info(f"  - {reason}")

            # 9. 规则评估（仅日志记录，实际应用在 _execute_trade 中）
            perf = self.performance_tracker.get_performance_metrics()
            rule_result = self.rules_engine.evaluate_all(market_state, perf)

            if rule_result["adjustments"]:
                logger.info(
                    f"[规则] 将应用 {len(rule_result['triggered_rules'])} 个规则: "
                    f"{rule_result['triggered_rules']}"
                )

            # 10. 信号决策
            final_signal = self._make_decision(ai_signal, selected, market_data)

            if final_signal["action"] == "skip":
                # 检查是否有持仓，有则更新止损
                if has_position:
                    logger.info("[决策] 跳过交易，但有持仓 -> 更新止损")
                    params = self.param_manager.get_current_params()
                    stop_loss_percent = params.get('stop_loss_percent', self.config.ai.stop_loss_percent or 0.02)
                    new_stop_price = current_price * (1 - stop_loss_percent)
                    await self._exchange.create_stop_loss(
                        symbol=self._exchange.symbol,
                        side="sell",
                        amount=position_data.get("amount", 0.01),
                        stop_price=new_stop_price,
                    )
                    logger.info(f"[决策] 止损单已更新: {new_stop_price}")
                logger.info("[决策] 跳过交易，等待下一个周期")
                logger.info("=" * 60)
                return
                logger.info("[决策] 跳过交易，等待下一个周期")
                logger.info("=" * 60)
                return

            # 11. 执行交易
            await self._execute_trade(
                final_signal["action"],
                current_price,
                has_position,
                position_data,
                market_data,
                selected_strategy=selected,
            )

        except Exception as e:
            logger.error(f"[周期] 执行出错: {e}")
            logger.exception("详细错误:")
            return

        logger.info("[周期] 完成")
        logger.info("=" * 60)

    def _make_decision(
        self,
        ai_signal: str,
        selected: Any,
        market_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        综合决策

        融合AI信号和策略选择的结果
        """
        # === P2: SafeMode 强制暂停检查 ===
        if (
            selected.strategy_type == "safe_mode"
            or "safe_mode" in selected.strategy_type
        ):
            logger.warning(f"[安全] 安全模式触发: {selected.reasons}")
            return {
                "action": "skip",
                "reason": f"安全模式强制暂停: {selected.reasons}",
                "confidence": 1.0,
                "strategy": "safe_mode",
            }

        # AI信号优先
        if ai_signal.upper() == "BUY":
            action = "open"
            reason = "AI信号买入"
        elif ai_signal.upper() == "SELL":
            if selected.signal.upper() == "SELL":
                action = "close"
                reason = "AI+策略共振卖出"
            else:
                action = "close"
                reason = "AI信号卖出"
        else:
            # HOLD信号，参考策略选择
            if selected.signal.upper() != "HOLD":
                action = "open" if selected.signal.upper() == "BUY" else "close"
                reason = f"策略信号: {selected.signal}"
            else:
                action = "skip"
                reason = "AI和策略都是HOLD"

        return {
            "action": action,
            "reason": reason,
            "confidence": selected.confidence,
            "strategy": selected.strategy_type,
        }

    async def _execute_trade(
        self,
        action: str,
        current_price: float,
        has_position: bool,
        position_data: Dict[str, Any],
        market_data: Dict[str, Any],
        selected_strategy: Optional[Any] = None,
    ) -> None:
        """执行交易"""
        logger.info(f"[执行] {action}: {current_price}")

        # 获取交易参数
        params = self.param_manager.get_current_params()

        # === P3: 获取规则引擎的调整 ===
        rule_adjustments = {}
        perf = self.performance_tracker.get_performance_metrics()
        market_state = self.regime_detector.detect(market_data)
        rule_result = self.rules_engine.evaluate_all(market_state, perf)

        if rule_result["adjustments"]:
            rule_adjustments = rule_result["adjustments"]
            logger.info(
                f"[规则] 触发 {len(rule_result['triggered_rules'])} 个规则: "
                f"{rule_result['triggered_rules']}"
            )
            # 应用规则调整到参数
            self.param_manager.config.apply_adjustments(rule_adjustments)

        # 应用风险控制（传入规则调整）
        risk_params = self.risk_manager.calculate_trade_params(
            {"side": action, "price": current_price},
            market_data,
            risk_score=0.5,
            rule_adjustments=rule_adjustments,
        )

        if action == "skip":
#KM|            # HOLD 信号 + 有持仓：更新止损
            if has_position:
                logger.info("[执行] HOLD信号 + 有持仓 -> 更新止损")
                stop_loss_percent = params.get('stop_loss_percent', self.config.ai.stop_loss_percent or 0.02)
                new_stop_price = current_price * (1 - stop_loss_percent)
                await self._exchange.create_stop_loss(
                    symbol=self._exchange.symbol,
                    side="sell",
                    amount=position_data.get("amount", 0.01),
                    stop_price=new_stop_price,
                )
                logger.info(f"[执行] 止损单已更新: {new_stop_price}")
                return
            return
            return

        # 类型断言
        assert self._exchange is not None, "Exchange client not initialized"

        if action == "open":
            if has_position:
                logger.info("[执行] 已有持仓，跳过开仓")
                return

            # 开仓
            logger.info(f"[执行] 开仓: 价格={current_price}")
            stop_loss_percent = params.get('stop_loss_percent', self.config.ai.stop_loss_percent or 0.02)
            stop_loss_price = current_price * (1 - stop_loss_percent)
            logger.info(f"[执行] 止损: {stop_loss_price:.1f} ({stop_loss_percent:.2%})")
            logger.info(f"[执行] 仓位: {risk_params.get('suggested_position', '默认')}")
            logger.info(f"[执行] 止损: {risk_params.get('stop_loss_price', '未设置')}")
            logger.info(f"[执行] 仓位: {risk_params.get('suggested_position', '默认')}")

            # === P1: 记录开仓（学习闭环开始） ===
            market_state = self.regime_detector.detect(market_data)
            confidence = selected_strategy.confidence if selected_strategy else 0.5
            self.performance_tracker.record_trade(
                entry_time=datetime.now(timezone.utc).isoformat(),
                entry_price=current_price,
                side="buy",
                confidence=confidence,
                signal_type="buy",
                market_regime=market_state.regime.value,
                used_threshold=params.get("fusion_threshold", 0.5),
                used_stop_loss=risk_params.get("stop_loss_percent", 0.005),
            )
            logger.info("[学习] 已记录开仓信号，用于后续学习")

            # 调用交易所API开仓
            symbol = self._exchange.symbol
            amount = risk_params.get("suggested_position", 0.01)
            stop_loss_price = risk_params.get("stop_loss_price")

            # 下市价买入单开仓
            order_id = await self._exchange.create_order(
                symbol=symbol,
                side="buy",
                amount=amount,
                order_type="market",
            )
            logger.info(f"[执行] 开仓订单已提交: {order_id}")

            # 如果有止损价，设置止损单
            if stop_loss_price:
                await self._exchange.create_stop_loss(
                    symbol=symbol,
                    side="sell",
                    amount=amount,
                    stop_price=stop_loss_price,
                )
                logger.info(f"[执行] 止损单已设置: {stop_loss_price}")

#KM|        elif action == "close":

#KM|        # HOLD 信号 + 有持仓：更新止损
        elif action in ["hold", "skip"]:
            if has_position:
                logger.info("[执行] HOLD信号 + 有持仓 -> 更新止损")
                stop_loss_percent = params.get('stop_loss_percent', self.config.ai.stop_loss_percent or 0.02)
                new_stop_price = current_price * (1 - stop_loss_percent)
                await self._exchange.create_stop_loss(
                    symbol=self._exchange.symbol,
                    side="sell",
                    amount=position_data.get("amount", 0.01),
                    stop_price=new_stop_price,
                )
                logger.info(f"[执行] 止损单已更新: {new_stop_price}")
                return

#KM|        elif action == "close":

        elif action == "close":
            if not has_position:
                logger.info("[执行] 无持仓，跳过平仓")
                return

            # 平仓
            logger.info(f"[执行] 平仓: 价格={current_price}")

            # === P1: 记录平仓（学习闭环完成） ===
            closed_trade = self.performance_tracker.close_trade(
                exit_time=datetime.now(timezone.utc).isoformat(),
                exit_price=current_price,
                reason="signal_close",
            )
            if closed_trade:
                # 更新策略权重（基于实际结果学习）
                self._update_strategy_weights(closed_trade)
                logger.info(
                    f"[学习] 平仓完成: 结果={closed_trade.outcome.value}, "
                    f"PnL={closed_trade.pnl_percent:.2%}%"
                )
            else:
                logger.warning("[学习] 无待平仓记录")

            # 调用交易所API平仓
            symbol = self._exchange.symbol
            amount = position_data.get("amount", 0.01)

            # 下市价卖出单平仓
            order_id = await self._exchange.create_order(
                symbol=symbol,
                side="sell",
                amount=amount,
                order_type="market",
            )
            logger.info(f"[执行] 平仓订单已提交: {order_id}")

        logger.info("[执行] 完成")

    def _update_strategy_weights(self, trade: Any) -> None:
        """
        根据交易结果更新策略权重（学习闭环）

        Args:
            trade: 已完成的交易记录
        """
        if not trade:
            return

        # 计算表现分数
        if trade.outcome.value == "win":
            performance_score = min(1.0, 0.5 + (trade.pnl_percent or 0) * 10)
        else:
            performance_score = max(0.0, 0.5 - abs(trade.pnl_percent or 0) * 5)

        # 更新策略库中对应策略的权重
        strategy_type = trade.signal_type
        if strategy_type in ["buy", "sell"]:
            for strategy in self.strategy_library.strategies.values():
                if strategy.strategy_type.value == f"{strategy_type}_following":
                    strategy.update_weight(performance_score)
                    logger.info(
                        f"[学习] 更新{strategy.name}权重: {strategy.weight:.2f} "
                        f"(得分: {performance_score:.2f})"
                    )
                    break

        # === ML 在线学习：更新 AI 提供商权重 ===
        try:
            if hasattr(trade, "signal_type"):
                provider = getattr(trade, "signal_provider", "unknown")
                confidence = getattr(trade, "confidence", 0.5)
                outcome = trade.outcome.value
                pnl = trade.pnl_percent or 0

                # 调用 ML 在线学习
                self.simple_learning.online_update(
                    provider=provider,
                    confidence=confidence,
                    outcome=outcome,
                    pnl_percent=pnl,
                )
                logger.info(
                    f"[ML学习] 在线更新: {provider}, outcome={outcome}, pnl={pnl:.2f}%"
                )
        except Exception as e:
            logger.warning(f"[ML学习] 在线更新失败: {e}")

    async def _background_optimization_task(self) -> None:
        """后台优化任务（每6小时运行一次ML学习，包括回测学习）"""
        from datetime import timezone

        while self._running:
            try:
                # 检查是否到达执行时间（每6小时）
                await asyncio.sleep(3600)  # 每小时检查

                now_utc = datetime.now(timezone.utc)
                should_run = now_utc.hour in [0, 6, 12, 18] and now_utc.minute <= 5

                if not should_run:
                    continue

                logger.info("[ML学习] 开始后台优化任务...")

                # 1. 获取当日表现数据
                metrics = self.performance_tracker.get_performance_metrics()
                daily_data = {
                    "trade_count": metrics.total_trades,
                    "win_rate": metrics.win_rate,
                    "total_pnl": metrics.total_pnl,
                }
                logger.info(
                    f"[ML学习] 当日数据: 交易次数={daily_data.get('trade_count', 0)}, "
                    f"胜率={daily_data.get('win_rate', 0):.2%}"
                )

                # 2. 运行回测学习（无需真实交易也能学习）
                try:
                    # 获取回测结果
                    backtest_result = self.backtest_learner.backtest_signals(
                        days=60, holding_hours=4, min_confidence=0.5
                    )

                    if backtest_result.total_signals > 0:
                        logger.info(
                            f"[ML学习] 回测结果: 信号数={backtest_result.total_signals}, "
                            f"胜率={backtest_result.win_rate:.2%}, "
                            f"平均收益={backtest_result.average_return:.2f}%"
                        )

                        # 显示各提供商表现
                        for provider, stats in backtest_result.provider_stats.items():
                            logger.info(
                                f"[ML学习] {provider}: 胜率={stats.get('win_rate', 0):.2%}, "
                                f"平均收益={stats.get('average_return', 0):.2f}%"
                            )

                        # 学习回测结果，更新权重
                        backtest_weights = self.backtest_learner.learn_from_backtest()

                        # 3. 结合真实交易数据学习
                        if metrics.total_trades > 0:
                            # 如果有真实交易，使用真实交易数据优化
                            trade_weights = self.simple_learning.learn_from_trades()
                            logger.info(f"[ML学习] 真实交易权重: {trade_weights}")

                        # 4. 应用学习结果
                        # 保存回测学习的权重
                        self.simple_learning.data_manager.save_model_weights(
                            backtest_weights, source="backtest_learn"
                        )

                        logger.info(f"[ML学习] 回测学习权重已保存: {backtest_weights}")
                    else:
                        logger.warning("[ML学习] 回测无结果，跳过回测学习")

                except Exception as e:
                    logger.warning(f"[ML学习] 回测学习失败: {e}")

                # 5. 获取优化后的权重
                optimized_weights, confidence = (
                    self.weight_optimizer.get_optimized_weights()
                )
                logger.info(
                    f"[ML学习] 优化权重: {optimized_weights}, 置信度={confidence:.2f}"
                )

                # 6. 应用优化后的权重到配置（内存中直接生效）
                if optimized_weights and confidence > 0.5:
                    try:
                        old_weights = getattr(self.config.ai, 'fusion_weights', {})
                        self.config.ai.fusion_weights = optimized_weights
                        logger.info(
                            f"[ML学习] ✅ 权重已应用: {old_weights} -> {optimized_weights}"
                        )
                    except Exception as e:
                        logger.warning(f"[ML学习] 应用权重失败: {e}")
                else:
                    logger.info(
                        f"[ML学习] 跳过应用: 置信度={confidence:.2f} <= 0.5"
                    )

                logger.info("[ML学习] 后台优化任务完成")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[ML学习] 任务出错: {e}")

    async def cleanup(self) -> None:
        """清理资源"""
        logger.info("清理资源...")

        # 保存表现数据
        self.performance_tracker._save_history()

        # 保存配置
        self.config_updater.create_version_snapshot("程序退出")

        if hasattr(self, "_exchange") and self._exchange is not None:
            await self._exchange.cleanup()

        logger.info("清理完成")

    def get_system_status(self) -> Dict[str, Any]:
        """获取系统状态"""
        return {
            "running": self._running,
            "initialized": self._initialized,
            "risk": self.risk_manager.get_risk_summary(),
            "strategies": self.strategy_library.get_strategy_summary(),
            "performance": self.performance_tracker.get_performance_metrics().__dict__,
            "config_version": self.config_updater.get_summary()["version"],
        }
