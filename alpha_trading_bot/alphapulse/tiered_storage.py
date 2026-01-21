"""
AlphaPulse 分层存储系统
高效存储和查询K线及技术指标历史数据

三层架构:
- 热数据 (Hot): 内存存储，实时监控，短期趋势
- 温数据 (Warm): SQLite数据库，中期分析，周级数据
- 冷数据 (Cold): 降采样数据库，长期趋势，月级数据
"""

import asyncio
import logging
import os
import sqlite3
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# 时间周期配置
TIMEFRAME_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
    "1w": 10080,
}

# 存储层级配置
STORAGE_CONFIG = {
    "hot": {
        "1m": 10080,  # 1周 * 1440条/天
        "5m": 2016,  # 1周 * 288条/天
        "15m": 672,  # 1周 * 96条/天
        "1h": 168,  # 1周
        "4h": 42,  # 1周
    },
    "warm": {
        "1m": 0,  # 不存储
        "5m": 0,  # 不存储
        "15m": 43200,  # 30天 * 96条/天
        "1h": 2160,  # 90天
        "4h": 540,  # 90天
        "1d": 180,  # 180天
    },
    "cold": {
        "15m": 0,  # 跳过
        "1h": 0,  # 跳过
        "4h": 0,  # 跳过
        "1d": 730,  # 2年
        "1w": 260,  # 5年
    },
}


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
        return [self.timestamp, self.open, self.high, self.low, self.close, self.volume]

    @classmethod
    def from_list(cls, data: List) -> "OHLCVData":
        return cls(
            timestamp=int(data[0]),
            open=float(data[1]),
            high=float(data[2]),
            low=float(data[3]),
            close=float(data[4]),
            volume=float(data[5]),
        )

    def to_dict(self) -> Dict:
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
class TrendData:
    """趋势分析数据"""

    symbol: str
    timeframe: str
    start_time: int
    end_time: int
    start_price: float
    end_price: float
    high_price: float
    low_price: float
    change_percent: float
    volatility_percent: float
    avg_volume: float
    trend_direction: str  # "up", "down", "sideways"
    sample_count: int


