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

from alpha_trading_bot.config.thresholds import (
    RSI_OVERSOLD,
    RSI_OVERBOUGHT,
    RSI_NEUTRAL_LOW,
)

logger = logging.getLogger(__name__)

from .market_regime import MarketRegimeState
from .performance_tracker import PerformanceMetrics


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
        """评估波动率规则

        dream 2026-09-16-loss-root-cause / R1 修复：
        原实现存在单位混淆 —— 高波动阈值 (0.60/0.35/0.20) 以小数
        atr_percent (0.0014 = 0.14%) 比较，即 60%/35%/20% ATR，
        在 15 分钟周期下永远不触发；而低波动分支 atr < 0.015 (=1.5%)
        几乎恒触发，把止损固定为 0.8% (≈5-8 倍 ATR) 并放大仓位 1.2x，
        导致实盘每笔亏损固定 -0.80% (2026-09-09~13 日志)。

        修复后 (阈值单位统一为小数, 与 atr_percent 一致):
        - 极高波动 ATR > 0.6%: 宽止损 1.5%, 减仓 0.5x, 收紧门禁 0.55
        - 高波动   ATR > 0.35%: 止损 1.0%, 0.7x, 收紧门禁 0.55
        - 中等波动 ATR > 0.20%: 止损 0.7%, 0.85x, 门禁 0.50
        - 低波动   ATR < 0.20%: 止损 = clamp(3×ATR, 0.3%, 0.5%),
          仓位 1.0x (不再放大), 收紧门禁 0.55, 仅深度超卖可买 (RSI<35)
          例: ATR 0.14% (2026-09-13 实盘值) → 止损 0.42% (原 0.8%)

        风险平价性质: 仓位×止损 ≈ 常数 (0.3%~0.75%), 波动越大仓位越小。
        高波动分支收紧 (而非放松) 置信度门禁: 高波动=更严格入场。
        """
        atr_percent = market_state.atr_percent

        if atr_percent > 0.006:  # ATR > 0.6%
            return RuleResult(
                rule_name=self.name,
                category=self.category,
                triggered=True,
                adjustment={
                    "stop_loss_percent": 0.015,
                    "position_multiplier": 0.5,
                    "fusion_threshold": 0.55,
                },
                reason=f"极高波动 (ATR%: {atr_percent * 100:.2f}%)",
                confidence=0.9,
            )

        elif atr_percent > 0.0035:  # ATR > 0.35%
            return RuleResult(
                rule_name=self.name,
                category=self.category,
                triggered=True,
                adjustment={
                    "stop_loss_percent": 0.01,
                    "position_multiplier": 0.7,
                    "fusion_threshold": 0.55,
                },
                reason=f"高波动 (ATR%: {atr_percent * 100:.2f}%)",
                confidence=0.85,
            )

        elif atr_percent > 0.002:  # ATR > 0.20%
            return RuleResult(
                rule_name=self.name,
                category=self.category,
                triggered=True,
                adjustment={
                    "stop_loss_percent": 0.007,
                    "position_multiplier": 0.85,
                    "fusion_threshold": 0.50,
                },
                reason=f"中等波动 (ATR%: {atr_percent * 100:.2f}%)",
                confidence=0.7,
            )

        elif atr_percent < 0.002:  # ATR < 0.20% (低波动/震荡区, 含正常波动)
            # 止损与波动率成比例: 3×ATR, 下限 0.3% 防极窄止损被噪音扫掉,
            # 上限 0.5% 防止接近中等波动带时止损过宽。
            # 原固定 0.8% 在 ATR 0.14% 时等于 5.7×ATR, 实盘验证为结构性亏损源。
            stop_loss_percent = min(max(3.0 * atr_percent, 0.003), 0.005)
            return RuleResult(
                rule_name=self.name,
                category=self.category,
                triggered=True,
                adjustment={
                    "stop_loss_percent": stop_loss_percent,
                    "position_multiplier": 1.0,
                    "fusion_threshold": 0.55,
                    "buy_rsi_threshold": 35,
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

        if rsi < RSI_OVERSOLD:  # 超卖
            return RuleResult(
                rule_name=self.name,
                category=self.category,
                triggered=True,
                adjustment={
                    "buy_rsi_threshold": 25,
                    "fusion_threshold": 0.45,
                    "position_multiplier": 0.8,
                },
                reason=f"RSI超卖 ({rsi:.1f})",
                confidence=0.85,
            )

        elif rsi < RSI_NEUTRAL_LOW:
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

        elif rsi > RSI_OVERBOUGHT:  # 超买
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

        # dream 2026-09-16-loss-root-cause: 原实现按优先级降序遍历 + 最后写入胜出,
        # 导致优先级最低的规则反而覆盖高优先级规则 (与文档字符串矛盾)。
        # 修复: 升序遍历, 高优先级规则后写入, 实现"高优先级覆盖低优先级"。
        for rule in sorted(self.rules, key=lambda r: r.priority):
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
