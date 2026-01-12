"""
实时价格监控模块 - 渐进式实时化第一阶段
实现3分钟价格变化监控，记录触发信号
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
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


class PriceMonitorConfig(BaseConfig):
    """价格监控配置"""

    monitor_cycle: int = 3 * 60  # 3分钟检查间隔
    price_change_threshold: float = 0.006  # 0.6%价格变化阈值
    enable_ai_check: bool = False  # 第一阶段不启用AI检查
    max_records_per_day: int = 1000  # 每天最多记录数
    enable_logging: bool = True

    def __init__(self, name: str = "PriceMonitor", **kwargs):
        super().__init__(name=name, **kwargs)


class PriceMonitor(BaseComponent):
    """价格监控器 - 第一阶段：记录触发信号"""

    def __init__(self, config: Optional[PriceMonitorConfig] = None):
        super().__init__(config or PriceMonitorConfig(name="PriceMonitor"))
        self.price_history: List[Dict[str, Any]] = []
        self.price_change_events: List[PriceChangeEvent] = []
        self.quick_signals: List[QuickSignalRecord] = []
        self.last_monitor_time: Optional[datetime] = None
        self.monitor_task: Optional[asyncio.Task] = None
        self.is_monitoring = False

    async def initialize(self) -> bool:
        """初始化价格监控器"""
        try:
            logger.info("正在初始化价格监控器...")
            self._initialized = True

            # 初始化价格历史记录（用于计算变化）
            await self._initialize_price_history()

            monitor_cycle = getattr(self.config, "monitor_cycle", 180)
            price_change_threshold = getattr(
                self.config, "price_change_threshold", 0.006
            )
            logger.info(
                f"价格监控器初始化完成 - 监控周期: {monitor_cycle}秒, 阈值: {price_change_threshold:.2%}"
            )
            return True

        except Exception as e:
            logger.error(f"价格监控器初始化失败: {e}")
            return False

    async def _initialize_price_history(self):
        """初始化价格历史记录"""
        try:
            # 从交易所获取最近的价格数据用于初始化
            from alpha_trading_bot.exchange.client import ExchangeClient

            exchange_client = ExchangeClient()

            if await exchange_client.initialize():
                # 获取最近1小时的数据用于初始化
                ohlcv_data = await exchange_client.fetch_ohlcv(
                    "BTC/USDT:USDT", "1m", limit=60
                )

                if ohlcv_data:
                    for candle in ohlcv_data[-20:]:  # 只保留最近20分钟
                        self.price_history.append(
                            {
                                "timestamp": datetime.fromtimestamp(candle[0] / 1000),
                                "open": candle[1],
                                "high": candle[2],
                                "low": candle[3],
                                "close": candle[4],
                                "volume": candle[5],
                            }
                        )

                    logger.info(
                        f"已初始化价格历史记录: {len(self.price_history)} 个数据点"
                    )

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
        """获取当前价格"""
        try:
            from alpha_trading_bot.exchange.client import ExchangeClient

            exchange_client = ExchangeClient()

            if await exchange_client.initialize():
                ticker = await exchange_client.fetch_ticker("BTC/USDT:USDT")
                if ticker and ticker.get("last"):
                    return float(ticker["last"])

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
            if not getattr(self.config, "enable_ai_check", False):
                # 第一阶段：仅记录价格变化
                logger.info(
                    f"记录价格变化事件: 时间={event.timestamp}, 变化={event.price_change_percent:.2%}"
                )
                return

            # 如果启用AI检查（第二阶段及以后）
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
        """获取市场上下文"""
        try:
            from alpha_trading_bot.exchange.client import ExchangeClient

            exchange_client = ExchangeClient()

            context = {
                "timestamp": datetime.now(),
                "price": None,
                "rsi": None,
                "macd": None,
                "volume": None,
            }

            if await exchange_client.initialize():
                # 获取当前价格
                ticker = await exchange_client.fetch_ticker("BTC/USDT:USDT")
                if ticker:
                    context["price"] = ticker.get("last")
                    context["volume"] = ticker.get("volume")

                # 获取技术指标（简化版）
                try:
                    ohlcv_data = await exchange_client.fetch_ohlcv(
                        "BTC/USDT:USDT", "1m", limit=20
                    )
                    if ohlcv_data and len(ohlcv_data) >= 14:
                        # 简单的RSI估算
                        closes = [d[4] for d in ohlcv_data]
                        if len(closes) >= 14:
                            gains = [
                                max(0, closes[i] - closes[i - 1])
                                for i in range(1, len(closes))
                            ]
                            losses = [
                                max(0, closes[i - 1] - closes[i])
                                for i in range(1, len(closes))
                            ]
                            avg_gain = sum(gains[-14:]) / 14
                            avg_loss = sum(losses[-14:]) / 14
                            if avg_loss != 0:
                                rs = avg_gain / avg_loss
                                context["rsi"] = 100 - (100 / (1 + rs))
                except Exception as e:
                    logger.debug(f"获取技术指标失败: {e}")

            return context

        except Exception as e:
            logger.error(f"获取市场上下文失败: {e}")
            return {}

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

    async def cleanup(self):
        """清理资源"""
        await self.stop_monitoring()
        self.price_history.clear()
        self.price_change_events.clear()
        self.quick_signals.clear()
        logger.info("价格监控器已清理")


# 全局价格监控器实例
price_monitor = PriceMonitor()
