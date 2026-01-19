"""
AlphaPulse 数据管理器
高效存储和查询K线及技术指标历史数据

已集成 TieredStorage 分层存储系统:
- 热数据 (Hot): 内存存储，实时监控，短期趋势
- 温数据 (Warm): SQLite数据库，中期分析，周级数据
- 冷数据 (Cold): 降采样数据库，长期趋势，月级数据
"""

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class TrendDirection(Enum):
    """趋势方向"""

    UP = "up"
    DOWN = "down"
    SIDEWAYS = "sideways"
    UNKNOWN = "unknown"


@dataclass
class OHLCVData:
    """K线数据"""

    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    datetime: Optional[datetime] = None

    def __post_init__(self):
        if self.datetime is None:
            self.datetime = datetime.fromtimestamp(self.timestamp / 1000)

    def to_list(self) -> List:
        """转换为列表格式 [timestamp, open, high, low, close, volume]"""
        return [
            self.timestamp,
            self.open,
            self.high,
            self.low,
            self.close,
            self.volume,
        ]

    @classmethod
    def from_list(cls, data: List) -> "OHLCVData":
        """从列表创建"""
        return cls(
            timestamp=int(data[0]),
            open=float(data[1]),
            high=float(data[2]),
            low=float(data[3]),
            close=float(data[4]),
            volume=float(data[5]),
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "datetime": self.datetime.isoformat() if self.datetime else None,
        }


@dataclass
class IndicatorSnapshot:
    """指标快照"""

    timestamp: datetime
    symbol: str
    timeframe: str

    # 价格数据
    current_price: float
    high_24h: float
    low_24h: float
    high_7d: float
    low_7d: float

    # 位置百分比
    price_position_24h: float  # 0-100%
    price_position_7d: float  # 0-100%

    # 技术指标
    atr: float
    atr_percent: float
    rsi: float
    macd: float
    macd_signal: float
    macd_histogram: float
    adx: float
    plus_di: float
    minus_di: float
    bb_upper: float
    bb_lower: float
    bb_middle: float
    bb_position: float  # 0-100%

    # 趋势分析
    trend_direction: str
    trend_strength: float  # 0-1

    # 原始K线数据引用
    ohlcv_data: List[List] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "current_price": self.current_price,
            "high_24h": self.high_24h,
            "low_24h": self.low_24h,
            "high_7d": self.high_7d,
            "low_7d": self.low_7d,
            "price_position_24h": self.price_position_24h,
            "price_position_7d": self.price_position_7d,
            "atr": self.atr,
            "atr_percent": self.atr_percent,
            "rsi": self.rsi,
            "macd": self.macd,
            "macd_signal": self.macd_signal,
            "macd_histogram": self.macd_histogram,
            "adx": self.adx,
            "plus_di": self.plus_di,
            "minus_di": self.minus_di,
            "bb_upper": self.bb_upper,
            "bb_lower": self.bb_lower,
            "bb_middle": self.bb_middle,
            "bb_position": self.bb_position,
            "trend_direction": self.trend_direction,
            "trend_strength": self.trend_strength,
        }


