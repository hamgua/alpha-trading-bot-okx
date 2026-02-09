"""
Monitoring Dashboard - 监控仪表盘
"""

import json
import os
from typing import Dict, Any, List
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class MetricPoint:
    timestamp: str
    value: float
    label: str


class MonitoringDashboard:
    """监控仪表盘"""

    def __init__(self, data_dir: str = "data/monitoring"):
        self.data_dir = data_dir
        self.metrics: Dict[str, List[MetricPoint]] = {}
        self._ensure_data_dir()

    def _ensure_data_dir(self):
        os.makedirs(self.data_dir, exist_ok=True)

    def record_metric(self, label: str, value: float):
        now = datetime.now().isoformat()
        point = MetricPoint(timestamp=now, value=value, label=label)

        if label not in self.metrics:
            self.metrics[label] = []

        self.metrics[label].append(point)

        if len(self.metrics[label]) > 1000:
            self.metrics[label] = self.metrics[label][-1000:]

    def get_metric_summary(self, label: str, hours: int = 24) -> Dict:
        if label not in self.metrics:
            return {"error": "Metric not found"}

        cutoff = datetime.now() - timedelta(hours=hours)
        points = [
            p
            for p in self.metrics[label]
            if datetime.fromisoformat(p.timestamp) > cutoff
        ]

        if not points:
            return {"error": "No data in time range"}

        values = [p.value for p in points]

        return {
            "label": label,
            "count": len(values),
            "avg": sum(values) / len(values),
            "min": min(values),
            "max": max(values),
            "latest": values[-1],
            "time_range": f"{hours}h",
        }

    def get_dashboard_summary(self) -> Dict:
        summary = {"timestamp": datetime.now().isoformat(), "metrics": {}}

        for label in self.metrics:
            if label.startswith("signal_") or label.startswith("weight_"):
                summary["metrics"][label] = self.get_metric_summary(label)

        return summary

    def export_dashboard(self) -> str:
        data = {
            "export_time": datetime.now().isoformat(),
            "metrics": {
                label: [{"timestamp": p.timestamp, "value": p.value} for p in points]
                for label, points in self.metrics.items()
            },
        }
        return json.dumps(data, indent=2)

    def save(self):
        filepath = os.path.join(self.data_dir, "dashboard_snapshot.json")
        with open(filepath, "w") as f:
            f.write(self.export_dashboard())
        logger.info(f"Dashboard saved: {filepath}")


class AlertManager:
    """告警管理器"""

    def __init__(self):
        self.alerts: List[Dict] = []
        self.thresholds = {
            "win_rate_drop": 0.3,
            "loss_streak": 3,
            "api_failure_rate": 0.1,
        }

    def check_alerts(
        self, win_rate: float, loss_streak: int, api_failure_rate: float
    ) -> List[str]:
        alerts = []

        if win_rate < self.thresholds["win_rate_drop"]:
            alerts.append(f"⚠️ 胜率下降至 {win_rate:.1%}")

        if loss_streak >= self.thresholds["loss_streak"]:
            alerts.append(f"🚨 连续亏损 {loss_streak} 次")

        if api_failure_rate > self.thresholds["api_failure_rate"]:
            alerts.append(f"❌ API 失败率过高: {api_failure_rate:.1%}")

        self.alerts.extend(
            [{"time": datetime.now().isoformat(), "alert": a} for a in alerts]
        )

        return alerts


def get_dashboard_status() -> Dict:
    dashboard = MonitoringDashboard()
    return dashboard.get_dashboard_summary()
