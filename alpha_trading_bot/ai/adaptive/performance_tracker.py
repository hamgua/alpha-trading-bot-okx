"""
表现追踪模块

功能：
- 追踪交易表现的各项指标
- 计算胜率、盈亏比、夏普比率等
- 记录连续盈亏情况
- 为参数自适应提供历史表现数据
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
from collections import deque
from enum import Enum
import json
import os

logger = logging.getLogger(__name__)


class TradeOutcome(Enum):
    """交易结果"""

    WIN = "win"
    LOSS = "loss"
    BREAKEVEN = "breakeven"
    PENDING = "pending"


@dataclass
class TradeRecord:
    """单笔交易记录"""

    entry_time: str
    exit_time: Optional[str]
    entry_price: float
    exit_price: Optional[float]
    side: str  # "buy" | "sell"
    pnl: Optional[float]
    pnl_percent: Optional[float]
    outcome: TradeOutcome
    confidence: float  # AI置信度
    signal_type: str  # "buy" | "hold" | "sell"
    market_regime: str  # 当时的市场环境
    used_threshold: float  # 当时使用的融合阈值
    used_stop_loss: float  # 当时使用的止损比例


@dataclass
class PerformanceMetrics:
    """绩效指标"""

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    average_win: float = 0.0
    average_loss: float = 0.0
    profit_factor: float = 0.0
    total_pnl: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    last_outcome: Optional[TradeOutcome] = None


class PerformanceTracker:
    """
    表现追踪器

    记录和分析交易表现，为自适应提供数据支持
    """

    def __init__(
        self,
        max_trades: int = 500,
        data_dir: str = "data_json",
    ):
        """
        初始化追踪器

        Args:
            max_trades: 最大保存交易记录数
            data_dir: 数据保存目录
        """
        self.max_trades = max_trades
        self.data_dir = data_dir

        # 交易记录
        self._trades: deque[TradeRecord] = deque(maxlen=max_trades)

        # 当前持仓
        self._open_position: Optional[TradeRecord] = None

        # 累计指标
        self._cumulative_pnl: list[float] = []
        self._peak_value: float = 10000  # 假设初始资金

        # 确保数据目录存在
        os.makedirs(data_dir, exist_ok=True)

        # 加载历史数据
        self._load_history()

    def record_trade(
        self,
        entry_time: str,
        entry_price: float,
        side: str,
        confidence: float,
        signal_type: str,
        market_regime: str,
        used_threshold: float,
        used_stop_loss: float,
    ) -> TradeRecord:
        """记录开仓"""
        trade = TradeRecord(
            entry_time=entry_time,
            exit_time=None,
            entry_price=entry_price,
            exit_price=None,
            side=side,
            pnl=None,
            pnl_percent=None,
            outcome=TradeOutcome.PENDING,
            confidence=confidence,
            signal_type=signal_type,
            market_regime=market_regime,
            used_threshold=used_threshold,
            used_stop_loss=used_stop_loss,
        )

        self._open_position = trade
        logger.info(
            f"[绩效追踪] 记录开仓: {side} @ {entry_price}, 置信度: {confidence}%"
        )

        return trade

    def close_trade(
        self,
        exit_time: str,
        exit_price: float,
        reason: str = "signal",
    ) -> Optional[TradeRecord]:
        """记录平仓"""
        if not self._open_position:
            logger.warning("[绩效追踪] 无持仓可平")
            return None

        trade = self._open_position
        trade.exit_time = exit_time
        trade.exit_price = exit_price

        # 计算盈亏
        if trade.side == "buy":
            trade.pnl = exit_price - trade.entry_price
            trade.pnl_percent = (exit_price - trade.entry_price) / trade.entry_price
        else:
            trade.pnl = trade.entry_price - exit_price
            trade.pnl_percent = (trade.entry_price - exit_price) / trade.entry_price

        # 判断结果
        if trade.pnl_percent > 0.001:  # > 0.1%
            trade.outcome = TradeOutcome.WIN
        elif trade.pnl_percent < -0.001:  # < -0.1%
            trade.outcome = TradeOutcome.LOSS
        else:
            trade.outcome = TradeOutcome.BREAKEVEN

        # 更新连续盈亏
        self._update_consecutive(trade.outcome)

        # 添加到记录
        self._trades.append(trade)

        logger.info(
            f"[绩效追踪] 记录平仓: {trade.side} @ {exit_price}, "
            f"PnL: {trade.pnl_percent:.2%}, 结果: {trade.outcome.value}"
        )

        # 更新累计曲线
        self._update_cumulative(trade.pnl_percent)

        # 清空当前持仓
        self._open_position = None

        # 保存数据
        self._save_history()

        return trade

    def _update_consecutive(self, outcome: TradeOutcome) -> None:
        """更新连续盈亏计数"""
        # 将在子类中实现

    def _update_cumulative(self, pnl_percent: float) -> None:
        """更新累计盈亏曲线"""
        if self._cumulative_pnl:
            last = self._cumulative_pnl[-1]
        else:
            last = 1.0  # 初始为1 (100%)

        self._cumulative_pnl.append(last * (1 + pnl_percent))

        # 更新最大回撤
        peak = max(self._cumulative_pnl)
        drawdown = (peak - self._cumulative_pnl[-1]) / peak
        self._current_max_drawdown = max(
            self._current_max_drawdown if hasattr(self, "_current_max_drawdown") else 0,
            drawdown,
        )

    def get_performance_metrics(self) -> PerformanceMetrics:
        """计算绩效指标"""
        closed_trades = [t for t in self._trades if t.outcome != TradeOutcome.PENDING]

        if not closed_trades:
            return PerformanceMetrics()

        wins = [t for t in closed_trades if t.outcome == TradeOutcome.WIN]
        losses = [t for t in closed_trades if t.outcome == TradeOutcome.LOSS]

        win_rate = len(wins) / len(closed_trades) if closed_trades else 0

        avg_win = sum(t.pnl_percent for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t.pnl_percent for t in losses) / len(losses) if losses else 0

        # 盈利因子
        gross_profit = sum(t.pnl_percent for t in wins)
        gross_loss = abs(sum(t.pnl_percent for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # 夏普比率 (简化版)
        if len(closed_trades) >= 10:
            returns = [t.pnl_percent for t in closed_trades]
            import statistics

            mean_return = statistics.mean(returns)
            std_return = statistics.stdev(returns) if len(returns) > 1 else 0.001
            sharpe = (mean_return / std_return) * 15 if std_return > 0 else 0  # 年化
        else:
            sharpe = 0

        # 连续盈亏
        consecutive_wins = self._get_consecutive_wins()
        consecutive_losses = self._get_consecutive_losses()

        # 总盈亏
        total_pnl = sum(t.pnl_percent for t in closed_trades)

        return PerformanceMetrics(
            total_trades=len(closed_trades),
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate=win_rate,
            average_win=avg_win,
            average_loss=avg_loss,
            profit_factor=profit_factor,
            total_pnl=total_pnl,
            sharpe_ratio=sharpe,
            max_drawdown=(
                self._current_max_drawdown
                if hasattr(self, "_current_max_drawdown")
                else 0
            ),
            consecutive_wins=consecutive_wins,
            consecutive_losses=consecutive_losses,
            last_outcome=closed_trades[-1].outcome if closed_trades else None,
        )

    def get_recent_performance(self, n_trades: int = 20) -> Dict[str, Any]:
        """获取最近 N 笔交易的表现"""
        recent = list(self._trades)[-n_trades:]
        if not recent:
            return {"message": "无交易记录"}

        wins = sum(1 for t in recent if t.outcome == TradeOutcome.WIN)
        losses = sum(1 for t in recent if t.outcome == TradeOutcome.LOSS)

        return {
            "n_trades": len(recent),
            "wins": wins,
            "losses": losses,
            "win_rate": wins / len(recent) if recent else 0,
            "recent_outcomes": [t.outcome.value for t in recent[-5:]],
            "consecutive_losses": self._get_consecutive_losses(),
            "avg_confidence": sum(t.confidence for t in recent) / len(recent),
            "regime_distribution": self._get_regime_distribution(recent),
        }

    def get_regime_performance(self) -> Dict[str, Dict[str, float]]:
        """获取不同市场环境下的表现"""
        regime_stats: Dict[str, Dict[str, float]] = {}

        for trade in self._trades:
            if trade.outcome == TradeOutcome.PENDING:
                continue

            regime = trade.market_regime
            if regime not in regime_stats:
                regime_stats[regime] = {"trades": 0, "wins": 0, "total_pnl": 0}

            regime_stats[regime]["trades"] += 1
            if trade.outcome == TradeOutcome.WIN:
                regime_stats[regime]["wins"] += 1
            regime_stats[regime]["total_pnl"] += trade.pnl_percent or 0

        # 计算各环境的胜率
        for regime in regime_stats:
            stats = regime_stats[regime]
            stats["win_rate"] = (
                stats["wins"] / stats["trades"] if stats["trades"] > 0 else 0
            )

        return regime_stats

    def _get_consecutive_wins(self) -> int:
        """获取连续盈利次数"""
        count = 0
        for trade in reversed(self._trades):
            if trade.outcome == TradeOutcome.WIN:
                count += 1
            else:
                break
        return count

    def _get_consecutive_losses(self) -> int:
        """获取连续亏损次数"""
        count = 0
        for trade in reversed(self._trades):
            if trade.outcome == TradeOutcome.LOSS:
                count += 1
            else:
                break
        return count

    def _get_regime_distribution(self, trades: List[TradeRecord]) -> Dict[str, int]:
        """获取交易的市场环境分布"""
        distribution: Dict[str, int] = {}
        for trade in trades:
            regime = trade.market_regime
            distribution[regime] = distribution.get(regime, 0) + 1
        return distribution

    def _save_history(self) -> None:
        """保存历史数据"""
        filepath = os.path.join(self.data_dir, "trade_history.json")
        data = {
            "trades": [
                {
                    "entry_time": t.entry_time,
                    "exit_time": t.exit_time,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "side": t.side,
                    "pnl": t.pnl,
                    "pnl_percent": t.pnl_percent,
                    "outcome": t.outcome.value,
                    "confidence": t.confidence,
                    "signal_type": t.signal_type,
                    "market_regime": t.market_regime,
                    "used_threshold": t.used_threshold,
                    "used_stop_loss": t.used_stop_loss,
                }
                for t in self._trades
            ],
            "cumulative_pnl": self._cumulative_pnl,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _load_history(self) -> None:
        """加载历史数据"""
        filepath = os.path.join(self.data_dir, "trade_history.json")
        if not os.path.exists(filepath):
            return

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._trades = deque(maxlen=self.max_trades)
            for t_data in data.get("trades", []):
                trade = TradeRecord(
                    entry_time=t_data["entry_time"],
                    exit_time=t_data.get("exit_time"),
                    entry_price=t_data["entry_price"],
                    exit_price=t_data.get("exit_price"),
                    side=t_data["side"],
                    pnl=t_data.get("pnl"),
                    pnl_percent=t_data.get("pnl_percent"),
                    outcome=TradeOutcome(t_data["outcome"]),
                    confidence=t_data["confidence"],
                    signal_type=t_data["signal_type"],
                    market_regime=t_data["market_regime"],
                    used_threshold=t_data["used_threshold"],
                    used_stop_loss=t_data["used_stop_loss"],
                )
                self._trades.append(trade)

            self._cumulative_pnl = data.get("cumulative_pnl", [])

            logger.info(f"[绩效追踪] 加载历史数据: {len(self._trades)} 笔交易")

        except Exception as e:
            logger.error(f"[绩效追踪] 加载历史数据失败: {e}")

    def reset(self) -> None:
        """重置追踪数据"""
        self._trades.clear()
        self._open_position = None
        self._cumulative_pnl = []
        self._current_max_drawdown = 0
