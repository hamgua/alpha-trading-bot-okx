"""
自适应规则引擎

功能：
- 定义参数调整规则
- 根据市场环境和表现自动应用规则
- 提供规则管理和热更新能力
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class RuleCategory(Enum):
    """规则类别"""

    VOLATILITY = "volatility"  # 波动率规则
    TREND = "trend"  # 趋势规则
    RSI = "rsi"  # RSI规则
    CONSECUTIVE = "consecutive"  # 连亏/连赢规则
    REGIME = "regime"  # 市场环境规则


@dataclass
class RuleResult:
    """规则应用结果"""

    rule_name: str
    category: RuleCategory
    triggered: bool
    adjustment: Dict[str, float]
    reason: str
    confidence: float  # 规则触发置信度


class AdaptiveRule(ABC):
    """自适应规则基类"""

    def __init__(self, name: str, category: RuleCategory, priority: int = 0):
        """
        初始化规则

        Args:
            name: 规则名称
            category: 规则类别
            priority: 优先级（数值越大优先级越高）
        """
        self.name = name
        self.category = category
        self.priority = priority
        self.enabled = True

    @abstractmethod
    def evaluate(
        self,
        market_state: "MarketRegimeState",
        performance: "PerformanceMetrics",
    ) -> RuleResult:
        """
        评估规则是否触发

        Args:
            market_state: 市场状态
            performance: 表现指标

        Returns:
            RuleResult: 规则评估结果
        """
        pass


class VolatilityRule(AdaptiveRule):
    """波动率自适应规则"""

    def __init__(self):
        super().__init__("volatility_rule", RuleCategory.VOLATILITY, priority=10)

    def evaluate(
        self,
        market_state: "MarketRegimeState",
        performance: "PerformanceMetrics",
    ) -> RuleResult:
        """评估波动率规则"""
        atr_percent = market_state.atr_percent

        if atr_percent > 45:  # 极高波动  # 极高波动
            return RuleResult(
                rule_name=self.name,
                category=self.category,
                triggered=True,
                adjustment={
                    "stop_loss_percent": 0.015,  # 放宽止损
                    "position_multiplier": 0.3,  # 大幅减仓
                    "fusion_threshold": 0.55,  # 更严格的信号
                },
                reason=f"极高波动 (ATR%: {atr_percent:.2%})",
                confidence=0.9,
            )

        elif atr_percent > 35:  # 高波动  # 高波动
            return RuleResult(
                rule_name=self.name,
                category=self.category,
                triggered=True,
                adjustment={
                    "stop_loss_percent": 0.01,
                    "position_multiplier": 0.5,
                    "fusion_threshold": 0.52,
                },
                reason=f"高波动 (ATR%: {atr_percent:.2%})",
                confidence=0.85,
            )

        elif atr_percent > 20:  # 中高波动  # 中高波动
            return RuleResult(
                rule_name=self.name,
                category=self.category,
                triggered=True,
                adjustment={
                    "stop_loss_percent": 0.007,
                    "position_multiplier": 0.7,
                    "fusion_threshold": 0.50,
                },
                reason=f"中等波动 (ATR%: {atr_percent:.2%})",
                confidence=0.7,
            )

        elif atr_percent < 0.015:  # 低波动
            return RuleResult(
                rule_name=self.name,
                category=self.category,
                triggered=True,
                adjustment={
                    "stop_loss_percent": 0.004,
                    "position_multiplier": 1.2,  # 可以适当加仓
                    "fusion_threshold": 0.45,  # 放宽信号要求
                },
                reason=f"低波动 (ATR%: {atr_percent:.2%})",
                confidence=0.65,
            )

        return RuleResult(
            rule_name=self.name,
            category=self.category,
            triggered=False,
            adjustment={},
            reason="波动率正常",
            confidence=0.0,
        )


class TrendRule(AdaptiveRule):
    """趋势自适应规则"""

    def __init__(self):
        super().__init__("trend_rule", RuleCategory.TREND, priority=8)

    def evaluate(
        self,
        market_state: "MarketRegimeState",
        performance: "PerformanceMetrics",
    ) -> RuleResult:
        """评估趋势规则"""
        trend = market_state.trend_strength
        regime = market_state.regime

        if regime.value.startswith("trend_up"):
            return RuleResult(
                rule_name=self.name,
                category=self.category,
                triggered=True,
                adjustment={
                    "buy_rsi_threshold": 75,  # 放宽买入条件
                    "stop_loss_percent": 0.004,
                    "fusion_threshold": 0.48,  # 更容易触发买入
                },
                reason=f"上升趋势 (强度: {trend:.2f})",
                confidence=0.8,
            )

        elif regime.value.startswith("trend_down"):
            return RuleResult(
                rule_name=self.name,
                category=self.category,
                triggered=True,
                adjustment={
                    "buy_rsi_threshold": 30,  # 严格买入条件
                    "stop_loss_percent": 0.003,
                    "fusion_threshold": 0.65,  # 更严格才买入
                },
                reason=f"下降趋势 (强度: {trend:.2f})",
                confidence=0.8,
            )

        return RuleResult(
            rule_name=self.name,
            category=self.category,
            triggered=False,
            adjustment={},
            reason="无明显趋势",
            confidence=0.0,
        )


class ConsecutiveLossRule(AdaptiveRule):
    """连亏自适应规则"""

    def __init__(self, consecutive_threshold: int = 3):
        super().__init__(
            "consecutive_loss_rule",
            RuleCategory.CONSECUTIVE,
            priority=15,
        )
        self.consecutive_threshold = consecutive_threshold

    def evaluate(
        self,
        market_state: "MarketRegimeState",
        performance: "PerformanceMetrics",
    ) -> RuleResult:
        """评估连亏规则"""
        consecutive_losses = performance.consecutive_losses

        if consecutive_losses >= 5:
            return RuleResult(
                rule_name=self.name,
                category=self.category,
                triggered=True,
                adjustment={
                    "position_multiplier": 0.2,  # 大幅减仓
                    "fusion_threshold": 0.70,  # 非常严格
                    "stop_loss_percent": 0.003,
                },
                reason=f"连续亏损 {consecutive_losses} 次",
                confidence=0.95,
            )

        elif consecutive_losses >= 3:
            return RuleResult(
                rule_name=self.name,
                category=self.category,
                triggered=True,
                adjustment={
                    "position_multiplier": 0.5,
                    "fusion_threshold": 0.60,
                    "stop_loss_percent": 0.004,
                },
                reason=f"连续亏损 {consecutive_losses} 次",
                confidence=0.85,
            )

        return RuleResult(
            rule_name=self.name,
            category=self.category,
            triggered=False,
            adjustment={},
            reason="无连亏",
            confidence=0.0,
        )


class RSIRule(AdaptiveRule):
    """RSI 自适应规则"""

    def __init__(self):
        super().__init__("rsi_rule", RuleCategory.RSI, priority=5)

    def evaluate(
        self,
        market_state: "MarketRegimeState",
        performance: "PerformanceMetrics",
    ) -> RuleResult:
        """评估 RSI 规则"""
        rsi = market_state.rsi_level

        if rsi < 30:  # 超卖
            return RuleResult(
                rule_name=self.name,
                category=self.category,
                triggered=True,
                adjustment={
                    "buy_rsi_threshold": 25,  # 更激进买入
                    "fusion_threshold": 0.45,
                    "position_multiplier": 1.3,
                },
                reason=f"RSI超卖 ({rsi:.1f})",
                confidence=0.85,
            )

        elif rsi < 40:
            return RuleResult(
                rule_name=self.name,
                category=self.category,
                triggered=True,
                adjustment={
                    "buy_rsi_threshold": 35,
                    "fusion_threshold": 0.48,
                    "position_multiplier": 1.1,
                },
                reason=f"RSI偏低 ({rsi:.1f})",
                confidence=0.7,
            )

        elif rsi > 70:  # 超买
            return RuleResult(
                rule_name=self.name,
                category=self.category,
                triggered=True,
                adjustment={
                    "buy_rsi_threshold": 80,  # 不轻易买入
                    "fusion_threshold": 0.60,
                    "position_multiplier": 0.7,
                },
                reason=f"RSI超买 ({rsi:.1f})",
                confidence=0.75,
            )

        return RuleResult(
            rule_name=self.name,
            category=self.category,
            triggered=False,
            adjustment={},
            reason="RSI正常",
            confidence=0.0,
        )


class AdaptiveRulesEngine:
    """
    自适应规则引擎

    管理和执行所有自适应规则
    """

    def __init__(self):
        """初始化规则引擎"""
        self.rules: list[AdaptiveRule] = []
        self._register_default_rules()

    def _register_default_rules(self) -> None:
        """注册默认规则"""
        self.rules = [
            ConsecutiveLossRule(consecutive_threshold=3),
            VolatilityRule(),
            TrendRule(),
            RSIRule(),
        ]
        # 按优先级排序
        self.rules.sort(key=lambda r: r.priority, reverse=True)

    def add_rule(self, rule: AdaptiveRule) -> None:
        """添加规则"""
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority, reverse=True)
        logger.info(f"[规则引擎] 添加规则: {rule.name} (优先级: {rule.priority})")

    def remove_rule(self, name: str) -> bool:
        """移除规则"""
        for i, rule in enumerate(self.rules):
            if rule.name == name:
                self.rules.pop(i)
                logger.info(f"[规则引擎] 移除规则: {name}")
                return True
        return False

    def evaluate_all(
        self,
        market_state: "MarketRegimeState",
        performance: "PerformanceMetrics",
    ) -> Dict[str, Any]:
        """
        执行所有规则

        Args:
            market_state: 市场状态
            performance: 表现指标

        Returns:
            合并的调整参数
        """
        triggered_rules: list[RuleResult] = []
        combined_adjustment: Dict[str, float] = {}

        for rule in self.rules:
            if not rule.enabled:
                continue

            result = rule.evaluate(market_state, performance)
            triggered_rules.append(result)

            if result.triggered:
                logger.info(f"[规则引擎] 触发规则: {rule.name} - {result.reason}")
                # 合并调整（高优先级规则覆盖低优先级）
                for key, value in result.adjustment.items():
                    combined_adjustment[key] = value

        return {
            "adjustments": combined_adjustment,
            "triggered_rules": [r.rule_name for r in triggered_rules if r.triggered],
            "rule_count": len(triggered_rules),
        }

    def get_rule_summary(self) -> list[Dict[str, Any]]:
        """获取规则摘要"""
        return [
            {
                "name": r.name,
                "category": r.category.value,
                "priority": r.priority,
                "enabled": r.enabled,
            }
            for r in self.rules
        ]
