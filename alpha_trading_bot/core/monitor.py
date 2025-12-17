"""
监控模块 - 实时监控系统状态和性能指标
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from collections import deque

# 尝试导入psutil，如果失败则使用降级方案
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    logging.warning("psutil模块未安装，系统监控功能将受限")

logger = logging.getLogger(__name__)

class SystemMonitor:
    """系统监控器"""

    def __init__(self, max_history: int = 100):
        self.max_history = max_history
        self.metrics_history: Dict[str, deque] = {
            'cpu_usage': deque(maxlen=max_history),
            'memory_usage': deque(maxlen=max_history),
            'execution_time': deque(maxlen=max_history),
            'api_latency': deque(maxlen=max_history),
            'trade_count': deque(maxlen=max_history),
            'error_count': deque(maxlen=max_history),
            'timestamp': deque(maxlen=max_history)
        }
        self.start_time = datetime.now()
        self.total_trades = 0
        self.total_errors = 0
        self.last_metric_time = datetime.now()

    async def collect_system_metrics(self) -> Dict[str, Any]:
        """收集系统指标 - 优化版"""
        try:
            metrics = {
                'timestamp': datetime.now()
            }

            # 添加性能计数器
            import time
            start_time = time.time()

            if HAS_PSUTIL:
                try:
                    # 使用更快的采样间隔
                    cpu_percent = psutil.cpu_percent(interval=0.1)

                    # 内存使用率
                    memory = psutil.virtual_memory()
                    memory_percent = memory.percent

                    # 磁盘使用率（缓存结果，避免频繁调用）
                    if not hasattr(self, '_last_disk_check') or \
                       (datetime.now() - self._last_disk_check).total_seconds() > 60:
                        disk = psutil.disk_usage('/')
                        self._last_disk_percent = (disk.used / disk.total) * 100
                        self._last_disk_check = datetime.now()
                    disk_percent = self._last_disk_percent

                    # 网络连接数（降低权限要求）
                    try:
                        # 只获取TCP连接，减少权限要求
                        connections = len([conn for conn in psutil.net_connections(kind='tcp')
                                         if conn.status == 'ESTABLISHED'])
                    except:
                        connections = 0

                    metrics.update({
                        'cpu_usage': cpu_percent,
                        'memory_usage': memory_percent,
                        'disk_usage': disk_percent,
                        'network_connections': connections
                    })
                except Exception as psutil_err:
                    logger.warning(f"psutil获取系统指标失败: {psutil_err}，使用降级方案")
                    # 禁用psutil，避免重复尝试
                    import sys
                    sys.modules[__name__].HAS_PSUTIL = False
                    # 降级到无psutil方案
            else:
                # 降级方案：使用虚拟数据
                metrics.update({
                    'cpu_usage': 0.0,
                    'memory_usage': 0.0,
                    'disk_usage': 0.0,
                    'network_connections': 0
                })

            # 计算收集耗时
            collection_time = time.time() - start_time
            metrics['collection_time'] = collection_time

            # 如果收集时间太长，发出警告
            if collection_time > 0.5:
                logger.warning(f"系统指标收集耗时过长: {collection_time:.3f}s")

            # 保存到历史记录（限制历史数据大小）
            for key, value in metrics.items():
                if key in self.metrics_history:
                    self.metrics_history[key].append(value)
                    # 限制历史数据大小，避免内存泄漏
                    if len(self.metrics_history[key]) > self.max_history:
                        self.metrics_history[key].popleft()

            return metrics

        except Exception as e:
            logger.error(f"收集系统指标失败: {e}")
            return {}

    def record_execution_time(self, execution_time: float) -> None:
        """记录执行时间"""
        self.metrics_history['execution_time'].append(execution_time)
        self.metrics_history['timestamp'].append(datetime.now())

    async def get_system_info(self) -> Dict[str, Any]:
        """获取系统信息"""
        try:
            metrics = await self.collect_system_metrics()

            # 返回格式化的系统信息
            system_info = {
                'cpu_percent': metrics.get('cpu_usage', 0),
                'memory_percent': metrics.get('memory_usage', 0),
                'disk_percent': metrics.get('disk_usage', 0),
                'network_connections': metrics.get('network_connections', 0),
                'has_psutil': HAS_PSUTIL
            }

            return system_info

        except Exception as e:
            logger.error(f"获取系统信息失败: {e}")
            # 返回降级信息
            return {
                'cpu_percent': 0,
                'memory_percent': 0,
                'disk_percent': 0,
                'network_connections': 0,
                'has_psutil': HAS_PSUTIL,
                'error': str(e)
            }

    def record_api_latency(self, latency: float) -> None:
        """记录API延迟"""
        self.metrics_history['api_latency'].append(latency)

    def record_trade(self) -> None:
        """记录交易"""
        self.total_trades += 1
        self.metrics_history['trade_count'].append(self.total_trades)

    def record_error(self) -> None:
        """记录错误"""
        self.total_errors += 1
        self.metrics_history['error_count'].append(self.total_errors)

    def get_average_metrics(self, hours: int = 1) -> Dict[str, float]:
        """获取平均指标"""
        try:
            cutoff_time = datetime.now() - timedelta(hours=hours)
            recent_data = []

            # 获取指定时间范围内的数据
            for i, timestamp in enumerate(self.metrics_history['timestamp']):
                if timestamp >= cutoff_time:
                    recent_data.append(i)

            if not recent_data:
                return {}

            averages = {}
            for metric_name in ['cpu_usage', 'memory_usage', 'execution_time', 'api_latency']:
                if metric_name in self.metrics_history:
                    values = [self.metrics_history[metric_name][i] for i in recent_data
                             if i < len(self.metrics_history[metric_name])]
                    if values:
                        averages[metric_name] = sum(values) / len(values)

            return averages

        except Exception as e:
            logger.error(f"获取平均指标失败: {e}")
            return {}

    def check_performance_alerts(self) -> List[Dict[str, Any]]:
        """检查性能告警"""
        alerts = []

        try:
            # 获取最近5次执行时间的平均值
            recent_exec_times = list(self.metrics_history['execution_time'])[-5:]
            if len(recent_exec_times) >= 3:
                avg_exec_time = sum(recent_exec_times) / len(recent_exec_times)
                if avg_exec_time > 20:
                    alerts.append({
                        'type': 'performance',
                        'severity': 'warning' if avg_exec_time < 30 else 'critical',
                        'message': f"平均执行时间过长: {avg_exec_time:.2f}s",
                        'timestamp': datetime.now()
                    })

            # 检查CPU使用率（仅在psutil可用时）
            if HAS_PSUTIL:
                recent_cpu = list(self.metrics_history['cpu_usage'])[-5:]
                if len(recent_cpu) >= 3:
                    avg_cpu = sum(recent_cpu) / len(recent_cpu)
                    if avg_cpu > 80:
                        alerts.append({
                            'type': 'system',
                            'severity': 'warning' if avg_cpu < 90 else 'critical',
                            'message': f"平均CPU使用率过高: {avg_cpu:.1f}%",
                            'timestamp': datetime.now()
                        })

                # 检查内存使用率
                recent_memory = list(self.metrics_history['memory_usage'])[-5:]
                if len(recent_memory) >= 3:
                    avg_memory = sum(recent_memory) / len(recent_memory)
                    if avg_memory > 85:
                        alerts.append({
                            'type': 'system',
                            'severity': 'warning' if avg_memory < 95 else 'critical',
                            'message': f"平均内存使用率过高: {avg_memory:.1f}%",
                            'timestamp': datetime.now()
                        })
            else:
                # psutil不可用时，添加提示信息
                if len(list(self.metrics_history['execution_time'])) >= 5:
                    alerts.append({
                        'type': 'system',
                        'severity': 'info',
                        'message': "系统监控功能受限（psutil未安装），建议安装psutil以获得完整监控功能",
                        'timestamp': datetime.now()
                    })

            # 检查错误率
            if self.total_errors > 10:
                error_rate = self.total_errors / max(self.total_trades, 1)
                if error_rate > 0.1:  # 错误率超过10%
                    alerts.append({
                        'type': 'error_rate',
                        'severity': 'warning' if error_rate < 0.2 else 'critical',
                        'message': f"错误率过高: {error_rate:.1%} ({self.total_errors}/{self.total_trades})",
                        'timestamp': datetime.now()
                    })

        except Exception as e:
            logger.error(f"检查性能告警失败: {e}")

        return alerts

    def get_system_summary(self) -> Dict[str, Any]:
        """获取系统摘要"""
        try:
            runtime = datetime.now() - self.start_time
            avg_metrics = self.get_average_metrics(hours=1)

            return {
                'runtime_hours': runtime.total_seconds() / 3600,
                'total_trades': self.total_trades,
                'total_errors': self.total_errors,
                'error_rate': self.total_errors / max(self.total_trades, 1),
                'average_metrics': avg_metrics,
                'last_update': datetime.now()
            }

        except Exception as e:
            logger.error(f"获取系统摘要失败: {e}")
            return {}

# 全局监控实例
_monitor = SystemMonitor()

def get_system_monitor() -> SystemMonitor:
    """获取系统监控器实例"""
    return _monitor

async def collect_metrics_periodically(interval: int = 60):
    """定期收集指标"""
    monitor = get_system_monitor()
    while True:
        try:
            await monitor.collect_system_metrics()
            await asyncio.sleep(interval)
        except Exception as e:
            logger.error(f"定期收集指标失败: {e}")
            await asyncio.sleep(interval)  # 出错后等待相同间隔再重试

async def monitor_performance():
    """监控性能并生成告警"""
    monitor = get_system_monitor()
    while True:
        try:
            # 检查性能告警
            alerts = monitor.check_performance_alerts()
            for alert in alerts:
                logger.warning(f"🚨 性能告警: {alert['message']}")

            await asyncio.sleep(300)  # 每5分钟检查一次
        except Exception as e:
            logger.error(f"性能监控失败: {e}")
            await asyncio.sleep(300)  # 出错后等待5分钟再重试