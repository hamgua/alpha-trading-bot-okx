"""
策略库模块

定义多种交易策略，每种策略针对特定市场环境：
- TrendFollowing: 趋势跟踪策略
- MeanReversion: 均值回归策略
- Breakout: 突破策略
- Scalping: 剥头皮策略
- SafeMode: 安全模式（极端市场）
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class StrategyType(Enum):
    """策略类型"""

    TREND_FOLLOWING = "trend_following"  # 趋势跟踪
    MEAN_REVERSION = "mean_reversion"  # 均值回归
    BREAKOUT = "breakout"  # 突破
    SCALPING = "scalping"  # 剥头皮
    SAFE_MODE = "safe_mode"  # 安全模式
    CUSTOM = "custom"  # 自定义


@dataclass
class StrategyConfig:
    """策略配置"""

    strategy_type: StrategyType
    enabled: bool = True
    weight: float = 1.0  # 策略权重
    priority: int = 0  # 优先级

    # 策略特定参数
    params: Dict[str, Any] = None

    def __post_init__(self):
        if self.params is None:
            self.params = {}


@dataclass
class StrategySignal:
    """策略信号"""

    strategy_type: StrategyType
    signal: str  # buy/hold/sell
    confidence: float  # 0-1
    weight: float  # 权重
    reason: str  # 信号原因
    market_conditions: Dict[str, Any]  # 市场条件
    risk_level: str  # low/medium/high


class BaseStrategy(ABC):
    """策略基类"""

    def __init__(self, name: str, strategy_type: StrategyType):
        self.name = name
        self.strategy_type = strategy_type
        self.enabled = True
        self.weight = 1.0
        self._performance_history: list[Dict[str, Any]] = []

    @abstractmethod
    def analyze(self, market_data: Dict[str, Any]) -> StrategySignal:
        """
        分析市场数据，生成策略信号

        Args:
            market_data: 市场数据

        Returns:
            StrategySignal: 策略信号
        """
        pass

    @abstractmethod
    def get_default_config(self) -> StrategyConfig:
        """获取默认配置"""
        pass

    def update_weight(self, performance_score: float) -> None:
        """
        根据表现更新策略权重

        Args:
            performance_score: 表现分数 (0-1)
        """
        # 简单的权重更新逻辑
        self.weight = 0.5 + 0.5 * performance_score
        logger.info(f"[策略库] {self.name} 权重更新: {self.weight:.2f}")

    def record_performance(self, signal: StrategySignal, actual_outcome: str) -> None:
        """
        记录策略表现

        Args:
            signal: 发出的信号
            actual_outcome: 实际结果 (win/loss)
        """
        self._performance_history.append(
            {
                "signal": signal.signal,
                "confidence": signal.confidence,
                "outcome": actual_outcome,
                "timestamp": signal.market_conditions.get("timestamp", ""),
            }
        )

        # 保持历史长度
        if len(self._performance_history) > 100:
            self._performance_history.pop(0)

    def get_performance_score(self) -> float:
        """计算策略表现分数"""
        if not self._performance_history:
            return 0.5  # 默认中性

        wins = sum(1 for p in self._performance_history if p["outcome"] == "win")
        total = len(self._performance_history)

        return wins / total if total > 0 else 0.5


class TrendFollowingStrategy(BaseStrategy):
    """趋势跟踪策略"""

    def __init__(self):
        super().__init__("趋势跟踪", StrategyType.TREND_FOLLOWING)

    def analyze(self, market_data: Dict[str, Any]) -> StrategySignal:
        """趋势跟踪信号分析"""
        technical = market_data.get("technical", {})
        trend_strength = technical.get("trend_strength", 0)
        trend_direction = technical.get("trend_direction", "sideways")
        rsi = technical.get("rsi", 50)

        # 趋势强度判断
        if abs(trend_strength) < 0.2:
            return StrategySignal(
                strategy_type=self.strategy_type,
                signal="hold",
                confidence=0.5,
                weight=self.weight,
                reason="趋势不明显",
                market_conditions={
                    "trend_strength": trend_strength,
                    "direction": trend_direction,
                },
                risk_level="medium",
            )

        # 强趋势 - 顺势交易
        if trend_direction == "up" and trend_strength > 0.3:
            # 回调时买入
            if 35 < rsi < 60:
                return StrategySignal(
                    strategy_type=self.strategy_type,
                    signal="buy",
                    confidence=min(0.9, 0.5 + trend_strength * 0.5),
                    weight=self.weight,
                    reason=f"上升趋势中({trend_strength:.2f}), RSI回调至{rsi:.1f}",
                    market_conditions={
                        "trend_strength": trend_strength,
                        "direction": trend_direction,
                        "rsi": rsi,
                    },
                    risk_level="low",
                )

        elif trend_direction == "down" and trend_strength > 0.3:
            # 反弹时卖出
            if 40 < rsi < 70:
                return StrategySignal(
                    strategy_type=self.strategy_type,
                    signal="sell",
                    confidence=min(0.9, 0.5 + trend_strength * 0.5),
                    weight=self.weight,
                    reason=f"下降趋势中({trend_strength:.2f}), RSI反弹至{rsi:.1f}",
                    market_conditions={
                        "trend_strength": trend_strength,
                        "direction": trend_direction,
                        "rsi": rsi,
                    },
                    risk_level="low",
                )

        return StrategySignal(
            strategy_type=self.strategy_type,
            signal="hold",
            confidence=0.6,
            weight=self.weight,
            reason="趋势中但无合适入场点",
            market_conditions={
                "trend_strength": trend_strength,
                "direction": trend_direction,
            },
            risk_level="medium",
        )

    def get_default_config(self) -> StrategyConfig:
        return StrategyConfig(
            strategy_type=StrategyType.TREND_FOLLOWING,
            enabled=True,
            weight=1.0,
            priority=5,
            params={
                "min_trend_strength": 0.2,
                "rsi_buy_range": (35, 60),
                "rsi_sell_range": (40, 70),
            },
        )


class MeanReversionStrategy(BaseStrategy):
    """均值回归策略"""

    def __init__(self):
        super().__init__("均值回归", StrategyType.MEAN_REVERSION)

    def analyze(self, market_data: Dict[str, Any]) -> StrategySignal:
        """均值回归信号分析"""
        technical = market_data.get("technical", {})
        rsi = technical.get("rsi", 50)
        bb_position = technical.get("bb_position", 0.5)
        atr_percent = technical.get("atr_percent", 0.02)

        # 超卖 - 买入
        if rsi < 30:
            return StrategySignal(
                strategy_type=self.strategy_type,
                signal="buy",
                confidence=0.85,
                weight=self.weight,
                reason=f"RSI超卖({rsi:.1f}), 布林带位置:{bb_position:.2%}",
                market_conditions={
                    "rsi": rsi,
                    "bb_position": bb_position,
                    "atr_percent": atr_percent,
                },
                risk_level="medium",
            )

        # 超买 - 卖出
        elif rsi > 70:
            return StrategySignal(
                strategy_type=self.strategy_type,
                signal="sell",
                confidence=0.80,
                weight=self.weight,
                reason=f"RSI超买({rsi:.1f}), 布林带位置:{bb_position:.2%}",
                market_conditions={
                    "rsi": rsi,
                    "bb_position": bb_position,
                    "atr_percent": atr_percent,
                },
                risk_level="medium",
            )

        # 中性
        return StrategySignal(
            strategy_type=self.strategy_type,
            signal="hold",
            confidence=0.5,
            weight=self.weight,
            reason="RSI处于中性区间",
            market_conditions={"rsi": rsi, "bb_position": bb_position},
            risk_level="low",
        )

    def get_default_config(self) -> StrategyConfig:
        return StrategyConfig(
            strategy_type=StrategyType.MEAN_REVERSION,
            enabled=True,
            weight=1.0,
            priority=4,
            params={
                "oversold_threshold": 30,
                "overbought_threshold": 70,
                "bb_buy_threshold": 0.2,
                "bb_sell_threshold": 0.8,
            },
        )


class BreakoutStrategy(BaseStrategy):
    """突破策略"""

    def __init__(self):
        super().__init__("突破", StrategyType.BREAKOUT)

    def analyze(self, market_data: Dict[str, Any]) -> StrategySignal:
        """突破信号分析"""
        technical = market_data.get("technical", {})
        bb_position = technical.get("bb_position", 0.5)
        atr_percent = technical.get("atr_percent", 0.02)
        trend_strength = technical.get("trend_strength", 0)

        # 布林带位置判断
        if bb_position > 0.85:
            # 接近上轨 - 可能突破
            if atr_percent > 0.025:
                return StrategySignal(
                    strategy_type=self.strategy_type,
                    signal="buy",
                    confidence=0.75,
                    weight=self.weight,
                    reason=f"布林带上轨({bb_position:.2%}), 高波动({atr_percent:.2%})",
                    market_conditions={
                        "bb_position": bb_position,
                        "atr_percent": atr_percent,
                        "trend": trend_strength,
                    },
                    risk_level="high",
                )

        elif bb_position < 0.15:
            # 接近下轨 - 可能跌破
            if atr_percent > 0.025:
                return StrategySignal(
                    strategy_type=self.strategy_type,
                    signal="sell",
                    confidence=0.75,
                    weight=self.weight,
                    reason=f"布林带下轨({bb_position:.2%}), 高波动({atr_percent:.2%})",
                    market_conditions={
                        "bb_position": bb_position,
                        "atr_percent": atr_percent,
                        "trend": trend_strength,
                    },
                    risk_level="high",
                )

        return StrategySignal(
            strategy_type=self.strategy_type,
            signal="hold",
            confidence=0.5,
            weight=self.weight,
            reason="无明显突破信号",
            market_conditions={"bb_position": bb_position},
            risk_level="low",
        )

    def get_default_config(self) -> StrategyConfig:
        return StrategyConfig(
            strategy_type=StrategyType.BREAKOUT,
            enabled=True,
            weight=0.8,
            priority=3,
            params={
                "bb_upper_threshold": 0.85,
                "bb_lower_threshold": 0.15,
                "min_volatility": 0.025,
            },
        )


class SafeModeStrategy(BaseStrategy):
    """安全模式策略"""

    def __init__(self):
        super().__init__("安全模式", StrategyType.SAFE_MODE)

    def analyze(self, market_data: Dict[str, Any]) -> StrategySignal:
        """安全模式信号 - 极端市场下强制暂停交易"""
        technical = market_data.get("technical", {})
        atr_percent = technical.get("atr_percent", 0.02)
        trend_strength = technical.get("trend_strength", 0)
        recent_drop = market_data.get("recent_drop_percent", 0)

        # 检测极端市场条件
        is_extreme = False
        reasons = []

        # 极高波动
        if atr_percent > 50:  # ATR% > 50%
            is_extreme = True
            reasons.append(f"波动率极高({atr_percent:.2%})")

        # 剧烈下跌
        if recent_drop < -0.03:
            is_extreme = True
            reasons.append(f"1小时跌幅({recent_drop:.2%})")

        # 趋势混乱
        if abs(trend_strength) < 0.1:
            is_extreme = True
            reasons.append("趋势混乱")

        if is_extreme:
            return StrategySignal(
                strategy_type=self.strategy_type,
                signal="hold",
                confidence=1.0,
                weight=2.0,  # 安全模式权重最高
                reason=f"极端市场: {', '.join(reasons)}",
                market_conditions={
                    "atr_percent": atr_percent,
                    "recent_drop": recent_drop,
                    "trend": trend_strength,
                },
                risk_level="critical",
            )

        return StrategySignal(
            strategy_type=self.strategy_type,
            signal="hold",
            confidence=0.3,
            weight=0.0,  # 正常市场下不激活
            reason="市场正常，安全模式不激活",
            market_conditions={},
            risk_level="low",
        )

    def get_default_config(self) -> StrategyConfig:
        return StrategyConfig(
            strategy_type=StrategyType.SAFE_MODE,
            enabled=True,
            weight=2.0,
            priority=10,  # 最高优先级
            params={
                "max_volatility": 50,  # 50% ATR 阈值
                "max_drop_1h": 0.03,
                "min_trend": 0.1,
            },
        )


class StrategyLibrary:
    """策略库管理"""

    def __init__(self):
        self.strategies: Dict[StrategyType, BaseStrategy] = {}
        self._register_default_strategies()

    def _register_default_strategies(self) -> None:
        """注册默认策略"""
        self.strategies = {
            StrategyType.TREND_FOLLOWING: TrendFollowingStrategy(),
            StrategyType.MEAN_REVERSION: MeanReversionStrategy(),
            StrategyType.BREAKOUT: BreakoutStrategy(),
            StrategyType.SAFE_MODE: SafeModeStrategy(),
        }
        logger.info(f"[策略库] 已注册 {len(self.strategies)} 个策略")

    def get_strategy(self, strategy_type: StrategyType) -> Optional[BaseStrategy]:
        """获取策略"""
        return self.strategies.get(strategy_type)

    def get_all_signals(self, market_data: Dict[str, Any]) -> list[StrategySignal]:
        """获取所有策略信号"""
        signals = []
        for strategy in self.strategies.values():
            if strategy.enabled:
                signal = strategy.analyze(market_data)
                signals.append(signal)
        return signals

    def get_active_strategies(self) -> list[BaseStrategy]:
        """获取所有启用的策略"""
        return [s for s in self.strategies.values() if s.enabled and s.weight > 0]

    def update_all_weights(self) -> None:
        """根据表现更新所有策略权重"""
        for strategy in self.strategies.values():
            score = strategy.get_performance_score()
            strategy.update_weight(score)

    def get_strategy_summary(self) -> list[Dict[str, Any]]:
        """获取策略摘要"""
        return [
            {
                "name": s.name,
                "type": s.strategy_type.value,
                "enabled": s.enabled,
                "weight": s.weight,
                "performance_score": s.get_performance_score(),
                "trades_count": len(s._performance_history),
            }
            for s in self.strategies.values()
        ]
