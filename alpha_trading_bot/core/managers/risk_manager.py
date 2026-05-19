"""
风险管理器 - 整合风控配置和评估

职责：
- 风险等级评估
- 仓位计算
- 熔断机制
- 风险边界管理
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """风险等级"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RiskAssessment:
    """风险评估结果"""

    risk_level: RiskLevel
    should_reduce_position: bool
    max_position_percent: float
    stop_loss_percent: float
    circuit_breaker_active: bool
    reason: str


class RiskControlManager:
    """风险管理器

    整合 ai.adaptive.risk_manager 的 RiskControlManager，
    提供统一的风险评估接口。
    """

    def __init__(
        self,
        hard_stop_loss_percent: float = 0.05,
        max_position_percent: float = 0.1,
        circuit_breaker_threshold: float = 0.03,
    ) -> None:
        from alpha_trading_bot.ai.adaptive.risk_manager import (
            RiskControlManager as AIRiskManager,
        )
        from alpha_trading_bot.ai.adaptive.risk_manager import RiskConfig

        risk_config = RiskConfig(
            hard_stop_loss_percent=hard_stop_loss_percent,
            max_position_percent=max_position_percent,
            circuit_breaker_threshold=circuit_breaker_threshold,
        )
        self._risk_manager = AIRiskManager(risk_config)
        logger.info("[RiskControlManager] 初始化完成")

    def evaluate_risk(
        self,
        market_data: Dict[str, Any],
        current_position_percent: float = 0.0,
    ) -> RiskAssessment:
        """评估当前风险

        Args:
            market_data: 市场数据
            current_position_percent: 当前仓位比例

        Returns:
            RiskAssessment: 风险评估结果
        """
        state = self._risk_manager.evaluate_risk(market_data, current_position_percent)

        return RiskAssessment(
            risk_level=RiskLevel(state.risk_level.value),
            should_reduce_position=state.circuit_breaker_active,
            max_position_percent=state.position_percent,
            stop_loss_percent=self._risk_manager.config.hard_stop_loss_percent,
            circuit_breaker_active=state.circuit_breaker_active,
            reason=state.circuit_breaker_reason,
        )

    def calculate_position_size(
        self,
        balance: float,
        price: float,
        risk_percent: float = 0.02,
    ) -> float:
        """计算仓位大小

        Args:
            balance: 账户余额
            price: 当前价格
            risk_percent: 风险比例

        Returns:
            可开仓位数量
        """
        max_contracts = (balance * risk_percent) / price
        return min(max_contracts, balance * 0.1 / price)

    def should_trigger_circuit_breaker(
        self,
        daily_pnl_percent: float,
    ) -> bool:
        """检查是否触发熔断

        Args:
            daily_pnl_percent: 当日盈亏百分比

        Returns:
            是否触发熔断
        """
        return daily_pnl_percent < -0.03

    def assess_risk(
        self,
        market_data: Dict[str, Any],
        position_data: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """评估当前风险状态

        委托给 AI 底层 RiskControlManager.assess_risk，
        直接透传 RiskState 对象以保持与 adaptive_bot 的兼容。

        Args:
            market_data: 市场数据
            position_data: 持仓数据（可选，无持仓时为None）

        Returns:
            ai.adaptive.risk_manager.RiskState: 风险状态
        """
        return self._risk_manager.assess_risk(market_data, position_data)

    def calculate_trade_params(
        self,
        signal: Dict[str, Any],
        market_data: Dict[str, Any],
        risk_score: float = 0.5,
        rule_adjustments: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """计算交易参数（带风险控制）

        委托给 AI 底层 RiskControlManager.calculate_trade_params。

        Args:
            signal: 原始信号
            market_data: 市场数据
            risk_score: 风险分数
            rule_adjustments: 规则引擎的调整参数（可选）

        Returns:
            带风险控制参数的信号字典
        """
        return self._risk_manager.calculate_trade_params(
            signal, market_data, risk_score, rule_adjustments
        )

    def get_risk_summary(self) -> Dict[str, Any]:
        """获取风险摘要

        委托给 AI 底层 RiskControlManager.get_risk_summary。

        Returns:
            风险摘要字典
        """
        return self._risk_manager.get_risk_summary()

    def record_trade_result(self, trade_result: Dict[str, Any]) -> None:
        """记录交易结果

        委托给 AI 底层 RiskControlManager.record_trade_result。

        Args:
            trade_result: {"pnl_percent": float, "outcome": "win"|"loss"}
        """
        self._risk_manager.record_trade_result(trade_result)

    def can_open_position(
        self, market_data: Dict, position_data: Dict
    ) -> tuple:
        """检查是否可以开仓

        委托给 AI 底层 RiskControlManager.can_open_position。

        Args:
            market_data: 市场数据
            position_data: 持仓数据

        Returns:
            (是否允许, 原因)
        """
        return self._risk_manager.can_open_position(market_data, position_data)

    def get_risk_config(self) -> Dict[str, float]:
        """获取风险配置"""
        return {
            "hard_stop_loss_percent": self._risk_manager.config.hard_stop_loss_percent,
            "max_position_percent": self._risk_manager.config.max_position_percent,
            "circuit_breaker_threshold": self._risk_manager.config.circuit_breaker_threshold,
        }
