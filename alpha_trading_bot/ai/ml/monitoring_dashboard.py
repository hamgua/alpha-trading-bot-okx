"""
Monitoring Dashboard - 监控仪表盘
"""

import json
import os
from typing import Dict, List
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
        try:
            os.chmod(self.data_dir, 0o700)
        except OSError:
            pass

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
        try:
            os.chmod(filepath, 0o600)
        except OSError:
            pass
        logger.info(f"Dashboard saved: {filepath}")


class AlertManager:
    """告警管理器"""

    def __init__(self):
        self.alerts: List[Dict] = []
        self.thresholds = {
            "win_rate_drop": 0.3,
            "loss_streak": 3,
            "api_failure_rate": 0.1,
            # Harness/Gemini 目标阈值
            "gemini_success_rate_min": 0.99,
            "gemini_fallback_rate_max": 0.05,
            "live_guard_false_trigger_max": 0.0,
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

    def check_gemini_slo_alerts(
        self,
        gemini_success_rate: float,
        gemini_fallback_rate: float,
        live_guard_false_trigger_rate: float,
    ) -> List[str]:
        """检查 Gemini/Safety SLO 告警。"""
        alerts: List[str] = []

        if gemini_success_rate < self.thresholds["gemini_success_rate_min"]:
            alerts.append(
                "❌ Gemini 成功率过低: "
                f"{gemini_success_rate:.2%} < "
                f"{self.thresholds['gemini_success_rate_min']:.0%}"
            )

        if gemini_fallback_rate > self.thresholds["gemini_fallback_rate_max"]:
            alerts.append(
                "⚠️ Gemini fallback 率过高: "
                f"{gemini_fallback_rate:.2%} > "
                f"{self.thresholds['gemini_fallback_rate_max']:.0%}"
            )

        if (
            live_guard_false_trigger_rate
            > self.thresholds["live_guard_false_trigger_max"]
        ):
            alerts.append("🚨 实盘闸门误触发率非零，违反生产基线")

        self.alerts.extend(
            [{"time": datetime.now().isoformat(), "alert": a} for a in alerts]
        )

        return alerts


def get_dashboard_status() -> Dict:
    dashboard = MonitoringDashboard()
    return dashboard.get_dashboard_summary()
