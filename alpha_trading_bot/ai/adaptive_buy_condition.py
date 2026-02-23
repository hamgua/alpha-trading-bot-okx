"""
自适应买入条件模块

功能：
- 支持多种买入模式（常规/超卖反弹/强势支撑/趋势确认）
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
class BuyConditionResult:
    """买入条件判断结果"""

    can_buy: bool
    mode: str  # regular | oversold_rebound | strong_support | trend_confirmation
    confidence: float  # 0-1
    reason: str
    details: Dict[str, Any]
    timestamp: str


@dataclass
class BuyConditions:
    """买入条件配置"""

    # 常规模式参数
    regular_trend_strength_min: float = 0.15
    regular_rsi_max: float = 70
    regular_bb_position_max: float = 70
    regular_adx_min: float = 15
    regular_momentum_min: float = 0.003

    # 超卖反弹模式参数
    oversold_enabled: bool = True
    oversold_rsi_max: float = 35  # 收紧到35，真正超卖才买入
    oversold_momentum_min: float = 0.005  # 提高到0.005，需要明显反弹
    oversold_trend_strength_min: float = 0.15  # 提高到0.15，需要一定趋势支撑
    oversold_bb_position_max: float = 40  # 收紧到40
    oversold_position_factor: float = 0.5  # 降低仓位系数

    # 强势支撑模式参数
    support_enabled: bool = True
    support_price_position_max: float = 35  # 从20提高到35，允许更高价位买入
    support_rsi_max: float = 45  # 从35提高到45
    support_momentum_min: float = 0.002  # 从0.003降低到0.002
    support_position_factor: float = 0.8  # 从0.7提高到0.8

    # 趋势确认模式参数
    confirmation_enabled: bool = True
    confirmation_consecutive_up: int = 2  # 从3降低到2，更容易触发
    confirmation_rsi_max: float = 60  # 从55提高到60
    confirmation_position_factor: float = 0.9  # 从0.8提高到0.9


class AdaptiveBuyCondition:
    """
    自适应买入条件判断

    支持四种买入模式：
    1. 常规模式：趋势向上 + RSI健康 + MACD正向
    2. 超卖反弹模式：RSI超卖 + 动量反转
    3. 强势支撑模式：价格低位 + RSI偏低
    4. 趋势确认模式：连续上涨 + 趋势明确

    中和风格设计：
    - 不过于激进：限制单次仓位
    - 不过于保守：识别明确的买入机会
    """

    def __init__(self, conditions: Optional[BuyConditions] = None):
        """
        初始化自适应买入条件模块

        Args:
            conditions: 买入条件配置，如果为None则使用默认配置
        """
        self.conditions = conditions or BuyConditions()
        self._validate_conditions()

        logger.info(
            f"[自适应买入条件] 初始化完成: "
            f"超卖反弹={self.conditions.oversold_enabled}, "
            f"强势支撑={self.conditions.support_enabled}, "
            f"趋势确认={self.conditions.confirmation_enabled}"
        )

    def should_buy(self, market_data: Dict[str, Any]) -> BuyConditionResult:
        """
        判断是否应该买入

        Args:
            market_data: 市场数据字典，包含：
                - price: 当前价格
                - recent_change_percent: 1小时涨跌幅
                - daily_change_percent: 24h涨跌幅
                - technical: 技术指标字典
                    - rsi: RSI值
                    - macd_hist: MACD柱状图
                    - bb_position: 布林带位置
                    - trend_direction: 趋势方向
                    - trend_strength: 趋势强度
                    - adx: ADX值
                - price_history: 历史价格列表
                - hourly_changes: 小时变化列表

        Returns:
            BuyConditionResult: 买入条件判断结果
        """
        technical = market_data.get("technical", {})
        recent_change = market_data.get("recent_change_percent", 0)
        trend_direction = technical.get("trend_direction", "sideways")
        trend_strength = technical.get("trend_strength", 0.3)
        rsi = technical.get("rsi", 50)
        macd_hist = technical.get("macd_hist", 0)
        bb_position = technical.get("bb_position", 50)
        adx = technical.get("adx", 20)

        results: Dict[str, Dict[str, Any]] = {}

        # 1. 常规模式检查
        regular_result = self._check_regular_mode(
            trend_direction,
            trend_strength,
            rsi,
            macd_hist,
            bb_position,
            adx,
            recent_change,
        )
        results["regular"] = regular_result

        # 2. 超卖反弹模式检查
        if self.conditions.oversold_enabled:
            oversold_result = self._check_oversold_rebound_mode(
                rsi, recent_change, trend_strength, bb_position
            )
            results["oversold_rebound"] = oversold_result

        # 3. 强势支撑模式检查
        if self.conditions.support_enabled:
            support_result = self._check_strong_support_mode(
                market_data, rsi, recent_change
            )
            results["strong_support"] = support_result

        # 4. 趋势确认模式检查
        if self.conditions.confirmation_enabled:
            confirmation_result = self._check_trend_confirmation_mode(market_data, rsi)
            results["trend_confirmation"] = confirmation_result

        # 选择最佳模式
        best_mode, best_result = self._select_best_mode(results)

        # 综合判断
        can_buy = best_result["passed"]
        final_confidence = best_result["confidence"]

        # 如果多个模式都通过，增加置信度
        passed_modes = sum(1 for r in results.values() if r["passed"])
        if passed_modes >= 2:
            final_confidence = min(final_confidence + 0.1, 0.92)

        result = BuyConditionResult(
            can_buy=can_buy,
            mode=best_mode,
            confidence=final_confidence,
            reason=best_result["reason"],
            details={
                "mode_results": results,
                "passed_modes": passed_modes,
                "confidence_bonus": passed_modes - 1 if passed_modes >= 2 else 0,
            },
            timestamp=datetime.now().isoformat(),
        )

        logger.info(
            f"[自适应买入条件] 结果: can_buy={can_buy}, mode={best_mode}, "
            f"confidence={final_confidence:.2%}, reason={best_result['reason']}"
        )

        return result

    def _check_regular_mode(
        self,
        trend_direction: str,
        trend_strength: float,
        rsi: float,
        macd_hist: float,
        bb_position: float,
        adx: float,
        recent_change: float,
    ) -> Dict[str, Any]:
        """
        检查常规买入模式

        条件：
        - 趋势不为down，且趋势强度足够
        - RSI在合理范围内
        - MACD柱状图为正
        - 布林带位置不太高
        """
        c = self.conditions

        # 检查各项条件
        checks = {
            "trend": trend_direction != "down"
            and trend_strength >= c.regular_trend_strength_min,
            "rsi": rsi < c.regular_rsi_max,
            "macd": macd_hist > 0,
            "bb": bb_position < c.regular_bb_position_max,
            "momentum": recent_change >= c.regular_momentum_min,
        }

        passed = sum(1 for v in checks.values() if v)
        pass_rate = passed / len(checks)

        # 基础置信度
        base_confidence = 0.55

        # 加分项
        if checks["trend"] and trend_strength > 0.35:
            base_confidence += 0.10
        if checks["rsi"] and rsi < 55:
            base_confidence += 0.08
        if checks["macd"]:
            base_confidence += 0.07
        if checks["bb"] and bb_position < 50:
            base_confidence += 0.05
        if checks["momentum"] and recent_change > 0.01:
            base_confidence += 0.08

        # 减分项
        if trend_direction == "down":
            base_confidence -= 0.20
        if rsi > 60:
            base_confidence -= 0.10
        if adx < 15:
            base_confidence -= 0.05

        final_confidence = max(min(base_confidence + pass_rate * 0.1, 0.90), 0.40)

        return {
            "passed": passed >= 4,
            "confidence": final_confidence,
            "checks": checks,
            "pass_rate": pass_rate,
            "reason": f"常规模式: {passed}/{len(checks)}条件通过",
        }

    def _check_oversold_rebound_mode(
        self,
        rsi: float,
        recent_change: float,
        trend_strength: float,
        bb_position: float,
    ) -> Dict[str, Any]:
        """
        检查超卖反弹模式

        条件：
        - RSI超卖（<30）
        - 有一定的动量反转迹象
        - 趋势不是特别强劲的下跌

        设计思路：
        - 超卖反弹是保守->激进的过渡
        - 允许试探性买入，但仓位减半
        """
        c = self.conditions

        checks = {
            "rsi": rsi < c.oversold_rsi_max,
            "momentum": recent_change > c.oversold_momentum_min,
            "trend": trend_strength > c.oversold_trend_strength_min,
            "bb": bb_position < c.oversold_bb_position_max,
        }

        passed = sum(1 for v in checks.values() if v)
        pass_rate = passed / len(checks)

        # 基础置信度（超卖反弹模式）
        base_confidence = 0.58

        # 严重超卖加分
        if rsi < 25:
            base_confidence += 0.15
        elif rsi < 28:
            base_confidence += 0.10

        # 动量明显反弹加分
        if recent_change > 0.01:
            base_confidence += 0.12
        elif recent_change > 0.005:
            base_confidence += 0.07

        # 布林带低位加分
        if bb_position < 35:
            base_confidence += 0.08

        # 减分项
        if trend_strength > 0.5:
            base_confidence -= 0.15  # 下跌趋势太强劲

        final_confidence = max(min(base_confidence + pass_rate * 0.05, 0.88), 0.45)

        return {
            "passed": passed >= 3,
            "confidence": final_confidence,
            "checks": checks,
            "pass_rate": pass_rate,
            "position_factor": c.oversold_position_factor,
            "reason": f"超卖反弹: {passed}/{len(checks)}条件通过, 仓位系数={c.oversold_position_factor}",
        }

    def _check_strong_support_mode(
        self, market_data: Dict[str, Any], rsi: float, recent_change: float
    ) -> Dict[str, Any]:
        """
        检查强势支撑模式

        条件：
        - 价格处于近期低位
        - RSI偏低
        - 有一定的支撑迹象

        设计思路：
        - 激进模式，认为是强势支撑位
        - 可以加大仓位
        """
        c = self.conditions

        technical = market_data.get("technical", {})
        bb_position = technical.get("bb_position", 50)
        price_position = technical.get("price_position", 50)

        # 如果有综合价格位置，使用它
        if "composite_price_position" in market_data:
            price_position = market_data["composite_price_position"]

        checks = {
            "price_position": price_position < c.support_price_position_max,
            "rsi": rsi < c.support_rsi_max,
            "momentum": recent_change > c.support_momentum_min,
        }

        passed = sum(1 for v in checks.values() if v)
        pass_rate = passed / len(checks)

        # 基础置信度（强势支撑模式）
        base_confidence = 0.60

        # 极低位置加分
        if price_position < 15:
            base_confidence += 0.15
        elif price_position < 20:
            base_confidence += 0.10

        # RSI严重偏低加分
        if rsi < 30:
            base_confidence += 0.12
        elif rsi < 32:
            base_confidence += 0.08

        # 动量支持
        if recent_change > 0.005:
            base_confidence += 0.08

        final_confidence = max(min(base_confidence + pass_rate * 0.08, 0.92), 0.50)

        return {
            "passed": passed >= 2,
            "confidence": final_confidence,
            "checks": checks,
            "pass_rate": pass_rate,
            "position_factor": c.support_position_factor,
            "price_position": price_position,
            "reason": f"强势支撑: {passed}/{len(checks)}条件通过, 仓位系数={c.support_position_factor}",
        }

    def _check_trend_confirmation_mode(
        self, market_data: Dict[str, Any], rsi: float
    ) -> Dict[str, Any]:
        """
        检查趋势确认模式

        条件：
        - 连续N个周期上涨
        - RSI在健康范围内
        - 趋势明确向上

        设计思路：
        - 最激进的模式，趋势确认后追涨
        - 加大仓位
        """
        c = self.conditions

        technical = market_data.get("technical", {})
        trend_direction = technical.get("trend_direction", "sideways")
        trend_strength = technical.get("trend_strength", 0.3)
        hourly_changes = market_data.get("hourly_changes", [])

        # 检查连续上涨周期数
        consecutive_up = 0
        for change in hourly_changes[: c.confirmation_consecutive_up]:
            if change > 0:
                consecutive_up += 1
            else:
                break

        checks = {
            "consecutive_up": consecutive_up >= c.confirmation_consecutive_up,
            "rsi": rsi < c.confirmation_rsi_max,
            "trend_up": trend_direction == "up",
        }

        passed = sum(1 for v in checks.values() if v)
        pass_rate = passed / len(checks)

        # 基础置信度（趋势确认模式）
        base_confidence = 0.62

        # 连续上涨越多越加分
        if consecutive_up >= 5:
            base_confidence += 0.15
        elif consecutive_up >= 4:
            base_confidence += 0.10

        # 趋势强度加分
        if trend_strength > 0.4:
            base_confidence += 0.10
        elif trend_strength > 0.3:
            base_confidence += 0.05

        # RSI健康加分
        if rsi < 50:
            base_confidence += 0.08

        # 减分项
        if rsi > 52:
            base_confidence -= 0.10

        final_confidence = max(min(base_confidence + pass_rate * 0.05, 0.95), 0.52)

        return {
            "passed": passed >= 2 and consecutive_up >= 3,
            "confidence": final_confidence,
            "checks": checks,
            "pass_rate": pass_rate,
            "consecutive_up": consecutive_up,
            "position_factor": c.confirmation_position_factor,
            "reason": f"趋势确认: 连续{consecutive_up}上涨, {passed}/{len(checks)}条件通过, 仓位系数={c.confirmation_position_factor}",
        }

    def _select_best_mode(self, results: Dict[str, Dict[str, Any]]) -> tuple:
        """
        选择最佳买入模式

        策略：
        1. 优先选择通过检查的模式
        2. 如果多个模式都通过，选择置信度最高的
        3. 如果都没有通过，选择置信度最高的hold模式
        """
        passed_modes = {k: v for k, v in results.items() if v["passed"]}

        if passed_modes:
            # 有通过的模式，选择置信度最高的
            best_mode = max(
                passed_modes.keys(), key=lambda k: passed_modes[k]["confidence"]
            )
            return best_mode, passed_modes[best_mode]
        else:
            # 没有通过的模式，选择置信度最高的hold
            best_mode = max(results.keys(), key=lambda k: results[k]["confidence"])
            return best_mode, results[best_mode]

    def _validate_conditions(self) -> None:
        """验证条件配置的合理性"""
        c = self.conditions

        # 验证RSI阈值
        if c.regular_rsi_max <= c.oversold_rsi_max:
            logger.warning(
                f"[自适应买入条件] 警告: regular_rsi_max({c.regular_rsi_max}) <= "
                f"oversold_rsi_max({c.oversold_rsi_max})，可能影响模式判断"
            )

        # 验证仓位系数
        for name, factor in [
            ("oversold", c.oversold_position_factor),
            ("support", c.support_position_factor),
            ("confirmation", c.confirmation_position_factor),
        ]:
            if factor > 1.0:
                logger.warning(
                    f"[自适应买入条件] 警告: {name}_position_factor({factor}) > 1.0，仓位可能超过100%"
                )
            elif factor <= 0:
                logger.warning(
                    f"[自适应买入条件] 警告: {name}_position_factor({factor}) <= 0，将无法建仓"
                )

    def get_position_factor(self, mode: str) -> float:
        """
        获取指定模式的仓位系数

        Args:
            mode: 模式名称

        Returns:
            float: 仓位系数（0-1）
        """
        c = self.conditions

        if mode == "oversold_rebound":
            return c.oversold_position_factor
        elif mode == "strong_support":
            return c.support_position_factor
        elif mode == "trend_confirmation":
            return c.confirmation_position_factor
        else:
            return 1.0  # 常规模式使用满仓
