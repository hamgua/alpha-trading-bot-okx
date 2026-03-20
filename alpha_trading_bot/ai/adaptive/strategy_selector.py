"""
策略选择器

功能：
- 基于市场状态自动选择最佳策略
- 动态调整策略权重
- 策略融合与优先级管理
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

from .strategy_library import StrategyType

logger = logging.getLogger(__name__)


class SelectionMode(Enum):
    """选择模式"""

    SINGLE_BEST = "single_best"  # 选择最佳单一策略
    WEIGHTED_FUSION = "weighted_fusion"  # 加权融合
    ADAPTIVE = "adaptive"  # 自适应选择


@dataclass
class SelectionConfig:
    """选择配置"""

    mode: SelectionMode = SelectionMode.ADAPTIVE
    min_confidence_threshold: float = 0.5
    max_active_strategies: int = 3
    enable_strategy_blending: bool = True
    blend_threshold: float = 0.7  # 融合阈值


@dataclass
class SelectedStrategy:
    """选中的策略"""

    strategy_type: str
    signal: str  # buy/hold/sell
    confidence: float
    weight: float
    source: str  # "ai_fusion" or "strategy_library"
    reasons: list[str]
    market_conditions: Dict[str, Any]


class StrategySelector:
    """
    策略选择器

    根据市场状态和表现历史，自动选择和融合策略信号
    """

    def __init__(self, config: Optional[SelectionConfig] = None):
        self.config = config or SelectionConfig()

        # 策略表现缓存
        self._strategy_performance: Dict[str, float] = {}
        self._last_selection_time: Optional[datetime] = None
        self._current_market_regime: Optional[str] = None

    def select(
        self,
        ai_signal: Dict[str, Any],
        strategy_signals: list[Dict[str, Any]],
        market_data: Dict[str, Any],
    ) -> SelectedStrategy:
        """
        选择最佳策略信号

        Args:
            ai_signal: AI融合信号
            strategy_signals: 策略库信号列表
            market_data: 市场数据

        Returns:
            SelectedStrategy: 选中的策略
        """
        # 检测当前市场状态
        self._current_market_regime = self._detect_regime(market_data)

        # 更新策略表现
        self._update_performance_cache(strategy_signals)

        # 根据模式选择
        if self.config.mode == SelectionMode.SINGLE_BEST:
            return self._select_single_best(ai_signal, strategy_signals, market_data)
        elif self.config.mode == SelectionMode.WEIGHTED_FUSION:
            return self._select_weighted_fusion(
                ai_signal, strategy_signals, market_data
            )
        else:  # ADAPTIVE
            return self._select_adaptive(ai_signal, strategy_signals, market_data)

    def _detect_regime(self, market_data: Dict[str, Any]) -> str:
        """检测当前市场状态"""
        technical = market_data.get("technical", {})
        trend = technical.get("trend_strength", 0)
        atr = technical.get("atr_percent", 0.02)
        rsi = technical.get("rsi", 50)

        if atr > 0.04:
            return "high_volatility"
        elif abs(trend) > 0.4:
            return "strong_trend" if trend > 0 else "strong_downtrend"
        elif rsi < 35:
            return "oversold"
        elif rsi > 65:
            return "overbought"
        else:
            return "normal"

    def _update_performance_cache(self, strategy_signals: list[Dict[str, Any]]) -> None:
        """更新策略表现缓存"""
        for signal in strategy_signals:
            strategy_type = signal.get("strategy_type", "unknown")
            confidence = signal.get("confidence", 0.5)

            # 简单的表现估算（置信度作为表现代理）
            if strategy_type not in self._strategy_performance:
                self._strategy_performance[strategy_type] = confidence
            else:
                # 平滑更新
                self._strategy_performance[strategy_type] = (
                    0.7 * self._strategy_performance[strategy_type] + 0.3 * confidence
                )

    def _select_single_best(
        self,
        ai_signal: Dict[str, Any],
        strategy_signals: list[Dict[str, Any]],
        market_data: Dict[str, Any],
    ) -> SelectedStrategy:
        """选择最佳单一策略"""
        # 合并所有信号
        all_signals = [ai_signal] + strategy_signals

        # 按置信度排序
        sorted_signals = sorted(
            all_signals, key=lambda x: x.get("confidence", 0), reverse=True
        )

        # 选择最佳
        best = sorted_signals[0]

        return SelectedStrategy(
            strategy_type=best.get("strategy_type", "ai"),
            signal=best.get("signal", "hold"),
            confidence=best.get("confidence", 0.5),
            weight=1.0,
            source="ai_fusion" if best == ai_signal else "strategy",
            reasons=[f"最高置信度: {best.get('confidence', 0):.2%}"],
            market_conditions={"regime": self._current_market_regime},
        )

    def _select_weighted_fusion(
        self,
        ai_signal: Dict[str, Any],
        strategy_signals: list[Dict[str, Any]],
        market_data: Dict[str, Any],
    ) -> SelectedStrategy:
        """加权融合选择"""
        # 合并所有信号
        all_signals = [ai_signal] + strategy_signals

        # 按置信度加权
        signal_scores: Dict[str, float] = {
            "buy": 0.0,
            "hold": 0.0,
            "sell": 0.0,
            "short": 0.0,
        }
        total_weight = 0.0

        for signal in all_signals:
            sig_type = signal.get("signal", "hold").lower()
            confidence = signal.get("confidence", 0.5)
            weight = signal.get("weight", 1.0) * confidence

            signal_scores[sig_type] += weight * confidence
            total_weight += weight

        # 归一化
        if total_weight > 0:
            for sig in signal_scores:
                signal_scores[sig] /= total_weight

        # 选择得分最高的
        final_signal = max(signal_scores, key=lambda k: signal_scores.get(k, 0.0))
        final_confidence = signal_scores[final_signal]

        # 计算权重
        if final_confidence >= self.config.blend_threshold:
            weight = 1.0
            source = "ai_fusion"
        else:
            weight = final_confidence
            source = "blended"

        return SelectedStrategy(
            strategy_type="blended",
            signal=final_signal,
            confidence=final_confidence,
            weight=weight,
            source=source,
            reasons=[f"加权融合: {signal_scores}"],
            market_conditions={"regime": self._current_market_regime},
        )

    def _select_adaptive(
        self,
        ai_signal: Dict[str, Any],
        strategy_signals: list[Dict[str, Any]],
        market_data: Dict[str, Any],
    ) -> SelectedStrategy:
        """自适应选择 - 根据市场状态选择最合适的策略"""
        regime = self._current_market_regime or "normal"
        reasons = []
        selected = None

        # 根据市场状态调整策略优先级
        regime_priority = {
            "high_volatility": ["safe_mode", "trend_following"],
            "strong_trend": ["trend_following", "mean_reversion"],
            "strong_downtrend": ["trend_following", "mean_reversion"],
            "oversold": ["mean_reversion", "breakout"],
            "overbought": ["mean_reversion", "breakout"],
            "normal": ["trend_following", "mean_reversion", "breakout"],
        }

        priority_order = regime_priority.get(regime, ["trend_following"])

        # 查找最佳匹配的策略
        for preferred_type in priority_order:
            for signal in strategy_signals:
                if signal.get("strategy_type") == preferred_type:
                    confidence = signal.get("confidence", 0)
                    if confidence >= self.config.min_confidence_threshold:
                        selected = signal
                        reasons.append(
                            f"优先策略: {preferred_type} (置信度: {confidence:.2%})"
                        )
                        break

            if selected:
                break

        # 如果没有找到匹配策略，使用 AI 信号
        if not selected:
            ai_confidence = ai_signal.get("confidence", 0)
            if ai_confidence >= self.config.min_confidence_threshold:
                selected = ai_signal
                reasons.append(f"使用AI信号 (置信度: {ai_confidence:.2%})")
            else:
                # 最低置信度检查
                all_signals = [ai_signal] + strategy_signals
                selected = max(all_signals, key=lambda x: x.get("confidence", 0))
                reasons.append(f"回退到最高置信度信号")

        # 添加市场状态说明
        reasons.append(f"市场状态: {regime}")

        return SelectedStrategy(
            strategy_type=selected.get("strategy_type", "ai"),
            signal=selected.get("signal", "hold"),
            confidence=selected.get("confidence", 0.5),
            weight=selected.get("weight", 1.0),
            source="ai_fusion" if selected == ai_signal else "strategy",
            reasons=reasons,
            market_conditions={"regime": regime},
        )

    def get_selection_summary(self) -> Dict[str, Any]:
        """获取选择器摘要"""
        return {
            "mode": self.config.mode.value,
            "current_regime": self._current_market_regime,
            "strategy_performance": self._strategy_performance,
            "last_selection": (
                self._last_selection_time.isoformat()
                if self._last_selection_time
                else None
            ),
        }


class AdaptiveStrategyManager:
    """
    自适应策略管理器

    整合策略库、策略选择器和表现追踪
    """

    def __init__(self):
        from .strategy_library import StrategyLibrary, StrategyType
        from .performance_tracker import PerformanceTracker

        # 初始化组件
        self.strategy_library = StrategyLibrary()
        self.selector = StrategySelector()
        self.performance_tracker = PerformanceTracker()

        # 策略配置
        self._strategy_configs: Dict[StrategyType, Dict[str, Any]] = {}

    def analyze_and_select(
        self,
        market_data: Dict[str, Any],
        position_data: Optional[Dict[str, Any]] = None,
    ) -> SelectedStrategy:
        """
        分析市场并选择策略

        Args:
            market_data: 市场数据
            position_data: 持仓数据（可选，无持仓时为None）

        Returns:
            SelectedStrategy: 选中的策略
        """
        # 处理无持仓情况
        if position_data is None:
            position_data = {}

        # 1. 获取所有策略信号
        strategy_signals = []
        for strategy in self.strategy_library.get_active_strategies():
            signal = strategy.analyze(market_data)
            strategy_signals.append(
                {
                    "strategy_type": strategy.strategy_type.value,
                    "signal": signal.signal,
                    "confidence": signal.confidence,
                    "weight": strategy.weight,
                    "reason": signal.reason,
                    "risk_level": signal.risk_level,
                }
            )

        # 2. AI信号（这里需要传入）
        ai_signal = {
            "strategy_type": "ai_fusion",
            "signal": "hold",
            "confidence": 0.5,
            "weight": 1.0,
        }

        # 3. 选择最佳策略
        selected = self.selector.select(ai_signal, strategy_signals, market_data)

        return selected

    def update_strategy_weights(self, trade_outcome: Dict[str, Any]) -> None:
        """
        根据交易结果更新策略权重

        Args:
            trade_outcome: {"strategy_type": str, "outcome": "win"/"loss", "pnl_percent": float}
        """
        strategy_type = trade_outcome.get("strategy_type", "")
        outcome = trade_outcome.get("outcome", "")
        pnl = trade_outcome.get("pnl_percent", 0)

        # 更新表现追踪
        self.performance_tracker.record_trade(
            entry_time="",
            entry_price=0,
            side="",
            confidence=0,
            signal_type="",
            market_regime=self.selector._current_market_regime or "unknown",
            used_threshold=0.5,
            used_stop_loss=0.005,
        )

        # 更新策略权重
        strategy = self.strategy_library.get_strategy(StrategyType(strategy_type))
        if strategy:
            if outcome == "win":
                performance_score = min(1.0, 0.5 + pnl * 10)
            else:
                performance_score = max(0.0, 0.5 - abs(pnl) * 5)

            strategy.update_weight(performance_score)

    def get_manager_summary(self) -> Dict[str, Any]:
        """获取管理器摘要"""
        return {
            "selector": self.selector.get_selection_summary(),
            "strategies": self.strategy_library.get_strategy_summary(),
        }
