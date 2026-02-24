"""
信号优化器

功能：
- 根据市场环境动态调整信号置信度
- 异常信号过滤
- 信号平滑处理
- 置信度校准

作者：AI Trading System
日期：2026-02-04
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
from enum import Enum

logger = logging.getLogger(__name__)


class SignalType(Enum):
    """信号类型"""

    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"


@dataclass
class SignalRecord:
    """信号记录"""

    signal: str
    confidence: float
    price: float
    timestamp: str
    source: str  # AI提供商来源
    mode: str = ""  # 决策模式


@dataclass
class OptimizedSignal:
    """优化后的信号"""

    signal: str
    confidence: float
    original_confidence: float
    adjustments: List[str]  # 调整原因
    is_filtered: bool
    details: Dict[str, Any]


@dataclass
class OptimizerConfig:
    """优化器配置"""

    # 信号优化参数调整为更积极以提高信号多样性
    # 异常信号过滤
    confidence_floor: float = 0.45  # 提高最低置信度阈值
    confidence_ceiling: float = 0.95  # 保持最高置信度
    rapid_change_threshold: float = 0.25  # 降低快速变化阈值

    # 信号平滑
    smoothing_window: int = 2  # 减小平滑窗口
    smoothing_enabled: bool = True

    # 市场环境适应
    volatility_adjustment: bool = True
    high_volatility_threshold: float = 0.04  # 提高高波动阈值

    # 连续信号检查
    consecutive_limit: int = 3  # 提高连续信号限制
    cooldown_period: int = 2  # 增加冷却期


class SignalOptimizer:
    """
    信号优化器

    功能：
    1. 异常信号过滤：置信度过低或过高的信号
    2. 信号平滑：连续信号的稳定性处理
    3. 市场环境适应：根据波动率调整置信度
    4. 置信度校准：基于历史表现的校准
    """

    def __init__(
        self,
        config: Optional[OptimizerConfig] = None,
        price_history: Optional[List[float]] = None,
    ):
        """
        初始化信号优化器

        Args:
            config: 优化器配置
            price_history: 历史价格列表（用于波动率计算）
        """
        self.config = config or OptimizerConfig()
        self.signal_history: deque = deque(maxlen=20)
        self.price_history = price_history or []

        logger.info(
            f"[信号优化器] 初始化完成: "
            f"置信度范围=[{self.config.confidence_floor:.0%}, {self.config.confidence_ceiling:.0%}], "
            f"平滑窗口={self.config.smoothing_window}, "
            f"高波动阈值={self.config.high_volatility_threshold:.1%}"
        )

    def optimize(
        self,
        signal: str,
        confidence: float,
        price: float,
        source: str = "ai",
        market_data: Optional[Dict[str, Any]] = None,
    ) -> OptimizedSignal:
        """
        优化信号

        Args:
            signal: 原始信号
            confidence: 原始置信度
            price: 当前价格
            source: 信号来源
            market_data: 市场数据（可选）

        Returns:
            OptimizedSignal: 优化后的信号
        """
        adjustments: List[str] = []
        original_confidence = confidence

        # 1. 置信度边界限制
        confidence = self._clip_confidence(confidence, adjustments)

        # 2. 异常信号过滤
        is_filtered, confidence = self._filter_abnormal_signal(
            signal, confidence, adjustments
        )

        # 3. 信号平滑处理
        if self.config.smoothing_enabled:
            confidence = self._smooth_signal(signal, confidence, adjustments)

        # 4. 市场环境适应
        if self.config.volatility_adjustment and market_data:
            confidence = self._adjust_for_volatility(
                signal, market_data, confidence, adjustments
            )

        # 5. 连续信号检查
        confidence = self._check_consecutive_signals(signal, confidence, adjustments)

        # 6. 记录信号历史
        self._record_signal(signal, confidence, price, source)

        result = OptimizedSignal(
            signal=signal if not is_filtered else "hold",
            confidence=confidence,
            original_confidence=original_confidence,
            adjustments=adjustments,
            is_filtered=is_filtered,
            details={
                "price": price,
                "source": source,
                "market_data": market_data,
                "signal_history_len": len(self.signal_history),
            },
        )

        logger.info(
            f"[信号优化] 结果: signal={result.signal}, confidence={result.confidence:.2%}, "
            f"original={original_confidence:.2%}, filtered={is_filtered}, "
            f"adjustments={len(adjustments)}"
        )

        return result

    def _clip_confidence(self, confidence: float, adjustments: List[str]) -> float:
        """限制置信度在合理范围内"""
        if confidence < self.config.confidence_floor:
            adjustments.append(
                f"置信度从{confidence:.2%}提升到{self.config.confidence_floor:.0%}"
            )
            confidence = self.config.confidence_floor
        elif confidence > self.config.confidence_ceiling:
            adjustments.append(
                f"置信度从{confidence:.2%}降低到{self.config.confidence_ceiling:.0%}"
            )
            confidence = self.config.confidence_ceiling

        return confidence

    def _filter_abnormal_signal(
        self, signal: str, confidence: float, adjustments: List[str]
    ) -> tuple:
        """过滤异常信号"""
        is_filtered = False

        # 置信度过低
        if confidence < self.config.confidence_floor:
            adjustments.append(f"置信度过低({confidence:.2%})，过滤信号")
            is_filtered = True
            signal = "hold"
            confidence = self.config.confidence_floor

        # 检查连续相同信号
        if len(self.signal_history) >= 2:
            last_record = self.signal_history[-1]
            if last_record.signal == signal:
                consecutive = 1
                # deque不支持切片，需要转换为list
                history_list = list(self.signal_history)
                for record in reversed(history_list[:-1]):
                    if record.signal == signal:
                        consecutive += 1
                    else:
                        break

                if consecutive >= self.config.consecutive_limit:
                    # 连续同一信号次数过多，警告
                    adjustments.append(
                        f"连续{consecutive}次相同信号({signal})，建议观望"
                    )

        return is_filtered, confidence

    def _smooth_signal(
        self, signal: str, confidence: float, adjustments: List[str]
    ) -> float:
        """信号平滑处理"""
        if len(self.signal_history) < 2:
            return confidence

        # 获取最近N个相同信号的置信度
        recent_confidences = []
        for record in list(self.signal_history)[-self.config.smoothing_window :]:
            if record.signal == signal:
                recent_confidences.append(record.confidence)

        if len(recent_confidences) >= 2:
            # 简单移动平均
            avg_confidence = sum(recent_confidences) / len(recent_confidences)
            # 权重：更近的信号更重要
            weights = [1 + i * 0.5 for i in range(len(recent_confidences))]
            weighted_avg = sum(
                c * w for c, w in zip(recent_confidences, weights)
            ) / sum(weights)

            # 平滑处理：向移动平均靠拢
            smoothed_confidence = (confidence + weighted_avg) / 2

            if abs(smoothed_confidence - confidence) > 0.05:
                adjustments.append(
                    f"平滑处理: {confidence:.2%} → {smoothed_confidence:.2%}"
                )

            return smoothed_confidence

        return confidence

    def _adjust_for_volatility(
        self,
        signal: str,
        market_data: Dict[str, Any],
        confidence: float,
        adjustments: List[str],
    ) -> float:
        """根据波动率调整置信度"""
        technical = market_data.get("technical", {})
        atr_pct = technical.get("atr_percent", 0)

        # 如果没有ATR，使用近期的价格变化计算
        if atr_pct == 0 and len(self.price_history) >= 2:
            recent_changes = []
            for i in range(1, min(len(self.price_history), 5)):
                change = (
                    abs(self.price_history[-i] - self.price_history[-i - 1])
                    / self.price_history[-i - 1]
                )
                recent_changes.append(change)
            if recent_changes:
                atr_pct = sum(recent_changes) / len(recent_changes)

        # 高波动环境
        if atr_pct > self.config.high_volatility_threshold:
            # BUY 信号在高波动时减少削减幅度（高波动可能是买入机会）
            # SELL 信号正常削减
            # HOLD 信号保持原有逻辑
            if signal.upper() == "BUY":
                adjustment = (atr_pct - self.config.high_volatility_threshold) * 1
                confidence = confidence * (1 - min(adjustment, 0.15))
                adjustments.append(
                    f"高波动({atr_pct:.1%})BUY调整: -{adjustment * 100:.1f}%"
                )
            else:
                adjustment = (atr_pct - self.config.high_volatility_threshold) * 2
                confidence = confidence * (1 - min(adjustment, 0.3))
                adjustments.append(
                    f"高波动({atr_pct:.1%})调整: -{adjustment * 100:.1f}%"
                )

        # 低波动环境
        elif atr_pct < 0.01:  # 1%
            # 低波动时小幅提升置信度
            confidence = confidence * 1.05
            adjustments.append(f"低波动({atr_pct:.1%})小幅提升置信度")

        return min(
            max(confidence, self.config.confidence_floor),
            self.config.confidence_ceiling,
        )

    def _check_consecutive_signals(
        self, signal: str, confidence: float, adjustments: List[str]
    ) -> float:
        """检查连续信号"""
        if len(self.signal_history) == 0:
            return confidence

        # 检查最近N个信号
        recent_signals = list(self.signal_history)[-self.config.smoothing_window :]

        # 统计各信号数量
        signal_counts = {"buy": 0, "hold": 0, "sell": 0}
        for record in recent_signals:
            if record.signal in signal_counts:
                signal_counts[record.signal] += 1

        # 如果当前信号与最近多数信号相反
        current_count = signal_counts.get(signal, 0)
        total = len(recent_signals)

        if total > 0 and current_count / total < 0.3:
            # 当前信号与历史多数相反，降低置信度
            confidence = confidence * 0.8
            adjustments.append(
                f"信号与历史多数相反({current_count}/{total})，置信度降低"
            )

        return confidence

    def _record_signal(
        self, signal: str, confidence: float, price: float, source: str
    ) -> None:
        """记录信号历史"""
        record = SignalRecord(
            signal=signal,
            confidence=confidence,
            price=price,
            timestamp=datetime.now().isoformat(),
            source=source,
        )
        self.signal_history.append(record)

    def update_price_history(self, price: float) -> None:
        """更新价格历史"""
        self.price_history.append(price)
        # 保持历史长度合理
        if len(self.price_history) > 100:
            self.price_history = self.price_history[-100:]

    def get_statistics(self) -> Dict[str, Any]:
        """获取优化器统计信息"""
        if not self.signal_history:
            return {"status": "no_data"}

        signal_counts = {"buy": 0, "hold": 0, "sell": 0}
        total_confidence = {"buy": 0, "hold": 0, "sell": 0}

        for record in self.signal_history:
            if record.signal in signal_counts:
                signal_counts[record.signal] += 1
                total_confidence[record.signal] += record.confidence

        avg_confidence = {}
        for sig in signal_counts:
            if signal_counts[sig] > 0:
                avg_confidence[sig] = total_confidence[sig] / signal_counts[sig]
            else:
                avg_confidence[sig] = 0

        return {
            "total_signals": len(self.signal_history),
            "signal_counts": signal_counts,
            "avg_confidence": avg_confidence,
            "recent_signals": [
                {"signal": r.signal, "confidence": r.confidence}
                for r in list(self.signal_history)[-5:]
            ],
        }

    def reset(self) -> None:
        """重置优化器状态"""
        self.signal_history.clear()
        self.price_history.clear()
        logger.info("[信号优化器] 已重置")