class DataManager:
    """
    数据管理器

    功能:
    - 存储K线历史数据
    - 存储技术指标历史
    - 高效查询趋势
    - 支持多时间周期
    - 自动同步到TieredStorage（温/冷数据）
    """

    def __init__(
        self,
        max_ohlcv_bars: int = 200,
        max_indicator_history: int = 100,
        tiered_storage=None,
    ):
        """
        初始化数据管理器

        Args:
            max_ohlcv_bars: 最大存储的OHLCV K线数量
            max_indicator_history: 最大存储的指标历史数量
            tiered_storage: 分层存储实例（可选，用于同步温/冷数据）
        """
        # K线数据存储 {symbol: {timeframe: deque([OHLCVData])}}
        self.ohlcv_storage: Dict[str, Dict[str, deque]] = {}

        # 指标历史存储 {symbol: deque([IndicatorSnapshot])}
        self.indicator_history: Dict[str, deque] = {}

        # 24h/7d高低价缓存 {symbol: {'high_24h': float, 'low_24h': float, ...}}
        self.price_range_cache: Dict[str, Dict[str, float]] = {}

        # 配置
        self.max_ohlcv_bars = max_ohlcv_bars
        self.max_indicator_history = max_indicator_history

        # 分层存储（用于持久化）
        self._tiered_storage = tiered_storage

        # 线程锁 + 初始化状态跟踪
        self._lock = asyncio.Lock()
        self._initializing: Dict[str, bool] = {}  # 跟踪正在初始化的符号

    async def initialize_symbol(self, symbol: str, timeframes: List[str] = None):
        """
        初始化交易对数据存储 - 优化版：避免死锁

        Args:
            symbol: 交易对
            timeframes: 时间周期列表
        """
        if timeframes is None:
            timeframes = ["1m", "5m", "15m", "1h", "4h"]

        # 检查是否正在初始化
        if symbol in self._initializing and self._initializing[symbol]:
            # 等待初始化完成
            for _ in range(50):  # 最多等待5秒
                await asyncio.sleep(0.1)
                if symbol not in self._initializing or not self._initializing[symbol]:
                    return  # 初始化完成
            logger.warning(f"⚠️ 等待 {symbol} 初始化超时")

        # 快速检查是否已初始化（无需锁）
        if symbol in self.ohlcv_storage and symbol in self.indicator_history:
            return  # 已初始化，直接返回

        # 获取锁并初始化
        async with self._lock:
            # 双重检查
            if symbol in self.ohlcv_storage and symbol in self.indicator_history:
                return

            logger.info(f"🔧 开始初始化: {symbol}")
            self._initializing[symbol] = True

            try:
                self.ohlcv_storage[symbol] = {}
                for tf in timeframes:
                    self.ohlcv_storage[symbol][tf] = deque(maxlen=self.max_ohlcv_bars)

                self.indicator_history[symbol] = deque(
                    maxlen=self.max_indicator_history
                )

                self.price_range_cache[symbol] = {
                    "high_24h": 0,
                    "low_24h": float("inf"),
                    "high_7d": 0,
                    "low_7d": float("inf"),
                    "last_update": None,
                }

                logger.info(f"✅ 数据管理器已初始化: {symbol}, 时间周期: {timeframes}")
            finally:
                self._initializing[symbol] = False

    async def update_ohlcv(
        self, symbol: str, timeframe: str, ohlcv: List, is_completed: bool = True
    ):
        """
        更新K线数据 - 无锁版本：使用原子操作避免锁竞争

        Args:
            symbol: 交易对
            timeframe: 时间周期
            ohlcv: OHLCV数据列表
            is_completed: 是否完整的K线
        """
        # 解析K线数据
        ohlcv_data = OHLCVData.from_list(ohlcv)

        # 确保存储初始化
        if symbol not in self.ohlcv_storage:
            await self.initialize_symbol(symbol, ["1m", "5m", "15m", "1h", "4h"])

        # 确保时间周期已初始化
        storage = None
        if timeframe not in self.ohlcv_storage[symbol]:
            async with self._lock:
                if timeframe not in self.ohlcv_storage[symbol]:
                    self.ohlcv_storage[symbol][timeframe] = deque(
                        maxlen=self.max_ohlcv_bars
                    )
                storage = self.ohlcv_storage[symbol][timeframe]
        else:
            storage = self.ohlcv_storage[symbol][timeframe]

        # 更新热数据存储（原子操作，无需锁）
        if storage and storage[-1].timestamp == ohlcv_data.timestamp:
            storage[-1] = ohlcv_data
        else:
            storage.append(ohlcv_data)

        # 更新价格区间缓存（原子操作，无需锁）
        if symbol not in self.price_range_cache:
            self.price_range_cache[symbol] = {
                "high_24h": ohlcv_data.close,
                "low_24h": ohlcv_data.close,
                "high_7d": ohlcv_data.close,
                "low_7d": ohlcv_data.close,
                "last_update": datetime.now(),
            }
        else:
            cache = self.price_range_cache[symbol]
            price = ohlcv_data.close
            cache["last_update"] = datetime.now()
            if price > cache["high_24h"]:
                cache["high_24h"] = price
            if price < cache["low_24h"]:
                cache["low_24h"] = price
            if price > cache["high_7d"]:
                cache["high_7d"] = price
            if price < cache["low_7d"]:
                cache["low_7d"] = price

        # 异步同步到温数据存储（后台执行）
        if self._tiered_storage is not None:
            try:
                asyncio.create_task(
                    self._tiered_storage.store_warm_async(symbol, timeframe, ohlcv_data)
                )
            except Exception as e:
                logger.warning(f"⚠️ [TieredStorage] 同步温数据失败: {e}")

    async def _update_price_range(self, symbol: str, price: float):
        """更新价格区间缓存"""
        now = datetime.now()

        if symbol not in self.price_range_cache:
            self.price_range_cache[symbol] = {
                "high_24h": price,
                "low_24h": price,
                "high_7d": price,
                "low_7d": price,
                "last_update": now,
            }
            return

        cache = self.price_range_cache[symbol]
        cache["last_update"] = now

        # 更新24h高低价
        if price > cache["high_24h"]:
            cache["high_24h"] = price
        if price < cache["low_24h"]:
            cache["low_24h"] = price

        # 更新7d高低价
        if price > cache["high_7d"]:
            cache["high_7d"] = price
        if price < cache["low_7d"]:
            cache["low_7d"] = price

    async def reset_price_range_24h(self, symbol: str):
        """重置24h价格区间（每天调用一次）"""
        async with self._lock:
            if symbol in self.price_range_cache:
                cache = self.price_range_cache[symbol]
                current_price = await self.get_current_price(symbol)

                if current_price:
                    cache["high_24h"] = current_price
                    cache["low_24h"] = current_price

                logger.info(f"已重置24h价格区间: {symbol}")

    async def get_ohlcv(
        self, symbol: str, timeframe: str, limit: int = None
    ) -> List[List]:
        """
        获取K线数据

        Args:
            symbol: 交易对
            timeframe: 时间周期
            limit: 获取数量

        Returns:
            OHLCV数据列表
        """
        async with self._lock:
            if (
                symbol not in self.ohlcv_storage
                or timeframe not in self.ohlcv_storage[symbol]
            ):
                return []

            data = list(self.ohlcv_storage[symbol][timeframe])
            if limit and len(data) > limit:
                data = data[-limit:]

            return [d.to_list() for d in data]

    async def get_current_price(self, symbol: str) -> Optional[float]:
        """获取当前价格"""
        async with self._lock:
            if (
                symbol not in self.ohlcv_storage
                or "1m" not in self.ohlcv_storage[symbol]
            ):
                return None

            data = self.ohlcv_storage[symbol]["1m"]
            if data:
                return data[-1].close

            return None

    async def get_price_range(self, symbol: str) -> Dict[str, float]:
        """
        获取价格区间

        Returns:
            {
                'high_24h': float,
                'low_24h': float,
                'high_7d': float,
                'low_7d': float,
                'range_24h': float,  # 24h波动幅度
                'range_7d': float,   # 7d波动幅度
            }
        """
        async with self._lock:
            if symbol not in self.price_range_cache:
                return {
                    "high_24h": 0,
                    "low_24h": 0,
                    "high_7d": 0,
                    "low_7d": 0,
                    "range_24h": 0,
                    "range_7d": 0,
                }

            cache = self.price_range_cache[symbol]
            current_price = await self.get_current_price(symbol)

            high_24h = cache["high_24h"]
            low_24h = cache["low_24h"]
            high_7d = cache["high_7d"]
            low_7d = cache["low_7d"]

            # 计算波动幅度
            range_24h = ((high_24h - low_24h) / low_24h * 100) if low_24h > 0 else 0
            range_7d = ((high_7d - low_7d) / low_7d * 100) if low_7d > 0 else 0

            return {
                "high_24h": high_24h,
                "low_24h": low_24h,
                "high_7d": high_7d,
                "low_7d": low_7d,
                "range_24h": range_24h,
                "range_7d": range_7d,
                "current_price": current_price,
            }

    def get_price_position(self, current: float, high: float, low: float) -> float:
        """
        计算价格位置百分比

        Args:
            current: 当前价格
            high: 最高价
            low: 最低价

        Returns:
            0-100的位置百分比
        """
        if high == low:
            return 50.0

        position = (current - low) / (high - low) * 100
        return max(0, min(100, position))

    async def update_indicator(self, symbol: str, indicator: IndicatorSnapshot):
        """更新指标快照"""
        async with self._lock:
            if symbol not in self.indicator_history:
                self.indicator_history[symbol] = deque(
                    maxlen=self.max_indicator_history
                )

            self.indicator_history[symbol].append(indicator)

    async def get_latest_indicator(self, symbol: str) -> Optional[IndicatorSnapshot]:
        """获取最新指标"""
        async with self._lock:
            if (
                symbol not in self.indicator_history
                or not self.indicator_history[symbol]
            ):
                return None

            return self.indicator_history[symbol][-1]

    async def get_indicator_history(
        self, symbol: str, limit: int = None
    ) -> List[IndicatorSnapshot]:
        """获取指标历史"""
        async with self._lock:
            if symbol not in self.indicator_history:
                return []

            history = list(self.indicator_history[symbol])
            if limit and len(history) > limit:
                history = history[-limit:]

            return history

    async def get_trend_analysis(
        self, symbol: str, period: str = "1h", bars: int = 20
    ) -> Dict[str, Any]:
        """
        趋势分析

        Args:
            symbol: 交易对
            period: 时间周期
            bars: 分析的K线数量

        Returns:
            趋势分析结果
        """
        ohlcv = await self.get_ohlcv(symbol, period, limit=bars)

        if len(ohlcv) < 5:
            return {
                "direction": TrendDirection.UNKNOWN.value,
                "strength": 0,
                "change_percent": 0,
                "volatility": 0,
                "message": "数据不足",
            }

        # 计算价格变化
        start_price = ohlcv[0][1]  # open
        end_price = ohlcv[-1][4]  # close
        change_percent = (end_price - start_price) / start_price * 100

        # 计算波动率
        prices = [d[4] for d in ohlcv]  # close prices
        volatility = (
            (max(prices) - min(prices)) / start_price * 100 if start_price > 0 else 0
        )

        # 判断趋势方向和强度
        if change_percent > 2:
            direction = TrendDirection.UP.value
            strength = min(1.0, change_percent / 10)
        elif change_percent < -2:
            direction = TrendDirection.DOWN.value
            strength = min(1.0, abs(change_percent) / 10)
        else:
            direction = TrendDirection.SIDEWAYS.value
            strength = 0.3

        # 计算移动平均线趋势
        if len(prices) >= 5:
            ma_short = sum(prices[-3:]) / 3
            ma_long = sum(prices[-5:]) / 5
            if ma_short > ma_long:
                ma_trend = "up"
            elif ma_short < ma_long:
                ma_trend = "down"
            else:
                ma_trend = "sideways"
        else:
            ma_trend = "unknown"

        return {
            "direction": direction,
            "strength": strength,
            "change_percent": change_percent,
            "volatility": volatility,
            "ma_trend": ma_trend,
            "start_price": start_price,
            "end_price": end_price,
            "bars_analyzed": len(ohlcv),
        }

    async def get_market_summary(self, symbol: str) -> Dict[str, Any]:
        """
        获取市场摘要

        Returns:
            市场状态摘要
        """
        # 获取最新指标
        latest_indicator = await self.get_latest_indicator(symbol)

        # 获取价格区间
        price_range = await self.get_price_range(symbol)

        # 获取趋势分析
        trend_1h = await self.get_trend_analysis(symbol, "1h", 20)
        trend_4h = await self.get_trend_analysis(symbol, "4h", 30)

        # 综合趋势
        if trend_1h["direction"] == trend_4h["direction"]:
            overall_trend = trend_4h["direction"]
            trend_strength = (trend_1h["strength"] + trend_4h["strength"]) / 2
        else:
            overall_trend = TrendDirection.SIDEWAYS.value
            trend_strength = 0.2

        return {
            "symbol": symbol,
            "timestamp": datetime.now().isoformat(),
            "current_price": price_range.get("current_price"),
            "price_range_24h": {
                "high": price_range["high_24h"],
                "low": price_range["low_24h"],
                "position": self.get_price_position(
                    price_range.get("current_price", 0),
                    price_range["high_24h"],
                    price_range["low_24h"],
                ),
                "range_percent": price_range["range_24h"],
            },
            "price_range_7d": {
                "high": price_range["high_7d"],
                "low": price_range["low_7d"],
                "position": self.get_price_position(
                    price_range.get("current_price", 0),
                    price_range["high_7d"],
                    price_range["low_7d"],
                ),
                "range_percent": price_range["range_7d"],
            },
            "trend": {
                "direction": overall_trend,
                "strength": trend_strength,
                "1h_change": trend_1h["change_percent"],
                "4h_change": trend_4h["change_percent"],
                "volatility": max(trend_1h["volatility"], trend_4h["volatility"]),
            },
            "indicators": latest_indicator.to_dict() if latest_indicator else None,
        }

    def get_storage_stats(self, symbol: str) -> Dict[str, int]:
        """获取存储统计"""
        stats = {}
        if symbol in self.ohlcv_storage:
            for tf, data in self.ohlcv_storage[symbol].items():
                stats[f"ohlcv_{tf}"] = len(data)

        if symbol in self.indicator_history:
            stats["indicators"] = len(self.indicator_history[symbol])

        return stats

    async def cleanup(self):
        """清理资源"""
        async with self._lock:
            self.ohlcv_storage.clear()
            self.indicator_history.clear()
            self.price_range_cache.clear()

        logger.info("数据管理器已清理")
