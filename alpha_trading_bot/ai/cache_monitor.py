"""
缓存性能监控模块
用于监控AI缓存系统的性能指标
"""

import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from collections import defaultdict
import json
import os

logger = logging.getLogger(__name__)


@dataclass
class CacheMetrics:
    """缓存指标"""
    hit_count: int = 0
    miss_count: int = 0
    eviction_count: int = 0
    total_requests: int = 0
    total_savings: float = 0.0  # 节省的API调用成本
    avg_hit_rate: float = 0.0
    avg_response_time: float = 0.0
    last_updated: datetime = field(default_factory=datetime.now)


@dataclass
class CacheEntryStats:
    """缓存条目统计"""
    key: str
    access_count: int = 0
    hit_count: int = 0
    miss_count: int = 0
    first_access: datetime = field(default_factory=datetime.now)
    last_access: datetime = field(default_factory=datetime.now)
    avg_access_interval: float = 0.0
    total_savings: float = 0.0


class CacheMonitor:
    """缓存性能监控器"""

    def __init__(self, log_file: Optional[str] = None):
        """初始化监控器"""
        self.log_file = log_file or "cache_monitor.log"
        self.metrics = CacheMetrics()
        self.entry_stats: Dict[str, CacheEntryStats] = {}
        self.hourly_stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {'hits': 0, 'misses': 0, 'evictions': 0})
        self.start_time = datetime.now()
        self.last_save_time = datetime.now()
        self.api_cost_per_request = 0.001  # 估算每次API调用成本（美元）
        self._setup_logging()

    def _setup_logging(self):
        """设置日志记录"""
        # 创建文件处理器
        file_handler = logging.FileHandler(self.log_file)
        file_handler.setLevel(logging.INFO)

        # 创建格式化器
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)

        # 添加处理器到logger
        logger.addHandler(file_handler)
        logger.setLevel(logging.INFO)

    def record_hit(self, cache_key: str, response_time: float = 0.0) -> None:
        """记录缓存命中"""
        self.metrics.hit_count += 1
        self.metrics.total_requests += 1
        self.metrics.total_savings += self.api_cost_per_request

        # 更新条目统计
        if cache_key not in self.entry_stats:
            self.entry_stats[cache_key] = CacheEntryStats(key=cache_key)

        entry = self.entry_stats[cache_key]
        entry.access_count += 1
        entry.hit_count += 1
        entry.last_access = datetime.now()
        entry.total_savings += self.api_cost_per_request

        # 更新平均响应时间
        if self.metrics.avg_response_time == 0:
            self.metrics.avg_response_time = response_time
        else:
            self.metrics.avg_response_time = (self.metrics.avg_response_time + response_time) / 2

        # 更新小时统计
        hour_key = datetime.now().strftime('%Y-%m-%d_%H')
        self.hourly_stats[hour_key]['hits'] += 1

        logger.info(f"缓存命中: {cache_key} (响应时间: {response_time:.3f}s)")

    def record_miss(self, cache_key: str) -> None:
        """记录缓存未命中"""
        self.metrics.miss_count += 1
        self.metrics.total_requests += 1

        # 更新条目统计
        if cache_key not in self.entry_stats:
            self.entry_stats[cache_key] = CacheEntryStats(key=cache_key)

        entry = self.entry_stats[cache_key]
        entry.access_count += 1
        entry.miss_count += 1
        entry.last_access = datetime.now()

        # 更新小时统计
        hour_key = datetime.now().strftime('%Y-%m-%d_%H')
        self.hourly_stats[hour_key]['misses'] += 1

        logger.info(f"缓存未命中: {cache_key}")

    def record_eviction(self, cache_key: str, reason: str = "") -> None:
        """记录缓存失效"""
        self.metrics.eviction_count += 1

        # 更新小时统计
        hour_key = datetime.now().strftime('%Y-%m-%d_%H')
        self.hourly_stats[hour_key]['evictions'] += 1

        logger.info(f"缓存失效: {cache_key} (原因: {reason})")

    def record_api_call(self, provider: str, cost: float = 0.0) -> None:
        """记录API调用"""
        logger.info(f"API调用: {provider} (成本: ${cost:.4f})")

    def get_hit_rate(self) -> float:
        """获取缓存命中率"""
        if self.metrics.total_requests == 0:
            return 0.0
        return self.metrics.hit_count / self.metrics.total_requests

    def get_savings_rate(self) -> float:
        """获取节省率（节省的API调用百分比）"""
        if self.metrics.total_requests == 0:
            return 0.0
        return self.metrics.hit_count / self.metrics.total_requests

    def get_total_savings(self) -> float:
        """获取总节省成本"""
        return self.metrics.total_savings

    def get_hot_keys(self, limit: int = 10) -> List[CacheEntryStats]:
        """获取热门缓存键"""
        entries = sorted(
            self.entry_stats.values(),
            key=lambda x: x.access_count,
            reverse=True
        )
        return entries[:limit]

    def get_cold_keys(self, limit: int = 10) -> List[CacheEntryStats]:
        """获取冷门缓存键"""
        entries = sorted(
            self.entry_stats.values(),
            key=lambda x: x.access_count
        )
        return entries[:limit]

    def get_hourly_stats(self, hours: int = 24) -> Dict[str, Dict[str, int]]:
        """获取小时统计"""
        result = {}
        current_hour = datetime.now()

        for i in range(hours):
            hour_time = current_hour - timedelta(hours=i)
            hour_key = hour_time.strftime('%Y-%m-%d_%H')
            result[hour_key] = dict(self.hourly_stats[hour_key])

        return result

    def generate_report(self) -> Dict[str, Any]:
        """生成监控报告"""
        runtime = datetime.now() - self.start_time
        hit_rate = self.get_hit_rate()
        savings_rate = self.get_savings_rate()
        total_savings = self.get_total_savings()

        # 获取热门和冷门键
        hot_keys = self.get_hot_keys(5)
        cold_keys = self.get_cold_keys(5)

        # 获取最近24小时的小时统计
        hourly_stats = self.get_hourly_stats(24)

        report = {
            'timestamp': datetime.now().isoformat(),
            'runtime_seconds': runtime.total_seconds(),
            'metrics': {
                'total_requests': self.metrics.total_requests,
                'hit_count': self.metrics.hit_count,
                'miss_count': self.metrics.miss_count,
                'eviction_count': self.metrics.eviction_count,
                'hit_rate': hit_rate,
                'savings_rate': savings_rate,
                'total_savings_usd': total_savings,
                'avg_response_time': self.metrics.avg_response_time
            },
            'hot_keys': [
                {
                    'key': entry.key,
                    'access_count': entry.access_count,
                    'hit_rate': entry.hit_count / entry.access_count if entry.access_count > 0 else 0,
                    'total_savings': entry.total_savings
                }
                for entry in hot_keys
            ],
            'cold_keys': [
                {
                    'key': entry.key,
                    'access_count': entry.access_count,
                    'hit_rate': entry.hit_count / entry.access_count if entry.access_count > 0 else 0,
                    'total_savings': entry.total_savings
                }
                for entry in cold_keys
            ],
            'hourly_stats': hourly_stats,
            'recommendations': self._generate_recommendations(hit_rate, savings_rate)
        }

        return report

    def _generate_recommendations(self, hit_rate: float, savings_rate: float) -> List[str]:
        """生成优化建议"""
        recommendations = []

        # 命中率建议
        if hit_rate < 0.3:
            recommendations.append("缓存命中率较低(30%)，建议优化缓存策略或增加缓存时间")
        elif hit_rate > 0.8:
            recommendations.append("缓存命中率很高(80%)，当前缓存策略效果良好")

        # 节省率建议
        if savings_rate < 0.2:
            recommendations.append("API调用节省率较低(20%)，建议分析缓存键生成逻辑")
        elif savings_rate > 0.7:
            recommendations.append("API调用节省效果显著(70%)，有效降低了成本")

        # 基于热门键的建议
        hot_keys = self.get_hot_keys(3)
        if hot_keys:
            max_access = hot_keys[0].access_count
            if max_access > self.metrics.total_requests * 0.5:
                recommendations.append(f"存在热点键({hot_keys[0].key})，建议考虑更细粒度的缓存策略")

        return recommendations

    def save_report(self, filename: Optional[str] = None) -> str:
        """保存报告到文件"""
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"cache_report_{timestamp}.json"

        report = self.generate_report()

        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)

            logger.info(f"缓存报告已保存到: {filename}")
            return filename
        except Exception as e:
            logger.error(f"保存报告失败: {e}")
            return ""

    def print_summary(self) -> None:
        """打印摘要信息"""
        hit_rate = self.get_hit_rate()
        savings_rate = self.get_savings_rate()
        total_savings = self.get_total_savings()

        print("\n" + "="*60)
        print("缓存性能监控摘要")
        print("="*60)
        print(f"运行时间: {datetime.now() - self.start_time}")
        print(f"总请求数: {self.metrics.total_requests}")
        print(f"缓存命中: {self.metrics.hit_count} ({hit_rate:.1%})")
        print(f"缓存未命中: {self.metrics.miss_count} ({1-hit_rate:.1%})")
        print(f"缓存失效: {self.metrics.eviction_count}")
        print(f"节省API调用: {self.metrics.hit_count} 次")
        print(f"节省成本: ${total_savings:.4f}")
        print(f"平均响应时间: {self.metrics.avg_response_time:.3f}s")

        # 热门键
        hot_keys = self.get_hot_keys(3)
        if hot_keys:
            print("\n热门缓存键:")
            for entry in hot_keys:
                print(f"  {entry.key}: {entry.access_count} 次访问, {entry.hit_count/entry.access_count:.1%} 命中率")

        # 建议
        recommendations = self._generate_recommendations(hit_rate, savings_rate)
        if recommendations:
            print("\n优化建议:")
            for rec in recommendations:
                print(f"  - {rec}")

        print("="*60 + "\n")

    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        return {
            'hit_count': self.metrics.hit_count,
            'miss_count': self.metrics.miss_count,
            'eviction_count': self.metrics.eviction_count,
            'total_requests': self.metrics.total_requests,
            'hit_rate': self.get_hit_rate(),
            'savings_rate': self.get_savings_rate(),
            'total_savings': self.get_total_savings(),
            'avg_response_time': self.metrics.avg_response_time
        }

    def reset_stats(self) -> None:
        """重置统计信息"""
        self.metrics = CacheMetrics()
        self.entry_stats.clear()
        self.hourly_stats.clear()
        self.start_time = datetime.now()
        logger.info("缓存统计已重置")


# 全局监控器实例
cache_monitor = CacheMonitor()