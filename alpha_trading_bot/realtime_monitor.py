"""
实时价格监控模块 - 渐进式实时化第一阶段
实现3分钟价格变化监控，记录触发信号
"""

import asyncio
import logging
import json
import os
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from alpha_trading_bot.core.base import BaseComponent, BaseConfig

logger = logging.getLogger(__name__)


@dataclass
class PriceChangeEvent:
    """价格变化事件"""

    timestamp: datetime
    price_change_percent: float
    current_price: float
    previous_price: float
    timeframe: int  # 分钟
    triggered: bool


@dataclass
class QuickSignalRecord:
    """快速信号记录"""

    timestamp: datetime
    price_change_percent: float
    signal_type: str
    confidence: float
    reason: str
    market_context: Dict[str, Any]


@dataclass
class PriceMonitorConfig(BaseConfig):
    """价格监控配置"""

    monitor_cycle: int = 3 * 60  # 3分钟检查间隔
    price_change_threshold: float = 0.006  # 0.6%价格变化阈值
    enable_ai_check: bool = False  # 第一阶段不启用AI检查
    max_records_per_day: int = 1000  # 每天最多记录数
    enable_logging: bool = True
    data_dir: str = "data/price_monitor"  # 数据存储目录
    save_interval: int = 300  # 数据保存间隔（秒），5分钟保存一次


