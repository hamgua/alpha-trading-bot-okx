"""
动态卖出条件模块

功能：
- 支持多种卖出模式（止损/止盈/风险规避/减仓）
- 根据市场环境动态调整条件
- 计算各模式的置信度
- 支持中和交易风格

作者：AI Trading System
日期：2026-02-04
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class SellConditionResult:
    """卖出条件判断结果"""

    should_sell: bool
    sell_type: str  # stop_loss | take_profit | risk_avoidance | partial
    confidence: float  # 0-1
    reason: str
    details: Dict[str, Any]
    timestamp: str


@dataclass
class SellConditions:
    """卖出条件配置"""

    # 止损参数
    stop_loss_percent: float = 0.02  # 2%
    stop_loss_profit_percent: float = 0.01  # 1%，盈利后回撤止损
    stop_loss_tolerance_percent: float = 0.001  # 止损价容错

    # 止盈参数
    take_profit_percent: float = 0.06  # 6%
    take_profit_partial_percent: float = 0.04  # 4%，分批止盈
    take_profit_rsi_threshold: float = 75  # RSI超买止盈

    # 风险规避参数
    risk_rsi_overbought: float = 80
    risk_rsi_high: float = 75
    risk_bb_position_max: float = 0.90
    risk_bb_position_high: float = 0.85
    risk_trend_down_strength: float = 0.4  # 趋势转空强度阈值
    risk_macd_negative: float = -0.002  # MACD转空阈值
    risk_drawdown_percent: float = 0.01  # 浮盈回撤阈值

    # 减仓参数
    partial_sell_enabled: bool = True
    partial_sell_factor: float = 0.5  # 减仓比例


class DynamicSellCondition:
    """
    动态卖出条件判断

    支持四种卖出模式：
    1. 止损模式：浮亏达到阈值
    2. 止盈模式：浮盈达到目标或超买
    3. 风险规避模式：多个风险信号
    4. 减仓模式：部分获利了结

    中和风格设计：
    - 及时止损：不让亏损扩大
    - 适度止盈：不过于贪婪
    - 风险控制：识别危险信号
    """

    def __init__(self, conditions: Optional[SellConditions] = None):
        """
        初始化动态卖出条件模块

        Args:
            conditions: 卖出条件配置，如果为None则使用默认配置
        """
        self.conditions = conditions or SellConditions()
        self._validate_conditions()

        logger.info(
            f"[动态卖出条件] 初始化完成: "
            f"止损={self.conditions.stop_loss_percent * 100}%, "
            f"止盈={self.conditions.take_profit_percent * 100}%, "
            f"减仓启用={self.conditions.partial_sell_enabled}"
        )

    def should_sell(
        self,
        position_pnl_percent: float,
        market_data: Dict[str, Any],
        has_reached_stop_loss: bool = False,
        has_reached_take_profit: bool = False,
    ) -> SellConditionResult:
        """
        判断是否应该卖出

        Args:
            position_pnl_percent: 持仓盈亏百分比
            market_data: 市场数据字典，包含：
                - technical: 技术指标字典
                    - rsi: RSI值
                    - bb_position: 布林带位置
                    - trend_direction: 趋势方向
                    - trend_strength: 趋势强度
                    - macd_hist: MACD柱状图
                - recent_change_percent: 1小时涨跌幅
            has_reached_stop_loss: 是否已触发止损
            has_reached_take_profit: 是否已触发止盈

        Returns:
            SellConditionResult: 卖出条件判断结果
        """
        technical = market_data.get("technical", {})
        rsi = technical.get("rsi", 50)
        bb_position = technical.get("bb_position", 0.5)
        trend_direction = technical.get("trend_direction", "sideways")
        trend_strength = technical.get("trend_strength", 0.3)
        macd_hist = technical.get("macd_hist", 0)
        recent_change = market_data.get("recent_change_percent", 0)

        results: Dict[str, Dict[str, Any]] = {}

        # 1. 止损检查
        stop_loss_result = self._check_stop_loss(
            position_pnl_percent, has_reached_stop_loss
        )
        results["stop_loss"] = stop_loss_result

        # 2. 止盈检查
        take_profit_result = self._check_take_profit(
            position_pnl_percent, rsi, has_reached_take_profit
        )
        results["take_profit"] = take_profit_result

        # 3. 风险规避检查
        risk_result = self._check_risk_avoidance(
            rsi,
            bb_position,
            trend_direction,
            trend_strength,
            macd_hist,
            position_pnl_percent,
        )
        results["risk_avoidance"] = risk_result

        # 4. 减仓检查（如果有盈利）
        if self.conditions.partial_sell_enabled and position_pnl_percent > 0:
            partial_result = self._check_partial_sell(
                position_pnl_percent, rsi, recent_change
            )
            results["partial_sell"] = partial_result

        # 决策逻辑
        return self._make_decision(results, position_pnl_percent)

    def _check_stop_loss(self, pnl_percent: float, has_reached: bool) -> Dict[str, Any]:
        """
        检查止损条件

        逻辑：
        - 新开仓：浮亏 > 2% 止损
        - 有盈利后：浮亏 > 1% 止损
        - 强制止损已触发
        """
        c = self.conditions

        # 检查是否触发止损
        if has_reached:
            return {
                "triggered": True,
                "confidence": 1.0,
                "reason": "强制止损已触发",
                "pnl": pnl_percent,
                "threshold": c.stop_loss_percent * 100,
            }

        # 亏损情况下的止损
        if pnl_percent < 0:
            # 新开仓：浮亏 > stop_loss_percent
            if pnl_percent < -c.stop_loss_percent * 100:
                return {
                    "triggered": True,
                    "confidence": 1.0,
                    "reason": f"浮亏({pnl_percent:.2f}%)超过止损阈值({c.stop_loss_percent * 100}%)",
                    "pnl": pnl_percent,
                    "threshold": c.stop_loss_percent * 100,
                }

            # 盈利后回撤：浮亏 > stop_loss_profit_percent
            if pnl_percent < -c.stop_loss_profit_percent * 100:
                return {
                    "triggered": True,
                    "confidence": 0.95,
                    "reason": f"浮盈回撤后浮亏({pnl_percent:.2f}%)超过回撤止损阈值({c.stop_loss_profit_percent * 100}%)",
                    "pnl": pnl_percent,
                    "threshold": c.stop_loss_profit_percent * 100,
                }

        return {
            "triggered": False,
            "confidence": 0.0,
            "reason": f"未触发止损，当前浮亏={pnl_percent:.2f}%",
            "pnl": pnl_percent,
        }

    def _check_take_profit(
        self, pnl_percent: float, rsi: float, has_reached: bool
    ) -> Dict[str, Any]:
        """
        检查止盈条件

        逻辑：
        - 浮盈达到目标（6%）
        - 浮盈4% + RSI超买
        - 浮盈3% + 趋势转空
        """
        c = self.conditions

        # 检查是否触发止盈
        if has_reached:
            return {
                "triggered": True,
                "confidence": 1.0,
                "reason": "强制止盈已触发",
                "pnl": pnl_percent,
                "threshold": c.take_profit_percent * 100,
            }

        # 盈利情况下的止盈检查
        if pnl_percent > 0:
            # 达到目标止盈
            if pnl_percent >= c.take_profit_percent * 100:
                return {
                    "triggered": True,
                    "confidence": 0.95,
                    "reason": f"浮盈({pnl_percent:.2f}%)达到止盈目标({c.take_profit_percent * 100}%)",
                    "pnl": pnl_percent,
                    "threshold": c.take_profit_percent * 100,
                }

            # 分批止盈条件
            if (
                pnl_percent >= c.take_profit_partial_percent * 100
                and rsi >= c.take_profit_rsi_threshold
            ):
                return {
                    "triggered": True,
                    "confidence": 0.85,
                    "reason": f"浮盈({pnl_percent:.2f}%)达标+RSI({rsi:.1f})超买，分批止盈",
                    "pnl": pnl_percent,
                    "threshold": c.take_profit_partial_percent * 100,
                    "action": "partial",
                }

        return {
            "triggered": False,
            "confidence": 0.0,
            "reason": f"未触发止盈，当前浮盈={pnl_percent:.2f}%",
            "pnl": pnl_percent,
        }

    def _check_risk_avoidance(
        self,
        rsi: float,
        bb_position: float,
        trend_direction: str,
        trend_strength: float,
        macd_hist: float,
        pnl_percent: float,
    ) -> Dict[str, Any]:
        """
        检查风险规避条件

        逻辑：
        - 多指标同时出现风险信号
        - RSI超买（>80）
        - 布林带超买（>90%）
        - 趋势明确转空
        - MACD转空
        """
        c = self.conditions

        risk_signals: list = []
        risk_score: float = 0.0

        # RSI超买检查
        if rsi >= c.risk_rsi_overbought:
            risk_signals.append(f"RSI严重超买({rsi:.1f})")
            risk_score += 1.0
        elif rsi >= c.risk_rsi_high:
            risk_signals.append(f"RSI偏高({rsi:.1f})")
            risk_score += 0.5

        # 布林带超买检查
        if bb_position >= c.risk_bb_position_max:
            risk_signals.append(f"布林带严重超买({bb_position:.1f}%)")
            risk_score += 1.0
        elif bb_position >= c.risk_bb_position_high:
            risk_signals.append(f"布林带偏高({bb_position:.1f}%)")
            risk_score += 0.5

        # 趋势转空检查
        if trend_direction == "down" and trend_strength >= c.risk_trend_down_strength:
            risk_signals.append(f"趋势明确转空(strength={trend_strength:.2f})")
            risk_score += 0.8

        # MACD转空检查
        if macd_hist <= c.risk_macd_negative:
            risk_signals.append(f"MACD转空({macd_hist:+.4f})")
            risk_score += 0.6

        # 浮盈大幅回撤检查：有盈利但利润回吐超过阈值
        if pnl_percent > 0 and pnl_percent < c.risk_drawdown_percent * 100:
            risk_signals.append(
                f"浮盈大幅回撤({pnl_percent:.2f}% < {c.risk_drawdown_percent * 100:.1f}%)"
            )
            risk_score += 0.5

        # 判断是否触发风险规避
        triggered = risk_score >= 1.5  # 需要至少1.5分

        if triggered:
            confidence = min(0.7 + (risk_score - 1.5) * 0.1, 0.95)
            reason = f"风险信号: {'; '.join(risk_signals)}"
        else:
            confidence = 0.0
            reason = f"风险信号不足({risk_score:.1f}分): {'; '.join(risk_signals) if risk_signals else '无明显风险'}"

        return {
            "triggered": triggered,
            "confidence": confidence,
            "reason": reason,
            "risk_signals": risk_signals,
            "risk_score": risk_score,
        }

    def _check_partial_sell(
        self, pnl_percent: float, rsi: float, recent_change: float
    ) -> Dict[str, Any]:
        """
        检查减仓条件

        逻辑：
        - 有一定盈利
        - 出现部分止盈信号
        - 可以分批获利了结
        """
        c = self.conditions

        # 减仓条件
        partial_conditions = [
            pnl_percent >= c.take_profit_partial_percent * 100,
            rsi >= 70,
            recent_change < -0.005,  # 短期下跌
        ]

        passed = sum(1 for v in partial_conditions if v)

        if passed >= 2:
            return {
                "triggered": True,
                "confidence": 0.75,
                "reason": f"满足减仓条件({passed}/3)，浮盈={pnl_percent:.2f}%",
                "pnl": pnl_percent,
                "factor": c.partial_sell_factor,
                "action": "partial",
            }

        return {
            "triggered": False,
            "confidence": 0.0,
            "reason": f"减仓条件不满足({passed}/3)",
            "pnl": pnl_percent,
        }

    def _make_decision(
        self, results: Dict[str, Dict[str, Any]], pnl_percent: float
    ) -> SellConditionResult:
        """
        综合决策

        优先级：
        1. 止损（最高优先级）
        2. 止盈
        3. 风险规避
        4. 减仓
        """
        # 优先级：止损 > 止盈 > 风险规避 > 减仓

        # 1. 止损
        if results["stop_loss"]["triggered"]:
            return SellConditionResult(
                should_sell=True,
                sell_type="stop_loss",
                confidence=results["stop_loss"]["confidence"],
                reason=results["stop_loss"]["reason"],
                details={"stop_loss": results["stop_loss"]},
                timestamp=datetime.now().isoformat(),
            )

        # 2. 止盈
        if results["take_profit"]["triggered"]:
            action = results["take_profit"].get("action", "full")
            return SellConditionResult(
                should_sell=True,
                sell_type="take_profit",
                confidence=results["take_profit"]["confidence"],
                reason=results["take_profit"]["reason"],
                details={
                    "take_profit": results["take_profit"],
                    "action": action,
                },
                timestamp=datetime.now().isoformat(),
            )

        # 3. 风险规避
        if results["risk_avoidance"]["triggered"]:
            return SellConditionResult(
                should_sell=True,
                sell_type="risk_avoidance",
                confidence=results["risk_avoidance"]["confidence"],
                reason=results["risk_avoidance"]["reason"],
                details={"risk_avoidance": results["risk_avoidance"]},
                timestamp=datetime.now().isoformat(),
            )

        # 4. 减仓
        if "partial_sell" in results and results["partial_sell"]["triggered"]:
            return SellConditionResult(
                should_sell=True,
                sell_type="partial",
                confidence=results["partial_sell"]["confidence"],
                reason=results["partial_sell"]["reason"],
                details={"partial_sell": results["partial_sell"]},
                timestamp=datetime.now().isoformat(),
            )

        # 不需要卖出
        return SellConditionResult(
            should_sell=False,
            sell_type="hold",
            confidence=1.0,
            reason=f"无需卖出，当前浮盈={pnl_percent:.2f}%",
            details={"pnl_percent": pnl_percent},
            timestamp=datetime.now().isoformat(),
        )

    def _validate_conditions(self) -> None:
        """验证条件配置的合理性"""
        c = self.conditions

        # 验证止损止盈参数
        if c.stop_loss_percent >= c.take_profit_percent:
            logger.warning(
                f"[动态卖出条件] 警告: stop_loss_percent({c.stop_loss_percent * 100}%) >= "
                f"take_profit_percent({c.take_profit_percent * 100}%)，可能无法盈利"
            )

        # 验证止损参数
        if c.stop_loss_percent > 0.1:
            logger.warning(
                f"[动态卖出条件] 警告: stop_loss_percent({c.stop_loss_percent * 100}%) > 10%，止损幅度过大"
            )

        # 验证减仓参数
        if c.partial_sell_enabled and c.partial_sell_factor > 1.0:
            logger.warning(
                f"[动态卖出条件] 警告: partial_sell_factor({c.partial_sell_factor}) > 1.0，减仓比例超过100%"
            )

    def get_stop_loss_price(
        self, entry_price: float, pnl_percent: float, is_new_position: bool = True
    ) -> float:
        """
        计算止损价

        Args:
            entry_price: 入场价格
            pnl_percent: 当前盈亏百分比
            is_new_position: 是否为新开仓

        Returns:
            float: 止损价格
        """
        c = self.conditions

        if is_new_position:
            stop_percent = c.stop_loss_percent
        else:
            # 有盈利后，使用盈利回撤止损
            stop_percent = c.stop_loss_profit_percent

        stop_price = entry_price * (1 - stop_percent)
        return stop_price

    def get_take_profit_price(self, entry_price: float) -> float:
        """
        计算止盈价

        Args:
            entry_price: 入场价格

        Returns:
            float: 止盈价格
        """
        c = self.conditions
        return entry_price * (1 + c.take_profit_percent)
