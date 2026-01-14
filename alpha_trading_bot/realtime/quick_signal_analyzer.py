"""
快速信号分析器 - 渐进式实时化第二阶段
实现价格触发时的快速AI分析，记录但不执行
用于小规模测试和信号质量分析
"""

import asyncio
import logging
import json
import os
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class QuickSignalRecord:
    """快速信号记录"""

    timestamp: datetime
    price_change_percent: float
    signal_type: str  # BUY/SELL/HOLD
    confidence: float
    reason: str
    market_context: Dict[str, Any]
    source: str = "quick_analysis"  # quick_analysis / ai_analysis


@dataclass
class SignalQualityMetrics:
    """信号质量指标"""

    total_signals: int
    buy_signals: int
    sell_signals: int
    hold_signals: int
    avg_confidence: float
    high_confidence_signals: int  # >= 0.85
    medium_confidence_signals: int  # 0.6-0.85
    low_confidence_signals: int  # < 0.6
    price_up_signals: int  # 价格上涨时
    price_down_signals: int  # 价格下跌时
    accuracy_rate: Optional[float] = None  # 准确率（如果有后续数据）


class QuickSignalAnalyzerConfig:
    """快速信号分析器配置"""

    def __init__(
        self,
        # AI分析配置
        enable_ai_analysis: bool = True,  # 是否启用AI分析
        ai_confidence_threshold: float = 0.75,  # AI分析置信度阈值
        max_ai_calls_per_hour: int = 20,  # 每小时最大AI调用次数
        ai_timeout: float = 10.0,  # AI超时时间（秒）
        # 信号记录配置
        record_only: bool = True,  # 仅记录，不执行交易
        min_confidence_to_record: float = 0.5,  # 最低记录置信度
        max_records_per_day: int = 100,  # 每天最大记录数
        # 触发条件配置
        price_change_threshold: float = 0.006,  # 价格变化阈值0.6%
        volume_surge_threshold: float = 2.0,  # 成交量激增阈值
        rsi_extreme_threshold: float = 25,  # RSI极端值阈值
        # 数据存储配置
        data_dir: str = "data/price_monitor",
        save_interval: int = 300,  # 保存间隔（秒）
        # 分析配置
        enable_quality_analysis: bool = True,  # 启用质量分析
        analysis_window_hours: int = 24,  # 分析窗口（小时）
    ):
        self.enable_ai_analysis = enable_ai_analysis
        self.ai_confidence_threshold = ai_confidence_threshold
        self.max_ai_calls_per_hour = max_ai_calls_per_hour
        self.ai_timeout = ai_timeout
        self.record_only = record_only
        self.min_confidence_to_record = min_confidence_to_record
        self.max_records_per_day = max_records_per_day
        self.price_change_threshold = price_change_threshold
        self.volume_surge_threshold = volume_surge_threshold
        self.rsi_extreme_threshold = rsi_extreme_threshold
        self.data_dir = data_dir
        self.save_interval = save_interval
        self.enable_quality_analysis = enable_quality_analysis
        self.analysis_window_hours = analysis_window_hours