class PriceMonitor(BaseComponent):
    """价格监控器 - 支持渐进式实时化各阶段"""

    def __init__(self, config: Optional[PriceMonitorConfig] = None):
        super().__init__(config or PriceMonitorConfig(name="PriceMonitor"))
        self.price_history: List[Dict[str, Any]] = []
        self.price_change_events: List[PriceChangeEvent] = []
        self.quick_signals: List[QuickSignalRecord] = []
        self.last_monitor_time: Optional[datetime] = None
        self.monitor_task: Optional[asyncio.Task] = None
        self.save_task: Optional[asyncio.Task] = None
        self.is_monitoring = False
        self.data_dir: str = getattr(self.config, "data_dir", "data/price_monitor")
        self.last_save_time: Optional[datetime] = None

        # 第二阶段：快速信号分析器
        self.quick_signal_analyzer = None
        self._init_quick_signal_analyzer()

    def _init_quick_signal_analyzer(self):
        """初始化快速信号分析器（第二阶段）"""
        try:
            from .realtime.quick_signal_analyzer import (
                QuickSignalAnalyzer,
                QuickSignalAnalyzerConfig,
            )

            analyzer_config = QuickSignalAnalyzerConfig(
                enable_ai_analysis=False,  # 第二阶段先使用规则分析
                record_only=True,  # 仅记录，不执行
                price_change_threshold=getattr(
                    self.config, "price_change_threshold", 0.006
                ),
                data_dir=self.data_dir,
            )
            self.quick_signal_analyzer = QuickSignalAnalyzer(analyzer_config)
            logger.info("快速信号分析器已初始化（第二阶段）")
        except Exception as e:
            logger.warning(f"快速信号分析器初始化失败: {e}")

    async def initialize(self) -> bool:
        """初始化价格监控器"""
        try:
            logger.info("正在初始化价格监控器...")
            self._initialized = True

            # 确保数据目录存在
            os.makedirs(self.data_dir, exist_ok=True)

            # 加载历史数据
            await self._load_historical_data()

            # 初始化价格历史记录（用于计算变化）
            await self._initialize_price_history()

            # 第二阶段：初始化快速信号分析器
            if self.quick_signal_analyzer:
                await self.quick_signal_analyzer.initialize()

            monitor_cycle = getattr(self.config, "monitor_cycle", 180)
            price_change_threshold = getattr(
                self.config, "price_change_threshold", 0.006
            )
            logger.info(
                f"价格监控器初始化完成 - 监控周期: {monitor_cycle}秒, 阈值: {price_change_threshold:.2%}"
            )
            logger.info(f"数据存储目录: {self.data_dir}")
            return True

        except Exception as e:
            logger.error(f"价格监控器初始化失败: {e}")
            return False

    async def _initialize_price_history(self):
        """初始化价格历史记录 - 轻量级实现"""
        try:
            # 使用ccxt直接获取OHLCV数据，避免ExchangeClient初始化
            import ccxt.async_support as ccxt

            exchange = ccxt.okx(
                {
                    "enableRateLimit": True,
                    "timeout": 10000,
                }
            )

            try:
                # 获取最近1小时的1分钟K线数据
                ohlcv_data = await exchange.fetch_ohlcv("BTC/USDT:USDT", "1m", limit=60)

                if ohlcv_data:
                    for candle in ohlcv_data[-20:]:  # 只保留最近20分钟
                        self.price_history.append(
                            {
                                "timestamp": datetime.fromtimestamp(candle[0] / 1000),
                                "open": float(candle[1])
                                if candle[1] is not None
                                else 0,
                                "high": float(candle[2])
                                if candle[2] is not None
                                else 0,
                                "low": float(candle[3]) if candle[3] is not None else 0,
                                "close": float(candle[4])
                                if candle[4] is not None
                                else 0,
                                "volume": float(candle[5])
                                if candle[5] is not None
                                else 0,
                            }
                        )

                    logger.info(
                        f"已初始化价格历史记录: {len(self.price_history)} 个数据点"
                    )
            finally:
                await exchange.close()

        except Exception as e:
            logger.warning(f"初始化价格历史失败，使用空历史: {e}")

    async def start_monitoring(self):
        """启动价格监控"""
        if self.is_monitoring:
            logger.warning("价格监控已在运行中")
            return

        logger.info("启动价格监控...")
        self.is_monitoring = True
        self.monitor_task = asyncio.create_task(self._monitor_loop())

        # 启动定期数据保存任务
        save_interval = getattr(self.config, "save_interval", 300)
        self.save_task = asyncio.create_task(self._auto_save_loop(save_interval))

        # 启动定期数据保存任务
        save_interval = getattr(self.config, "save_interval", 300)
        self.save_task = asyncio.create_task(self._auto_save_loop(save_interval))

    async def stop_monitoring(self):
        """停止价格监控"""
        if not self.is_monitoring:
            logger.info("价格监控未运行")
            return

        logger.info("停止价格监控...")
        self.is_monitoring = False

        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass

        self.monitor_task = None

    async def _monitor_loop(self):
        """监控主循环"""
        logger.info(
            f"价格监控循环启动 - 间隔: {getattr(self.config, 'monitor_cycle', 180)}秒"
        )

        while self.is_monitoring:
            try:
                await asyncio.sleep(getattr(self.config, "monitor_cycle", 180))

                if not self.is_monitoring:  # 检查是否仍在运行
                    break

                # 执行价格监控检查
                await self._check_price_changes()

            except asyncio.CancelledError:
                logger.info("价格监控循环被取消")
                break
            except Exception as e:
                logger.error(f"价格监控循环异常: {e}")
                await asyncio.sleep(10)  # 出错后等待10秒再试

    async def _check_price_changes(self):
        """检查价格变化"""
        try:
            # 获取当前价格
            current_price = await self._get_current_price()
            if current_price is None:
                return

            # 更新价格历史
            current_time = datetime.now()
            self.price_history.append(
                {"timestamp": current_time, "close": current_price}
            )

            # 保持历史记录在合理范围内
            if len(self.price_history) > 60:  # 最多保留60个数据点
                self.price_history = self.price_history[-60:]

            # 计算价格变化（基于3分钟）
            price_change = self._calculate_price_change(minutes=3)

            if price_change is None:
                return

            # 记录价格变化事件
            event = PriceChangeEvent(
                timestamp=current_time,
                price_change_percent=price_change,
                current_price=current_price,
                previous_price=current_price / (1 + price_change),
                timeframe=3,
                triggered=abs(price_change)
                > getattr(self.config, "price_change_threshold", 0.006),
            )

            self.price_change_events.append(event)

            # 保持事件记录在合理范围内
            if len(self.price_change_events) > getattr(
                self.config, "max_records_per_day", 1000
            ):
                self.price_change_events = self.price_change_events[
                    -getattr(self.config, "max_records_per_day", 1000) :
                ]

            # 检查是否触发
            if abs(price_change) > getattr(
                self.config, "price_change_threshold", 0.006
            ):
                logger.info(
                    f"📈 检测到显著价格变化: {price_change:.2%} (阈值: {getattr(self.config, 'price_change_threshold', 0.006):.2%})"
                )

                # 记录触发事件
                await self._record_trigger_event(event)

                # 第一阶段：仅记录，不调用AI
                if not getattr(self.config, "enable_ai_check", False):
                    logger.info("第一阶段：仅记录价格变化事件，不触发AI分析")

            # 定期清理旧记录（保留24小时）
            self._cleanup_old_records()

        except Exception as e:
            logger.error(f"价格变化检查异常: {e}")

    async def _get_current_price(self) -> Optional[float]:
        """获取当前价格 - 轻量级实现，避免初始化交易功能"""
        try:
            # 使用ccxt的异步版本获取价格
            import ccxt.async_support as ccxt

            exchange = ccxt.okx(
                {
                    "enableRateLimit": True,
                    "timeout": 10000,
                    # 不设置API密钥，只用于公开数据获取
                }
            )

            ticker = await exchange.fetch_ticker("BTC/USDT:USDT")
            await exchange.close()

            if ticker and "last" in ticker:
                last_price = ticker["last"]
                if last_price is not None:
                    try:
                        return float(last_price)
                    except (ValueError, TypeError):
                        logger.warning(f"价格数据类型错误: {type(last_price)}")
                        return None

        except Exception as e:
            logger.error(f"获取当前价格失败: {e}")

        return None

    def _calculate_price_change(self, minutes: int) -> Optional[float]:
        """计算指定分钟内的价格变化"""
        try:
            if len(self.price_history) < 2:
                return None

            # 查找指定分钟前的数据点
            target_time = datetime.now() - timedelta(minutes=minutes)

            # 从最新的开始查找
            current_price = None
            past_price = None

            for record in reversed(self.price_history):
                if record["timestamp"] >= target_time:
                    if current_price is None:
                        current_price = record["close"]
                    past_price = record["close"]
                else:
                    break

            if current_price and past_price and past_price > 0:
                return (current_price - past_price) / past_price

        except Exception as e:
            logger.error(f"计算价格变化失败: {e}")

        return None

    async def _record_trigger_event(self, event: PriceChangeEvent):
        """记录触发事件"""
        try:
            # 第二阶段：使用快速信号分析器
            if self.quick_signal_analyzer:
                # 获取市场上下文
                market_context = await self._get_market_context()

                # 执行快速信号分析（仅记录，不执行）
                signal = await self.quick_signal_analyzer.analyze_price_change(
                    price_change_percent=event.price_change_percent,
                    current_price=event.current_price,
                    market_data=market_context,
                )

                if signal:
                    logger.info(
                        f"第二阶段快速信号: {signal.signal_type} @ {signal.timestamp} "
                        f"(置信度: {signal.confidence:.2f})"
                    )
                else:
                    logger.debug("未生成快速信号")
                return

            # 第一阶段：仅记录价格变化（原有逻辑）
            if not getattr(self.config, "enable_ai_check", False):
                logger.info(
                    f"记录价格变化事件: 时间={event.timestamp}, 变化={event.price_change_percent:.2%}"
                )
                return

            # 如果启用AI检查（旧版）
            await self._perform_quick_ai_check(event)

        except Exception as e:
            logger.error(f"记录触发事件失败: {e}")

    async def _perform_quick_ai_check(self, event: PriceChangeEvent):
        """执行快速AI检查"""
        try:
            # 获取市场上下文
            market_context = await self._get_market_context()

            # 调用AI快速分析
            quick_signal = await self._quick_ai_analysis(event, market_context)

            if quick_signal:
                # 记录快速信号
                record = QuickSignalRecord(
                    timestamp=datetime.now(),
                    price_change_percent=event.price_change_percent,
                    signal_type=quick_signal.get("type", "UNKNOWN"),
                    confidence=quick_signal.get("confidence", 0.0),
                    reason=quick_signal.get("reason", ""),
                    market_context=market_context,
                )

                self.quick_signals.append(record)

                # 保持信号记录在合理范围内
                if len(self.quick_signals) > 100:  # 最多保留100个信号
                    self.quick_signals = self.quick_signals[-100:]

                logger.info(
                    f"记录快速信号: {record.signal_type} (置信度: {record.confidence:.2f})"
                )

        except Exception as e:
            logger.error(f"快速AI检查失败: {e}")

    async def _get_market_context(self) -> Dict[str, Any]:
        """获取市场上下文 - 第一阶段简化版"""
        # 第一阶段只返回基本信息，不获取复杂技术指标
        return {
            "timestamp": datetime.now(),
            "price": await self._get_current_price(),
            "rsi": None,
            "macd": None,
            "volume": None,
        }

    async def _load_historical_data(self):
        """加载历史数据"""
        try:
            # 加载价格变化事件
            events_file = os.path.join(self.data_dir, "price_change_events.json")
            if os.path.exists(events_file):
                with open(events_file, "r", encoding="utf-8") as f:
                    events_data = json.load(f)
                    for event_data in events_data:
                        event = PriceChangeEvent(**event_data)
                        self.price_change_events.append(event)
                logger.info(
                    f"已加载 {len(self.price_change_events)} 个历史价格变化事件"
                )

            # 加载快速信号记录
            signals_file = os.path.join(self.data_dir, "quick_signals.json")
            if os.path.exists(signals_file):
                with open(signals_file, "r", encoding="utf-8") as f:
                    signals_data = json.load(f)
                    for signal_data in signals_data:
                        signal = QuickSignalRecord(**signal_data)
                        self.quick_signals.append(signal)
                logger.info(f"已加载 {len(self.quick_signals)} 个历史快速信号")

        except Exception as e:
            logger.warning(f"加载历史数据失败: {e}")

    async def _save_data(self):
        """保存数据到文件"""
        try:
            # 保存价格变化事件
            events_file = os.path.join(self.data_dir, "price_change_events.json")
            events_data = [
                asdict(event) for event in self.price_change_events[-1000:]
            ]  # 只保存最近1000个
            with open(events_file, "w", encoding="utf-8") as f:
                json.dump(events_data, f, ensure_ascii=False, indent=2, default=str)

            # 保存快速信号记录
            signals_file = os.path.join(self.data_dir, "quick_signals.json")
            signals_data = [
                asdict(signal) for signal in self.quick_signals[-500:]
            ]  # 只保存最近500个
            with open(signals_file, "w", encoding="utf-8") as f:
                json.dump(signals_data, f, ensure_ascii=False, indent=2, default=str)

            logger.debug(f"数据已保存到 {self.data_dir}")

        except Exception as e:
            logger.error(f"保存数据失败: {e}")

    async def _auto_save_loop(self, interval: int):
        """自动保存数据循环"""
        while self.is_monitoring:
            try:
                await asyncio.sleep(interval)
                if self.is_monitoring:  # 再次检查，确保仍在运行
                    await self._save_data()
                    self.last_save_time = datetime.now()
            except asyncio.CancelledError:
                logger.info("自动保存循环被取消")
                break
            except Exception as e:
                logger.error(f"自动保存循环异常: {e}")
                await asyncio.sleep(10)  # 出错后等待10秒再试

    async def _quick_ai_analysis(
        self, event: PriceChangeEvent, market_context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """快速AI分析"""
        try:
            # 这是第二阶段及以后的功能，第一阶段返回None
            if not getattr(self.config, "enable_ai_check", False):
                return None

            # TODO: 实现快速AI分析逻辑
            # 这里应该调用简化版的AI分析，只关注关键指标

            logger.info("执行快速AI分析...")
            return {
                "type": "HOLD",  # 保守起见，默认观望
                "confidence": 0.5,
                "reason": "快速分析结果",
            }

        except Exception as e:
            logger.error(f"快速AI分析失败: {e}")
            return None

    def _cleanup_old_records(self):
        """清理旧记录"""
        try:
            cutoff_time = datetime.now() - timedelta(hours=24)  # 保留24小时记录

            # 清理价格变化事件
            self.price_change_events = [
                event
                for event in self.price_change_events
                if event.timestamp > cutoff_time
            ]

            # 清理快速信号
            self.quick_signals = [
                signal
                for signal in self.quick_signals
                if signal.timestamp > cutoff_time
            ]

        except Exception as e:
            logger.debug(f"清理旧记录失败: {e}")

    def get_monitoring_stats(self) -> Dict[str, Any]:
        """获取监控统计信息"""
        return {
            "is_monitoring": self.is_monitoring,
            "price_change_events_count": len(self.price_change_events),
            "quick_signals_count": len(self.quick_signals),
            "last_monitor_time": self.last_monitor_time,
            "monitor_cycle": getattr(self.config, "monitor_cycle", 180),
            "price_change_threshold": getattr(
                self.config, "price_change_threshold", 0.006
            ),
            "price_history_count": len(self.price_history),
        }

    def get_recent_events(self, hours: int = 24) -> List[PriceChangeEvent]:
        """获取最近的事件"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        return [
            event for event in self.price_change_events if event.timestamp > cutoff_time
        ]

    def get_recent_signals(self, hours: int = 24) -> List[QuickSignalRecord]:
        """获取最近的信号"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        return [
            signal for signal in self.quick_signals if signal.timestamp > cutoff_time
        ]

    def get_signal_quality_report(self, hours: int = 24) -> Dict[str, Any]:
        """获取信号质量报告（第二阶段）"""
        if not self.quick_signal_analyzer:
            return {"error": "快速信号分析器未初始化"}

        stats = self.quick_signal_analyzer.get_stats()
        summary = self.quick_signal_analyzer.get_signal_summary(hours)

        return {
            "stats": stats,
            "summary": summary,
            "recent_signals_count": len(
                self.quick_signal_analyzer.get_recent_signals(hours)
            ),
        }

    async def cleanup(self):
        """清理资源"""
        await self.stop_monitoring()

        # 保存最终数据
        try:
            await self._save_data()

            # 第二阶段：保存快速信号
            if self.quick_signal_analyzer:
                await self.quick_signal_analyzer.save_signals()

            logger.info("最终数据已保存")
        except Exception as e:
            logger.error(f"保存最终数据失败: {e}")

        # 清理快速信号分析器
        if self.quick_signal_analyzer:
            self.quick_signal_analyzer.signals.clear()

        self.price_history.clear()
        self.price_change_events.clear()
        self.quick_signals.clear()
        logger.info("价格监控器已清理")


# 全局价格监控器实例
price_monitor = PriceMonitor()
