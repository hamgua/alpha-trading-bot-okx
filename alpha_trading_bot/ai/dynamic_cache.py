"""
动态缓存配置模块
提供基于市场波动率的智能缓存策略
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class CacheConfig:
    """缓存配置"""
    enabled: bool = True
    base_duration: int = 900  # 基础缓存时间（秒）
    min_duration: int = 300   # 最小缓存时间（秒）
    max_duration: int = 1800  # 最大缓存时间（秒）
    price_bucket_size: float = 50.0  # 价格分桶大小（美元）
    rsi_bucket_size: int = 10        # RSI分桶大小
    atr_threshold_high: float = 2.0  # 高波动阈值
    atr_threshold_medium: float = 1.0 # 中波动阈值
    volume_spike_threshold: float = 2.0 # 成交量异常阈值
    price_breakout_threshold: float = 0.8 # 价格突破阈值（基于ATR）


class DynamicCacheManager:
    """动态缓存管理器"""

    def __init__(self, config: Optional[CacheConfig] = None):
        self.config = config or CacheConfig()
        self._cache_stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'total_requests': 0
        }

    def calculate_volatility_factor(self, atr_percentage: float) -> str:
        """
        基于ATR百分比计算波动率因子

        Args:
            atr_percentage: ATR百分比（如1.5表示1.5%）

        Returns:
            波动率等级：'high', 'medium', 'low'
        """
        if atr_percentage >= self.config.atr_threshold_high:
            return 'high'
        elif atr_percentage >= self.config.atr_threshold_medium:
            return 'medium'
        else:
            return 'low'

    def get_dynamic_cache_duration(self, atr_percentage: float) -> int:
        """
        获取动态缓存时间

        Args:
            atr_percentage: ATR百分比

        Returns:
            缓存时间（秒）
        """
        volatility_factor = self.calculate_volatility_factor(atr_percentage)

        # 高波动：短时间缓存，快速响应
        if volatility_factor == 'high':
            return self.config.min_duration  # 5分钟
        # 中波动：中等时间缓存
        elif volatility_factor == 'medium':
            return (self.config.min_duration + self.config.base_duration) // 2  # 10分钟
        # 低波动：长时间缓存，节省成本
        else:
            return self.config.base_duration  # 15分钟

    def calculate_price_bucket(self, price: float, bucket_size: Optional[float] = None) -> int:
        """
        计算价格分桶

        Args:
            price: 当前价格
            bucket_size: 分桶大小（可选）

        Returns:
            价格桶值
        """
        size = bucket_size or self.config.price_bucket_size
        return int(round(price / size) * size)

    def calculate_rsi_bucket(self, rsi: float) -> int:
        """
        计算RSI分桶

        Args:
            rsi: RSI值（0-100）

        Returns:
            RSI桶值（10的倍数）
        """
        if rsi is None or rsi < 0:
            return 50  # 默认值

        # 限制在0-100范围内
        rsi = max(0, min(100, rsi))
        return int(round(rsi / self.config.rsi_bucket_size) * self.config.rsi_bucket_size)

    def calculate_macd_signal(self, macd_histogram: float) -> str:
        """
        计算MACD信号

        Args:
            macd_histogram: MACD柱状图值

        Returns:
            信号类型：'bullish', 'bearish', 'neutral'
        """
        if macd_histogram > 0:
            return 'bullish'
        elif macd_histogram < 0:
            return 'bearish'
        else:
            return 'neutral'

    def calculate_atr_level(self, atr_percentage: float) -> str:
        """
        计算ATR等级

        Args:
            atr_percentage: ATR百分比

        Returns:
            ATR等级：'high', 'medium', 'low'
        """
        if atr_percentage >= self.config.atr_threshold_high:
            return 'high'
        elif atr_percentage >= self.config.atr_threshold_medium:
            return 'medium'
        else:
            return 'low'

    def detect_volume_spike(self, current_volume: float, average_volume: float) -> bool:
        """
        检测成交量异常放大

        Args:
            current_volume: 当前成交量
            average_volume: 平均成交量

        Returns:
            是否异常放大
        """
        if average_volume <= 0:
            return False

        ratio = current_volume / average_volume
        return ratio >= self.config.volume_spike_threshold

    def detect_price_breakout(self,
                            current_price: float,
                            support_level: float,
                            resistance_level: float,
                            atr_value: float) -> Tuple[bool, str]:
        """
        检测价格突破

        Args:
            current_price: 当前价格
            support_level: 支撑位
            resistance_level: 阻力位
            atr_value: ATR值

        Returns:
            (是否突破, 突破类型)
        """
        # 计算突破阈值（基于ATR）
        breakout_threshold = atr_value * self.config.price_breakout_threshold

        # 检测向上突破
        if current_price > resistance_level + breakout_threshold:
            return True, 'upward'

        # 检测向下突破
        if current_price < support_level - breakout_threshold:
            return True, 'downward'

        return False, 'none'

    def should_invalidate_cache(self,
                              market_data: Dict[str, Any],
                              cached_data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        判断是否应该使缓存失效

        Args:
            market_data: 当前市场数据
            cached_data: 缓存的市场数据

        Returns:
            (是否应该失效, 原因)
        """
        # 检查价格突破
        current_price = market_data.get('price', 0)
        cached_price = cached_data.get('price', 0)

        # 检查成交量异常
        current_volume = market_data.get('volume', 0)
        avg_volume = market_data.get('average_volume', current_volume)

        if self.detect_volume_spike(current_volume, avg_volume):
            return True, "成交量异常放大"

        # 检查价格大幅变化（超过1.5个ATR）
        atr_value = market_data.get('atr', 0)
        if atr_value > 0:
            price_change = abs(current_price - cached_price)
            if price_change > atr_value * 1.5:
                return True, f"价格变化过大({price_change:.2f} > {atr_value * 1.5:.2f})"

        # 检查波动率变化
        current_atr_pct = market_data.get('atr_percentage', 0)
        cached_atr_pct = cached_data.get('atr_percentage', 0)

        if abs(current_atr_pct - cached_atr_pct) > 1.0:  # 波动率变化超过1%
            return True, f"波动率显著变化({cached_atr_pct:.2f}% → {current_atr_pct:.2f}%)"

        return False, ""

    def generate_cache_key_v2(self, market_data: Dict[str, Any]) -> str:
        """
        生成V2版本缓存键（包含技术指标）

        Args:
            market_data: 市场数据

        Returns:
            缓存键字符串
        """
        # 获取基础数据
        price = market_data.get('price', 0)
        volume = market_data.get('volume', 0)
        atr_percentage = market_data.get('atr_percentage', 0)

        # 计算技术指标
        technical_data = market_data.get('technical_data', {})
        rsi = technical_data.get('rsi', 50)
        macd_histogram = technical_data.get('macd_histogram', 0)

        # 分桶计算
        price_bucket = self.calculate_price_bucket(price)
        volume_bucket = self._calculate_volume_bucket(volume)
        rsi_bucket = self.calculate_rsi_bucket(rsi)
        macd_signal = self.calculate_macd_signal(macd_histogram)
        atr_level = self.calculate_atr_level(atr_percentage)
        volatility_factor = self.calculate_volatility_factor(atr_percentage)

        # 生成缓存键
        cache_key = f"ai_signal_v2_{price_bucket}_{volume_bucket}_{rsi_bucket}_{macd_signal}_{atr_level}_{volatility_factor}_{datetime.now().hour}"

        logger.debug(f"生成V2缓存键: {cache_key} (价格桶: {price_bucket}, RSI桶: {rsi_bucket}, MACD: {macd_signal}, ATR: {atr_level})")

        return cache_key

    def _calculate_volume_bucket(self, volume: float) -> int:
        """计算成交量分桶"""
        if volume > 1000000:
            return int(round(volume / 100000) * 100000)
        elif volume > 100000:
            return int(round(volume / 10000) * 10000)
        else:
            return int(round(volume / 1000) * 1000)

    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        total = self._cache_stats['hits'] + self._cache_stats['misses']
        hit_rate = self._cache_stats['hits'] / total if total > 0 else 0

        return {
            'hit_rate': hit_rate,
            'total_requests': total,
            'hits': self._cache_stats['hits'],
            'misses': self._cache_stats['misses'],
            'evictions': self._cache_stats['evictions']
        }

    def record_cache_hit(self) -> None:
        """记录缓存命中"""
        self._cache_stats['hits'] += 1
        self._cache_stats['total_requests'] += 1

    def record_cache_miss(self) -> None:
        """记录缓存未命中"""
        self._cache_stats['misses'] += 1
        self._cache_stats['total_requests'] += 1

    def record_cache_eviction(self) -> None:
        """记录缓存失效"""
        self._cache_stats['evictions'] += 1


# 全局实例
cache_manager = DynamicCacheManager()