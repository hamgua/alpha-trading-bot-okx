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

        self._position_recovery: Optional[Any] = None
        self._adaptive_stop_loss: Optional[Any] = None
        self._strategy_weight_manager: Optional[Any] = None
        self._ml_optimization_task: Optional[Any] = None
        self._decision_engine: Optional[Any] = None
        self._param_applier: Optional[Any] = None

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

        from .strategy_weight_manager import StrategyWeightManager

        self._strategy_weight_manager = StrategyWeightManager(
            self.strategy_library, self.simple_learning
        )

        from .ml_optimization_task import MLOptimizationTask

        self._ml_optimization_task = MLOptimizationTask(
            self,
            self.performance_tracker,
            self.backtest_learner,
            self.simple_learning,
            self.weight_optimizer,
        )

        from .decision_engine import DecisionEngine

        self._decision_engine = DecisionEngine(self.config)

        from .param_applier import ParamApplier
        from .take_profit_calculator import TakeProfitCalculator

        self._param_applier = ParamApplier(self.config, self._ai_client)
        self._take_profit_calculator = TakeProfitCalculator(self.config)

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
                allow_short_selling=self.config.trading.allow_short_selling,
            )
            await self._exchange.initialize()
            await self._exchange.set_leverage(self.config.exchange.leverage)

            from .position_recovery import PositionRecoveryManager
            from .adaptive_stop_loss import AdaptiveStopLossManager

            self._position_recovery = PositionRecoveryManager(
                self._exchange, self.position_manager
            )
            self._adaptive_stop_loss = AdaptiveStopLossManager(self._exchange)

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

            current_params = self.param_manager.get_current_params()
            if self._param_applier:
                self._param_applier.apply_adaptive_params(current_params)
            # 4. 获取所有策略信号
            strategy_signals = self.strategy_library.get_all_signals(market_data)
            logger.info(f"[策略] {len(strategy_signals)} 个策略产生信号")

            # 5. 获取AI融合信号
            logger.info("[AI] 获取融合信号...")
            ai_signal = await self._ai_client.get_signal(market_data)
            ai_signal = SignalProcessor.process(ai_signal)
            logger.info(f"[AI] 原始信号: {ai_signal}")

            # 6. 策略选择（此时还没有持仓数据）
            selected = self.strategy_manager.analyze_and_select(
                market_data,
                {},  # 无持仓
            )
            logger.info(
                f"[选择] {selected.strategy_type}: {selected.signal} "
                f"(置信度: {selected.confidence:.0%})"
            )
            for reason in selected.reasons:
                logger.info(f"  - {reason}")

            # 7. 获取持仓状态
            # 7. 获取持仓状态（带重试机制）
            position_data = (
                await self._exchange.get_position_with_retry(
                    max_retries=3, retry_delay=1.0
                )
                or {}
            )
            has_position = bool(position_data.get("amount", 0) > 0)
            position_side = position_data.get("side", "")
            is_short_to_close = position_side == "short_to_close"

            if has_position:
                self.position_manager.update_from_exchange(position_data)
                entry_price = position_data.get("entry_price", 0)
                if is_short_to_close:
                    logger.warning(f"[持仓] 检测到空单需平仓: {entry_price}")
                else:
                    logger.info(f"[持仓] 有持仓: {entry_price}")
            else:
                logger.info("[持仓] 无持仓")

            # 8. 风险状态评估
            risk_state = self.risk_manager.assess_risk(market_data, position_data)
            logger.info(
                f"[风险] 等级: {risk_state.risk_level.value}, "
                f"回撤: {risk_state.current_drawdown:.2%}, "
                f"熔断: {'是' if risk_state.circuit_breaker_active else '否'}"
            )

            if risk_state.circuit_breaker_active:
                logger.warning(f"[风险] 熔断中: {risk_state.circuit_breaker_reason}")
                logger.info("跳过后续交易，等待下一个周期")
                return

            # 9. 规则评估
            perf = self.performance_tracker.get_performance_metrics()
            market_state = self.regime_detector.detect(market_data)
            rule_result = self.rules_engine.evaluate_all(market_state, perf)

            if rule_result["adjustments"]:
                logger.info(
                    f"[规则] 将应用 {len(rule_result['triggered_rules'])} 个规则: "
                    f"{rule_result['triggered_rules']}"
                )

            # 将 has_position 传入 market_data 供决策使用
            market_data["has_position"] = has_position

            # 10. 信号决策
            final_signal = self._make_decision(ai_signal, selected, market_data)

            # 强制平空仓
            if is_short_to_close:
                logger.warning("[决策] 检测到空单，强制平仓")
                final_signal = {
                    "action": "close_short",
                    "reason": "强制平空单",
                    "confidence": 1.0,
                    "strategy": "auto_close_short",
                }

            # 有持仓时的处理
            if has_position and not is_short_to_close:
                if final_signal["action"] == "open":
                    logger.info("[决策] 已有持仓，跳过开仓，更新止损")
                    final_signal = {"action": "skip", "reason": "已有持仓"}

            if final_signal["action"] == "skip":
                if has_position and not is_short_to_close:
                    await self._update_stop_loss(current_price, position_data)
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
            # 检测到空单平仓后，跳过后续所有交易，等待下一个周期
            if final_signal.get("action") == "close_short":
                logger.warning("[决策] 空单已平仓，跳过后续交易，等待下一个周期")
                logger.info("=" * 60)
                return
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
        """综合决策"""
        if self._decision_engine is None:
            return {
                "action": "skip",
                "reason": "engine_not_initialized",
                "confidence": 0,
                "strategy": "none",
            }
        return self._decision_engine.make_decision(ai_signal, selected, market_data)

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
        # action=reduce 开仓时按做多计算止损，传入 side="buy"
        side_for_params = "buy" if action == "reduce" else action
        risk_params = self.risk_manager.calculate_trade_params(
            {
                "side": side_for_params,
                "price": current_price,
                "entry_price": current_price,
            },
            market_data,
            risk_score=0.5,
            rule_adjustments=rule_adjustments,
        )

        if action == "skip":
            if has_position:
                logger.info("[执行] HOLD信号 + 有持仓 -> 更新止损")
                await self._update_stop_loss(current_price, position_data)
            return

        if action == "reduce":
            if has_position:
                amount = position_data.get("amount", 0)
                if amount > 0:
                    position_side = position_data.get("side", "long")
                    entry_price = position_data.get("entry_price", current_price)
                    reduce_amount = amount * 0.5
                    order_side = "sell" if position_side == "long" else "buy"
                    if reduce_amount < 0.01:
                        logger.warning(
                            f"[执行] 降低仓位: {reduce_amount} < 最小交易量0.01，跳过降低仓位操作"
                        )
                    else:
                        logger.info(
                            f"[执行] 降低仓位: 平仓50% = {reduce_amount}, 方向={order_side}"
                        )
                        order_id = await self._exchange.create_order(
                            symbol=self._exchange.symbol,
                            side=order_side,
                            amount=reduce_amount,
                        )
                        if not order_id:
                            logger.error(f"[执行] 降低仓位订单失败，跳过状态更新")
                        else:
                            new_amount = amount - reduce_amount
                            if new_amount > 0:
                                self.position_manager.update_position(
                                    amount=new_amount,
                                    entry_price=entry_price,
                                    symbol=self._exchange.symbol,
                                    side=position_side,
                                )
            else:
                logger.info("[执行] 安全模式: 无持仓 → 正常开仓")
                suggested_amount = risk_params.get("suggested_position", 0.01)
                max_amount = 0.01
                amount = min(suggested_amount, max_amount)
                stop_loss_price = risk_params.get("stop_loss_price")
                position_side = "long"
                order_side = "buy"
                order_id = await self._exchange.create_order(
                    symbol=self._exchange.symbol,
                    side=order_side,
                    amount=amount,
                )
                if order_id:
                    self.position_manager.update_position(
                        amount=amount,
                        entry_price=current_price,
                        symbol=self._exchange.symbol,
                        side=position_side,
                    )
                    if stop_loss_price:
                        await self._create_stop_loss_with_retry(
                            amount=amount,
                            stop_price=stop_loss_price,
                            current_price=current_price,
                            position_side=position_side,
                            max_retries=3,
                        )
            return

        # 类型断言
        assert self._exchange is not None, "Exchange client not initialized"
        # 开仓操作: action = "open" (做多) 或 action = "sell" (做空)
        if action in ["open", "sell"]:
            if has_position:
                logger.info("[执行] 已有持仓，跳过开仓")
                return

            # 获取持仓方向 (基于 allow_short_selling 和信号)
            # action = "open" 表示做多, action = "sell" 表示做空
            if action == "sell" and self.config.trading.allow_short_selling:
                position_side = "short"
            else:
                position_side = "long"  # 默认做多

            logger.info(f"[执行] 开仓: 方向={position_side}, 价格={current_price}")
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
            suggested_amount = risk_params.get("suggested_position", 0.01)
            # 限制仓位不超过最大仓位 (0.01 BTC，符合OKX最小交易单位和配置要求)
            max_amount = 0.01
            amount = min(suggested_amount, max_amount)
            stop_loss_price = risk_params.get("stop_loss_price")

            take_profit_price = self._take_profit_calculator.calculate(
                current_price, position_side
            )

            # 下市价单开仓 (根据 position_side 决定买入还是卖出)
            order_side = "buy" if position_side == "long" else "sell"

            order_id = await self._exchange.create_order(
                symbol=symbol,
                side=order_side,
                amount=amount,
            )

            # P0: 验证订单是否创建成功
            if not order_id:
                logger.error("[执行] 开仓订单创建失败！尝试重新获取持仓状态验证")
                await self._verify_and_recover_position()
                return

            # 开仓成功后，更新持仓信息 (支持做多和做空)
            self.position_manager.update_position(
                amount=amount,
                entry_price=current_price,
                symbol=symbol,
                side=position_side,
            )
            logger.info(f"[执行] 开仓订单已提交: {order_id}")

            # 如果有止损价，设置止损单（带重试机制）
            if stop_loss_price:
                stop_order_id = await self._create_stop_loss_with_retry(
                    amount=amount,
                    stop_price=stop_loss_price,
                    current_price=current_price,
                    position_side=position_side,
                    max_retries=3,
                )
                if stop_order_id:
                    self.position_manager.set_stop_order(stop_order_id, stop_loss_price)
                    logger.info(f"[执行] 止损单已设置: {stop_loss_price}")
                else:
                    logger.warning("[执行] 止损单创建失败")
        elif action in ["close", "close_short"]:
            if not has_position:
                logger.info("[执行] 无持仓，跳过平仓")
                return

            # 平仓前先取消现有止损单
            await self._cancel_stop_loss_before_close(position_data)

            # 平仓
            logger.info(f"[执行] 平仓: 价格={current_price}")

            # === P1: 记录平仓（学习闭环完成） ===
            closed_trade = self.performance_tracker.close_trade(
                exit_time=datetime.now(timezone.utc).isoformat(),
                exit_price=current_price,
                reason="signal_close",
            )
            if closed_trade:
                self._update_strategy_weights(closed_trade)
                logger.info(
                    f"[学习] 平仓完成: 结果={closed_trade.outcome.value}, "
                    f"PnL={closed_trade.pnl_percent:.2%}%"
                )
            else:
                logger.warning("[学习] 无待平仓记录")

            # 调用交易所API平仓
            # 根据持仓方向决定平仓方式：做空持仓用"buy"平，做多用"sell"平
            symbol = self._exchange.symbol
            amount = position_data.get("amount", 0.01)
            position_side = position_data.get("side", "long")

            # 平仓方向：根据持仓类型决定
            if position_side in ["short", "short_to_close"]:
                # 平空单 = 买入
                logger.info(f"[执行] 平空单(买入): 价格={current_price}")
                close_side = "buy"
            else:
                # 平多单 = 卖出
                logger.info(f"[执行] 平多单(卖出): 价格={current_price}")
                close_side = "sell"

            order_id = await self._exchange.create_order(
                symbol=symbol,
                side=close_side,
                amount=amount,
                order_type="market",
            )
            # P0: 验证订单是否创建成功
            if not order_id:
                logger.error(
                    f"[执行] 平{position_side}单订单创建失败！尝试重新获取持仓状态验证"
                )
                await self._verify_and_recover_position()
                return
            logger.info(f"[执行] 平仓订单已提交: {order_id}")

        logger.info("[执行] 完成")

    def _update_strategy_weights(self, trade: Any) -> None:
        """根据交易结果更新策略权重（学习闭环）"""
        if self._strategy_weight_manager is None:
            return
        self._strategy_weight_manager.update_strategy_weights(trade)

    async def _background_optimization_task(self) -> None:
        """后台优化任务（委托给MLOptimizationTask）"""
        if self._ml_optimization_task is None:
            return
        await self._ml_optimization_task.run()

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

    async def _create_stop_loss_with_retry(
        self,
        amount: float,
        stop_price: float,
        current_price: float,
        max_retries: int = 3,
        position_side: str = "long",
    ) -> Optional[str]:
        """创建止损单（带重试机制）"""
        if self._adaptive_stop_loss is None:
            return None
        return await self._adaptive_stop_loss.create_stop_loss_with_retry(
            amount, stop_price, current_price, max_retries, position_side
        )

    async def _verify_and_recover_position(self) -> None:
        """验证并恢复持仓状态"""
        if self._position_recovery is None:
            return
        await self._position_recovery.verify_and_recover_position()

    async def _cancel_stop_loss_before_close(
        self, position_data: Dict[str, Any]
    ) -> None:
        """平仓前取消现有止损单"""
        if self._position_recovery is None:
            return
        await self._position_recovery.cancel_stop_loss_before_close()

    async def _update_stop_loss(
        self, current_price: float, position_data: Dict[str, Any]
    ) -> None:
        """更新止损订单（带容错判断，避免频繁更新）"""
        # === P0: 先查询交易所实际止损单状态 ===
        existing_stop_id = await self._get_existing_stop_order_id()

        # === P1: 获取参数和计算止损百分比 ===
        params = self.param_manager.get_current_params()
        base_stop_loss = params.get(
            "stop_loss_percent", self.config.ai.stop_loss_percent or 0.02
        )
        entry_price = position_data.get("entry_price", 0)

        # 动态调整止损百分比
        if current_price > entry_price:
            # 有盈利：用较小止损锁定利润
            stop_loss_percent = min(base_stop_loss, 0.002)
            logger.info(
                f"[止损调整] 有盈利({current_price} > {entry_price}) → 较小止损: {stop_loss_percent}"
            )
        else:
            # 亏损/保本：用较大止损给回调空间
            stop_loss_percent = max(base_stop_loss, 0.005)
            logger.info(
                f"[止损调整] 亏损/保本({current_price} <= {entry_price}) → 较大止损: {stop_loss_percent}"
            )

        logger.info(f"[止损调试] stop_loss_percent={stop_loss_percent}")

        # 获取持仓方向
        position_side = position_data.get("side", "long")

        # 计算新止损价
        if position_side == "short":
            new_stop_price = current_price * (1 + stop_loss_percent)
            logger.info(f"[止损更新-做空] 止损价={new_stop_price:.1f}")
        else:
            new_stop_price = current_price * (1 - stop_loss_percent)
            logger.info(f"[止损更新-做多] 止损价={new_stop_price:.1f}")

        # === P2: 交易所无止损单时，直接创建 ===
        if not existing_stop_id:
            logger.info("[止损更新] 交易所无止损单，直接创建新止损单")
            amount = position_data.get("amount", 0.01)
            stop_order_id = await self._create_stop_loss_with_retry(
                amount=amount,
                stop_price=new_stop_price,
                current_price=current_price,
                position_side=position_side,
                max_retries=3,
            )
            if stop_order_id:
                self.position_manager.set_stop_order(stop_order_id, new_stop_price)
                logger.info(f"[止损更新] 止损单设置完成: {stop_order_id}")
            else:
                logger.error("[止损更新] 止损单创建失败")
            return

        old_stop = self.position_manager.last_stop_price
        logger.info(
            f"[止损调试] current_price={current_price}, old_stop={old_stop}, new_stop={new_stop_price}"
        )

        # 容错检查：变化太小则跳过
        if old_stop > 0:
            tolerance = self.config.stop_loss.stop_loss_tolerance_percent
            price_diff_percent = abs(new_stop_price - old_stop) / old_stop
            if price_diff_percent < tolerance:
                logger.info(
                    f"[止损更新] 变化率:{price_diff_percent * 100:.4f}% < 容错:{tolerance * 100}%, 跳过更新"
                )
                return

        # === 止损价只能上升不能下跌（做多）===
        if position_side == "long":
            # 做多：止损价只能上升，不能下降
            if old_stop > 0 and new_stop_price <= old_stop:
                logger.info(
                    f"[止损更新] 止损价未上升({new_stop_price:.1f} <= {old_stop:.1f}), 跳过更新"
                )
                return
        else:
            # 做空：止损价只能下降，不能上升
            if old_stop > 0 and new_stop_price >= old_stop:
                logger.info(
                    f"[止损更新] 止损价未下降({new_stop_price:.1f} >= {old_stop:.1f}), 跳过更新"
                )
                return

        # 取消旧止损单

        # 取消旧止损单

        # 取消旧止损单
        logger.info(f"[止损更新] 取消现有止损单: {existing_stop_id}")
        try:
            await self._exchange.cancel_algo_order(
                str(existing_stop_id), self._exchange.symbol
            )
            logger.info("[止损更新] 止损单取消成功")
        except Exception as e:
            logger.warning(f"[止损更新] 取消止损单失败: {e}")

        # 创建新止损单
        amount = position_data.get("amount", 0.01)
        stop_order_id = await self._create_stop_loss_with_retry(
            amount=amount,
            stop_price=new_stop_price,
            current_price=current_price,
            position_side=position_side,
            max_retries=3,
        )
        if stop_order_id:
            self.position_manager.set_stop_order(stop_order_id, new_stop_price)
            logger.info(f"[止损更新] 止损单设置完成: {stop_order_id}")
        else:
            logger.error("[止损更新] 止损单创建失败")

    async def _get_existing_stop_order_id(self) -> Optional[str]:
        """查询交易所中现有的止损单ID"""
        try:
            algo_orders = await self._exchange.get_algo_orders(self._exchange.symbol)
            for order in algo_orders:
                # CCXT 返回结构: order["info"] 包含 algoId 和 slTriggerPx
                info = order.get("info", {})
                algo_id = info.get("algoId")

                # 检查是否是止损单
                if algo_id:
                    stop_price = info.get("slTriggerPx") or info.get("stopLossPrice")
                    if stop_price:
                        logger.info(
                            f"[止损查询] 找到现有止损单: algoId={algo_id}, 止损价={stop_price}"
                        )
                        return str(algo_id)
            logger.debug("[止损查询] 无现有止损单")
        except Exception as e:
            logger.warning(f"[止损查询] 查询失败: {e}")
        return None

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
