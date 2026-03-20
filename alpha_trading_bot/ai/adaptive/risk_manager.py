"""
风险控制模块

核心功能：
- 硬止损（不可突破）
- 动态仓位计算
- 规则熔断机制
- 风险边界管理

设计原则：
1. 硬止损：强制执行，无法被覆盖
2. 动态仓位：根据波动率和风险敞口自动调整
3. 熔断机制：极端市场下暂停所有交易
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """风险等级"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RiskConfig:
    """风险配置"""

    # 硬止损配置（强制执行）
    hard_stop_loss_percent: float = 0.05  # 5% 硬止损（绝对底线）
    hard_stop_loss_profit_percent: float = 0.03  # 盈利时硬止损 3%

    # 动态止损配置
    stop_loss_percent: float = 0.005  # 基础止损 0.5%
    stop_loss_profit_percent: float = 0.002  # 盈利时止损 0.2%
    stop_loss_atr_multiplier: float = 2.0  # ATR 倍数

    # 仓位配置
    max_position_percent: float = 0.1  # 最大仓位 10%
    min_position_percent: float = 0.02  # 最小仓位 2%
    position_atr_based: bool = True  # 基于 ATR 动态计算

    # 熔断配置
    circuit_breaker_enabled: bool = True
    circuit_breaker_threshold: float = 0.03  # 3% 日内亏损触发熔断
    circuit_breaker_cooldown_hours: int = 4  # 熔断冷却 4 小时

    # 风险等级阈值
    risk_thresholds: Dict[str, float] = field(
        default_factory=lambda: {
            "low": 0.02,  # <2% 风险
            "medium": 0.04,  # <4% 风险
            "high": 0.06,  # <6% 风险
        }
    )


@dataclass
class RiskState:
    """当前风险状态"""

    risk_level: RiskLevel
    current_drawdown: float
    daily_pnl_percent: float
    position_percent: float
    atr_percent: float
    circuit_breaker_active: bool
    circuit_breaker_reason: str
    last_risk_check: str


class RiskBoundary(ABC):
    """风险边界基类"""

    @abstractmethod
    def check(self, market_data: Dict, position_data: Dict) -> tuple[bool, str]:
        """
        检查风险边界

        Returns:
            (是否通过, 失败原因)
        """
        pass

    @abstractmethod
    def apply(self, signal: Dict) -> Dict:
        """
        应用风险调整

        Returns:
            调整后的信号
        """
        pass


class HardStopLossBoundary(RiskBoundary):
    """
    硬止损边界

    这是最后一道防线，绝对不能被突破
    """

    def __init__(self, config: RiskConfig):
        self.config = config
        self._last_stop_price: Optional[float] = None

    def check(self, market_data: Dict, position_data: Dict) -> tuple[bool, str]:
        """检查是否触发硬止损"""
        current_price = market_data.get("price", 0)
        entry_price = position_data.get("entry_price", 0)
        side = position_data.get("side", "")

        if not entry_price or not current_price:
            return True, ""

        # 计算当前亏损
        if side == "buy":
            pnl_percent = (current_price - entry_price) / entry_price
        else:
            pnl_percent = (entry_price - current_price) / entry_price

        # 检查硬止损
        if pnl_percent < -self.config.hard_stop_loss_percent:
            return (
                False,
                f"触发硬止损: 亏损 {pnl_percent:.2%} > {self.config.hard_stop_loss_percent:.2%}",
            )

        # 检查盈利时的硬止损
        if pnl_percent > 0:
            if pnl_percent < self.config.hard_stop_loss_profit_percent:
                # 盈利回吐超过阈值
                if pnl_percent < self.config.hard_stop_loss_profit_percent * 0.5:
                    return (
                        False,
                        f"触发盈利硬保护: 盈利回吐至 {pnl_percent:.2%}",
                    )

        return True, ""

    def apply(self, signal: Dict) -> Dict:
        """
        为信号添加硬止损价格

        如果没有提供止损价格，添加硬止损
        """
        if "stop_loss_price" not in signal:
            entry_price = signal.get("entry_price", 0)
            side = signal.get("side", "")
            is_long = side in ["buy", "open", "long"]
            if entry_price and is_long:
                signal["stop_loss_price"] = entry_price * (
                    1 - self.config.hard_stop_loss_percent
                )
            elif entry_price:
                signal["stop_loss_price"] = entry_price * (
                    1 + self.config.hard_stop_loss_percent
                )

        signal["hard_stop_loss_percent"] = self.config.hard_stop_loss_percent
        return signal


