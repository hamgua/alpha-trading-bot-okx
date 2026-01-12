"""
智能信号过滤器 - 提高交易信号质量，减少过度交易
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SignalFilterResult:
    """信号过滤结果"""

    passed: bool  # 是否通过过滤
    score: float  # 信号质量评分 (0-100)
    reasons: List[str]  # 通过/拒绝的原因
    confidence_level: str  # 置信度等级: LOW/MEDIUM/HIGH
    recommended_action: str  # 推荐操作: BUY/SELL/HOLD/SKIP
    cooldown_minutes: int  # 建议冷却时间（分钟）


class IntelligentSignalFilter:
    """智能信号过滤器"""

    def __init__(self):
        # 配置参数
        self.min_confidence_high_quality = 0.75  # 高质量信号最低置信度
        self.min_confidence_medium_quality = 0.60  # 中等质量信号最低置信度

        # 信号历史记录（用于避免重复信号）
        self.signal_history: List[Dict] = []

        # 交易冷却配置
        self.last_buy_time: Optional[datetime] = None
        self.last_sell_time: Optional[datetime] = None

        # 配置
        self.min_signal_interval = timedelta(minutes=30)  # 同方向信号最小间隔
        self.max_signals_per_hour = 2  # 每小时最大信号数量
        self.last_hour_signals: List[datetime] = []

    def analyze_signal_quality(
        self,
        signal: Dict[str, Any],
        market_data: Dict[str, Any],
        position_info: Optional[Dict] = None,
    ) -> SignalFilterResult:
        """
        分析信号质量并返回过滤结果

        Args:
            signal: 交易信号
            market_data: 市场数据
            position_info: 当前持仓信息（可选）

        Returns:
            SignalFilterResult: 信号过滤结果
        """
        score = 0.0
        reasons = []
        passed = True
        recommended_action = "HOLD"
        cooldown_minutes = 0

        signal_type = signal.get("signal", signal.get("type", "HOLD")).upper()
        confidence = signal.get("confidence", 0.5)

        # 1. 基础置信度评分 (0-30分)
        if confidence >= 0.85:
            score += 30
            confidence_level = "HIGH"
            reasons.append("✅ 高置信度信号 (>= 85%)")
        elif confidence >= 0.70:
            score += 20
            confidence_level = "MEDIUM"
            reasons.append("✅ 中等置信度信号 (>= 70%)")
        elif confidence >= 0.50:
            score += 10
            confidence_level = "LOW"
            reasons.append("⚠️  低置信度信号 (< 70%)")
        else:
            score += 0
            confidence_level = "LOW"
            reasons.append("❌ 置信度过低 (< 50%)")
            passed = False

        # 2. 市场波动率分析 (0-20分)
        atr_percentage = market_data.get("atr_percentage", 0)
        volatility_regime = market_data.get("volatility_regime", "unknown")

        if volatility_regime == "low" or atr_percentage < 0.2:
            # 低波动市场
            if signal_type in ["BUY", "SELL"]:
                score -= 15
                reasons.append(f"⚠️ 低波动市场不适合主动交易 (ATR={atr_percentage:.2%})")
                cooldown_minutes = 45  # 建议45分钟冷却
                recommended_action = "HOLD"
        elif volatility_regime == "high" or atr_percentage > 0.5:
            # 高波动市场
            score += 10
            reasons.append(f"✅ 高波动市场适合捕捉趋势 (ATR={atr_percentage:.2%})")
        else:
            # 正常波动
            score += 5
            reasons.append(f"✅ 波动率适中 (ATR={atr_percentage:.2%})")

        # 3. 价格位置分析 (0-15分)
        price_position = market_data.get("composite_price_position", 50)

        if signal_type == "BUY":
            # 买入信号
            if price_position < 25:
                score += 15
                reasons.append(f"✅ 价格处于低位区间 ({price_position:.1f}%)")
            elif price_position < 40:
                score += 10
                reasons.append(f"✅ 价格处于中低位区间 ({price_position:.1f}%)")
            elif price_position > 60:
                score -= 10
                reasons.append(
                    f"⚠️ 价格处于高位区间，买入风险高 ({price_position:.1f}%)"
                )
            else:
                score += 5
                reasons.append(f"✅ 价格处于中等区间 ({price_position:.1f}%)")

        elif signal_type == "SELL":
            # 卖出信号
            if price_position > 75:
                score += 15
                reasons.append(f"✅ 价格处于高位区间 ({price_position:.1f}%)")
            elif price_position > 60:
                score += 10
                reasons.append(f"✅ 价格处于中高位区间 ({price_position:.1f}%)")
            elif price_position < 40:
                score -= 10
                reasons.append(
                    f"⚠️ 价格处于低位区间，卖出风险高 ({price_position:.1f}%)"
                )
            else:
                score += 5
                reasons.append(f"✅ 价格处于中等区间 ({price_position:.1f}%)")

        # 4. 技术指标确认 (0-20分)
        tech_data = market_data.get("technical_data", {})
        rsi = tech_data.get("rsi", 50)
        macd = tech_data.get("macd", 0)
        macd_histogram = tech_data.get("macd_histogram", 0)

        if signal_type == "BUY":
            # 买入需要RSI不超买
            if rsi < 30:
                score += 10
                reasons.append(f"✅ RSI超卖 ({rsi:.1f})")
            elif rsi < 45:
                score += 5
                reasons.append(f"✅ RSI偏低 ({rsi:.1f})")
            elif rsi > 70:
                score -= 15
                reasons.append(f"❌ RSI超买 ({rsi:.1f})，不适合买入")
                passed = False
            else:
                score += 0

            # 买入需要MACD向上
            if macd_histogram > 0:
                score += 10
                reasons.append(f"✅ MACD柱状图向上 ({macd_histogram:.2f})")
            else:
                score -= 5
                reasons.append(f"⚠️ MACD柱状图向下 ({macd_histogram:.2f})")

        elif signal_type == "SELL":
            # 卖出需要RSI不超卖
            if rsi > 70:
                score += 10
                reasons.append(f"✅ RSI超买 ({rsi:.1f})")
            elif rsi > 55:
                score += 5
                reasons.append(f"✅ RSI偏高 ({rsi:.1f})")
            elif rsi < 30:
                score -= 15
                reasons.append(f"❌ RSI超卖 ({rsi:.1f})，不适合卖出")
                passed = False
            else:
                score += 0

            # 卖出需要MACD向下
            if macd_histogram < 0:
                score += 10
                reasons.append(f"✅ MACD柱状图向下 ({macd_histogram:.2f})")
            else:
                score -= 5
                reasons.append(f"⚠️ MACD柱状图向上 ({macd_histogram:.2f})")

        # 5. 信号一致性检查 (0-15分)
        signal_sources = signal.get("sources", [])
        if len(signal_sources) >= 2:
            # 多AI信号融合
            buy_count = sum(
                1 for s in signal_sources if s.get("signal", "").upper() == "BUY"
            )
            sell_count = sum(
                1 for s in signal_sources if s.get("signal", "").upper() == "SELL"
            )
            hold_count = sum(
                1 for s in signal_sources if s.get("signal", "").upper() == "HOLD"
            )
            total = len(signal_sources)

            consensus = max(buy_count, sell_count, hold_count) / total

            if signal_type == "BUY" and consensus >= 0.8:
                score += 15
                reasons.append(f"✅ 高度一致的买入信号 ({consensus * 100:.0f}%)")
            elif signal_type == "BUY" and consensus < 0.6:
                score -= 10
                reasons.append(f"⚠️ 信号分歧大 ({consensus * 100:.0f}%)")
                passed = False
            elif signal_type == "BUY" and hold_count / total > 0.5:
                score -= 15
                reasons.append("❌ 多数AI建议观望，不建议买入")
                passed = False

        # 6. 交易频率控制 (0-20分)
        current_time = datetime.now()

        if signal_type == "BUY":
            # 检查买入冷却
            if self.last_buy_time:
                time_since_last = current_time - self.last_buy_time
                if time_since_last < self.min_signal_interval:
                    score -= 20
                    reasons.append(
                        f"❌ 距离上次买入仅{time_since_last.total_seconds() / 60:.1f}分钟，未达到冷却期"
                    )
                    passed = False
                    recommended_action = "SKIP"
                else:
                    score += 5
                    reasons.append(f"✅ 已通过买入冷却期")

            # 检查每小时信号数量
            self._cleanup_old_signals(current_time)
            recent_signals = [
                t
                for t in self.last_hour_signals
                if (current_time - t).total_seconds() < 3600
            ]

            if len(recent_signals) >= self.max_signals_per_hour:
                score -= 15
                reasons.append(f"❌ 本小时已有{len(recent_signals)}个信号，达到上限")
                passed = False
                recommended_action = "SKIP"
                cooldown_minutes = 30
            else:
                score += 5
                reasons.append(
                    f"✅ 本小时信号数量正常 ({len(recent_signals)}/{self.max_signals_per_hour})"
                )

        elif signal_type == "SELL":
            # 检查卖出冷却
            if self.last_sell_time:
                time_since_last = current_time - self.last_sell_time
                if time_since_last < self.min_signal_interval:
                    score -= 20
                    reasons.append(
                        f"❌ 距离上次卖出仅{time_since_last.total_seconds() / 60:.1f}分钟，未达到冷却期"
                    )
                    passed = False
                    recommended_action = "SKIP"
                else:
                    score += 5
                    reasons.append(f"✅ 已通过卖出冷却期")

        # 7. 持仓状态检查 (0-10分)
        if position_info:
            has_position = position_info.get("has_position", False)
            position_side = position_info.get("side", None)

            if has_position:
                if signal_type == "BUY" and position_side == "long":
                    # 已有多头，继续买入需要加仓逻辑
                    if position_info.get("can_add_position", False):
                        score += 5
                        reasons.append("✅ 可以加仓")
                    else:
                        score -= 10
                        reasons.append("⚠️ 已有持仓，建议先管理现有仓位")
                        passed = False
                        recommended_action = "HOLD"

                elif signal_type == "SELL" and position_side == "long":
                    # 有多头，建议平仓而不是做空
                    score += 10
                    reasons.append("✅ 有多头，卖出信号转为平仓信号")
                    recommended_action = "SELL"  # 保持SELL操作

        # 8. 趋势方向确认 (0-10分) - 增强趋势判断权重
        trend_strength = market_data.get("trend_strength", 0)
        trend_direction = market_data.get("trend_direction", "neutral")

        if signal_type == "BUY":
            if trend_direction == "up" and abs(trend_strength) > 0.3:
                score += 15  # 增强上升趋势权重
                reasons.append(f"✅ 上升趋势 (强度={trend_strength:.2f})")
            elif trend_direction == "down":
                if abs(trend_strength) > 0.5:
                    score -= 25  # 增强下跌趋势惩罚
                    reasons.append(
                        f"❌ 强烈下跌趋势，不适合买入 (强度={trend_strength:.2f})"
                    )
                    passed = False
                    recommended_action = "HOLD"
                    cooldown_minutes = 90  # 下跌趋势建议1.5小时冷却
                else:
                    score -= 10  # 轻微下跌趋势也给予惩罚
                    reasons.append(
                        f"⚠️ 下跌趋势，不建议买入 (强度={trend_strength:.2f})"
                    )
            elif trend_direction == "neutral":
                score += 0
                reasons.append("⚠️ 趋势不明，需要其他指标确认")

        # 9. 评分修正和最终判断
        # 确保评分在0-100范围内
        score = max(0, min(100, score))

        # 根据评分确定是否通过 - 提高BUY信号质量阈值
        if signal_type == "BUY":
            # BUY信号需要更高的质量要求
            min_buy_score = 60  # 提高BUY信号最低评分
            if passed and score >= min_buy_score:
                passed = True
                recommended_action = signal_type
            else:
                passed = False
                recommended_action = "HOLD"  # BUY信号质量不足转为观望
        else:
            # 其他信号使用原有逻辑
            if passed and score >= 60:
                passed = True
                recommended_action = signal_type
            elif passed and score >= 40:
                passed = True
                recommended_action = "HOLD"  # 低质量信号转为观望
            else:
                passed = False
                recommended_action = "SKIP"

        # 更新信号历史
        if signal_type in ["BUY", "SELL"]:
            self.signal_history.append(
                {
                    "timestamp": current_time,
                    "type": signal_type,
                    "score": score,
                    "passed": passed,
                }
            )

            # 更新最近信号时间
            if signal_type == "BUY":
                self.last_buy_time = current_time
                self.last_hour_signals.append(current_time)
            elif signal_type == "SELL":
                self.last_sell_time = current_time
                self.last_hour_signals.append(current_time)

        # 生成建议的冷却时间
        if not passed and cooldown_minutes == 0:
            if score < 40:
                cooldown_minutes = 30  # 低质量信号，冷却30分钟
            else:
                cooldown_minutes = 15  # 中等质量信号，冷却15分钟

        # 整理原因
        reasons_sorted = sorted(reasons, key=lambda x: ("❌" in x, "⚠️" in x, "✅" in x))

        return SignalFilterResult(
            passed=passed,
            score=score,
            reasons=reasons_sorted,
            confidence_level=confidence_level,
            recommended_action=recommended_action,
            cooldown_minutes=cooldown_minutes,
        )

    def _cleanup_old_signals(self, current_time: datetime):
        """清理超过1小时的信号记录"""
        self.last_hour_signals = [
            t
            for t in self.last_hour_signals
            if (current_time - t).total_seconds() < 3600
        ]

    def get_signal_statistics(self) -> Dict[str, Any]:
        """获取信号统计信息"""
        if not self.signal_history:
            return {
                "total_signals": 0,
                "passed_signals": 0,
                "pass_rate": 0.0,
                "avg_score": 0.0,
            }

        total = len(self.signal_history)
        passed = sum(1 for s in self.signal_history if s["passed"])
        scores = [s["score"] for s in self.signal_history]

        return {
            "total_signals": total,
            "passed_signals": passed,
            "pass_rate": passed / total if total > 0 else 0.0,
            "avg_score": sum(scores) / len(scores) if scores else 0.0,
            "last_24h_signals": len(
                [
                    s
                    for s in self.signal_history
                    if (datetime.now() - s["timestamp"]).total_seconds() < 86400
                ]
            ),
        }

    def reset_history(self):
        """重置信号历史（通常在新的一天开始时调用）"""
        self.signal_history = []
        self.last_hour_signals = []
        logger.info("信号过滤器历史已重置")