class QuickSignalAnalyzer:
    """快速信号分析器 - 第二阶段实现"""

    def __init__(self, config: Optional[QuickSignalAnalyzerConfig] = None):
        self.config = config or QuickSignalAnalyzerConfig()
        self.signals: List[QuickSignalRecord] = []
        self.last_ai_call_time: Optional[datetime] = None
        self.ai_calls_this_hour: int = 0
        self.ai_call_timestamps: List[datetime] = []  # 记录AI调用时间
        self.is_analyzing = False
        self.data_dir: str = self.config.data_dir
        self.last_save_time: Optional[datetime] = None

    async def initialize(self) -> bool:
        """初始化快速信号分析器"""
        try:
            logger.info("正在初始化快速信号分析器...")

            # 确保数据目录存在
            os.makedirs(self.data_dir, exist_ok=True)

            # 加载历史信号
            await self._load_historical_signals()

            # 重置每小时计数
            self._reset_hourly_counters()

            logger.info(
                f"快速信号分析器初始化完成 - AI分析: {self.config.enable_ai_analysis}, "
                f"仅记录模式: {self.config.record_only}, "
                f"数据目录: {self.data_dir}"
            )
            return True

        except Exception as e:
            logger.error(f"快速信号分析器初始化失败: {e}")
            return False

    def _reset_hourly_counters(self):
        """重置每小时计数器"""
        current_hour = datetime.now().replace(minute=0, second=0, microsecond=0)
        self.ai_call_timestamps = [
            t for t in self.ai_call_timestamps if t >= current_hour
        ]
        self.ai_calls_this_hour = len(self.ai_call_timestamps)

    def _check_ai_call_limit(self) -> bool:
        """检查AI调用次数限制"""
        current_hour = datetime.now().replace(minute=0, second=0, microsecond=0)

        # 清理旧记录
        self.ai_call_timestamps = [
            t for t in self.ai_call_timestamps if t >= current_hour
        ]

        if len(self.ai_call_timestamps) >= self.config.max_ai_calls_per_hour:
            logger.warning(
                f"AI调用次数达到上限: {self.config.max_ai_calls_per_hour}/小时"
            )
            return False

        return True

    async def analyze_price_change(
        self,
        price_change_percent: float,
        current_price: float,
        market_data: Dict[str, Any],
    ) -> Optional[QuickSignalRecord]:
        """分析价格变化并生成快速信号

        Args:
            price_change_percent: 价格变化百分比
            current_price: 当前价格
            market_data: 市场数据

        Returns:
            QuickSignalRecord or None: 快速信号记录（仅记录模式，不执行交易）
        """
        try:
            # 检查是否达到触发条件
            if not self._should_trigger_analysis(price_change_percent, market_data):
                return None

            # 检查AI调用限制
            if self.config.enable_ai_analysis and not self._check_ai_call_limit():
                return None

            # 执行快速AI分析
            if self.config.enable_ai_analysis:
                signal = await self._perform_ai_analysis(
                    price_change_percent, current_price, market_data
                )
            else:
                # 简化分析（基于规则）
                signal = self._simple_rule_analysis(
                    price_change_percent, current_price, market_data
                )

            if signal:
                # 记录信号（仅记录，不执行）
                await self._record_signal(signal)

                # 记录AI调用时间
                if self.config.enable_ai_analysis:
                    self.ai_call_timestamps.append(datetime.now())

            return signal

        except Exception as e:
            logger.error(f"价格变化分析失败: {e}")
            return None

    def _should_trigger_analysis(
        self, price_change_percent: float, market_data: Dict[str, Any]
    ) -> bool:
        """判断是否应该触发分析"""
        # 1. 价格变化触发
        if abs(price_change_percent) >= self.config.price_change_threshold:
            return True

        # 2. RSI极端值触发
        rsi = market_data.get("technical_data", {}).get("rsi", 50)
        if rsi is not None:
            if rsi <= self.config.rsi_extreme_threshold or rsi >= (
                100 - self.config.rsi_extreme_threshold
            ):
                return True

        # 3. 成交量激增触发
        volume_ratio = market_data.get("volume_ratio", 1.0)
        if volume_ratio >= self.config.volume_surge_threshold:
            return True

        return False

    async def _perform_ai_analysis(
        self,
        price_change_percent: float,
        current_price: float,
        market_data: Dict[str, Any],
    ) -> Optional[QuickSignalRecord]:
        """执行AI快速分析"""
        try:
            # 构建简化版AI提示
            prompt = self._build_quick_prompt(
                price_change_percent, current_price, market_data
            )

            # 调用AI（简化版，不使用完整的AI客户端）
            # 这里使用简化的规则模拟AI分析，实际应该调用AI API
            technical_data = market_data.get("technical_data", {})

            # 基于规则生成信号（模拟AI分析结果）
            signal_type, confidence, reason = self._generate_signal_from_analysis(
                price_change_percent, market_data
            )

            # 构建市场上下文
            market_context = {
                "timestamp": datetime.now(),
                "price": current_price,
                "price_change_percent": price_change_percent,
                "rsi": technical_data.get("rsi"),
                "macd": technical_data.get("macd"),
                "volume_ratio": market_data.get("volume_ratio"),
                "trend_direction": market_data.get("trend_direction"),
                "trend_strength": market_data.get("trend_strength"),
                "atr_percentage": market_data.get("atr_percentage"),
            }

            # 创建信号记录
            signal = QuickSignalRecord(
                timestamp=datetime.now(),
                price_change_percent=price_change_percent,
                signal_type=signal_type,
                confidence=confidence,
                reason=reason,
                market_context=market_context,
                source="ai_analysis",
            )

            logger.info(
                f"AI快速分析: {signal_type} (置信度: {confidence:.2f}) - {reason}"
            )

            return signal

        except Exception as e:
            logger.error(f"AI快速分析失败: {e}")
            return None

    def _build_quick_prompt(
        self,
        price_change_percent: float,
        current_price: float,
        market_data: Dict[str, Any],
    ) -> str:
        """构建快速AI提示词"""
        technical_data = market_data.get("technical_data", {})

        trend_direction = market_data.get("trend_direction", "neutral")
        trend_strength = market_data.get("trend_strength", 0.0)
        rsi = technical_data.get("rsi", 50)
        volume_ratio = market_data.get("volume_ratio", 1.0)

        return f"""
【快速分析请求】
价格变化: {price_change_percent:+.2f}%
当前价格: ${current_price:,.2f}
趋势方向: {trend_direction} (强度: {trend_strength:.2f})
RSI: {rsi:.1f}
成交量比: {volume_ratio:.2f}

请给出简短的交易建议（BUY/SELL/HOLD），格式：
SIGNAL: [BUY/SELL/HOLD]
CONFIDENCE: [0-1]
REASON: [简要原因]
"""

    def _generate_signal_from_analysis(
        self, price_change_percent: float, market_data: Dict[str, Any]
    ) -> Tuple[str, float, str]:
        """根据分析生成信号（简化版规则）"""
        technical_data = market_data.get("technical_data", {})
        trend_direction = market_data.get("trend_direction", "neutral")
        trend_strength = market_data.get("trend_strength", 0.0)
        rsi = technical_data.get("rsi", 50)
        volume_ratio = market_data.get("volume_ratio", 1.0)

        # 因素评分
        buy_score = 0
        sell_score = 0
        reasons = []

        # 1. 价格变化方向
        if price_change_percent > 0.01:  # 上涨超过1%
            buy_score += 2
            reasons.append(f"价格快速上涨({price_change_percent:.2%})")
        elif price_change_percent > 0.006:  # 上涨0.6-1%
            buy_score += 1
            reasons.append(f"价格上涨({price_change_percent:.2%})")
        elif price_change_percent < -0.01:  # 下跌超过1%
            sell_score += 2
            reasons.append(f"价格快速下跌({price_change_percent:.2%})")
        elif price_change_percent < -0.006:  # 下跌0.6-1%
            sell_score += 1
            reasons.append(f"价格下跌({price_change_percent:.2%})")

        # 2. 趋势方向
        if trend_direction == "up" and trend_strength > 0.3:
            buy_score += 2
            reasons.append("上涨趋势确认")
        elif trend_direction == "down" and trend_strength > 0.3:
            sell_score += 2
            reasons.append("下跌趋势确认")

        # 3. RSI
        if rsi < 30:
            buy_score += 2
            reasons.append(f"RSI超卖({rsi:.1f})")
        elif rsi < 40:
            buy_score += 1
            reasons.append(f"RSI偏低({rsi:.1f})")
        elif rsi > 70:
            sell_score += 2
            reasons.append(f"RSI超买({rsi:.1f})")
        elif rsi > 60:
            sell_score += 1
            reasons.append(f"RSI偏高({rsi:.1f})")

        # 4. 成交量
        if volume_ratio > 1.5:
            if price_change_percent > 0:
                buy_score += 1
                reasons.append("放量上涨")
            else:
                sell_score += 1
                reasons.append("放量下跌")
        elif volume_ratio < 0.7:
            if price_change_percent > 0:
                buy_score -= 0.5
                reasons.append("缩量上涨，可疑")
            else:
                sell_score -= 0.5
                reasons.append("缩量下跌，可能企稳")

        # 生成最终信号
        if buy_score >= 4 and buy_score > sell_score + 2:
            signal_type = "BUY"
            confidence = min(0.95, 0.6 + buy_score * 0.05)
        elif sell_score >= 4 and sell_score > buy_score + 2:
            signal_type = "SELL"
            confidence = min(0.95, 0.6 + sell_score * 0.05)
        elif buy_score > sell_score + 1:
            signal_type = "BUY"
            confidence = 0.5 + (buy_score - sell_score) * 0.05
        elif sell_score > buy_score + 1:
            signal_type = "SELL"
            confidence = 0.5 + (sell_score - buy_score) * 0.05
        else:
            signal_type = "HOLD"
            confidence = 0.5

        reason = " | ".join(reasons) if reasons else "市场方向不明，建议观望"

        return signal_type, confidence, reason

    def _simple_rule_analysis(
        self,
        price_change_percent: float,
        current_price: float,
        market_data: Dict[str, Any],
    ) -> Optional[QuickSignalRecord]:
        """简化规则分析（不使用AI）"""
        technical_data = market_data.get("technical_data", {})

        trend_direction = market_data.get("trend_direction", "neutral")
        rsi = technical_data.get("rsi", 50)

        # 简单规则
        if price_change_percent > 0.008 and rsi < 60:
            signal_type = "BUY"
            confidence = 0.65
            reason = f"价格快速上涨{price_change_percent:.2%}，RSI中性"
        elif price_change_percent > 0.006 and trend_direction == "up":
            signal_type = "BUY"
            confidence = 0.60
            reason = f"价格上涨{price_change_percent:.2%}，趋势向上"
        elif price_change_percent < -0.008 and rsi > 40:
            signal_type = "SELL"
            confidence = 0.65
            reason = f"价格快速下跌{price_change_percent:.2%}，RSI偏高"
        elif price_change_percent < -0.006 and trend_direction == "down":
            signal_type = "SELL"
            confidence = 0.60
            reason = f"价格下跌{price_change_percent:.2%}，趋势向下"
        elif rsi < 30:
            signal_type = "BUY"
            confidence = 0.55
            reason = f"RSI超卖({rsi:.1f})，可能反弹"
        elif rsi > 70:
            signal_type = "SELL"
            confidence = 0.55
            reason = f"RSI超买({rsi:.1f})，可能回调"
        else:
            signal_type = "HOLD"
            confidence = 0.50
            reason = "无明显交易信号"

        market_context = {
            "timestamp": datetime.now(),
            "price": current_price,
            "price_change_percent": price_change_percent,
            "rsi": rsi,
            "trend_direction": trend_direction,
        }

        return QuickSignalRecord(
            timestamp=datetime.now(),
            price_change_percent=price_change_percent,
            signal_type=signal_type,
            confidence=confidence,
            reason=reason,
            market_context=market_context,
            source="rule_analysis",
        )

    async def _record_signal(self, signal: QuickSignalRecord):
        """记录信号"""
        try:
            # 检查是否满足记录条件
            if signal.confidence < self.config.min_confidence_to_record:
                logger.debug(f"信号置信度过低，不记录: {signal.confidence:.2f}")
                return

            # 添加到记录列表
            self.signals.append(signal)

            # 限制记录数量
            if len(self.signals) > self.config.max_records_per_day:
                self.signals = self.signals[-self.config.max_records_per_day :]

            logger.info(
                f"记录快速信号: {signal.signal_type} @ {signal.timestamp} "
                f"(置信度: {signal.confidence:.2f})"
            )

        except Exception as e:
            logger.error(f"记录信号失败: {e}")

    async def _load_historical_signals(self):
        """加载历史信号"""
        try:
            signals_file = os.path.join(self.data_dir, "quick_signals.json")
            if os.path.exists(signals_file):
                with open(signals_file, "r", encoding="utf-8") as f:
                    signals_data = json.load(f)
                    for signal_data in signals_data:
                        # 处理datetime
                        if "timestamp" in signal_data:
                            if isinstance(signal_data["timestamp"], str):
                                signal_data["timestamp"] = datetime.fromisoformat(
                                    signal_data["timestamp"]
                                )
                        signal = QuickSignalRecord(**signal_data)
                        self.signals.append(signal)
                logger.info(f"已加载 {len(self.signals)} 个历史快速信号")
        except Exception as e:
            logger.warning(f"加载历史信号失败: {e}")

    async def save_signals(self):
        """保存信号到文件"""
        try:
            signals_file = os.path.join(self.data_dir, "quick_signals.json")
            signals_data = [asdict(s) for s in self.signals[-500:]]  # 保存最近500个
            with open(signals_file, "w", encoding="utf-8") as f:
                json.dump(signals_data, f, ensure_ascii=False, indent=2, default=str)
            logger.debug(f"快速信号已保存到 {signals_file}")
        except Exception as e:
            logger.error(f"保存快速信号失败: {e}")

    def get_quality_metrics(self, hours: int = 24) -> SignalQualityMetrics:
        """获取信号质量指标"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        recent_signals = [s for s in self.signals if s.timestamp > cutoff_time]

        if not recent_signals:
            return SignalQualityMetrics(
                total_signals=0,
                buy_signals=0,
                sell_signals=0,
                hold_signals=0,
                avg_confidence=0.0,
                high_confidence_signals=0,
                medium_confidence_signals=0,
                low_confidence_signals=0,
                price_up_signals=0,
                price_down_signals=0,
            )

        # 统计各类信号
        buy_signals = sum(1 for s in recent_signals if s.signal_type == "BUY")
        sell_signals = sum(1 for s in recent_signals if s.signal_type == "SELL")
        hold_signals = sum(1 for s in recent_signals if s.signal_type == "HOLD")

        # 置信度分布
        high_confidence = sum(1 for s in recent_signals if s.confidence >= 0.85)
        medium_confidence = sum(1 for s in recent_signals if 0.6 <= s.confidence < 0.85)
        low_confidence = sum(1 for s in recent_signals if s.confidence < 0.6)

        # 价格方向分布
        price_up = sum(1 for s in recent_signals if s.price_change_percent > 0)
        price_down = sum(1 for s in recent_signals if s.price_change_percent < 0)

        # 平均置信度
        avg_confidence = np.mean([s.confidence for s in recent_signals])

        return SignalQualityMetrics(
            total_signals=len(recent_signals),
            buy_signals=buy_signals,
            sell_signals=sell_signals,
            hold_signals=hold_signals,
            avg_confidence=avg_confidence,
            high_confidence_signals=high_confidence,
            medium_confidence_signals=medium_confidence,
            low_confidence_signals=low_confidence,
            price_up_signals=price_up,
            price_down_signals=price_down,
        )

    def get_signal_summary(self, hours: int = 24) -> Dict[str, Any]:
        """获取信号摘要"""
        metrics = self.get_quality_metrics(hours)

        # 生成摘要
        summary = {
            "time_range": f"最近{hours}小时",
            "total_signals": metrics.total_signals,
            "signal_distribution": {
                "BUY": metrics.buy_signals,
                "SELL": metrics.sell_signals,
                "HOLD": metrics.hold_signals,
            },
            "confidence_distribution": {
                "high": metrics.high_confidence_signals,
                "medium": metrics.medium_confidence_signals,
                "low": metrics.low_confidence_signals,
            },
            "avg_confidence": f"{metrics.avg_confidence:.2%}",
            "price_direction": {
                "up": metrics.price_up_signals,
                "down": metrics.price_down_signals,
            },
            "signal_quality": self._evaluate_signal_quality(metrics),
            "recommendations": self._generate_recommendations(metrics),
        }

        return summary

    def _evaluate_signal_quality(self, metrics: SignalQualityMetrics) -> str:
        """评估信号质量"""
        if metrics.total_signals == 0:
            return "无数据"

        # 计算高置信度信号占比
        high_ratio = metrics.high_confidence_signals / metrics.total_signals

        # 计算BUY/SELL比例
        directional_signals = metrics.buy_signals + metrics.sell_signals
        if directional_signals > 0:
            buy_ratio = metrics.buy_signals / directional_signals
        else:
            buy_ratio = 0.5

        # 评估
        if high_ratio >= 0.3 and 0.3 <= buy_ratio <= 0.7:
            return "良好 - 高置信度信号占比合理，多空信号均衡"
        elif high_ratio >= 0.2:
            return "一般 - 高置信度信号占比适中"
        else:
            return "需优化 - 高置信度信号较少，建议调整触发条件"

    def _generate_recommendations(self, metrics: SignalQualityMetrics) -> List[str]:
        """生成建议"""
        recommendations = []

        if metrics.total_signals == 0:
            return ["暂无信号数据，继续监控"]

        # 检查置信度
        if metrics.low_confidence_signals > metrics.high_confidence_signals:
            recommendations.append("低置信度信号较多，建议提高触发阈值")

        # 检查多空平衡
        directional_signals = metrics.buy_signals + metrics.sell_signals
        if directional_signals > 0:
            buy_ratio = metrics.buy_signals / directional_signals
            if buy_ratio > 0.8:
                recommendations.append("BUY信号占比过高，可能过于激进")
            elif buy_ratio < 0.2:
                recommendations.append("SELL信号占比过高，市场可能处于下跌趋势")

        # 检查频率
        if metrics.total_signals > 50:
            recommendations.append("信号频率较高，可考虑提高触发阈值")

        if not recommendations:
            recommendations.append("信号质量良好，当前配置可继续使用")

        return recommendations

    def get_recent_signals(self, hours: int = 24) -> List[QuickSignalRecord]:
        """获取最近的信号"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        return [s for s in self.signals if s.timestamp > cutoff_time]

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_signals": len(self.signals),
            "ai_calls_this_hour": len(
                [
                    t
                    for t in self.ai_call_timestamps
                    if t >= datetime.now().replace(minute=0, second=0, microsecond=0)
                ]
            ),
            "ai_call_limit": self.config.max_ai_calls_per_hour,
            "enable_ai_analysis": self.config.enable_ai_analysis,
            "record_only": self.config.record_only,
            "price_change_threshold": self.config.price_change_threshold,
        }


# 全局实例
quick_signal_analyzer = QuickSignalAnalyzer()