class DynamicPositionBoundary(RiskBoundary):
    """
    动态仓位边界

    根据市场波动率自动调整仓位大小
    """

    def __init__(self, config: RiskConfig):
        self.config = config
        self._base_position: float = 0.1  # 基准仓位 10%

    def check(self, market_data: Dict, position_data: Dict) -> tuple[bool, str]:
        """检查仓位是否超出限制"""
        position_percent = position_data.get("position_percent", 0)

        if position_percent > self.config.max_position_percent:
            return (
                False,
                f"仓位超出限制: {position_percent:.2%} > {self.config.max_position_percent:.2%}",
            )

        return True, ""

    def calculate_position(self, market_data: Dict, risk_score: float) -> float:
        """
        计算建议仓位

        Args:
            market_data: 市场数据
            risk_score: 风险分数 (0-1, 越高风险越大)

        Returns:
            建议仓位比例
        """
        atr_percent = market_data.get("technical", {}).get("atr_percent", 0.02)

        # 波动率调整
        if atr_percent > 0.05:
            volatility_factor = 0.3  # 高波动，减仓
        elif atr_percent > 0.03:
            volatility_factor = 0.6
        elif atr_percent > 0.02:
            volatility_factor = 0.8
        else:
            volatility_factor = 1.0

        # 风险调整
        risk_factor = 1.0 - risk_score * 0.5

        # 计算最终仓位
        position = self._base_position * volatility_factor * risk_factor

        # 限制范围
        position = max(
            self.config.min_position_percent,
            min(self.config.max_position_percent, position),
        )

        return position

    def apply(self, signal: Dict) -> Dict:
        """为信号添加动态仓位"""
        market_data = signal.get("market_data", {})
        risk_score = signal.get("risk_score", 0.5)

        signal["suggested_position"] = self.calculate_position(market_data, risk_score)
        return signal


class CircuitBreakerBoundary(RiskBoundary):
    """
    熔断边界

    极端情况下暂停所有交易
    """

    def __init__(self, config: RiskConfig):
        self.config = config
        self._breaker_triggered: bool = False
        self._breaker_triggered_at: Optional[datetime] = None
        self._breaker_reason: str = ""
        self._daily_high_water_mark: float = 0
        self._consecutive_losses: int = 0

    def check(self, market_data: Dict, position_data: Dict) -> tuple[bool, str]:
        """检查是否触发熔断"""
        # 检查冷却期
        if self._breaker_triggered and self._breaker_triggered_at:
            elapsed = (datetime.now() - self._breaker_triggered_at).total_seconds()
            cooldown = self.config.circuit_breaker_cooldown_hours * 3600

            if elapsed < cooldown:
                return (
                    False,
                    f"熔断中: 剩余 {int((cooldown - elapsed) / 60)} 分钟, 原因: {self._breaker_reason}",
                )
            else:
                # 冷却完成，重置熔断
                self._breaker_triggered = False
                self._breaker_triggered_at = None
                logger.info("[风险] 熔断冷却完成，交易恢复")

        return True, ""

    def trigger_breaker(self, reason: str) -> None:
        """触发熔断"""
        self._breaker_triggered = True
        self._breaker_triggered_at = datetime.now()
        self._breaker_reason = reason
        logger.warning(f"[风险] 触发熔断: {reason}")

    def record_loss(self, loss_percent: float) -> None:
        """记录亏损"""
        # 更新连亏计数
        self._consecutive_losses += 1

        # 检查是否触发熔断
        if loss_percent < -self.config.circuit_breaker_threshold:
            self.trigger_breaker(
                f"单笔亏损 {loss_percent:.2%} 超过阈值 {self.config.circuit_breaker_threshold:.2%}"
            )

    def record_win(self) -> None:
        """记录盈利，重置连亏"""
        self._consecutive_losses = 0

    def update_high_water_mark(self, current_value: float) -> None:
        """更新最高水位线"""
        if current_value > self._daily_high_water_mark:
            self._daily_high_water_mark = current_value

    def check_drawdown(self, current_value: float) -> tuple[bool, str]:
        """检查回撤是否超限"""
        if self._daily_high_water_mark == 0:
            return True, ""

        drawdown = (
            self._daily_high_water_mark - current_value
        ) / self._daily_high_water_mark

        if drawdown > self.config.circuit_breaker_threshold:
            self.trigger_breaker(
                f"回撤 {drawdown:.2%} 超过阈值 {self.config.circuit_breaker_threshold:.2%}"
            )
            return False, f"回撤超限: {drawdown:.2%}"

        return True, ""

    def apply(self, signal: Dict) -> Dict:
        """为信号添加熔断状态"""
        signal["circuit_breaker_active"] = self._breaker_triggered
        signal["circuit_breaker_reason"] = self._breaker_reason
        return signal


