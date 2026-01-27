"""
AlphaPulse 主引擎
协调所有模块，提供统一的交易信号生成接口
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .config import AlphaPulseConfig
from .data_manager import DataManager
from .market_monitor import MarketMonitor, SignalCheckResult
from .signal_validator import SignalValidator, ValidationResult
from .ai_analyzer import AIAnalyzer, AIAnalysisResult
from .tiered_storage import TieredStorage, create_tiered_storage

logger = logging.getLogger(__name__)


@dataclass
class TradingSignal:
    """交易信号"""

    symbol: str
    signal_type: str  # "buy", "sell", "hold"
    source: str  # "alphapulse", "fallback"
    confidence: float
    timestamp: datetime
    reasoning: str
    execution_params: Dict[str, Any]
    market_data: Dict[str, Any]
    ai_result: Optional[Dict[str, Any]] = None


class AlphaPulseEngine:
    """
    AlphaPulse 主引擎

    功能:
    - 协调所有模块工作
    - 提供统一的信号生成接口
    - 支持后备定时任务模式
    - 与交易执行器集成
    """

    def __init__(
        self,
        exchange_client,
        config: AlphaPulseConfig = None,
        trade_executor=None,
        ai_manager=None,
        on_signal: Callable[[TradingSignal], None] = None,
    ):
        """
        初始化AlphaPulse引擎

        Args:
            exchange_client: 交易所客户端
            config: 配置（可选，默认从环境变量加载）
            trade_executor: 交易执行器（可选）
            ai_manager: AI管理器（可选）
            on_signal: 信号回调函数
        """
        self.exchange_client = exchange_client
        self.config = config or AlphaPulseConfig.from_env()
        self.trade_executor = trade_executor
        self.ai_manager = ai_manager
        self.on_signal = on_signal

        # 初始化日志（必须在使用logger之前）
        self.logger = logging.getLogger(__name__)

        # 自动创建数据目录
        data_dir = Path("data/alphapulse")
        data_dir.mkdir(parents=True, exist_ok=True)

        # 初始化分层存储（自动创建数据库文件）
        self.tiered_storage = create_tiered_storage(str(data_dir))
        self.logger.info(f"分层存储已初始化: {data_dir}")

        # 初始化组件
        self.data_manager = DataManager(
            max_ohlcv_bars=self.config.max_ohlcv_bars,
            max_indicator_history=self.config.max_indicator_history,
            tiered_storage=self.tiered_storage,  # 传入分层存储以同步数据
        )

        self.market_monitor = MarketMonitor(
            exchange_client=exchange_client,
            config=self.config,
            data_manager=self.data_manager,
            on_signal=self.on_signal,
        )

        self.signal_validator = SignalValidator(self.config)

        self.ai_analyzer = AIAnalyzer(
            config=self.config,
            data_manager=self.data_manager,
            ai_manager=ai_manager,
        )

        # 状态管理
        self._running = False
        self._last_signal_time = {}
        self._signal_history: List[TradingSignal] = []

        # 事件
        self._signal_event = asyncio.Event()

        # 初始化日志
        self.logger = logging.getLogger(__name__)

    async def start(self):
        """启动引擎"""
        if self._running:
            self.logger.warning("⚠️ AlphaPulse引擎已在运行")
            return

        self.logger.info("=" * 60)
        self.logger.info("🚀 启动 AlphaPulse 实时市场监控系统")
        self.logger.info("=" * 60)
        self.logger.info(f"📋 配置信息:")
        self.logger.info(
            f"   模式: {'✅ 实时监控' if self.config.enabled else '⏸️ 仅后备模式'}"
        )
        self.logger.info(f"   监控间隔: {self.config.monitor_interval}秒")
        self.logger.info(
            f"   AI验证: {'✅ 启用' if self.config.use_ai_validation else '⛔ 禁用'}"
        )
        self.logger.info(f"   买入阈值: {self.config.buy_threshold}")
        self.logger.info(f"   卖出阈值: {self.config.sell_threshold}")
        self.logger.info(f"   交易对: {', '.join(self.config.symbols)}")
        self.logger.info(f"   数据存储: data/alphapulse/")
        if hasattr(self, "tiered_storage"):
            stats = (
                self.tiered_storage.get_stats(self.config.symbols[0])
                if self.config.symbols
                else {}
            )
            self.logger.info(
                f"   存储状态: 热数据={stats.get('hot', {})}, 温数据={len(stats.get('warm', {}))}项"
            )
        self.logger.info("=" * 60)

        self._running = True

        # 启动市场监控
        if self.config.enabled:
            await self.market_monitor.start()
            self.logger.info("✅ 市场监控已启动")
        else:
            self.logger.info("⏸️ 实时监控已跳过 (enabled=false)")

        self.logger.info("✅ AlphaPulse引擎启动完成")

    async def stop(self):
        """停止引擎"""
        self._running = False
        await self.market_monitor.stop()
        await self.data_manager.cleanup()
        self.logger.info("AlphaPulse引擎已停止")

    async def process_cycle(
        self, symbol: str = None, timeout: float = 30.0
    ) -> Optional[TradingSignal]:
        """
        处理一个交易周期

        Args:
            symbol: 交易对（可选，默认使用配置的的第一个交易对）
            timeout: 超时时间（秒）

        Returns:
            交易信号
        """
        import asyncio

        target_symbol = symbol or self.config.symbols[0]

        self.logger.info(f"🔄 AlphaPulse 后备模式处理: {target_symbol}")

        try:
            # 使用超时包装整个处理过程
            signal_result = await asyncio.wait_for(
                self.market_monitor.manual_check(target_symbol), timeout=timeout
            )
            self.logger.info(
                f"📊 manual_check 完成, 信号结果: {'有信号' if signal_result else '无信号'}"
            )

            if not signal_result:
                self.logger.info(f"💤 {target_symbol} 无信号 (数据不足)")
                return None

            if not signal_result.should_trade:
                self.logger.info(
                    f"💤 {target_symbol} 不满足交易条件: {signal_result.message}"
                )
                self.logger.info(
                    f"   分数: BUY={signal_result.buy_score:.2f}, SELL={signal_result.sell_score:.2f}"
                )
                return None

            self.logger.info(
                f"🎯 {target_symbol} 检测到信号: {signal_result.signal_type.upper()}"
            )
            self.logger.info(f"   置信度: {signal_result.confidence:.2f}")
            self.logger.info(f"   触发因素: {', '.join(signal_result.triggers)}")

            # 2. 验证信号
            self.logger.info(f"🔍 正在验证信号...")
            market_summary = await asyncio.wait_for(
                self.data_manager.get_market_summary(target_symbol), timeout=timeout
            )

            validation = await asyncio.wait_for(
                self.signal_validator.validate(
                    target_symbol, signal_result, market_summary
                ),
                timeout=timeout,
            )

            if not validation.passed:
                # 强信号快速通道：高置信度信号直接执行
                if signal_result.confidence >= 0.8:
                    self.logger.warning(
                        f"🚀 强信号快速通道: {target_symbol} 信号验证未通过但置信度高，直接执行"
                    )
                    # 直接创建交易信号，跳过AI验证
                    trading_signal = await self._create_trading_signal(
                        target_symbol, signal_result, validation, None, market_summary
                    )
                    if self.trade_executor and trading_signal.signal_type in [
                        "buy",
                        "sell",
                    ]:
                        await self._execute_trade(trading_signal)
                    return trading_signal
                else:
                    self.logger.info(
                        f"❌ {target_symbol} 信号验证未通过: {validation.final_message}"
                    )
                    self.logger.info(f"   详细: {validation.final_message}")
                    return None

            self.logger.info(f"✅ {target_symbol} 信号验证通过!")

            # 3. 决定是否需要AI
            need_ai = self.signal_validator.should_use_ai(validation)
            ai_result = None

            if need_ai:
                self.logger.info(f"🤖 正在调用AI验证信号...")
                ai_result = await asyncio.wait_for(
                    self.ai_analyzer.analyze(
                        target_symbol, signal_result.indicator_result, validation
                    ),
                    timeout=60.0,  # AI可能需要更长时间
                )

                if ai_result:
                    self.logger.info(
                        f"🤖 AI分析完成: signal={ai_result.signal}, confidence={ai_result.confidence:.2f}"
                    )

                    should_exec, reason = self.ai_analyzer.should_execute(
                        validation, ai_result
                    )
                    if not should_exec:
                        self.logger.info(f"❌ AI阻止执行: {reason}")
                        return None

            # 4. 生成交易信号
            trading_signal = await self._create_trading_signal(
                target_symbol, signal_result, validation, ai_result, market_summary
            )

            # 5. 保存信号
            self._signal_history.append(trading_signal)
            self._last_signal_time[target_symbol] = datetime.now()

            self.logger.info(f"🚀 生成最终信号: {trading_signal.signal_type.upper()}")
            self.logger.info(f"   置信度: {trading_signal.confidence:.2f}")
            self.logger.info(f"   推理: {trading_signal.reasoning[:100]}...")

            # 6. 触发回调
            if self.on_signal:
                self.on_signal(trading_signal)

            # 7. 如果有交易执行器，执行交易
            if self.trade_executor and trading_signal.signal_type in ["buy", "sell"]:
                await self._execute_trade(trading_signal)

            return trading_signal

        except asyncio.TimeoutError:
            self.logger.error(f"❌ {target_symbol} 处理超时 ({timeout}秒)")
            return None
        except Exception as e:
            self.logger.error(f"❌ {target_symbol} 处理异常: {e}", exc_info=True)
            return None

            if not signal_result.should_trade:
                self.logger.info(
                    f"💤 {target_symbol} 不满足交易条件: {signal_result.message}"
                )
                self.logger.info(
                    f"   分数: BUY={signal_result.buy_score:.2f}, SELL={signal_result.sell_score:.2f}"
                )
                return None

            self.logger.info(
                f"🎯 {target_symbol} 检测到信号: {signal_result.signal_type.upper()}"
            )
            self.logger.info(f"   置信度: {signal_result.confidence:.2f}")
            self.logger.info(f"   触发因素: {', '.join(signal_result.triggers)}")

            # 2. 验证信号
            market_summary = await self.data_manager.get_market_summary(target_symbol)

            self.logger.info(f"🔍 验证信号...")
            validation = await self.signal_validator.validate(
                target_symbol, signal_result, market_summary
            )

            if not validation.passed:
                self.logger.info(
                    f"❌ {target_symbol} 信号验证未通过: {validation.final_message}"
                )
                self.logger.info(f"   详细: {validation.final_message}")
                return None

            self.logger.info(f"✅ {target_symbol} 信号验证通过!")

            # 3. 决定是否需要AI
            need_ai = self.signal_validator.should_use_ai(validation)
            ai_result = None

            if need_ai:
                self.logger.info(f"🤖 调用AI验证信号...")
                ai_result = await self.ai_analyzer.analyze(
                    target_symbol,
                    signal_result.indicator_result,
                    validation,
                )

                if ai_result:
                    self.logger.info(
                        f"🤖 AI分析结果: signal={ai_result.signal}, confidence={ai_result.confidence:.2f}"
                    )

                    # 检查是否应该执行
                    should_exec, reason = self.ai_analyzer.should_execute(
                        validation, ai_result
                    )
                    if not should_exec:
                        self.logger.info(f"❌ AI阻止执行: {reason}")
                        return None

            # 4. 生成交易信号
            trading_signal = await self._create_trading_signal(
                target_symbol, signal_result, validation, ai_result, market_summary
            )

            # 5. 保存信号
            self._signal_history.append(trading_signal)
            self._last_signal_time[target_symbol] = datetime.now()

            self.logger.info(f"🚀 生成最终信号: {trading_signal.signal_type.upper()}")
            self.logger.info(f"   置信度: {trading_signal.confidence:.2f}")
            self.logger.info(f"   推理: {trading_signal.reasoning[:100]}...")

            # 6. 触发回调
            if self.on_signal:
                self.on_signal(trading_signal)

            # 7. 如果有交易执行器，执行交易
            if self.trade_executor and trading_signal.signal_type in ["buy", "sell"]:
                await self._execute_trade(trading_signal)

            return trading_signal

        except Exception as e:
            self.logger.error(f"❌ 处理交易周期失败: {e}")
            return None

            if not signal_result.should_trade:
                self.logger.debug(f"不满足交易条件: {signal_result.message}")
                return None

            # 2. 验证信号
            market_summary = await self.data_manager.get_market_summary(target_symbol)
            validation = await self.signal_validator.validate(
                target_symbol, signal_result, market_summary
            )

            if not validation.passed:
                self.logger.info(f"信号验证未通过: {validation.final_message}")
                return None

            # 3. 决定是否需要AI
            need_ai = self.signal_validator.should_use_ai(validation)
            ai_result = None

            if need_ai:
                self.logger.info(f"调用AI验证信号...")
                ai_result = await self.ai_analyzer.analyze(
                    target_symbol,
                    signal_result.indicator_result,
                    validation,
                )

                if ai_result:
                    # 检查是否应该执行
                    should_exec, reason = self.ai_analyzer.should_execute(
                        validation, ai_result
                    )
                    if not should_exec:
                        self.logger.info(f"AI阻止执行: {reason}")
                        return None

            # 4. 生成交易信号
            trading_signal = await self._create_trading_signal(
                target_symbol, signal_result, validation, ai_result, market_summary
            )

            # 5. 保存信号
            self._signal_history.append(trading_signal)
            self._last_signal_time[target_symbol] = datetime.now()

            # 6. 触发回调
            if self.on_signal:
                self.on_signal(trading_signal)

            # 7. 如果有交易执行器，执行交易
            if self.trade_executor and trading_signal.signal_type in ["buy", "sell"]:
                await self._execute_trade(trading_signal)

            return trading_signal

        except Exception as e:
            self.logger.error(f"处理交易周期失败: {e}")
            return None

    async def _create_trading_signal(
        self,
        symbol: str,
        signal_result: SignalCheckResult,
        validation: ValidationResult,
        ai_result: Optional[AIAnalysisResult],
        market_summary: Dict[str, Any],
    ) -> TradingSignal:
        """创建交易信号"""
        # 确定最终信号
        if ai_result:
            signal_type = ai_result.signal
            confidence = ai_result.confidence
            reasoning = ai_result.reasoning
            execution_params = self.ai_analyzer.get_execution_params(
                ai_result,
                {
                    "take_profit_percent": validation.confidence * 3,
                    "stop_loss_percent": validation.confidence * 1.5,
                },
            )
        else:
            signal_type = signal_result.signal_type
            confidence = validation.confidence
            reasoning = validation.final_message
            execution_params = {
                "take_profit_percent": 2.0,
                "stop_loss_percent": 1.0,
                "position_ratio": 0.5,
            }

        return TradingSignal(
            symbol=symbol,
            signal_type=signal_type,
            source="alphapulse",
            confidence=confidence,
            timestamp=datetime.now(),
            reasoning=reasoning,
            execution_params=execution_params,
            market_data={
                "indicators": signal_result.indicator_result.to_dict(),
                "validation_details": validation.score_details,
                "market_summary": market_summary,
            },
            ai_result=ai_result.to_dict() if ai_result else None,
        )

    async def _execute_trade(self, signal: TradingSignal):
        """执行交易"""
        try:
            self.logger.info(
                f"📊 AlphaPulse执行交易: {signal.signal_type.upper()} {signal.symbol} "
                f"(置信度: {signal.confidence:.2f})"
            )

            # 调用交易执行器
            if self.trade_executor:
                result = await self.trade_executor.execute_trade(
                    symbol=signal.symbol,
                    side=signal.signal_type,
                    amount=signal.execution_params.get("position_ratio", 0.5),
                    take_profit_percent=signal.execution_params.get(
                        "take_profit_percent", 2.0
                    ),
                    stop_loss_percent=signal.execution_params.get(
                        "stop_loss_percent", 1.0
                    ),
                )

                if result.success:
                    self.logger.info(f"✅ 交易执行成功: {result.order_id}")
                else:
                    self.logger.error(f"❌ 交易执行失败: {result.error_message}")

        except Exception as e:
            self.logger.error(f"执行交易失败: {e}")

    async def get_status(self) -> Dict[str, Any]:
        """获取引擎状态"""
        return {
            "running": self._running,
            "enabled": self.config.enabled,
            "symbols": self.config.symbols,
            "last_signals": [
                {
                    "symbol": s.symbol,
                    "type": s.signal_type,
                    "confidence": s.confidence,
                    "timestamp": s.timestamp.isoformat(),
                }
                for s in self._signal_history[-10:]
            ],
            "data_stats": {
                symbol: self.data_manager.get_storage_stats(symbol)
                for symbol in self.config.symbols
            },
        }

    def get_signal_history(self, limit: int = 20) -> List[TradingSignal]:
        """获取信号历史"""
        return self._signal_history[-limit:]

    async def reset_daily_range(self):
        """重置24h价格区间（每天调用一次）"""
        for symbol in self.config.symbols:
            await self.data_manager.reset_price_range_24h(symbol)
        self.logger.info("已重置所有交易对的24h价格区间")
