"""
BUY信号专项优化器 - 针对qwen BUY信号导致亏损的优化
基于2025-12-25交易记录分析
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import numpy as np

logger = logging.getLogger(__name__)


class BuySignalOptimizer:
    """BUY信号专项优化器"""

    def __init__(self):
        # BUY信号专项优化参数 - 基础配置（优化后：放宽限制，允许更多交易机会）
        self.base_optimizations = {
            # 价格位置限制 - 放宽至90%
            "max_price_position": 0.90,  # 0.85 -> 0.90
            "min_price_position": 0.15,
            # RSI限制 - 放宽至70
            "max_rsi_for_buy": 70,  # 65 -> 70
            "min_rsi_for_buy": 35,
            # ATR波动率限制 - 降低最低阈值
            "min_atr_for_buy": 0.10,  # 0.15 -> 0.10
            "max_atr_for_buy": 3.0,
            # 趋势要求 - 降低最低要求
            "min_trend_strength": 0.15,  # 0.2 -> 0.15
            "min_adx": 15,  # 20 -> 15
            # 成交量要求 - 降低最低比例
            "min_volume_ratio": 0.6,  # 0.8 -> 0.6
            "max_volume_spike": 3.0,
            # 时间窗口限制
            "avoid_last_hour": True,
            "cooldown_minutes": 20,  # 30 -> 20
        }

        # 分级风控配置 - 基于趋势强度动态调整（优化后：提高强制HOLD的阈值）
        self.dynamic_thresholds = {
            "strong_trend": {  # 趋势强度 > 0.5
                "max_price_position": 0.98,
                "max_rsi_for_buy": 80,
                "risk_factor_threshold": 5,  # 4 -> 5
                "price_position_weight": 0.5,
                "rsi_weight": 0.3,
                "trend_weight": 1.5,
            },
            "medium_trend": {  # 趋势强度 0.3-0.5
                "max_price_position": 0.95,  # 0.90 -> 0.95
                "max_rsi_for_buy": 75,  # 70 -> 75
                "risk_factor_threshold": 4,  # 3 -> 4
                "price_position_weight": 0.7,
                "rsi_weight": 0.5,
                "trend_weight": 1.2,
            },
            "weak_trend": {  # 趋势强度 < 0.3
                "max_price_position": 0.90,  # 0.85 -> 0.90
                "max_rsi_for_buy": 70,  # 65 -> 70
                "risk_factor_threshold": 4,  # 3 -> 4
                "price_position_weight": 0.8,
                "rsi_weight": 0.7,
                "trend_weight": 0.8,
            },
        }

        # 分级风控配置 - 基于趋势强度动态调整（优化后：降低风险因素阈值）
        self.dynamic_thresholds = {
            "strong_trend": {  # 趋势强度 > 0.5
                "max_price_position": 0.98,  # 放宽至98%
                "max_rsi_for_buy": 80,  # 放宽至80
                "risk_factor_threshold": 5,  # 原为4，5个因素才强制HOLD
                "price_position_weight": 0.5,  # 降低权重
                "rsi_weight": 0.3,  # 降低权重
                "trend_weight": 1.5,  # 提高趋势权重
            },
            "medium_trend": {  # 趋势强度 0.3-0.5
                "max_price_position": 0.95,  # 原为90%，放宽至95%
                "max_rsi_for_buy": 75,  # 原为70，放宽至75
                "risk_factor_threshold": 4,  # 原为3，4个因素才强制HOLD
                "price_position_weight": 0.7,
                "rsi_weight": 0.5,
                "trend_weight": 1.2,
            },
            "weak_trend": {  # 趋势强度 < 0.3
                "max_price_position": 0.90,  # 原为85%，放宽至90%
                "max_rsi_for_buy": 70,  # 原为65，放宽至70
                "risk_factor_threshold": 4,  # 原为3，4个因素才强制HOLD
                "price_position_weight": 0.8,  # 降低权重
                "rsi_weight": 0.7,  # 降低权重
                "trend_weight": 0.8,  # 降低趋势权重
            },
        }

        # 记录BUY信号历史
        self.buy_signal_history = []
        self.recent_buy_signals = []  # 最近30分钟的BUY信号

    def _calculate_moving_averages(
        self, close_prices: List[float], periods: List[int] = [20, 50, 200]
    ) -> Dict[int, float]:
        """计算移动平均线

        Args:
            close_prices: 收盘价列表
            periods: 周期列表

        Returns:
            周期->MA值的字典
        """
        mas = {}
        prices = np.array(close_prices)
        for period in periods:
            if len(prices) >= period:
                mas[period] = float(np.mean(prices[-period:]))
        return mas

    def _check_pullback_opportunity(
        self,
        current_price: float,
        close_prices: List[float],
        trend_direction: str = "up",
    ) -> tuple:
        """检查是否处于回调买入机会

        Args:
            current_price: 当前价格
            close_prices: 收盘价历史
            trend_direction: 趋势方向

        Returns:
            (是否回调机会, 回调幅度, 说明)
        """
        if not close_prices or len(close_prices) < 20:
            return False, 0.0, "数据不足"

        if trend_direction != "up":
            return False, 0.0, "非上涨趋势，不考虑回调买入"

        # 计算移动平均线
        mas = self._calculate_moving_averages(close_prices, [20, 50, 200])
        if not mas:
            return False, 0.0, "均线数据不足"

        # 获取短期均线
        short_ma_period = min(mas.keys())
        short_ma = mas[short_ma_period]

        # 计算价格到均线的回调距离
        if current_price > short_ma:
            distance = (current_price - short_ma) / current_price
            pullback_pct = distance * 100

            # 回调距离小于5%认为是合理回调
            if distance <= 0.05:
                return (
                    True,
                    pullback_pct,
                    f"回调至{short_ma_period}日均线附近({pullback_pct:.1f}%)",
                )
            else:
                return (
                    False,
                    pullback_pct,
                    f"回调过深({pullback_pct:.1f}%)，超过5%",
                )
        else:
            return False, 0.0, f"价格低于{short_ma_period}日均线"

    def _calculate_recent_trend(self, close_prices: List[float]) -> int:
        """计算近期趋势方向"""
        if len(close_prices) < 2:
            return 0
        increases = 0
        for i in range(1, len(close_prices)):
            if close_prices[i] > close_prices[i - 1]:
                increases += 1
            elif close_prices[i] < close_prices[i - 1]:
                increases -= 1
        return increases

    def _get_trend_level(self, trend_strength: float) -> str:
        """根据趋势强度返回趋势级别"""
        if trend_strength > 0.6:  # 0.5 -> 0.6 放宽阈值
            return "strong_trend"
        elif trend_strength > 0.25:  # 0.3 -> 0.25 放宽阈值
            return "medium_trend"
        else:
            return "weak_trend"

    def _get_dynamic_thresholds(self, trend_strength: float) -> dict:
        """获取基于趋势强度的动态阈值"""
        trend_level = self._get_trend_level(trend_strength)
        return self.dynamic_thresholds[trend_level]

    def optimize_buy_signals(
        self, signals: List[Dict[str, Any]], market_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """优化BUY信号"""
        optimized_signals = []

        for signal in signals:
            signal_type = signal.get("signal", "HOLD").upper()
            provider = signal.get("provider", "unknown")

            # 只对BUY信号进行优化
            if signal_type == "BUY":
                optimized_signal = self._optimize_buy_signal(
                    signal, market_data, provider
                )
                optimized_signals.append(optimized_signal)

                # 记录BUY信号历史
                self._record_buy_signal(optimized_signal, market_data)
            else:
                # 非BUY信号直接通过
                optimized_signals.append(signal)

        return optimized_signals

    def _optimize_buy_signal(
        self, signal: Dict[str, Any], market_data: Dict[str, Any], provider: str
    ) -> Dict[str, Any]:
        """优化单个BUY信号"""
        optimized = signal.copy()
        original_confidence = signal.get("confidence", 0.5)
        reason = signal.get("reason", "")

        # 记录优化开始
        logger.debug(
            f"🎯 {provider.upper()} BUY信号优化开始 - 原始信心度: {original_confidence:.2f}"
        )

        # Ensure 'reason' key exists
        if "reason" not in optimized:
            optimized["reason"] = ""

        # 获取技术指标
        technical_data = market_data.get("technical_data", {})
        price_position = technical_data.get("price_position", 0.5)
        rsi = technical_data.get("rsi", 50)
        adx = technical_data.get("adx", 0)
        trend_strength = technical_data.get("trend_strength", 0)

        # 获取市场数据
        current_price = market_data.get("price", 0)
        atr_percentage = market_data.get("atr_percentage", 0)
        volume = market_data.get("volume", 0)
        avg_volume = market_data.get("avg_volume_24h", volume)

        # 记录当前市场条件
        logger.debug(
            f"📊 市场条件 - 价格位置: {price_position * 100:.1f}%, RSI: {rsi:.1f}, ATR: {atr_percentage:.2f}%, 趋势强度: {trend_strength:.2f}"
        )

        # 获取基于趋势强度的动态阈值
        thresholds = self._get_dynamic_thresholds(trend_strength)

        # 1. 价格位置检查（动态风控）
        if price_position > thresholds["max_price_position"]:
            # 🔥 高位检查：首先检查是否是回调买入机会
            close_prices = market_data.get("close_prices", [])
            trend_direction = market_data.get("trend_direction", "neutral")

            is_pullback, pullback_pct, pullback_reason = (
                self._check_pullback_opportunity(
                    current_price, close_prices, trend_direction
                )
            )

            if is_pullback:
                # 回调买入机会：允许买入，降低惩罚
                optimized["reason"] += (
                    f" | ✅ 回调买入机会 - {pullback_reason}，允许买入"
                )
                logger.info(
                    f"✅ {provider.upper()}: 回调买入机会 - 价格位置{price_position * 100:.1f}%但{pullback_reason}，允许买入"
                )
                # 不降低信心度，保持原信号
            else:
                # 非回调机会：正常高位风险处理
                confidence_reduction = 0.15 * thresholds["price_position_weight"]
                optimized["confidence"] = max(
                    original_confidence - confidence_reduction, 0.3
                )
                optimized["reason"] += (
                    f" | ⚠️ 价格处于{price_position * 100:.1f}%高位，风险较高（趋势强度：{trend_strength:.2f}）"
                )
                logger.debug(
                    f"🚨 价格位置风险: {price_position * 100:.1f}% > {thresholds['max_price_position'] * 100:.0f}%，降低信心度{confidence_reduction * 100:.0f}%"
                )

                # 如果信心度降得太低，考虑转为HOLD
                if optimized["confidence"] < 0.45:
                    optimized["signal"] = "HOLD"
                    optimized["reason"] += " | 高位风险过大，建议观望"
                    logger.info(
                        f"🔄 {provider.upper()}: BUY转HOLD - 价格位置风险过高（趋势强度：{trend_strength:.2f}）"
                    )

        # 2. RSI检查（动态风控）
        elif rsi > thresholds["max_rsi_for_buy"]:
            confidence_reduction = 0.1 * thresholds["rsi_weight"]
            optimized["confidence"] = max(
                original_confidence - confidence_reduction, 0.35
            )
            optimized["reason"] += (
                f" | RSI为{rsi:.1f}，接近超买区域（趋势强度：{trend_strength:.2f}）"
            )
            logger.debug(
                f"🚨 RSI超买风险: {rsi:.1f} > {thresholds['max_rsi_for_buy']}，降低信心度{confidence_reduction * 100:.0f}%"
            )

        # 3. 低波动率陷阱检查
        elif atr_percentage < self.base_optimizations["min_atr_for_buy"]:
            optimized["confidence"] = max(original_confidence - 0.12, 0.35)
            optimized["reason"] += f" | ATR仅{atr_percentage:.2f}%，低波动可能为陷阱"
            logger.debug(
                f"🚨 低波动率陷阱: ATR {atr_percentage:.2f}% < 0.15%，降低信心度12%"
            )

        # 4. 趋势强度检查
        elif trend_strength < self.base_optimizations["min_trend_strength"]:
            optimized["confidence"] = max(original_confidence - 0.08, 0.4)
            optimized["reason"] += f" | 趋势强度{trend_strength:.2f}较弱，买入需谨慎"

        # 5. ADX检查（避免无趋势行情）
        elif adx < self.base_optimizations["min_adx"]:
            optimized["confidence"] = max(original_confidence - 0.08, 0.4)
            optimized["reason"] += f" | ADX为{adx:.1f}，市场无明显趋势"

        # 6. 成交量检查
        elif avg_volume > 0:
            volume_ratio = volume / avg_volume
            if volume_ratio < self.base_optimizations["min_volume_ratio"]:
                optimized["confidence"] = max(original_confidence - 0.06, 0.45)
                optimized["reason"] += (
                    f" | 成交量仅为均值{volume_ratio:.1f}倍，动能不足"
                )

        # 7. 风险累积检查（多个风险因素叠加） - 基于趋势强度的动态风控
        risk_factors = 0
        risk_details = []

        # 获取基于趋势强度的动态阈值
        thresholds = self._get_dynamic_thresholds(trend_strength)

        # 价格位置风险（动态阈值）
        if price_position > thresholds["max_price_position"]:
            risk_factors += thresholds["price_position_weight"]
            risk_details.append(f"价格位置({price_position * 100:.0f}%)")

        # RSI风险（动态阈值）
        if rsi > thresholds["max_rsi_for_buy"]:
            risk_factors += thresholds["rsi_weight"]
            risk_details.append(f"RSI({rsi:.0f})")

        # ATR风险（标准，不受趋势影响）
        if atr_percentage < self.base_optimizations["min_atr_for_buy"]:
            risk_factors += 1.0
            risk_details.append(f"低ATR({atr_percentage:.2f}%)")

        # 趋势强度风险（关键指标，权重更高）
        if (
            trend_strength < self.base_optimizations["min_trend_strength"]
        ):  # 使用绝对阈值
            risk_factors += thresholds["trend_weight"]
            risk_details.append(f"弱趋势({trend_strength:.2f})")

        # 根据趋势强度调整风控严格程度
        risk_threshold = thresholds["risk_factor_threshold"]

        if risk_factors >= risk_threshold:
            # 重度风险 - 根据趋势强度决定是否强制HOLD
            if trend_strength > 0.5:
                # 强趋势市场 - 降低惩罚，保持BUY但大幅降低信心度
                optimized["confidence"] = max(
                    optimized.get("confidence", original_confidence) - 0.3, 0.3
                )
                optimized["reason"] += (
                    f" | 强趋势市场中风险较高({risk_factors:.1f}个风险因素)"
                )
                logger.warning(
                    f"⚠️ {provider.upper()}: 强趋势市场中风险较高 - {', '.join(risk_details)}"
                )
            else:
                # 弱趋势市场 - 维持严格风控
                optimized["signal"] = "HOLD"
                optimized["confidence"] = min(
                    optimized.get("confidence", original_confidence) - 0.2, 0.4
                )
                optimized["reason"] += f" | 累积风险过高({risk_factors:.1f}个风险因素)"
                logger.warning(
                    f"⚠️ {provider.upper()}: 累积风险过高 - {', '.join(risk_details)}，强制转HOLD"
                )
        elif risk_factors >= 2.0:
            # 中度风险 - 降低信心度但不强制HOLD
            confidence_reduction = min(0.15, risk_factors * 0.08)
            optimized["confidence"] = max(
                optimized.get("confidence", original_confidence) - confidence_reduction,
                0.45,
            )
            optimized["reason"] += f" | 检测到风险因素({risk_factors:.1f}个)"
            logger.info(
                f"⚠️ {provider.upper()}: 检测到{risk_factors:.1f}个风险因素 - {', '.join(risk_details)}"
            )

        # 8. 增强买入信号（满足多个有利条件）
        else:
            # 检查是否有利条件组合
            favorable_conditions = 0

            # 低位买入
            if price_position < 0.35:
                favorable_conditions += 1
                optimized["reason"] += " | 低位买入机会"

            # RSI超卖
            if rsi < 40:
                favorable_conditions += 1
                optimized["reason"] += f" | RSI超卖({rsi:.1f})"

            # 强趋势
            if trend_strength > 0.5 and adx > 25:
                favorable_conditions += 1
                optimized["reason"] += " | 强趋势确认"

            # 成交量放大
            if avg_volume > 0:
                volume_ratio = volume / avg_volume
                if volume_ratio > 1.2:
                    favorable_conditions += 1
                    optimized["reason"] += f" | 成交量放大{volume_ratio:.1f}倍"

            # 根据有利条件数量增强信号
            if favorable_conditions >= 3:
                optimized["confidence"] = min(original_confidence + 0.1, 0.9)
                optimized["reason"] += " | 多重利好确认，强烈买入信号"
                logger.info(
                    f"✅ {provider.upper()}: 信号增强 - 满足{favorable_conditions}个有利条件"
                )
            elif favorable_conditions >= 2:
                optimized["confidence"] = min(original_confidence + 0.05, 0.85)
                optimized["reason"] += " | 双重利好确认"
                logger.debug(
                    f"✅ {provider.upper()}: 信号增强 - 满足{favorable_conditions}个有利条件"
                )

        # 8. 提供商特定优化
        if provider == "qwen":
            logger.debug(f"🔧 {provider.upper()}: 应用提供商特定优化")
            optimized = self._optimize_qwen_buy_signal(optimized, market_data)
        elif provider == "deepseek":
            logger.debug(f"🔧 {provider.upper()}: 应用提供商特定优化")
            optimized = self._optimize_deepseek_buy_signal(optimized, market_data)
        elif provider == "kimi":
            logger.debug(f"🔧 {provider.upper()}: 应用提供商特定优化")
            optimized = self._optimize_kimi_buy_signal(optimized, market_data)
        elif provider == "openai":
            logger.debug(f"🔧 {provider.upper()}: 应用提供商特定优化")
            optimized = self._optimize_openai_buy_signal(optimized, market_data)

        # 9. 时间窗口检查（避免特定时段）
        current_hour = datetime.now().hour
        current_minute = datetime.now().minute

        # 避免最后一小时交易（交易所结算风险）
        if self.base_optimizations["avoid_last_hour"] and current_hour == 23:
            optimized["confidence"] = max(
                optimized.get("confidence", original_confidence) - 0.1, 0.3
            )
            optimized["reason"] += " | 避开最后一小时交易"

        # 冷却期检查
        if self._is_in_cooldown():
            optimized["confidence"] = max(
                optimized.get("confidence", original_confidence) - 0.15, 0.25
            )
            optimized["reason"] += " | 买入冷却期内，降低信号强度"

        # 记录优化详情
        if (
            original_confidence != optimized["confidence"]
            or signal.get("signal") != optimized["signal"]
        ):
            change = optimized["confidence"] - original_confidence
            direction = "增强" if change > 0 else "减弱"
            signal_change = ""
            if signal.get("signal") != optimized["signal"]:
                signal_change = f"，信号 {signal.get('signal')} → {optimized['signal']}"

            if abs(change) > 0.1 or signal.get("signal") != optimized["signal"]:
                # 显著变化记录为INFO
                logger.info(
                    f"🔧 {provider.upper()} BUY信号优化: "
                    f"信心 {original_confidence:.2f} → "
                    f"{optimized['confidence']:.2f} ({direction}){signal_change}"
                )
            else:
                # 微小变化记录为DEBUG
                logger.debug(
                    f"🔧 {provider.upper()} BUY信号优化: "
                    f"信心 {original_confidence:.2f} → "
                    f"{optimized['confidence']:.2f} ({direction}){signal_change}"
                )
        else:
            logger.debug(
                f"✅ {provider.upper()} BUY信号无需优化 - 信心度保持 {original_confidence:.2f}"
            )

        # 记录优化结束
        logger.debug(
            f"🎯 {provider.upper()} BUY信号优化完成 - 最终信心度: {optimized['confidence']:.2f}"
        )

        return optimized

    def _optimize_qwen_buy_signal(
        self, signal: Dict[str, Any], market_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """优化qwen的BUY信号（基于历史表现）"""
        optimized = signal.copy()
        reason = signal.get("reason", "")

        # 1. 修正累积变化为0的问题
        if "累积变化为0.00%" in reason:
            change_percent = market_data.get("change_percent", 0)
            if abs(change_percent) > 0.001:  # 有微小变化
                optimized["reason"] = reason.replace(
                    "累积变化为0.00%", f"当前变化{change_percent:+.3f}%"
                )

        # 2. 增强连续涨跌识别
        if "连续涨跌次数为0" in reason:
            close_prices = market_data.get("close_prices", [])
            recent_trend = (
                self._calculate_recent_trend(close_prices[-5:])
                if len(close_prices) >= 5
                else 0
            )
            if recent_trend != 0:
                optimized["reason"] = reason.replace(
                    "连续涨跌次数为0", f"连续{recent_trend}个周期同向变化"
                )

        # 3. 增强低位识别
        technical_data = market_data.get("technical_data", {})
        price_position = technical_data.get("price_position", 0.5)
        rsi = technical_data.get("rsi", 50)

        if price_position < 0.25 and rsi < 40:
            # 低位+超卖，增强信号
            current_confidence = optimized.get(
                "confidence", signal.get("confidence", 0.5)
            )
            optimized["confidence"] = min(current_confidence + 0.08, 0.85)
            optimized["reason"] += " | 低位超卖增强信号"

        return optimized

    def _optimize_deepseek_buy_signal(
        self, signal: Dict[str, Any], market_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """优化deepseek的BUY信号"""
        optimized = signal.copy()
        reason = signal.get("reason", "")

        # 获取price_position用于多个检查
        technical_data = market_data.get("technical_data", {})
        price_position = technical_data.get("price_position", 0.5)

        # 1. 平衡过度谨慎的BUY信号
        if "建议谨慎" in reason or "风险" in reason:
            if price_position < 0.4:  # 实际处于低位
                # 降低谨慎程度
                current_confidence = optimized.get(
                    "confidence", signal.get("confidence", 0.5)
                )
                optimized["confidence"] = min(current_confidence + 0.05, 0.8)
                optimized["reason"] = reason.replace("建议谨慎", "位置相对安全")

        # 2. 增强区间位置判断精度
        import re

        position_matches = re.findall(r"(\d+(?:\.\d+)?)%", reason)
        if position_matches:
            position = float(position_matches[0])
            if position > 80 and price_position < 0.7:  # 判断有误
                optimized["reason"] += f" | 实际位置{price_position * 100:.1f}%更安全"

        return optimized

    def _optimize_kimi_buy_signal(
        self, signal: Dict[str, Any], market_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """优化kimi的BUY信号"""
        optimized = signal.copy()
        reason = signal.get("reason", "")

        # 1. 验证突破有效性
        if "突破" in reason:
            change_percent = market_data.get("change_percent", 0)
            atr_percentage = market_data.get("atr_percentage", 0)

            # 突破需要超过0.5倍ATR才视为有效
            if abs(change_percent) < atr_percentage * 0.5:
                current_confidence = optimized.get(
                    "confidence", signal.get("confidence", 0.5)
                )
                optimized["confidence"] = max(current_confidence - 0.06, 0.45)
                optimized["reason"] += (
                    f" | 突破幅度不足({change_percent:+.2f}% < {atr_percentage * 0.5:.2f}%)"
                )

        # 2. 验证成交量放大
        if "成交量放大" in reason:
            volume = market_data.get("volume", 0)
            avg_volume = market_data.get("avg_volume_24h", volume)
            if avg_volume > 0:
                actual_ratio = volume / avg_volume
                # 如果实际比例与理由不符，调整信号
                if actual_ratio < 1.2:  # 放大不足
                    current_confidence = optimized.get(
                        "confidence", signal.get("confidence", 0.5)
                    )
                    optimized["confidence"] = max(current_confidence - 0.05, 0.5)
                    optimized["reason"] += f" | 实际仅{actual_ratio:.1f}倍，放大不足"

        return optimized

    def _optimize_openai_buy_signal(
        self, signal: Dict[str, Any], market_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """优化openai的BUY信号"""
        optimized = signal.copy()
        reason = signal.get("reason", "")

        # 1. 验证概率数值
        import re

        prob_matches = re.findall(r"(\d+(?:\.\d+)?)%", reason)
        if prob_matches:
            claimed_prob = float(prob_matches[0])
            # 检查是否与市场条件匹配
            technical_data = market_data.get("technical_data", {})
            rsi = technical_data.get("rsi", 50)
            trend_strength = technical_data.get("trend_strength", 0)

            # 简单验证：如果RSI>60且声称70%上涨概率，需要谨慎
            if claimed_prob > 70 and rsi > 60:
                current_confidence = optimized.get(
                    "confidence", signal.get("confidence", 0.5)
                )
                optimized["confidence"] = max(current_confidence - 0.08, 0.4)
                optimized["reason"] += " | 高概率与超买RSI矛盾"

        # 2. 验证风险回报比
        if "风险回报比" in reason or "回报" in reason:
            price_position = market_data.get("technical_data", {}).get(
                "price_position", 0.5
            )
            if price_position > 0.7:  # 高位买入，风险较大
                current_confidence = optimized.get(
                    "confidence", signal.get("confidence", 0.5)
                )
                optimized["confidence"] = max(current_confidence - 0.1, 0.35)
                optimized["reason"] += " | 高位买入，风险回报比不佳"

        return optimized

    def _record_buy_signal(
        self, signal: Dict[str, Any], market_data: Dict[str, Any]
    ) -> None:
        """记录BUY信号"""
        record = {
            "timestamp": datetime.now(),
            "provider": signal.get("provider", "unknown"),
            "confidence": signal.get("confidence", 0),
            "price": market_data.get("price", 0),
            "price_position": market_data.get("technical_data", {}).get(
                "price_position", 0.5
            ),
            "rsi": market_data.get("technical_data", {}).get("rsi", 50),
            "atr_percentage": market_data.get("atr_percentage", 0),
            "reason": signal.get("reason", ""),
            "market_data": market_data.copy(),
        }

        self.buy_signal_history.append(record)
        self.recent_buy_signals.append(record)

        # 只保留最近30分钟的记录
        cutoff_time = datetime.now() - timedelta(minutes=30)
        self.recent_buy_signals = [
            s for s in self.recent_buy_signals if s["timestamp"] > cutoff_time
        ]

        # 只保留最近1000条历史记录
        if len(self.buy_signal_history) > 1000:
            self.buy_signal_history = self.buy_signal_history[-1000:]

    def _is_in_cooldown(self) -> bool:
        """检查是否在买入冷却期内"""
        if not self.recent_buy_signals:
            return False

        # 最近30分钟内是否有BUY信号
        cutoff_time = datetime.now() - timedelta(minutes=30)
        recent_signals = [
            s for s in self.recent_buy_signals if s["timestamp"] > cutoff_time
        ]

        return len(recent_signals) > 3  # 30分钟内超过3个BUY信号则进入冷却

    def get_buy_signal_stats(self) -> Dict[str, Any]:
        """获取BUY信号统计"""
        if not self.buy_signal_history:
            return {
                "total_signals": 0,
                "recent_signals_30min": 0,
                "provider_distribution": {},
                "avg_confidence": 0.0,
                "avg_price_position": 0.0,
                "avg_rsi": 0.0,
                "in_cooldown": False,
            }

        total_signals = len(self.buy_signal_history)
        recent_signals = len(self.recent_buy_signals)

        # 统计提供商分布
        provider_stats = {}
        for signal in self.buy_signal_history:
            provider = signal["provider"]
            provider_stats[provider] = provider_stats.get(provider, 0) + 1

        # 平均信心度
        avg_confidence = np.mean([s["confidence"] for s in self.buy_signal_history])

        # 平均价格位置
        avg_price_position = np.mean(
            [s["price_position"] for s in self.buy_signal_history]
        )

        # 平均RSI
        avg_rsi = np.mean([s["rsi"] for s in self.buy_signal_history])

        return {
            "total_signals": total_signals,
            "recent_signals_30min": recent_signals,
            "provider_distribution": provider_stats,
            "avg_confidence": avg_confidence,
            "avg_price_position": avg_price_position,
            "avg_rsi": avg_rsi,
            "in_cooldown": self._is_in_cooldown(),
        }