class RiskControlManager:
    """
    风险管理器

    整合所有风险边界，提供统一的风险管理接口
    """

    def __init__(self, config: Optional[RiskConfig] = None):
        self.config = config or RiskConfig()

        # 初始化风险边界
        self.stop_loss_boundary = HardStopLossBoundary(self.config)
        self.position_boundary = DynamicPositionBoundary(self.config)
        self.circuit_breaker_boundary = CircuitBreakerBoundary(self.config)

        # 当前状态
        self._current_risk_level: RiskLevel = RiskLevel.LOW
        self._last_check: Optional[datetime] = None

    def assess_risk(
        self,
        market_data: Dict[str, Any],
        position_data: Optional[Dict[str, Any]] = None,
    ) -> RiskState:
        """
        评估当前风险状态

        Args:
            market_data: 市场数据
            position_data: 持仓数据（可选，无持仓时为None）

        Returns:
            RiskState: 风险状态
        """
        # 处理无持仓情况
        if position_data is None:
            position_data = {}

        technical = market_data.get("technical", {})
        atr_percent = technical.get("atr_percent", 0.02)

        # 计算当前回撤
        entry_price = position_data.get("entry_price", 0)
        current_price = market_data.get("price", 0)
        position_percent = position_data.get("position_percent", 0)

        daily_pnl = position_data.get("daily_pnl_percent", 0)
        drawdown = abs(daily_pnl) if daily_pnl < 0 else 0

        # 评估风险等级
        risk_score = 0
        risk_score += min(0.3, atr_percent / 0.05)  # 波动率风险
        risk_score += min(0.3, drawdown / 0.05)  # 回撤风险
        risk_score += min(0.2, position_percent / 0.2)  # 仓位风险
        risk_score += 0.2 if self.circuit_breaker_boundary._breaker_triggered else 0

        if risk_score < 0.2:
            risk_level = RiskLevel.LOW
        elif risk_score < 0.4:
            risk_level = RiskLevel.MEDIUM
        elif risk_score < 0.6:
            risk_level = RiskLevel.HIGH
        else:
            risk_level = RiskLevel.CRITICAL

        self._current_risk_level = risk_level
        self._last_check = datetime.now()

        return RiskState(
            risk_level=risk_level,
            current_drawdown=drawdown,
            daily_pnl_percent=daily_pnl,
            position_percent=position_percent,
            atr_percent=atr_percent,
            circuit_breaker_active=self.circuit_breaker_boundary._breaker_triggered,
            circuit_breaker_reason=self.circuit_breaker_boundary._breaker_reason,
            last_risk_check=self._last_check.isoformat() if self._last_check else "",
        )

    def can_open_position(
        self, market_data: Dict, position_data: Dict
    ) -> tuple[bool, str]:
        """
        检查是否可以开仓

        Returns:
            (是否允许, 原因)
        """
        # 检查熔断
        can_trade, reason = self.circuit_breaker_boundary.check(
            market_data, position_data
        )
        if not can_trade:
            return False, reason

        # 检查仓位限制
        can_trade, reason = self.position_boundary.check(market_data, position_data)
        if not can_trade:
            return False, reason

        # 检查硬止损
        can_trade, reason = self.stop_loss_boundary.check(market_data, position_data)
        if not can_trade:
            return False, reason

        return True, "风险检查通过"

    def calculate_trade_params(
        self,
        signal: Dict,
        market_data: Dict,
        risk_score: float,
        rule_adjustments: Optional[Dict[str, float]] = None,
    ) -> Dict:
        """
        计算交易参数（带风险控制）

        Args:
            signal: 原始信号
            market_data: 市场数据
            risk_score: 风险分数
            rule_adjustments: 规则引擎的调整参数（可选）

        Returns:
            带风险控制参数的信号
        """
        # 应用各个边界
        signal = self.stop_loss_boundary.apply(signal)
        signal = self.position_boundary.apply(signal)
        signal = self.circuit_breaker_boundary.apply(signal)

        # 添加风险分数
        signal["risk_score"] = risk_score
        signal["risk_level"] = self._current_risk_level.value

        # === P3: 应用规则引擎的调整 ===
        if rule_adjustments:
            # 规则引擎优先级最高，覆盖默认风险设置
            if "stop_loss_percent" in rule_adjustments:
                # 使用规则引擎的动态止损比例
                stop_loss_pct = rule_adjustments["stop_loss_percent"]
                side = signal.get("side", "")
                # 做多/开仓: 止损价 = 入场价 * (1 - 止损百分比)
                # 做空: 止损价 = 入场价 * (1 + 止损百分比)
                if side.lower() == "buy":
                    signal["stop_loss_price"] = signal.get("price", 0) * (
                        1 - stop_loss_pct
                    )
                else:
                    signal["stop_loss_price"] = signal.get("price", 0) * (
                        1 + stop_loss_pct
                    )
                logger.info(f"[规则] 应用动态止损: {stop_loss_pct:.2%}")

            if "position_multiplier" in rule_adjustments:
                position_mult = rule_adjustments["position_multiplier"]
                signal["position_adjustment"] = position_mult
                logger.info(f"[规则] 应用仓位调整: {position_mult:.2f}x")

            if "fusion_threshold" in rule_adjustments:
                signal["fusion_threshold"] = rule_adjustments["fusion_threshold"]
                logger.info(
                    f"[规则] 应用融合阈值: {rule_adjustments['fusion_threshold']:.2f}"
                )

        # 根据风险等级调整（规则引擎未覆盖时的默认行为）
        if "position_adjustment" not in signal:
            if self._current_risk_level == RiskLevel.HIGH:
                signal["position_adjustment"] = 0.5
            elif self._current_risk_level == RiskLevel.CRITICAL:
                signal["position_adjustment"] = 0.2
            else:
                signal["position_adjustment"] = 1.0

        return signal

    def record_trade_result(self, trade_result: Dict) -> None:
        """
        记录交易结果

        Args:
            trade_result: {"pnl_percent": float, "outcome": "win"|"loss"}
        """
        pnl_percent = trade_result.get("pnl_percent", 0)
        outcome = trade_result.get("outcome", "")

        if outcome == "loss":
            self.circuit_breaker_boundary.record_loss(pnl_percent)
        else:
            self.circuit_breaker_boundary.record_win()

    def get_risk_summary(self) -> Dict[str, Any]:
        """获取风险摘要"""
        return {
            "current_risk_level": self._current_risk_level.value,
            "circuit_breaker_active": self.circuit_breaker_boundary._breaker_triggered,
            "circuit_breaker_reason": self.circuit_breaker_boundary._breaker_reason,
            "consecutive_losses": self.circuit_breaker_boundary._consecutive_losses,
            "config": {
                "hard_stop_loss": self.config.hard_stop_loss_percent,
                "max_position": self.config.max_position_percent,
                "circuit_breaker_threshold": self.config.circuit_breaker_threshold,
            },
        }
