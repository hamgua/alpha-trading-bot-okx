"""
一致性强化融合策略

功能：
- 支持多种融合策略（加权平均/多数表决/共识/置信度优先）
- 新增一致性强化机制
- 当多个AI一致时强化信号
- 支持动态阈值调整

作者：AI Trading System
日期：2026-02-04
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class FusionStrategyType(Enum):
    """融合策略类型"""

    WEIGHTED = "weighted"  # 加权平均
    MAJORITY = "majority"  # 多数表决
    CONSENSUS = "consensus"  # 共识（需全一致）
    CONFIDENCE = "confidence"  # 置信度优先
    CONSENSUS_BOOSTED = "consensus_boosted"  # 一致性强化（推荐）


@dataclass
class FusionConfig:
    """融合配置"""

    strategy: FusionStrategyType = FusionStrategyType.CONSENSUS_BOOSTED
    threshold: float = 0.42  # 从0.50降低到0.42，更容易触发信号
    consensus_boost_full: float = 1.3  # 全部一致时强化倍数
    consensus_boost_partial: float = 1.1  # 2/3一致时强化倍数（从1.15降低）
    default_confidence: int = 70  # 默认置信度
    # === 反弹检测 + 条件性放行 ===
    partial_consensus_threshold: float = (
        0.5  # 部分一致阈值（从0.60降低到0.50，更容易达成共识）
    )
    kimi_buy_rebound_boost: float = 1.2  # Kimi BUY 在反弹区间加权（从1.3降低）
    rsi_rebound_low: float = 30  # RSI 反弹区间下限（从40降低，扩大区间）
    rsi_rebound_high: float = 70  # RSI 反弹区间上限（从58提高到70，允许更高RSI时买入）
    rsi_high_suppression: float = (
        72  # RSI 高于此值抑制 BUY（从60提高到72，减少高位抑制）
    )
    enable_rebound_mode: bool = True  # 启用反弹检测模式


@dataclass
class FusionResult:
    """融合结果"""

    signal: str  # buy | hold | sell
    confidence: float  # 0-1
    scores: Dict[str, float]  # 各信号得分
    threshold: float
    is_valid: bool
    consensus_ratio: float  # 一致性比例
    strategy_used: str
    details: Dict[str, Any]


class ConsensusBoostedFusion:
    """
    一致性强化融合策略

    核心思想：
    1. 当多个AI给出相同信号时，该信号的可信度更高
    2. 全部一致时强化1.3倍
    3. 2/3以上一致时强化1.15倍
    4. 分歧时使用加权平均

    支持的策略：
    - weighted: 加权平均（置信度加权）
    - majority: 多数表决
    - consensus: 共识（需所有AI一致）
    - confidence: 置信度优先
    - consensus_boosted: 一致性强化（推荐）
    """

    def __init__(self, config: Optional[FusionConfig] = None):
        """
        初始化融合策略

        Args:
            config: 融合配置，如果为None则使用默认配置
        """
        self.config = config or FusionConfig()
        self._validate_config()

        logger.info(
            f"[一致性强化融合] 初始化完成: "
            f"策略={self.config.strategy.value}, "
            f"阈值={self.config.threshold}, "
            f"全一致强化={self.config.consensus_boost_full}x, "
            f"部分一致强化={self.config.consensus_boost_partial}x"
        )

    def fuse(
        self,
        signals: List[Dict[str, str]],
        weights: Dict[str, float],
        threshold: Optional[float] = None,
        confidences: Optional[Dict[str, int]] = None,
        market_data: Optional[Dict[str, Any]] = None,
    ) -> FusionResult:
        """
        融合多个AI信号

        Args:
            signals: [{"provider": "deepseek", "signal": "buy"}, ...]
            weights: {"deepseek": 0.5, "kimi": 0.5, ...}
            threshold: 融合阈值（可选，覆盖配置）
            confidences: {"deepseek": 70, "kimi": 75, ...} 置信度（可选）

        Returns:
            FusionResult: 融合结果
        """
        if not signals:
            logger.warning("[融合] 无有效信号，返回hold")
            return FusionResult(
                signal="hold",
                confidence=0.6,
                scores={"buy": 0, "hold": 1, "sell": 0},
                threshold=threshold or self.config.threshold,
                is_valid=False,
                consensus_ratio=0.0,
                strategy_used=self.config.strategy.value,
                details={"reason": "no signals"},
            )

        # 计算一致性比例
        signal_counts = self._count_signals(signals)
        total = len(signals)
        max_count = max(signal_counts.values())
        consensus_ratio = max_count / total

        # 根据策略进行融合
        if self.config.strategy == FusionStrategyType.WEIGHTED:
            return self._fuse_weighted(
                signals, weights, threshold, confidences, consensus_ratio
            )
        elif self.config.strategy == FusionStrategyType.MAJORITY:
            return self._fuse_majority(signals, threshold, consensus_ratio)
        elif self.config.strategy == FusionStrategyType.CONSENSUS:
            return self._fuse_consensus(signals, threshold, consensus_ratio)
        elif self.config.strategy == FusionStrategyType.CONFIDENCE:
            return self._fuse_confidence(signals, threshold, consensus_ratio)
        else:
            # 修复 BUG：始终计算动态阈值，不依赖 threshold 是否为 None
            # 根据市场环境动态调整信号触发条件

            # 先计算原始得分，确定可能胜出的信号类型
            raw_scores = {"buy": 0, "hold": 0, "sell": 0}
            for s in signals:
                sig = s["signal"]
                weight = weights.get(s["provider"], 1.0)
                confidence = (
                    confidences.get(s["provider"], self.config.default_confidence)
                    if confidences
                    else self.config.default_confidence
                )
                raw_scores[sig] += weight * (confidence / 100.0)

            # 确定可能胜出的信号类型
            likely_winner = max(raw_scores, key=raw_scores.get)

            # 根据可能的胜出信号类型计算动态阈值
            signal_type = (
                likely_winner if likely_winner in ["buy", "sell"] else "general"
            )
            effective_threshold = self._calculate_dynamic_threshold(
                market_data, signal_type
            )

            return self._fuse_consensus_boosted(
                signals,
                weights,
                effective_threshold,
                confidences,
                consensus_ratio,
                market_data,
            )

    def _count_signals(self, signals: List[Dict[str, str]]) -> Dict[str, int]:
        """统计各信号数量"""
        counts = {"buy": 0, "hold": 0, "sell": 0}
        for s in signals:
            sig = s["signal"]
            if sig in counts:
                counts[sig] += 1
        return counts

    def _fuse_weighted(
        self,
        signals: List[Dict[str, str]],
        weights: Dict[str, float],
        threshold: Optional[float],
        confidences: Optional[Dict[str, int]],
        consensus_ratio: float,
    ) -> FusionResult:
        """加权平均融合"""
        threshold = threshold or self.config.threshold

        weighted_scores = {"buy": 0, "hold": 0, "sell": 0}
        total_weight = 0

        for s in signals:
            provider = s["provider"]
            sig = s["signal"]
            weight = weights.get(provider, 1.0)
            confidence = self.config.default_confidence
            if confidences:
                confidence = confidences.get(provider, self.config.default_confidence)

            adjusted_weight = weight * (confidence / 100.0)
            weighted_scores[sig] += adjusted_weight
            total_weight += adjusted_weight

        # 归一化
        if total_weight > 0:
            for sig in weighted_scores:
                weighted_scores[sig] /= total_weight

        max_sig = max(weighted_scores, key=weighted_scores.get)
        max_score = weighted_scores[max_sig]
        is_valid = max_score >= threshold

        logger.info(
            f"[融合-加权平均] 结果: {max_sig} (buy:{weighted_scores['buy']:.2f}, "
            f"hold:{weighted_scores['hold']:.2f}, sell:{weighted_scores['sell']:.2f}, "
            f"阈值:{threshold}, 有效:{is_valid})"
        )

        return FusionResult(
            signal=max_sig,
            confidence=max_score,
            scores=weighted_scores,
            threshold=threshold,
            is_valid=is_valid,
            consensus_ratio=consensus_ratio,
            strategy_used="weighted",
            details={"type": "weighted"},
        )

    def _fuse_majority(
        self,
        signals: List[Dict[str, str]],
        threshold: Optional[float],
        consensus_ratio: float,
    ) -> FusionResult:
        """多数表决融合"""
        threshold = threshold or self.config.threshold

        signal_counts = self._count_signals(signals)
        total = len(signals)

        for sig, count in signal_counts.items():
            if count / total >= threshold:
                logger.info(
                    f"[融合-多数表决] 结果: {sig} ({count}/{total} >= {threshold})"
                )
                return FusionResult(
                    signal=sig,
                    confidence=count / total,
                    scores={k: v / total for k, v in signal_counts.items()},
                    threshold=threshold,
                    is_valid=True,
                    consensus_ratio=consensus_ratio,
                    strategy_used="majority",
                    details={"count": count, "total": total},
                )

        # 未达阈值，取最多的
        max_sig = max(signal_counts, key=signal_counts.get)
        logger.info(f"[融合-多数表决-降级] 结果: {max_sig} (max count)")

        return FusionResult(
            signal=max_sig,
            confidence=signal_counts[max_sig] / total,
            scores={k: v / total for k, v in signal_counts.items()},
            threshold=threshold,
            is_valid=False,
            consensus_ratio=consensus_ratio,
            strategy_used="majority",
            details={"count": signal_counts[max_sig], "total": total, "fallback": True},
        )

    def _fuse_consensus(
        self,
        signals: List[Dict[str, str]],
        threshold: Optional[float],
        consensus_ratio: float,
    ) -> FusionResult:
        """共识融合（需所有AI一致）"""
        threshold = threshold or self.config.threshold

        unique_signals = set(s["signal"] for s in signals)
        if len(unique_signals) == 1:
            sig = list(unique_signals)[0]
            logger.info(f"[融合-共识] 结果: {sig} (all agreed)")

            if sig == "hold":
                confidence = min(0.6 * consensus_ratio, 0.7)
            else:
                confidence = 1.0

            return FusionResult(
                signal=sig,
                confidence=confidence,
                scores={
                    "buy": 1.0 if sig == "buy" else 0,
                    "hold": 1.0 if sig == "hold" else 0,
                    "sell": 1.0 if sig == "sell" else 0,
                },
                threshold=threshold,
                is_valid=True,
                consensus_ratio=consensus_ratio,
                strategy_used="consensus",
                details={"reason": "all agreed"},
            )
        else:
            logger.warning(f"[融合-共识] 未达成共识: {unique_signals}，默认hold")
            return FusionResult(
                signal="hold",
                confidence=0.6,
                scores={"buy": 0, "hold": 1, "sell": 0},
                threshold=threshold,
                is_valid=False,
                consensus_ratio=consensus_ratio,
                strategy_used="consensus",
                details={"reason": "no consensus", "signals": list(unique_signals)},
            )

    def _fuse_confidence(
        self,
        signals: List[Dict[str, str]],
        threshold: Optional[float],
        consensus_ratio: float,
    ) -> FusionResult:
        """置信度优先融合"""
        threshold = threshold or self.config.threshold

        signal_counts = {"buy": 0, "hold": 0, "sell": 0}
        for s in signals:
            if s["signal"] in signal_counts:
                signal_counts[s["signal"]] += 1

        buy_count = signal_counts["buy"]
        sell_count = signal_counts["sell"]
        total = len(signals)

        if buy_count > sell_count and buy_count / total >= threshold:
            logger.info(f"[融合-置信度] 结果: buy ({buy_count}/{total})")
            return FusionResult(
                signal="buy",
                confidence=buy_count / total,
                scores={k: v / total for k, v in signal_counts.items()},
                threshold=threshold,
                is_valid=True,
                consensus_ratio=consensus_ratio,
                strategy_used="confidence",
                details={"count": buy_count, "total": total},
            )
        elif sell_count > buy_count and sell_count / total >= threshold:
            logger.info(f"[融合-置信度] 结果: sell ({sell_count}/{total})")
            return FusionResult(
                signal="sell",
                confidence=sell_count / total,
                scores={k: v / total for k, v in signal_counts.items()},
                threshold=threshold,
                is_valid=True,
                consensus_ratio=consensus_ratio,
                strategy_used="confidence",
                details={"count": sell_count, "total": total},
            )

        logger.info("[融合-置信度] 结果: hold (no majority)")
        return FusionResult(
            signal="hold",
            confidence=0.6,
            scores={k: v / total for k, v in signal_counts.items()},
            threshold=threshold,
            is_valid=False,
            consensus_ratio=consensus_ratio,
            strategy_used="confidence",
            details={"reason": "no majority"},
        )

    def _fuse_consensus_boosted(
        self,
        signals: List[Dict[str, str]],
        weights: Dict[str, float],
        threshold: Optional[float],
        confidences: Optional[Dict[str, int]],
        consensus_ratio: float,
        market_data: Optional[Dict[str, Any]] = None,
    ) -> FusionResult:
        """
        一致性强化融合（推荐策略）+ 反弹检测增强

        核心逻辑：
        1. 计算加权得分
        2. 根据一致性比例强化得分
        3. 全部一致时强化1.3倍
        4. 2/3以上一致时强化1.15倍
        5. 反弹区间Kimi BUY加权，高位抑制
        """
        threshold = threshold or self.config.threshold

        # 提取RSI和趋势方向
        rsi = 50  # 默认中性
        trend_direction = "neutral"
        if market_data:
            technical = market_data.get("technical", {})
            rsi = technical.get("rsi", 50)
            trend_direction = technical.get("trend_direction", "neutral")

        # 记录反弹检测信息
        if self.config.enable_rebound_mode:
            logger.info(
                f"[融合-反弹+高位] 反弹检测: RSI={rsi:.1f}, 趋势={trend_direction}, "
                f"反弹区间=[{self.config.rsi_rebound_low}-{self.config.rsi_rebound_high}], "
                f"高位抑制=[>{self.config.rsi_high_suppression}]"
            )

        # 步骤1: 计算加权得分
        weighted_scores = {"buy": 0, "hold": 0, "sell": 0}
        total_weight = 0

        # 检查是否有Kimi BUY信号
        has_kimi_buy = any(
            s["provider"] == "kimi" and s["signal"] == "buy" for s in signals
        )

        for s in signals:
            provider = s["provider"]
            sig = s["signal"]
            weight = weights.get(provider, 1.0)
            confidence = self.config.default_confidence
            if confidences:
                confidence = confidences.get(provider, self.config.default_confidence)

            adjusted_weight = weight * (confidence / 100.0)

            # Kimi BUY在反弹区间加权
            if (
                self.config.enable_rebound_mode
                and sig == "buy"
                and provider == "kimi"
                and self.config.rsi_rebound_low <= rsi <= self.config.rsi_rebound_high
                and trend_direction != "bearish"
            ):
                adjusted_weight *= self.config.kimi_buy_rebound_boost
                logger.info(
                    f"[融合] Kimi BUY反弹加权: 置信度={confidence}%, "
                    f"RSI={rsi:.1f}, 加权后={adjusted_weight:.3f}"
                )

            weighted_scores[sig] += adjusted_weight
            total_weight += adjusted_weight

        # 步骤2: 一致性强化 + 阈值调整
        boost_factor = 1.0
        boost_reason = ""

        if consensus_ratio >= 1.0:
            # 全部一致
            boost_factor = self.config.consensus_boost_full
            boost_reason = f"全部一致，强化{boost_factor}x"
        elif consensus_ratio >= self.config.partial_consensus_threshold:
            # 放宽部分一致阈值（0.50 → 0.60）
            boost_factor = self.config.consensus_boost_partial
            boost_reason = f"部分一致({consensus_ratio:.0%})，强化{boost_factor}x"
        elif (
            self.config.enable_rebound_mode
            and has_kimi_buy
            and self.config.rsi_rebound_low <= rsi <= self.config.rsi_rebound_high
        ):
            # 反弹区间内的Kimi BUY，即使一致性不足也给予部分强化
            boost_factor = 1.1
            boost_reason = f"Kimi反弹区间，强化{boost_factor}x"

        # 找到最高得分的信号
        max_sig = max(weighted_scores, key=weighted_scores.get)

        # 高位抑制BUY（RSI > 60 时）
        if (
            self.config.enable_rebound_mode
            and max_sig == "buy"
            and rsi > self.config.rsi_high_suppression
        ):
            weighted_scores["buy"] *= 0.5
            logger.info(
                f"[融合] 高位抑制BUY: RSI={rsi:.1f} > {self.config.rsi_high_suppression}, "
                f"得分减半"
            )
            # 重新确定胜出信号
            max_sig = max(weighted_scores, key=weighted_scores.get)

        weighted_scores[max_sig] *= boost_factor

        # 步骤3: 归一化
        total = sum(weighted_scores.values())
        if total > 0:
            for sig in weighted_scores:
                weighted_scores[sig] /= total

        # 步骤4: 最终判断
        max_sig = max(weighted_scores, key=weighted_scores.get)
        max_score = weighted_scores[max_sig]
        is_valid = max_score >= threshold

        logger.info(
            f"[融合-一致性强化] 结果: {max_sig} "
            f"(buy:{weighted_scores['buy']:.2f}, hold:{weighted_scores['hold']:.2f}, "
            f"sell:{weighted_scores['sell']:.2f}, 阈值:{threshold}, "
            f"有效:{is_valid}, 一致性:{consensus_ratio:.0%}, {boost_reason})"
        )

        return FusionResult(
            signal=max_sig,
            confidence=max_score,
            scores=weighted_scores,
            threshold=threshold,
            is_valid=is_valid,
            consensus_ratio=consensus_ratio,
            strategy_used="consensus_boosted",
            details={
                "type": "consensus_boosted",
                "boost_factor": boost_factor,
                "boost_reason": boost_reason,
                "scheme_d_enabled": self.config.enable_rebound_mode,
                "rsi": rsi,
                "trend_direction": trend_direction,
                "original_scores": {
                    k: v / boost_factor if k == max_sig and boost_factor > 1 else v
                    for k, v in weighted_scores.items()
                },
            },
        )

    def _calculate_dynamic_threshold(
        self,
        market_data: Optional[Dict[str, Any]],
        signal_type: str = "general",
    ) -> float:
        """
        动态阈值计算

        根据市场环境和信号类型动态调整融合阈值：
        - RSI超卖区域：降低买入阈值，更容易触发买入
        - RSI超买区域：降低卖出阈值，更容易获利了结
        - 高波动环境 + 上升趋势：降低买入阈值（顺势做多）
        - 高波动环境 + 下降趋势：提高买入阈值（避免抄底）
        - 强趋势环境：根据趋势方向调整

        Args:
            market_data: 市场数据字典
            signal_type: 信号类型 ("buy"/"sell"/"general")

        Returns:
            float: 动态调整后的阈值
        """
        if not market_data:
            return self.config.threshold

        base_threshold = self.config.threshold
        technical = market_data.get("technical", {})
        rsi = technical.get("rsi", 50)
        atr_pct = technical.get("atr_percent", 0)
        trend_strength = technical.get("trend_strength", 0)
        trend_direction = technical.get("trend_direction", "neutral")

        # 记录趋势方向信息
        logger.info(
            f"[融合-动态阈值] 趋势方向={trend_direction}, 强度={trend_strength:.2f}, "
            f"信号类型={signal_type}, RSI={rsi:.1f}, ATR={atr_pct:.1%}"
        )

        # RSI超卖区域（<35）：降低买入阈值，更容易抄底
        if rsi < 35:
            dynamic_threshold = max(0.30, base_threshold - 0.10)
            logger.info(
                f"[融合-动态阈值] RSI超卖({rsi:.1f})，阈值调整: {base_threshold:.2f} -> {dynamic_threshold:.2f}"
            )
            return dynamic_threshold

        # RSI超买区域（>65）：降低卖出阈值，更容易获利了结
        elif rsi > 65:
            dynamic_threshold = max(0.30, base_threshold - 0.08)
            logger.info(
                f"[融合-动态阈值] RSI超买({rsi:.1f})，阈值调整: {base_threshold:.2f} -> {dynamic_threshold:.2f}"
            )
            return dynamic_threshold

        # 高波动环境（ATR > 3%）：根据趋势方向调整
        elif atr_pct > 0.03:
            if trend_direction == "bullish":
                # 上升趋势中：降低买入阈值，顺势做多
                dynamic_threshold = max(0.35, base_threshold - 0.08)
                logger.info(
                    f"[融合-动态阈值] 高波动+上升趋势，{signal_type}阈值调整: "
                    f"{base_threshold:.2f} -> {dynamic_threshold:.2f} (顺势做多)"
                )
            elif trend_direction == "bearish":
                # 下降趋势中：提高买入阈值，避免逆势抄底
                dynamic_threshold = min(0.55, base_threshold + 0.08)
                logger.info(
                    f"[融合-动态阈值] 高波动+下降趋势，{signal_type}阈值调整: "
                    f"{base_threshold:.2f} -> {dynamic_threshold:.2f} (避免抄底)"
                )
            else:
                # 震荡市：保持基准
                dynamic_threshold = base_threshold
                logger.info(
                    f"[融合-动态阈值] 高波动+震荡市，{signal_type}阈值保持: {base_threshold:.2f}"
                )
            return dynamic_threshold

        # 强趋势环境：根据趋势方向调整
        elif trend_strength > 0.4:
            if trend_direction == "bullish":
                # 上升趋势：buy 略微放宽，sell 略微收紧
                if signal_type == "buy":
                    dynamic_threshold = max(0.40, base_threshold - 0.05)
                    logger.info(
                        f"[融合-动态阈值] 强上升趋势，buy阈值调整: "
                        f"{base_threshold:.2f} -> {dynamic_threshold:.2f} (顺势做多)"
                    )
                elif signal_type == "sell":
                    dynamic_threshold = min(0.55, base_threshold + 0.05)
                    logger.info(
                        f"[融合-动态阈值] 强上升趋势，sell阈值调整: "
                        f"{base_threshold:.2f} -> {dynamic_threshold:.2f} (谨慎做空)"
                    )
                else:
                    dynamic_threshold = base_threshold
            elif trend_direction == "bearish":
                # 下降趋势：buy 收紧，sell 放宽
                if signal_type == "buy":
                    dynamic_threshold = min(0.55, base_threshold + 0.05)
                    logger.info(
                        f"[融合-动态阈值] 强下降趋势，buy阈值调整: "
                        f"{base_threshold:.2f} -> {dynamic_threshold:.2f} (避免抄底)"
                    )
                elif signal_type == "sell":
                    dynamic_threshold = max(0.40, base_threshold - 0.05)
                    logger.info(
                        f"[融合-动态阈值] 强下降趋势，sell阈值调整: "
                        f"{base_threshold:.2f} -> {dynamic_threshold:.2f} (顺势做空)"
                    )
                else:
                    dynamic_threshold = base_threshold
            else:
                dynamic_threshold = base_threshold
            return dynamic_threshold

        # 默认阈值
        return base_threshold

    def _validate_config(self) -> None:
        """验证配置合理性"""
        if self.config.threshold < 0 or self.config.threshold > 1:
            logger.warning(
                f"[融合] 警告: threshold({self.config.threshold})应在0-1之间"
            )
        if self.config.consensus_boost_full < 1:
            logger.warning(
                f"[融合] 警告: consensus_boost_full({self.config.consensus_boost_full})应>=1"
            )
        if self.config.consensus_boost_partial < 1:
            logger.warning(
                f"[融合] 警告: consensus_boost_partial({self.config.consensus_boost_partial})应>=1"
            )

    def get_strategy(self, name: str) -> "ConsensusBoostedFusion":
        """获取指定策略的融合器"""
        strategy_map = {
            "weighted": FusionStrategyType.WEIGHTED,
            "majority": FusionStrategyType.MAJORITY,
            "consensus": FusionStrategyType.CONSENSUS,
            "confidence": FusionStrategyType.CONFIDENCE,
            "consensus_boosted": FusionStrategyType.CONSENSUS_BOOSTED,
        }

        strategy_type = strategy_map.get(name, FusionStrategyType.CONSENSUS_BOOSTED)
        self.config.strategy = strategy_type
        return self


def get_fusion_strategy(
    name: str, config: Optional[FusionConfig] = None
) -> ConsensusBoostedFusion:
    """
    获取融合策略实例

    Args:
        name: 策略名称
        config: 配置

    Returns:
        ConsensusBoostedFusion: 融合策略实例
    """
    fusion = ConsensusBoostedFusion(config)
    return fusion.get_strategy(name)
