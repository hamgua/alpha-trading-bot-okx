"""
信号监控指标模块
用于跟踪信号通过率、拦截原因分布等关键指标
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from collections import Counter
import logging

logger = logging.getLogger(__name__)


@dataclass
class SignalMetrics:
    """信号监控指标"""

    # 基础计数
    total_signals: int = 0
    buy_signals: int = 0
    sell_signals: int = 0
    hold_signals: int = 0

    # 执行相关
    executed_signals: int = 0
    blocked_signals: int = 0

    # 拦截原因分类
    block_reasons: Dict[str, int] = field(default_factory=dict)

    # 时间戳
    last_update: datetime = field(default_factory=datetime.now)

    # 锁（线程安全）
    _lock: threading.Lock = field(default_factory=threading.Lock)


class SignalMetricsTracker:
    """
    信号指标跟踪器

    功能:
    - 记录所有信号及其状态
    - 统计拦截原因分布
    - 计算通过率等关键指标
    - 生成报告
    """

    def __init__(self):
        self._metrics = SignalMetrics()
        self._signal_history: List[Dict] = []  # 最近100条信号历史
        self._max_history = 100
        self._lock = threading.Lock()

    def record_signal(
        self,
        signal_type: str,
        should_trade: bool,
        trade_score: float,
        confidence: float,
        block_reason: Optional[str] = None,
        symbol: str = "BTC/USDT:USDT",
    ) -> None:
        """
        记录信号

        Args:
            signal_type: 信号类型 (buy/sell/hold)
            should_trade: 是否应该交易
            trade_score: 交易分数
            confidence: 置信度
            block_reason: 拦截原因（如果有）
            symbol: 交易对
        """
        with self._lock:
            self._metrics.total_signals += 1
            self._metrics.last_update = datetime.now()

            # 记录信号类型
            if signal_type == "buy":
                self._metrics.buy_signals += 1
            elif signal_type == "sell":
                self._metrics.sell_signals += 1
            else:
                self._metrics.hold_signals += 1

            # 记录执行状态
            if should_trade:
                self._metrics.executed_signals += 1
            else:
                self._metrics.blocked_signals += 1
                if block_reason:
                    self._metrics.block_reasons[block_reason] = (
                        self._metrics.block_reasons.get(block_reason, 0) + 1
                    )

            # 记录历史
            signal_record = {
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "signal_type": signal_type,
                "should_trade": should_trade,
                "trade_score": trade_score,
                "confidence": confidence,
                "block_reason": block_reason,
            }
            self._signal_history.append(signal_record)

            # 保持历史在限制内
            if len(self._signal_history) > self._max_history:
                self._signal_history = self._signal_history[-self._max_history :]

    def record_buy_blocked(
        self,
        reason: str,
        bb_position: float,
        price_position_24h: float,
        price_position_7d: float,
        trade_score: float,
        symbol: str = "BTC/USDT:USDT",
    ) -> None:
        """
        记录BUY信号被拦截

        Args:
            reason: 拦截原因
            bb_position: BB位置
            price_position_24h: 24h价格位置
            price_position_7d: 7d价格位置
            trade_score: 交易分数
            symbol: 交易对
        """
        block_reason = f"BUY拦截: {reason} (BB={bb_position:.1f}%, 24h={price_position_24h:.1f}%, 7d={price_position_7d:.1f}%, score={trade_score:.2f})"
        self.record_signal(
            signal_type="buy",
            should_trade=False,
            trade_score=trade_score,
            confidence=0.0,
            block_reason=block_reason,
            symbol=symbol,
        )

    def get_summary(self) -> Dict[str, any]:
        """获取指标摘要"""
        with self._lock:
            total = self._metrics.total_signals
            executed = self._metrics.executed_signals
            blocked = self._metrics.blocked_signals

            return {
                "total_signals": total,
                "buy_signals": self._metrics.buy_signals,
                "sell_signals": self._metrics.sell_signals,
                "hold_signals": self._metrics.hold_signals,
                "executed_signals": executed,
                "blocked_signals": blocked,
                "execution_rate": executed / total if total > 0 else 0,
                "block_rate": blocked / total if total > 0 else 0,
                "buy_block_rate": (
                    self._metrics.block_reasons.get("BUY", 0)
                    / self._metrics.buy_signals
                    if self._metrics.buy_signals > 0
                    else 0
                ),
                "top_block_reasons": sorted(
                    self._metrics.block_reasons.items(),
                    key=lambda x: x[1],
                    reverse=True,
                )[:5],
                "last_update": self._metrics.last_update.isoformat(),
            }

    def get_block_reasons_report(self) -> str:
        """生成拦截原因报告"""
        with self._lock:
            if not self._metrics.block_reasons:
                return "暂无拦截记录"

            report_lines = ["=" * 60, "📊 信号拦截原因分析报告", "=" * 60]

            total_blocked = sum(self._metrics.block_reasons.values())
            for reason, count in sorted(
                self._metrics.block_reasons.items(), key=lambda x: x[1], reverse=True
            ):
                percentage = count / total_blocked * 100 if total_blocked > 0 else 0
                report_lines.append(f"[{count:4d}次 ({percentage:5.1f}%)] {reason}")

            report_lines.append("=" * 60)
            report_lines.append(f"总计拦截: {total_blocked}次")
            report_lines.append(f"总信号数: {self._metrics.total_signals}")
            report_lines.append(
                f"总拦截率: {total_blocked / self._metrics.total_signals * 100:.1f}%"
                if self._metrics.total_signals > 0
                else "N/A"
            )

            return "\n".join(report_lines)

    def get_execution_report(self) -> str:
        """生成执行情况报告"""
        with self._lock:
            total = self._metrics.total_signals
            executed = self._metrics.executed_signals
            blocked = self._metrics.blocked_signals

            report_lines = ["=" * 60, "📈 信号执行情况报告", "=" * 60]
            report_lines.append(f"总信号数: {total}")
            report_lines.append(f"  - BUY信号: {self._metrics.buy_signals}")
            report_lines.append(f"  - SELL信号: {self._metrics.sell_signals}")
            report_lines.append(f"  - HOLD信号: {self._metrics.hold_signals}")
            report_lines.append(f"执行信号: {executed}")
            report_lines.append(f"拦截信号: {blocked}")
            report_lines.append(
                f"执行率: {executed / total * 100:.1f}%" if total > 0 else "N/A"
            )
            report_lines.append(
                f"拦截率: {blocked / total * 100:.1f}%" if total > 0 else "N/A"
            )
            report_lines.append("=" * 60)

            return "\n".join(report_lines)

    def reset(self) -> None:
        """重置所有指标"""
        with self._lock:
            self._metrics = SignalMetrics()
            self._signal_history = []

    def get_recent_signals(self, count: int = 10) -> List[Dict]:
        """获取最近的信号历史"""
        with self._lock:
            return self._signal_history[-count:]


# 全局单例
signal_metrics_tracker = SignalMetricsTracker()


def get_signal_metrics() -> SignalMetricsTracker:
    """获取信号指标跟踪器"""
    return signal_metrics_tracker


def record_alpha_pulse_signal(
    signal_type: str,
    should_trade: bool,
    trade_score: float,
    confidence: float,
    block_reason: Optional[str] = None,
    symbol: str = "BTC/USDT:USDT",
) -> None:
    """
    便捷函数：记录AlphaPulse信号

    Args:
        signal_type: 信号类型 (buy/sell/hold)
        should_trade: 是否应该交易
        trade_score: 交易分数
        confidence: 置信度
        block_reason: 拦截原因（如果有）
        symbol: 交易对
    """
    signal_metrics_tracker.record_signal(
        signal_type=signal_type,
        should_trade=should_trade,
        trade_score=trade_score,
        confidence=confidence,
        block_reason=block_reason,
        symbol=symbol,
    )
