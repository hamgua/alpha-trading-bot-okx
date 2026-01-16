"""
保守交易执行器 - 渐进式实时化第三阶段
实现快速信号的小规模交易执行，严格控制风险
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class TradingMode(Enum):
    DISABLED = "disabled"
    RECORD_ONLY = "record_only"
    CONSERVATIVE = "conservative"
    NORMAL = "normal"


@dataclass
class TradeDecision:
    signal_type: str
    confidence: float
    reason: str
    position_size: float
    stop_loss: float
    take_profit: float
    risk_level: str
    timestamp: datetime


@dataclass
class TradingStats:
    total_signals: int
    executed_trades: int
    successful_trades: int
    failed_trades: int
    total_profit: float
    avg_confidence: float
    last_trade_time: Optional[datetime]


class ConservativeTraderConfig:
    def __init__(
        self,
        trading_mode: str = "record_only",
        min_confidence_to_trade: float = 0.85,
        min_confidence_for_buy: float = 0.85,
        min_confidence_for_sell: float = 0.80,
        max_position_size: float = 0.01,
        min_position_size: float = 0.005,
        position_size_ratio: float = 0.3,
        max_trades_per_hour: int = 2,
        min_trade_interval: int = 900,
        max_daily_trades: int = 6,
        stop_loss_percent: float = 0.005,
        take_profit_percent: float = 0.03,
        trailing_stop_percent: float = 0.015,
        max_price_position: float = 0.95,
        min_price_position: float = 0.15,
        circuit_breaker_enabled: bool = True,
        circuit_breaker_threshold: float = 0.02,
        circuit_breaker_cooldown: int = 3600,
        emergency_stop_enabled: bool = True,
        emergency_stop_loss_threshold: float = 0.05,
        max_consecutive_losses: int = 3,
        data_dir: str = "data/price_monitor",
        trade_log_file: str = "conservative_trades.json",
    ):
        self.trading_mode = trading_mode
        self.min_confidence_to_trade = min_confidence_to_trade
        self.min_confidence_for_buy = min_confidence_for_buy
        self.min_confidence_for_sell = min_confidence_for_sell
        self.max_position_size = max_position_size
        self.min_position_size = min_position_size
        self.position_size_ratio = position_size_ratio
        self.max_trades_per_hour = max_trades_per_hour
        self.min_trade_interval = min_trade_interval
        self.max_daily_trades = max_daily_trades
        self.stop_loss_percent = stop_loss_percent
        self.take_profit_percent = take_profit_percent
        self.trailing_stop_percent = trailing_stop_percent
        self.max_price_position = max_price_position
        self.min_price_position = min_price_position
        self.circuit_breaker_enabled = circuit_breaker_enabled
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.circuit_breaker_cooldown = circuit_breaker_cooldown
        self.emergency_stop_enabled = emergency_stop_enabled
        self.emergency_stop_loss_threshold = emergency_stop_loss_threshold
        self.max_consecutive_losses = max_consecutive_losses
        self.data_dir = data_dir
        self.trade_log_file = trade_log_file


class ConservativeTrader:
    def __init__(self, config: Optional[ConservativeTraderConfig] = None):
        self.config = config or ConservativeTraderConfig()
        self.mode = TradingMode(self.config.trading_mode)
        self.trade_history: List[Dict[str, Any]] = []
        self.trade_timestamps: List[datetime] = []
        self.daily_trade_count: int = 0
        self.last_trade_time: Optional[datetime] = None
        self.consecutive_losses: int = 0
        self.total_profit: float = 0.0
        self.circuit_breaker_triggered: bool = False
        self.circuit_breaker_end_time: Optional[datetime] = None
        self.emergency_stop_triggered: bool = False
        self._last_daily_reset: datetime = datetime.now()

    def set_mode(self, mode: str):
        try:
            self.mode = TradingMode(mode)
            self.config.trading_mode = mode
            logger.info(f"交易模式已设置为: {mode}")
        except ValueError:
            logger.error(f"无效的交易模式: {mode}")

    def _check_market_conditions(
        self, signal_type: str, price_position: float, market_data: Dict[str, Any]
    ) -> tuple:
        if self.mode == TradingMode.DISABLED:
            return False, "交易已禁用"
        if self.mode == TradingMode.RECORD_ONLY:
            return False, "仅记录模式，不执行交易"
        if self.circuit_breaker_triggered:
            remaining = (self.circuit_breaker_end_time - datetime.now()).total_seconds()
            if remaining > 0:
                return False, f"熔断中，剩余{int(remaining)}秒"
            self.circuit_breaker_triggered = False
            logger.info("熔断已解除")
        if self.emergency_stop_triggered:
            return False, "紧急停止已触发"
        if signal_type == "BUY":
            if price_position > self.config.max_price_position:
                return False, f"价格位置{price_position:.1%}超过上限"
            if price_position < self.config.min_price_position:
                return False, f"价格位置{price_position:.1%}低于下限"
        if not self._check_trade_frequency():
            return False, "交易频率超过限制"
        return True, "市场条件满足"

    def _check_trade_frequency(self) -> bool:
        now = datetime.now()
        if now.date() > self._last_daily_reset.date():
            self.daily_trade_count = 0
            self._last_daily_reset = now
        if self.daily_trade_count >= self.config.max_daily_trades:
            return False
        hour_ago = now - timedelta(hours=1)
        recent_trades = sum(1 for t in self.trade_timestamps if t > hour_ago)
        if recent_trades >= self.config.max_trades_per_hour:
            return False
        if self.last_trade_time:
            elapsed = (now - self.last_trade_time).total_seconds()
            if elapsed < self.config.min_trade_interval:
                return False
        return True

    def calculate_position_size(
        self, confidence: float, account_balance: float, current_price: float
    ) -> float:
        size_ratio = min(confidence * self.config.position_size_ratio, 1.0)
        base_position = account_balance * self.config.max_position_size
        adjusted_position = base_position * size_ratio
        position = max(self.config.min_position_size, adjusted_position)
        position = min(self.config.max_position_size, position)
        return position

    def calculate_stop_loss(self, signal_type: str, entry_price: float) -> float:
        if signal_type == "BUY":
            return entry_price * (1 - self.config.stop_loss_percent)
        return entry_price * (1 + self.config.stop_loss_percent)

    def calculate_take_profit(self, signal_type: str, entry_price: float) -> float:
        if signal_type == "BUY":
            return entry_price * (1 + self.config.take_profit_percent)
        return entry_price * (1 - self.config.take_profit_percent)

    def evaluate_signal(
        self,
        signal_type: str,
        confidence: float,
        price_position: float,
        current_price: float,
        market_data: Dict[str, Any],
        account_balance: float = 10000.0,
    ) -> TradeDecision:
        can_trade, reason = self._check_market_conditions(
            signal_type, price_position, market_data
        )
        if not can_trade:
            return TradeDecision(
                signal_type="HOLD",
                confidence=confidence,
                reason=reason,
                position_size=0,
                stop_loss=0,
                take_profit=0,
                risk_level="N/A",
                timestamp=datetime.now(),
            )
        min_conf = (
            self.config.min_confidence_for_buy
            if signal_type == "BUY"
            else self.config.min_confidence_for_sell
        )
        if confidence < min_conf:
            return TradeDecision(
                signal_type="HOLD",
                confidence=confidence,
                reason=f"置信度{confidence:.2%}低于{min_conf:.0%}阈值",
                position_size=0,
                stop_loss=0,
                take_profit=0,
                risk_level="N/A",
                timestamp=datetime.now(),
            )
        position_size = self.calculate_position_size(
            confidence, account_balance, current_price
        )
        stop_loss = self.calculate_stop_loss(signal_type, current_price)
        take_profit = self.calculate_take_profit(signal_type, current_price)
        risk_level = self._evaluate_risk_level(confidence, price_position, market_data)
        return TradeDecision(
            signal_type=signal_type,
            confidence=confidence,
            reason=f"信号评估通过 - {reason}",
            position_size=position_size,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_level=risk_level,
            timestamp=datetime.now(),
        )

    def _evaluate_risk_level(
        self, confidence: float, price_position: float, market_data: Dict[str, Any]
    ) -> str:
        risk_score = 0
        if confidence >= 0.90:
            risk_score += 0
        elif confidence >= 0.85:
            risk_score += 1
        else:
            risk_score += 2
        if price_position < 0.3:
            risk_score += 0
        elif price_position < 0.5:
            risk_score += 1
        elif price_position < 0.7:
            risk_score += 2
        else:
            risk_score += 3
        atr_pct = market_data.get("atr_percentage", 0)
        if atr_pct < 0.5:
            risk_score += 0
        elif atr_pct < 1.0:
            risk_score += 1
        else:
            risk_score += 2
        if risk_score <= 2:
            return "low"
        elif risk_score <= 4:
            return "medium"
        return "high"

    def record_trade_result(
        self, trade_decision: TradeDecision, executed: bool, profit: float = 0.0
    ):
        now = datetime.now()
        trade_record = {
            "timestamp": now.isoformat(),
            "signal_type": trade_decision.signal_type,
            "confidence": trade_decision.confidence,
            "position_size": trade_decision.position_size,
            "executed": executed,
            "profit": profit if executed else 0,
            "risk_level": trade_decision.risk_level,
            "mode": self.mode.value,
        }
        self.trade_history.append(trade_record)
        if executed:
            self.trade_timestamps.append(now)
            self.daily_trade_count += 1
            self.last_trade_time = now
            if profit > 0:
                self.consecutive_losses = 0
                self.total_profit += profit
            else:
                self.consecutive_losses += 1
            if (
                self.config.emergency_stop_enabled
                and self.consecutive_losses >= self.config.max_consecutive_losses
            ):
                self._trigger_emergency_stop()
            if self.config.circuit_breaker_enabled:
                if profit < -self.config.circuit_breaker_threshold * 1000:
                    self._trigger_circuit_breaker()

    def _trigger_emergency_stop(self):
        self.emergency_stop_triggered = True
        logger.critical("紧急停止触发！连续亏损次数达到上限")

    def _trigger_circuit_breaker(self):
        self.circuit_breaker_triggered = True
        self.circuit_breaker_end_time = datetime.now() + timedelta(
            seconds=self.config.circuit_breaker_cooldown
        )
        logger.warning("熔断触发！暂停交易")

    def reset_circuit_breaker(self):
        self.circuit_breaker_triggered = False
        self.circuit_breaker_end_time = None

    def reset_emergency_stop(self):
        self.emergency_stop_triggered = False
        self.consecutive_losses = 0

    def get_status_report(self) -> Dict[str, Any]:
        stats = self.get_trading_stats()
        return {
            "mode": self.mode.value,
            "trading_enabled": self.mode != TradingMode.DISABLED,
            "circuit_breaker": {
                "triggered": self.circuit_breaker_triggered,
                "remaining_seconds": (
                    (self.circuit_breaker_end_time - datetime.now()).total_seconds()
                    if self.circuit_breaker_end_time and self.circuit_breaker_triggered
                    else 0
                ),
            },
            "emergency_stop": {
                "triggered": self.emergency_stop_triggered,
                "consecutive_losses": self.consecutive_losses,
            },
            "performance": {
                "total_signals": stats.total_signals,
                "executed_trades": stats.executed_trades,
                "success_rate": (
                    stats.successful_trades / stats.executed_trades
                    if stats.executed_trades > 0
                    else 0
                ),
                "total_profit": stats.total_profit,
            },
        }

    def get_trading_stats(self) -> TradingStats:
        now = datetime.now()
        executed_trades = [t for t in self.trade_history if t.get("executed", False)]
        successful_trades = [t for t in executed_trades if t.get("profit", 0) > 0]
        failed_trades = [t for t in executed_trades if t.get("profit", 0) <= 0]
        avg_confidence = (
            sum(t["confidence"] for t in executed_trades) / len(executed_trades)
            if executed_trades
            else 0.0
        )
        return TradingStats(
            total_signals=len(self.trade_history),
            executed_trades=len(executed_trades),
            successful_trades=len(successful_trades),
            failed_trades=len(failed_trades),
            total_profit=self.total_profit,
            avg_confidence=avg_confidence,
            last_trade_time=self.last_trade_time,
        )
