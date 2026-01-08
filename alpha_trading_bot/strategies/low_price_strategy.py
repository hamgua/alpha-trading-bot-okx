"""
低价格位置策略模块
专门处理价格位置低于35%时的交易机会
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class LowPriceStrategy:
    """低价格位置交易策略"""

    def __init__(self):
        # 低价格位置阈值
        self.low_price_threshold = 35.0  # 35%以下
        self.extreme_low_threshold = 15.0  # 15%以下极低位

        # 低价格位置的专项参数
        self.params = {
            "rsi_buy_threshold": 45,  # 低价格位置时RSI买入阈值提高到45
            "confidence_boost": 1.3,  # 信心度增强30%
            "position_size_boost": 1.5,  # 仓位增加50%
            "stop_loss_relax": 0.8,  # 止损放宽20%
            "min_accumulation_pct": 0.5,  # 累积涨幅阈值降低到0.5%
            "min_single_gain_pct": 0.4,  # 单次涨幅阈值降低到0.4%
            "consecutive_up_threshold": 2,  # 连续上涨次数要求降低到2次
        }

    def is_applicable(self, price_position: float) -> bool:
        """判断策略是否适用"""
        return price_position < self.low_price_threshold

    def get_price_level(self, price_position: float) -> str:
        """获取价格位置级别"""
        if price_position < self.extreme_low_threshold:
            return "extreme_low"
        elif price_position < 25:
            return "low"
        elif price_position < self.low_price_threshold:
            return "moderate_low"
        else:
            return "normal"

    def enhance_signal_for_low_price(
        self, signal: Dict[str, Any], market_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """为低价格位置增强信号"""
        try:
            price_position = market_data.get("composite_price_position", 50.0)

            if not self.is_applicable(price_position):
                return signal

            level = self.get_price_level(price_position)
            logger.info(
                f"🎯 应用低价格位置策略 - 级别: {level}, 位置: {price_position:.1f}%"
            )

            # 获取原始信号参数
            original_signal = signal.get("signal", "HOLD")
            original_confidence = signal.get("confidence", 0.5)
            original_reason = signal.get("reason", "")

            # 根据价格位置级别应用不同的增强
            if level == "extreme_low":
                enhanced_signal = self._apply_extreme_low_strategy(signal, market_data)
            elif level == "low":
                enhanced_signal = self._apply_low_strategy(signal, market_data)
            elif level == "moderate_low":
                enhanced_signal = self._apply_moderate_low_strategy(signal, market_data)
            else:
                return signal

            # 记录增强信息
            enhanced_signal["low_price_strategy_applied"] = True
            enhanced_signal["price_level"] = level
            enhanced_signal["price_position"] = price_position

            return enhanced_signal

        except Exception as e:
            logger.error(f"低价格位置策略增强失败: {e}")
            return signal

    def _apply_extreme_low_strategy(
        self, signal: Dict[str, Any], market_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """应用极低位策略（<15%）"""
        enhanced = signal.copy()

        # 检查是否处于强势下跌趋势
        trend_strength = market_data.get("trend_strength", 0.0)
        is_strong_downtrend = trend_strength < -0.3

        if is_strong_downtrend:
            # 强势下跌趋势中，即使价格位置极低也不强制买入
            logger.warning(
                f"⚠️ 强势下跌趋势中跳过极低位买入策略 (趋势强度: {trend_strength:.2f})"
            )
            enhanced["reason"] = (
                f"⚠️ 强势下跌中暂不买入 ({market_data.get('composite_price_position', 0):.1f}%) - {signal.get('reason', '')}"
            )
            return enhanced

        # 非强势下跌趋势时，极低位时积极买入
        if signal.get("signal") == "HOLD" and self._check_buy_conditions(market_data):
            enhanced["signal"] = "BUY"
            enhanced["confidence"] = min(1.0, signal.get("confidence", 0.5) * 1.5)
            enhanced["reason"] = (
                f"🚀 极低位反弹信号（{market_data.get('composite_price_position', 0):.1f}%）- {signal.get('reason', '')}"
            )
        elif signal.get("signal") == "BUY":
            # 增强已有买入信号
            enhanced["confidence"] = min(1.0, signal.get("confidence", 0.5) * 1.3)
            enhanced["reason"] = (
                f"🔥 极低位强化买入（{market_data.get('composite_price_position', 0):.1f}%）- {signal.get('reason', '')}"
            )

        return enhanced

    def _apply_low_strategy(
        self, signal: Dict[str, Any], market_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """应用低位策略（15-25%）"""
        enhanced = signal.copy()

        # 检查是否处于强势下跌趋势
        trend_strength = market_data.get("trend_strength", 0.0)
        is_strong_downtrend = trend_strength < -0.3

        if is_strong_downtrend:
            # 强势下跌趋势中，即使价格位置较低也不强制买入
            logger.warning(
                f"⚠️ 强势下跌趋势中跳过低位买入策略 (趋势强度: {trend_strength:.2f})"
            )
            enhanced["reason"] = (
                f"⚠️ 强势下跌中暂不买入 ({market_data.get('composite_price_position', 0):.1f}%) - {signal.get('reason', '')}"
            )
            return enhanced

        # 非强势下跌趋势时，低位时增强买入信号
        if signal.get("signal") == "HOLD" and self._check_buy_conditions(market_data):
            enhanced["signal"] = "BUY"
            enhanced["confidence"] = min(1.0, signal.get("confidence", 0.5) * 1.3)
            enhanced["reason"] = (
                f"📈 低位买入信号（{market_data.get('composite_price_position', 0):.1f}%）- {signal.get('reason', '')}"
            )
        elif signal.get("signal") == "BUY":
            enhanced["confidence"] = min(1.0, signal.get("confidence", 0.5) * 1.2)
            enhanced["reason"] = (
                f"💪 低位增强买入（{market_data.get('composite_price_position', 0):.1f}%）- {signal.get('reason', '')}"
            )

        return enhanced

    def _apply_moderate_low_strategy(
        self, signal: Dict[str, Any], market_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """应用偏低策略（25-35%）"""
        enhanced = signal.copy()

        # 偏低位置时适度增强
        if signal.get("signal") == "BUY":
            enhanced["confidence"] = min(1.0, signal.get("confidence", 0.5) * 1.1)
            enhanced["reason"] = (
                f"👀 偏低位置增强（{market_data.get('composite_price_position', 0):.1f}%）- {signal.get('reason', '')}"
            )

        return enhanced

    def _check_buy_conditions(self, market_data: Dict[str, Any]) -> bool:
        """检查低价格位置的买入条件"""
        try:
            # 获取技术指标
            technical_data = market_data.get("technical_data", {})
            rsi = technical_data.get("rsi", 50)
            macd = technical_data.get("macd", 0)
            adx = technical_data.get("adx", 20)

            # 低价格位置时的宽松条件
            conditions = [
                rsi <= self.params["rsi_buy_threshold"],  # RSI低于45
                macd > 0 or abs(macd) < 10,  # MACD为正或接近零轴
                adx >= 15,  # 趋势强度足够（降低要求）
            ]

            # 满足2个条件即可
            return sum(conditions) >= 2

        except Exception as e:
            logger.error(f"检查低价格位置买入条件失败: {e}")
            return False

    def get_strategy_recommendation(self, price_position: float) -> str:
        """获取策略建议"""
        level = self.get_price_level(price_position)

        recommendations = {
            "extreme_low": "🔥 极低位区域 - 积极寻找买入机会，可适当提高仓位",
            "low": "📈 低位区域 - 增强买入意愿，分批建仓",
            "moderate_low": "👀 偏低位置 - 可考虑逐步建仓，保持关注",
            "normal": "⚖️ 中性位置 - 按标准策略执行",
        }

        return recommendations.get(level, "按标准策略执行")

    def get_risk_adjustment(self, price_position: float) -> Dict[str, float]:
        """获取风险调整参数"""
        level = self.get_price_level(price_position)

        adjustments = {
            "extreme_low": {
                "stop_loss_factor": 1.2,  # 止损放宽20%
                "position_size_factor": 1.5,  # 仓位增加50%
                "take_profit_factor": 1.3,  # 止盈提高30%
            },
            "low": {
                "stop_loss_factor": 1.1,  # 止损放宽10%
                "position_size_factor": 1.3,  # 仓位增加30%
                "take_profit_factor": 1.2,  # 止盈提高20%
            },
            "moderate_low": {
                "stop_loss_factor": 1.05,  # 止损放宽5%
                "position_size_factor": 1.1,  # 仓位增加10%
                "take_profit_factor": 1.1,  # 止盈提高10%
            },
            "normal": {
                "stop_loss_factor": 1.0,
                "position_size_factor": 1.0,
                "take_profit_factor": 1.0,
            },
        }

        return adjustments.get(level, adjustments["normal"])
