"""
健康检查模块 - 监控系统健康状况
"""

import asyncio
import logging
from ..utils.price_calculator import PriceCalculator
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class HealthCheck:
    """健康检查类"""

    def __init__(self):
        self.checks: Dict[str, Any] = {}
        self.alerts: List[Dict[str, Any]] = []
        self.last_check_time: Optional[datetime] = None

    async def check_liquidity_health(
        self, market_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """检查市场流动性健康状况"""
        try:
            volume = market_data.get("volume", 0)
            atr = market_data.get("atr", 0)
            orderbook = market_data.get("orderbook", {})
            price = market_data.get("price", 0)

            # 计算健康分数 (0-100)
            health_score = 100
            issues = []

            # 检查成交量
            if volume == 0:
                health_score -= 40
                issues.append("成交量为0")
            elif volume < 0.1:
                health_score -= 20
                issues.append("成交量过低")

            # 检查ATR
            atr_info = {}
            if atr is not None and atr > 0:
                # 计算ATR相关指标
                # 使用统一的ATR百分比计算器
                atr_percentage = PriceCalculator.calculate_atr_percentage(atr, price)
                    atr_info = {
                        "atr_value": atr,
                        "atr_percentage": atr_percentage,
                        "price": price,
                    }

                    # 根据不同的ATR百分比进行评估 - 针对BTC等加密货币调整阈值
                    if atr_percentage < 0.1:  # 小于0.1%认为过低（BTC在平静期常见）
                        health_score -= 25
                        issues.append(f"ATR过低({atr_percentage:.2f}% < 0.1%)")
                    elif atr_percentage < 0.2:  # 小于0.2%认为偏低
                        health_score -= 15
                        issues.append(f"ATR偏低({atr_percentage:.2f}% < 0.2%)")
                    elif atr_percentage > 2.0:  # 大于2%认为波动过大
                        health_score -= 10
                        issues.append(f"ATR过高({atr_percentage:.2f}% > 2.0%)")

                    # 添加详细ATR信息
                    if atr_percentage < 0.1:
                        atr_info["assessment"] = "极低"
                    elif atr_percentage < 0.2:
                        atr_info["assessment"] = "偏低"
                    elif atr_percentage > 2.0:
                        atr_info["assessment"] = "过高"
                    else:
                        atr_info["assessment"] = "正常"
                else:
                    health_score -= 20
                    issues.append("无法计算ATR百分比(价格无效)")
            else:
                health_score -= 25
                issues.append("ATR数据缺失或无效")

            # 检查买卖价差
            if orderbook and "bids" in orderbook and "asks" in orderbook:
                bids = orderbook["bids"]
                asks = orderbook["asks"]
                if bids and asks:
                    best_bid = float(bids[0][0])
                    best_ask = float(asks[0][0])
                    spread = (best_ask - best_bid) / best_bid
                    if spread > 0.01:
                        health_score -= 20
                        issues.append(f"买卖价差过大({spread:.2%})")

            return {
                "status": "healthy"
                if health_score >= 70
                else "warning"
                if health_score >= 40
                else "critical",
                "score": health_score,
                "issues": issues,
                "timestamp": datetime.now(),
                "atr_info": atr_info,  # 添加详细的ATR信息
            }

        except Exception as e:
            logger.error(f"流动性健康检查失败: {e}")
            return {
                "status": "error",
                "score": 0,
                "issues": [f"检查异常: {e}"],
                "timestamp": datetime.now(),
            }

    async def check_system_performance(self, execution_time: float) -> Dict[str, Any]:
        """检查系统性能健康状况"""
        try:
            # 执行时间阈值
            if execution_time > 30:
                status = "critical"
                issues = [f"执行时间过长({execution_time:.2f}s > 30s)"]
            elif execution_time > 15:
                status = "warning"
                issues = [f"执行时间较长({execution_time:.2f}s > 15s)"]
            else:
                status = "healthy"
                issues = []

            return {
                "status": status,
                "execution_time": execution_time,
                "issues": issues,
                "timestamp": datetime.now(),
            }

        except Exception as e:
            logger.error(f"性能健康检查失败: {e}")
            return {
                "status": "error",
                "execution_time": execution_time,
                "issues": [f"检查异常: {e}"],
                "timestamp": datetime.now(),
            }

    async def check_api_health(
        self, api_response_time: float, api_errors: int = 0
    ) -> Dict[str, Any]:
        """检查API健康状况"""
        try:
            # 响应时间阈值
            if api_response_time > 10:
                status = "critical"
                issues = [f"API响应过慢({api_response_time:.2f}s > 10s)"]
            elif api_response_time > 5:
                status = "warning"
                issues = [f"API响应较慢({api_response_time:.2f}s > 5s)"]
            else:
                status = "healthy"
                issues = []

            # 错误计数
            if api_errors > 5:
                status = "critical"
                issues.append(f"API错误过多({api_errors} > 5)")
            elif api_errors > 2:
                status = "warning"
                issues.append(f"API错误较多({api_errors} > 2)")

            return {
                "status": status,
                "response_time": api_response_time,
                "error_count": api_errors,
                "issues": issues,
                "timestamp": datetime.now(),
            }

        except Exception as e:
            logger.error(f"API健康检查失败: {e}")
            return {
                "status": "error",
                "response_time": api_response_time,
                "error_count": api_errors,
                "issues": [f"检查异常: {e}"],
                "timestamp": datetime.now(),
            }

    def add_alert(
        self, alert_type: str, message: str, severity: str = "warning"
    ) -> None:
        """添加告警"""
        alert = {
            "type": alert_type,
            "message": message,
            "severity": severity,
            "timestamp": datetime.now(),
        }
        self.alerts.append(alert)

        # 保持最近100条告警
        if len(self.alerts) > 100:
            self.alerts = self.alerts[-100:]

    def get_recent_alerts(self, hours: int = 24) -> List[Dict[str, Any]]:
        """获取最近告警"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        return [alert for alert in self.alerts if alert["timestamp"] > cutoff_time]

    async def perform_health_check(
        self,
        market_data: Dict[str, Any],
        execution_time: float,
        api_response_time: float,
        api_errors: int = 0,
    ) -> Dict[str, Any]:
        """执行完整健康检查"""
        self.last_check_time = datetime.now()

        # 并行执行所有检查
        liquidity_health, performance_health, api_health = await asyncio.gather(
            self.check_liquidity_health(market_data),
            self.check_system_performance(execution_time),
            self.check_api_health(api_response_time, api_errors),
        )

        # 综合评估
        all_checks = [liquidity_health, performance_health, api_health]
        critical_count = sum(1 for check in all_checks if check["status"] == "critical")
        warning_count = sum(1 for check in all_checks if check["status"] == "warning")

        if critical_count > 0:
            overall_status = "critical"
        elif warning_count > 0:
            overall_status = "warning"
        else:
            overall_status = "healthy"

        # 生成综合报告
        report = {
            "overall_status": overall_status,
            "liquidity": liquidity_health,
            "performance": performance_health,
            "api": api_health,
            "critical_count": critical_count,
            "warning_count": warning_count,
            "timestamp": self.last_check_time,
        }

        # 添加告警
        if overall_status != "healthy":
            issues = []
            for check_name, check_data in [
                ("流动性", liquidity_health),
                ("性能", performance_health),
                ("API", api_health),
            ]:
                if check_data["status"] != "healthy":
                    issues.extend(check_data.get("issues", []))

            if issues:
                self.add_alert(
                    "health_check",
                    f"系统健康检查异常: {', '.join(issues)}",
                    overall_status,
                )

        return report

    def is_healthy(self) -> bool:
        """判断系统是否健康"""
        return (
            self.last_check_time is not None
            and (datetime.now() - self.last_check_time).total_seconds() < 300
        )  # 5分钟内的检查才有效


# 全局健康检查实例
_health_check = HealthCheck()


async def get_health_check() -> HealthCheck:
    """获取健康检查实例"""
    return _health_check
