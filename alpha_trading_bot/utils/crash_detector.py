#!/usr/bin/env python3
"""
改进的暴跌检测器
提供多时间框架、动态阈值的暴跌检测
"""

import time
import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class CrashLevel(Enum):
    """暴跌等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class CrashEvent:
    """暴跌事件"""
    level: CrashLevel
    timeframe: str
    price_change: float
    threshold: float
    timestamp: float
    reason: str


class DataQualityChecker:
    """数据质量检查器"""

    def __init__(self):
        self.max_price_age = 300  # 5分钟
        self.min_valid_volume = 0.1  # 最小有效成交量

    def validate_market_data(self, market_data: Dict) -> Tuple[bool, str]:
        """验证市场数据的有效性"""
        try:
            # 检查必需字段
            required_fields = ['current_price', 'open', 'high', 'low', 'volume']
            for field in required_fields:
                if field not in market_data:
                    return False, f"缺少字段: {field}"

            # 检查价格有效性
            current_price = float(market_data.get('current_price', 0))
            if current_price <= 0:
                return False, "当前价格无效"

            # 检查成交量
            volume = float(market_data.get('volume', 0))
            if volume < self.min_valid_volume:
                return False, f"成交量过低: {volume}"

            # 检查价格是否过期
            timestamp = market_data.get('timestamp', time.time())
            if (time.time() - timestamp) > self.max_price_age:
                return False, "价格数据过期"

            # 检查价格合理性（与当日高低价比较）
            high = float(market_data.get('high', 0))
            low = float(market_data.get('low', 0))
            if current_price > high * 1.1 or current_price < low * 0.9:
                return False, "价格超出合理范围"

            return True, "数据正常"

        except (ValueError, TypeError) as e:
            return False, f"数据类型错误: {e}"

    def is_price_stale(self, market_data: Dict, max_age: int = 300) -> bool:
        """检查价格数据是否过期"""
        timestamp = market_data.get('timestamp', time.time())
        return (time.time() - timestamp) > max_age


class ImprovedCrashDetector:
    """改进的暴跌检测器"""

    def __init__(self):
        # 多时间框架配置（时间窗口: 阈值）
        self.timeframes = {
            '5m': {'window': 1, 'threshold': 0.008},    # 0.8% for 5min - 早期预警
            '15m': {'window': 1, 'threshold': 0.015},   # 1.5% for 15min
            '1h': {'window': 4, 'threshold': 0.025},    # 2.5% for 1h
            '2h': {'window': 8, 'threshold': 0.030},    # 3.0% for 2h
            '4h': {'window': 16, 'threshold': 0.035},   # 3.5% for 4h
        }

        # 暴跌预警级别配置（价格水平感知）
        self.early_warning_thresholds = {
            'minor': 0.005,      # 0.5% - 轻微预警
            'moderate': 0.010,   # 1.0% - 中等预警
            'severe': 0.015,     # 1.5% - 严重预警
        }

        # 价格水平感知的暴跌检测阈值
        self.price_level_thresholds = {
            'high_price': {       # >$50,000 (如BTC高价期)
                'percentage_multiplier': 0.8,    # 降低百分比阈值敏感度
                'absolute_threshold': 500,       # $500绝对跌幅
                'early_warning_multipliers': {
                    'minor': 0.6,      # 0.3% (0.5% * 0.6)
                    'moderate': 0.7,   # 0.7% (1.0% * 0.7)
                    'severe': 0.8      # 1.2% (1.5% * 0.8)
                }
            },
            'medium_price': {      # $10,000-$50,000
                'percentage_multiplier': 1.0,
                'absolute_threshold': 200,
                'early_warning_multipliers': {
                    'minor': 0.8,
                    'moderate': 0.9,
                    'severe': 1.0
                }
            },
            'low_price': {         # <$10,000
                'percentage_multiplier': 1.2,
                'absolute_threshold': 100,
                'early_warning_multipliers': {
                    'minor': 1.0,
                    'moderate': 1.0,
                    'severe': 1.0
                }
            }
        }

        # 币种特异性阈值调整
        self.symbol_adjustments = {
            'BTC/USDT': 1.0,    # 基准
            'ETH/USDT': 1.2,    # ETH波动性比BTC高20%
            'SHIB/USDT': 2.5,   # SHIB波动性高150%
        }

        self.data_validator = DataQualityChecker()
        self.price_history = {}  # 存储价格历史
        self.max_history_size = 100  # 最大历史数据条数

    def add_price_data(self, symbol: str, price: float, timestamp: Optional[float] = None):
        """添加价格数据到历史记录"""
        if symbol not in self.price_history:
            self.price_history[symbol] = []

        if timestamp is None:
            timestamp = time.time()

        self.price_history[symbol].append({
            'price': price,
            'timestamp': timestamp
        })

        # 保持历史数据在合理范围内
        if len(self.price_history[symbol]) > self.max_history_size:
            self.price_history[symbol] = self.price_history[symbol][-self.max_history_size:]

    def detect_crash(self, market_data: Dict, symbol: str = 'BTC/USDT') -> List[CrashEvent]:
        """
        检测暴跌事件

        Args:
            market_data: 市场数据字典
            symbol: 交易对符号

        Returns:
            暴跌事件列表
        """
        crash_events = []

        # 1. 数据质量检查
        is_valid, reason = self.data_validator.validate_market_data(market_data)
        if not is_valid:
            logger.warning(f"数据验证失败: {reason}")
            return crash_events

        current_price = float(market_data['current_price'])
        current_time = market_data.get('timestamp', time.time())

        # 添加到价格历史
        self.add_price_data(symbol, current_price, current_time)

        # 2. 多时间框架检测
        for tf_name, tf_config in self.timeframes.items():
            crash_event = self._check_timeframe_crash(
                symbol, tf_name, tf_config, current_price, current_time
            )
            if crash_event:
                crash_events.append(crash_event)

        # 3. 连续下跌检测
        consecutive_crash = self._check_consecutive_drops(symbol, current_price)
        if consecutive_crash:
            crash_events.append(consecutive_crash)

        # 4. 早期暴跌预警检测
        early_warning = self._check_early_warning(symbol, current_price)
        if early_warning:
            crash_events.append(early_warning)

        # 5. 加速下跌检测
        acceleration_crash = self._check_acceleration_drop(symbol, current_price)
        if acceleration_crash:
            crash_events.append(acceleration_crash)

        # 记录检测结果
        if crash_events:
            logger.warning(f"检测到 {len(crash_events)} 个暴跌事件: {[e.level.value for e in crash_events]}")
            for event in crash_events:
                logger.warning(f"  - {event.timeframe}: {event.price_change*100:.2f}% (阈值: {event.threshold*100:.2f}%)")

        return crash_events

    def _check_timeframe_crash(self, symbol: str, tf_name: str, tf_config: dict,
                              current_price: float, current_time: float) -> Optional[CrashEvent]:
        """检查特定时间框架的暴跌"""
        if symbol not in self.price_history or len(self.price_history[symbol]) < tf_config['window']:
            return None

        # 获取时间窗口内的价格数据
        recent_data = self.price_history[symbol][-tf_config['window']:]

        # 找到窗口内的最高价
        max_price = max(data['price'] for data in recent_data)

        # 计算从最高价到当前价的跌幅
        price_change = (current_price - max_price) / max_price

        # 获取币种特异性调整
        adjustment = self.symbol_adjustments.get(symbol, 1.0)
        adjusted_threshold = tf_config['threshold'] * adjustment

        # 检查是否达到暴跌阈值
        if price_change < -adjusted_threshold:
            # 确定暴跌等级
            drop_ratio = abs(price_change) / adjusted_threshold
            if drop_ratio > 2.0:
                level = CrashLevel.CRITICAL
            elif drop_ratio > 1.5:
                level = CrashLevel.HIGH
            elif drop_ratio > 1.2:
                level = CrashLevel.MEDIUM
            else:
                level = CrashLevel.LOW

            return CrashEvent(
                level=level,
                timeframe=tf_name,
                price_change=price_change,
                threshold=adjusted_threshold,
                timestamp=current_time,
                reason=f"从{tf_name}最高价下跌{price_change*100:.2f}%"
            )

        return None

    def _check_consecutive_drops(self, symbol: str, current_price: float) -> Optional[CrashEvent]:
        """检查连续下跌"""
        if symbol not in self.price_history or len(self.price_history[symbol]) < 5:
            return None

        # 获取最近5个周期的价格变化
        recent_data = self.price_history[symbol][-5:]
        changes = []

        for i in range(1, len(recent_data)):
            change = (recent_data[i]['price'] - recent_data[i-1]['price']) / recent_data[i-1]['price']
            changes.append(change)

        # 检查是否连续下跌
        if len(changes) >= 4 and all(change < 0 for change in changes[-4:]):
            total_drop = sum(changes[-4:])

            # 如果连续4个周期下跌且总跌幅超过2%
            if abs(total_drop) > 0.02:
                return CrashEvent(
                    level=CrashLevel.MEDIUM,
                    timeframe='consecutive',
                    price_change=total_drop,
                    threshold=0.02,
                    timestamp=recent_data[-1]['timestamp'],
                    reason=f"连续4个周期下跌，总跌幅{total_drop*100:.2f}%"
                )

        return None

    def _check_acceleration_drop(self, symbol: str, current_price: float) -> Optional[CrashEvent]:
        """检查加速下跌"""
        if symbol not in self.price_history or len(self.price_history[symbol]) < 4:
            return None

        # 获取最近的价格变化
        recent_data = self.price_history[symbol][-4:]
        changes = []

        for i in range(1, len(recent_data)):
            change = (recent_data[i]['price'] - recent_data[i-1]['price']) / recent_data[i-1]['price']
            changes.append(change)

        # 检查是否加速下跌（跌幅逐渐扩大）
        if len(changes) >= 3:
            is_accelerating = True
            for i in range(1, len(changes)):
                if changes[i] >= changes[i-1]:  # 没有加速
                    is_accelerating = False
                    break

            if is_accelerating:
                total_drop = sum(changes)
                if abs(total_drop) > 0.015:  # 总跌幅超过1.5%
                    return CrashEvent(
                        level=CrashLevel.HIGH,
                        timeframe='acceleration',
                        price_change=total_drop,
                        threshold=0.015,
                        timestamp=recent_data[-1]['timestamp'],
                        reason=f"加速下跌，总跌幅{total_drop*100:.2f}%"
                    )

        return None

    def _get_price_level_config(self, current_price: float) -> Dict:
        """根据当前价格获取价格水平配置"""
        if current_price > 50000:
            return self.price_level_thresholds['high_price']
        elif current_price > 10000:
            return self.price_level_thresholds['medium_price']
        else:
            return self.price_level_thresholds['low_price']

    def detect_crash_with_price_awareness(self, market_data: Dict, symbol: str = 'BTC/USDT') -> List[CrashEvent]:
        """价格水平感知的暴跌检测"""
        crash_events = []

        # 获取基础检测结果
        base_events = self.detect_crash(market_data, symbol)
        crash_events.extend(base_events)

        # 价格水平感知增强检测
        current_price = float(market_data.get('current_price', 0))
        if current_price <= 0:
            return crash_events

        price_level_config = self._get_price_level_config(current_price)

        # 1. 绝对跌幅检测（适用于高价资产）
        if self.price_history.get(symbol) and len(self.price_history[symbol]) >= 2:
            # 计算从近期高点下跌的绝对金额
            recent_high = max(data['price'] for data in self.price_history[symbol][-10:])
            absolute_drop = recent_high - current_price

            if absolute_drop > price_level_config['absolute_threshold']:
                # 检查是否已经检测过类似的百分比跌幅
                percentage_drop = absolute_drop / recent_high
                if not any(e.timeframe == 'absolute_price' for e in crash_events):
                    crash_events.append(CrashEvent(
                        level=CrashLevel.HIGH,
                        timeframe='absolute_price',
                        price_change=-percentage_drop,
                        threshold=price_level_config['absolute_threshold'] / recent_high,
                        timestamp=market_data.get('timestamp', time.time()),
                        reason=f"绝对跌幅${absolute_drop:.0f}超过阈值${price_level_config['absolute_threshold']}"
                    ))

        # 2. 高价资产的早期预警增强
        early_warning_events = self._check_early_warning_with_price_awareness(symbol, current_price, price_level_config)
        crash_events.extend(early_warning_events)

        return crash_events

    def _check_early_warning_with_price_awareness(self, symbol: str, current_price: float, price_level_config: Dict) -> List[CrashEvent]:
        """价格水平感知的早期暴跌预警检测"""
        events = []

        if symbol not in self.price_history or len(self.price_history[symbol]) < 3:
            return events

        # 获取最近3个价格点
        recent_data = self.price_history[symbol][-3:]

        # 计算短期跌幅
        short_term_drop = (current_price - recent_data[0]['price']) / recent_data[0]['price']

        # 根据价格水平调整阈值
        adjusted_thresholds = {
            'minor': self.early_warning_thresholds['minor'] * price_level_config['early_warning_multipliers']['minor'],
            'moderate': self.early_warning_thresholds['moderate'] * price_level_config['early_warning_multipliers']['moderate'],
            'severe': self.early_warning_thresholds['severe'] * price_level_config['early_warning_multipliers']['severe']
        }

        # 检查是否触发早期预警（使用调整后的阈值）
        if abs(short_term_drop) > adjusted_thresholds['severe']:
            # 严重预警
            events.append(CrashEvent(
                level=CrashLevel.HIGH,
                timeframe='early_warning_price_aware',
                price_change=short_term_drop,
                threshold=adjusted_thresholds['severe'],
                timestamp=recent_data[-1]['timestamp'],
                reason=f"高价资产早期暴跌预警 - 短期跌幅{short_term_drop*100:.2f}%（价格水平调整）"
            ))
        elif abs(short_term_drop) > adjusted_thresholds['moderate']:
            # 中等预警
            events.append(CrashEvent(
                level=CrashLevel.MEDIUM,
                timeframe='early_warning_price_aware',
                price_change=short_term_drop,
                threshold=adjusted_thresholds['moderate'],
                timestamp=recent_data[-1]['timestamp'],
                reason=f"高价资产早期下跌预警 - 短期跌幅{short_term_drop*100:.2f}%（价格水平调整）"
            ))
        elif abs(short_term_drop) > adjusted_thresholds['minor']:
            # 轻微预警
            events.append(CrashEvent(
                level=CrashLevel.LOW,
                timeframe='early_warning_price_aware',
                price_change=short_term_drop,
                threshold=adjusted_thresholds['minor'],
                timestamp=recent_data[-1]['timestamp'],
                reason=f"高价资产轻微下跌预警 - 短期跌幅{short_term_drop*100:.2f}%（价格水平调整）"
            ))

        return events

    def _check_early_warning(self, symbol: str, current_price: float) -> Optional[CrashEvent]:
        if symbol not in self.price_history or len(self.price_history[symbol]) < 3:
            return None

        # 获取最近3个价格点
        recent_data = self.price_history[symbol][-3:]

        # 计算短期跌幅
        short_term_drop = (current_price - recent_data[0]['price']) / recent_data[0]['price']

        # 检查是否触发早期预警
        if abs(short_term_drop) > self.early_warning_thresholds['severe']:
            # 严重预警 - 1.5%跌幅
            return CrashEvent(
                level=CrashLevel.HIGH,
                timeframe='early_warning',
                price_change=short_term_drop,
                threshold=self.early_warning_thresholds['severe'],
                timestamp=recent_data[-1]['timestamp'],
                reason=f"早期暴跌预警 - 短期跌幅{short_term_drop*100:.2f}%"
            )
        elif abs(short_term_drop) > self.early_warning_thresholds['moderate']:
            # 中等预警 - 1.0%跌幅
            return CrashEvent(
                level=CrashLevel.MEDIUM,
                timeframe='early_warning',
                price_change=short_term_drop,
                threshold=self.early_warning_thresholds['moderate'],
                timestamp=recent_data[-1]['timestamp'],
                reason=f"早期下跌预警 - 短期跌幅{short_term_drop*100:.2f}%"
            )
        elif abs(short_term_drop) > self.early_warning_thresholds['minor']:
            # 轻微预警 - 0.5%跌幅
            return CrashEvent(
                level=CrashLevel.LOW,
                timeframe='early_warning',
                price_change=short_term_drop,
                threshold=self.early_warning_thresholds['minor'],
                timestamp=recent_data[-1]['timestamp'],
                reason=f"轻微下跌预警 - 短期跌幅{short_term_drop*100:.2f}%"
            )

        return None

    def get_current_stats(self, symbol: str = 'BTC/USDT') -> Dict:
        """获取当前统计信息"""
        if symbol not in self.price_history or len(self.price_history[symbol]) < 2:
            return {}

        recent_data = self.price_history[symbol][-20:]  # 最近20条
        prices = [data['price'] for data in recent_data]

        # 计算各种统计指标
        current_price = prices[-1]
        max_price = max(prices)
        min_price = min(prices)

        stats = {
            'current_price': current_price,
            'max_20period': max_price,
            'min_20period': min_price,
            'change_from_max': (current_price - max_price) / max_price,
            'change_from_min': (current_price - min_price) / min_price,
            'price_history_count': len(self.price_history.get(symbol, [])),
            'data_quality': 'good' if len(recent_data) >= 10 else 'insufficient'
        }

        return stats


# 全局实例
crash_detector = ImprovedCrashDetector()


def detect_crash_events(market_data: Dict, symbol: str = 'BTC/USDT') -> List[CrashEvent]:
    """
    便捷的暴跌检测函数

    Args:
        market_data: 市场数据
        symbol: 交易对

    Returns:
        暴跌事件列表
    """
    return crash_detector.detect_crash(market_data, symbol)