class TieredStorage:
    """
    分层存储管理器

    特点:
    - 热数据: 内存存储，O(1) 查询
    - 温数据: SQLite 持久化，带索引
    - 冷数据: 降采样存储，长期分析
    """

    def __init__(self, data_dir: str = "data/alphapulse"):
        """初始化分层存储"""
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 热数据存储 (内存)
        self.hot_storage: Dict[str, Dict[str, deque]] = {}
        self.hot_timestamps: Dict[str, Dict[str, List[int]]] = {}

        # 数据库连接
        self.warm_db_path = self.data_dir / "warm_storage.db"
        self.cold_db_path = self.data_dir / "cold_storage.db"

        self._init_databases()

        # 聚合缓存
        self._aggregation_cache: Dict[str, List[OHLCVData]] = {}
        self._last_aggregation: Dict[str, float] = {}

    def _init_databases(self):
        """初始化数据库表"""
        # 温数据数据库
        self._init_db(
            self.warm_db_path,
            """
            CREATE TABLE IF NOT EXISTS ohlcv (
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                PRIMARY KEY (symbol, timeframe, timestamp)
            )
            """,
        )

        # 创建索引
        with self._get_conn(self.warm_db_path) as conn:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_warm_symbol_time ON ohlcv(symbol, timeframe, timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_warm_timestamp ON ohlcv(timestamp)"
            )

        # 冷数据数据库 (降采样)
        self._init_db(
            self.cold_db_path,
            """
            CREATE TABLE IF NOT EXISTS ohlcv (
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                source_timeframe TEXT,
                aggregation_count INTEGER,
                PRIMARY KEY (symbol, timeframe, timestamp)
            )
            """,
        )

        with self._get_conn(self.cold_db_path) as conn:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cold_symbol_time ON ohlcv(symbol, timeframe, timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cold_timestamp ON ohlcv(timestamp)"
            )

    def _init_db(self, db_path: Path, schema: str):
        """初始化单个数据库"""
        with self._get_conn(db_path) as conn:
            conn.execute(schema)
            conn.commit()

    @contextmanager
    def _get_conn(self, db_path: Path):
        """获取数据库连接"""
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # ==================== 热数据操作 ====================

    def _ensure_hot_storage(self, symbol: str, timeframe: str):
        """确保热数据存储存在"""
        if symbol not in self.hot_storage:
            self.hot_storage[symbol] = {}
            self.hot_timestamps[symbol] = {}

        if timeframe not in self.hot_storage[symbol]:
            max_len = STORAGE_CONFIG["hot"].get(timeframe, 1000)
            self.hot_storage[symbol][timeframe] = deque(maxlen=max_len)
            self.hot_timestamps[symbol][timeframe] = []

    def store_hot(self, symbol: str, timeframe: str, ohlcv: OHLCVData):
        """存储热数据 (内存)"""
        self._ensure_hot_storage(symbol, timeframe)

        storage = self.hot_storage[symbol][timeframe]
        timestamps = self.hot_timestamps[symbol][timeframe]

        # 更新或追加
        if storage and storage[-1].timestamp == ohlcv.timestamp:
            storage[-1] = ohlcv
            timestamps[-1] = ohlcv.timestamp
        else:
            storage.append(ohlcv)
            timestamps.append(ohlcv.timestamp)

    def store_hot_batch(self, symbol: str, timeframe: str, ohlcv_list: List[OHLCVData]):
        """批量存储热数据"""
        for ohlcv in ohlcv_list:
            self.store_hot(symbol, timeframe, ohlcv)

    def get_hot(self, symbol: str, timeframe: str, limit: int = 100) -> List[OHLCVData]:
        """获取热数据"""
        if symbol not in self.hot_storage or timeframe not in self.hot_storage[symbol]:
            return []

        storage = self.hot_storage[symbol][timeframe]
        return list(storage)[-limit:] if limit > 0 else list(storage)

    def query_hot_by_time(
        self, symbol: str, timeframe: str, start_ts: int, end_ts: int
    ) -> List[OHLCVData]:
        """按时间范围查询热数据 (使用二分查找)"""
        import bisect

        if symbol not in self.hot_storage:
            return []

        timestamps = self.hot_timestamps[symbol].get(timeframe, [])
        if not timestamps:
            return []

        storage = self.hot_storage[symbol][timeframe]

        # 二分查找
        start_idx = bisect.bisect_left(timestamps, start_ts)
        end_idx = bisect.bisect_right(timestamps, end_ts)

        return list(storage)[start_idx:end_idx]

    # ==================== 温数据操作 ====================

    async def store_warm_async(self, symbol: str, timeframe: str, ohlcv: OHLCVData):
        """异步存储温数据 (SQLite)"""
        loop = asyncio.get_event_loop()

        def _store():
            with self._get_conn(self.warm_db_path) as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO ohlcv 
                    (symbol, timeframe, timestamp, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        symbol,
                        timeframe,
                        ohlcv.timestamp,
                        ohlcv.open,
                        ohlcv.high,
                        ohlcv.low,
                        ohlcv.close,
                        ohlcv.volume,
                    ),
                )
                conn.commit()

        await loop.run_in_executor(None, _store)

    def store_warm(self, symbol: str, timeframe: str, ohlcv: OHLCVData):
        """存储温数据 (SQLite) - 同步方法（已废弃，请使用 store_warm_async）"""
        with self._get_conn(self.warm_db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO ohlcv 
                (symbol, timeframe, timestamp, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    timeframe,
                    ohlcv.timestamp,
                    ohlcv.open,
                    ohlcv.high,
                    ohlcv.low,
                    ohlcv.close,
                    ohlcv.volume,
                ),
            )
            conn.commit()

    async def store_warm_batch_async(
        self, symbol: str, timeframe: str, ohlcv_list: List[OHLCVData]
    ):
        """异步批量存储温数据 (SQLite)"""
        if not ohlcv_list:
            return

        loop = asyncio.get_event_loop()

        def _store_batch():
            data = [
                (
                    symbol,
                    timeframe,
                    o.timestamp,
                    o.open,
                    o.high,
                    o.low,
                    o.close,
                    o.volume,
                )
                for o in ohlcv_list
            ]
            with self._get_conn(self.warm_db_path) as conn:
                conn.executemany(
                    """
                    INSERT OR IGNORE INTO ohlcv 
                    (symbol, timeframe, timestamp, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    data,
                )
                conn.commit()

        await loop.run_in_executor(None, _store_batch)

    def store_warm_batch(
        self, symbol: str, timeframe: str, ohlcv_list: List[OHLCVData]
    ):
        """批量存储温数据"""
        if not ohlcv_list:
            return

        with self._get_conn(self.warm_db_path) as conn:
            data = [
                (
                    symbol,
                    timeframe,
                    o.timestamp,
                    o.open,
                    o.high,
                    o.low,
                    o.close,
                    o.volume,
                )
                for o in ohlcv_list
            ]
            conn.executemany(
                """
                INSERT OR IGNORE INTO ohlcv 
                (symbol, timeframe, timestamp, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                data,
            )
            conn.commit()

    def get_warm(
        self, symbol: str, timeframe: str, limit: int = 100, offset: int = 0
    ) -> List[OHLCVData]:
        """获取温数据"""
        with self._get_conn(self.warm_db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM ohlcv 
                WHERE symbol = ? AND timeframe = ?
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """,
                (symbol, timeframe, limit, offset),
            ).fetchall()

        return [self._row_to_ohlcv(row) for row in rows]

    def query_warm_by_time(
        self, symbol: str, timeframe: str, start_ts: int, end_ts: int, limit: int = 1000
    ) -> List[OHLCVData]:
        """按时间范围查询温数据 (使用索引)"""
        with self._get_conn(self.warm_db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM ohlcv 
                WHERE symbol = ? AND timeframe = ? 
                AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (symbol, timeframe, start_ts, end_ts, limit),
            ).fetchall()

        return [self._row_to_ohlcv(row) for row in rows]

    def _row_to_ohlcv(self, row: sqlite3.Row) -> OHLCVData:
        """将数据库行转换为OHLCV对象"""
        return OHLCVData(
            timestamp=row["timestamp"],
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            volume=row["volume"],
        )

    # ==================== 冷数据操作 ====================

    def store_cold(
        self,
        symbol: str,
        timeframe: str,
        ohlcv: OHLCVData,
        source_tf: str = None,
        agg_count: int = 1,
    ):
        """存储冷数据 (降采样)"""
        with self._get_conn(self.cold_db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO ohlcv 
                (symbol, timeframe, timestamp, open, high, low, close, volume, source_timeframe, aggregation_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    timeframe,
                    ohlcv.timestamp,
                    ohlcv.open,
                    ohlcv.high,
                    ohlcv.low,
                    ohlcv.close,
                    ohlcv.volume,
                    source_tf,
                    agg_count,
                ),
            )
            conn.commit()

    def get_cold(
        self, symbol: str, timeframe: str, limit: int = 100, offset: int = 0
    ) -> List[OHLCVData]:
        """获取冷数据"""
        with self._get_conn(self.cold_db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM ohlcv 
                WHERE symbol = ? AND timeframe = ?
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """,
                (symbol, timeframe, limit, offset),
            ).fetchall()

        return [self._row_to_ohlcv(row) for row in rows]

    def query_cold_by_time(
        self, symbol: str, timeframe: str, start_ts: int, end_ts: int, limit: int = 1000
    ) -> List[OHLCVData]:
        """按时间范围查询冷数据"""
        with self._get_conn(self.cold_db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM ohlcv 
                WHERE symbol = ? AND timeframe = ?
                AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (symbol, timeframe, start_ts, end_ts, limit),
            ).fetchall()

        return [self._row_to_ohlcv(row) for row in rows]

    # ==================== 聚合与降采样 ====================

    def _aggregate_ohlcv(
        self, ohlcv_list: List[OHLCVData], target_tf: str
    ) -> OHLCVData:
        """聚合K线数据"""
        if not ohlcv_list:
            return None

        # 按时间排序
        sorted_data = sorted(ohlcv_list, key=lambda x: x.timestamp)

        return OHLCVData(
            timestamp=sorted_data[0].timestamp,  # 使用第一根K线的开盘时间
            open=sorted_data[0].open,
            high=max(d.high for d in sorted_data),
            low=min(d.low for d in sorted_data),
            close=sorted_data[-1].close,
            volume=sum(d.volume for d in sorted_data),
        )

    async def aggregate_and_store(self, symbol: str, source_tf: str, target_tf: str):
        """
        聚合并存储到下一层级

        例如: 15分钟 -> 1小时 -> 4小时 -> 1天 -> 1周
        """
        cache_key = f"{symbol}:{source_tf}:{target_tf}"

        # 避免重复聚合
        now = time.time()
        if cache_key in self._last_aggregation:
            last_run = self._last_aggregation[cache_key]
            if now - last_run < 60:  # 至少间隔60秒
                return

        self._last_aggregation[cache_key] = now

        # 获取源数据
        source_data = self.get_hot(symbol, source_tf, limit=10000)

        # 计算聚合因子
        source_minutes = TIMEFRAME_MINUTES.get(source_tf, 15)
        target_minutes = TIMEFRAME_MINUTES.get(target_tf, 60)
        factor = target_minutes // source_minutes

        if factor <= 1:
            return

        # 分组聚合
        for i in range(0, len(source_data), factor):
            chunk = source_data[i : i + factor]
            if len(chunk) >= factor * 0.8:  # 至少80%的数据
                aggregated = self._aggregate_ohlcv(chunk, target_tf)
                if aggregated:
                    # 存储到热数据
                    self.store_hot(symbol, target_tf, aggregated)
                    # 存储到冷数据
                    self.store_cold(
                        symbol, target_tf, aggregated, source_tf, len(chunk)
                    )

    # ==================== 统一查询接口 ====================

    def get(
        self, symbol: str, timeframe: str, limit: int = 100, use_cold: bool = False
    ) -> List[OHLCVData]:
        """
        统一获取数据接口

        优先从热数据获取，不足时从温数据补充
        """
        # 尝试热数据
        hot_data = self.get_hot(symbol, timeframe, limit)

        if len(hot_data) >= limit:
            return hot_data[-limit:]

        # 补充温数据
        needed = limit - len(hot_data)
        warm_data = self.get_warm(symbol, timeframe, limit=needed)

        if use_cold and not warm_data:
            cold_data = self.get_cold(symbol, timeframe, limit=needed)
            return cold_data + [d.to_list() for d in hot_data]

        return [d.to_list() for d in warm_data] + [d.to_list() for d in hot_data]

    def query_by_period(
        self, symbol: str, timeframe: str, period: str = "1d", limit: int = 1000
    ) -> List[OHLCVData]:
        """
        按时间段查询

        period: "1h", "4h", "1d", "1w", "1m"(1月)
        """
        now = int(datetime.now().timestamp() * 1000)
        period_ms = {
            "1h": 3600 * 1000,
            "4h": 4 * 3600 * 1000,
            "1d": 24 * 3600 * 1000,
            "24h": 24 * 3600 * 1000,  # 24小时，与1d等价
            "1w": 7 * 24 * 3600 * 1000,
            "7d": 7 * 24 * 3600 * 1000,  # 7天，与1w等价
            "1m": 30 * 24 * 3600 * 1000,
        }

        start_ts = now - period_ms.get(period, 24 * 3600 * 1000)

        # 优先热数据
        hot_data = self.query_hot_by_time(symbol, timeframe, start_ts, now)
        if len(hot_data) >= limit:
            return hot_data[-limit:]

        # 补充温数据
        warm_data = self.query_warm_by_time(
            symbol, timeframe, start_ts, now, limit - len(hot_data)
        )

        return warm_data + hot_data

    # ==================== 趋势分析 ====================

    def analyze_trend(
        self, symbol: str, timeframe: str, period: str = "1d"
    ) -> TrendData:
        """
        分析趋势

        返回:
        - 涨跌幅
        - 波动率
        - 趋势方向
        - 成交量变化
        """
        data = self.query_by_period(symbol, timeframe, period, limit=1000)

        if not data:
            return None

        if isinstance(data[0], OHLCVData):
            data = [d.to_list() for d in data]

        if not data:
            return None

        opens = [d[1] for d in data]
        highs = [d[2] for d in data]
        lows = [d[3] for d in data]
        closes = [d[4] for d in data]
        volumes = [d[5] for d in data]

        start_price = opens[0]
        end_price = closes[-1]
        high_price = max(highs)
        low_price = min(lows)

        change_percent = (end_price - start_price) / start_price * 100
        volatility_percent = (high_price - low_price) / start_price * 100
        avg_volume = sum(volumes) / len(volumes) if volumes else 0

        # 判断趋势方向
        if change_percent > 1.5:
            direction = "up"
        elif change_percent < -1.5:
            direction = "down"
        else:
            direction = "sideways"

        return TrendData(
            symbol=symbol,
            timeframe=timeframe,
            start_time=data[0][0],
            end_time=data[-1][0],
            start_price=start_price,
            end_price=end_price,
            high_price=high_price,
            low_price=low_price,
            change_percent=change_percent,
            volatility_percent=volatility_percent,
            avg_volume=avg_volume,
            trend_direction=direction,
            sample_count=len(data),
        )

    def get_price_position(
        self, symbol: str, current_price: float, period: str = "24h"
    ) -> float:
        """计算价格位置 (0-100%)"""
        data = self.query_by_period(symbol, "15m", period, limit=1000)

        if not data:
            return 50.0  # 默认中间位置

        if isinstance(data[0], OHLCVData):
            data = [d.to_list() for d in data]

        closes = [d[4] for d in data]
        high = max(closes)
        low = min(closes)

        if high == low:
            return 50.0

        return (current_price - low) / (high - low) * 100

    # ==================== 统计信息 ====================

    def get_stats(self, symbol: str) -> Dict:
        """获取存储统计"""
        stats = {
            "symbol": symbol,
            "hot": {},
            "warm": {},
            "cold": {},
        }

        # 热数据统计
        if symbol in self.hot_storage:
            for tf, storage in self.hot_storage[symbol].items():
                stats["hot"][tf] = len(storage)

        # 温数据统计
        with self._get_conn(self.warm_db_path) as conn:
            for row in conn.execute(
                "SELECT timeframe, COUNT(*) as count FROM ohlcv WHERE symbol = ? GROUP BY timeframe",
                (symbol,),
            ):
                stats["warm"][row["timeframe"]] = row["count"]

        # 冷数据统计
        with self._get_conn(self.cold_db_path) as conn:
            for row in conn.execute(
                "SELECT timeframe, COUNT(*) as count FROM ohlcv WHERE symbol = ? GROUP BY timeframe",
                (symbol,),
            ):
                stats["cold"][row["timeframe"]] = row["count"]

        return stats

    def clear(self, symbol: str = None):
        """清空数据"""
        if symbol:
            # 清空指定交易对
            if symbol in self.hot_storage:
                self.hot_storage[symbol].clear()
                self.hot_timestamps[symbol].clear()

            with self._get_conn(self.warm_db_path) as conn:
                conn.execute("DELETE FROM ohlcv WHERE symbol = ?", (symbol,))
                conn.commit()

            with self._get_conn(self.cold_db_path) as conn:
                conn.execute("DELETE FROM ohlcv WHERE symbol = ?", (symbol,))
                conn.commit()
        else:
            # 清空所有
            self.hot_storage.clear()
            self.hot_timestamps.clear()

            with self._get_conn(self.warm_db_path) as conn:
                conn.execute("DELETE FROM ohlcv")
                conn.commit()

            with self._get_conn(self.cold_db_path) as conn:
                conn.execute("DELETE FROM ohlcv")
                conn.commit()


# 便捷函数
def create_tiered_storage(data_dir: str = "data/alphapulse") -> TieredStorage:
    """创建分层存储实例"""
    return TieredStorage(data_dir)
