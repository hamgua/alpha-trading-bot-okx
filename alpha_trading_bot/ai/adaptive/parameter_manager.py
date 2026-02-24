"""
参数自适应管理器

功能：
- 整合市场环境检测和表现追踪
- 应用自适应规则调整交易参数
- 提供统一的参数调整接口
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class AdaptiveConfig:
    """
    自适应配置

    存储基础配置和当前调整后的配置
    """

    # 基础配置（来自环境变量或配置文件）
    base_fusion_threshold: float = 0.5
    base_stop_loss_percent: float = 0.005
    base_stop_loss_profit_percent: float = 0.002
    base_position_multiplier: float = 1.0
    base_buy_rsi_threshold: float = 70.0
    base_buy_trend_strength: float = 0.15

    # === 新增：adaptive_buy_condition 参数 ===
    base_oversold_rsi_max: float = 38.0
    base_oversold_momentum_min: float = 0.004
    base_oversold_trend_strength_min: float = 0.12
    base_oversold_bb_position_max: float = 42.0
    base_oversold_position_factor: float = 0.55
    base_support_price_position_max: float = 40.0
    base_support_position_factor: float = 0.85

    # === 新增：signal_optimizer 参数 ===
    base_confidence_floor: float = 0.42
    base_rapid_change_threshold: float = 0.20

    # 当前调整后的值
    current_fusion_threshold: float = 0.5
    current_stop_loss_percent: float = 0.005
    current_stop_loss_profit_percent: float = 0.002
    current_position_multiplier: float = 1.0
    current_buy_rsi_threshold: float = 70.0
    current_buy_trend_strength: float = 0.15

    # === 新增：adaptive_buy_condition 当前值 ===
    current_oversold_rsi_max: float = 38.0
    current_oversold_momentum_min: float = 0.004
    current_oversold_trend_strength_min: float = 0.12
    current_oversold_bb_position_max: float = 42.0
    current_oversold_position_factor: float = 0.55
    current_support_price_position_max: float = 40.0
    current_support_position_factor: float = 0.85

    # === 新增：signal_optimizer 当前值 ===
    current_confidence_floor: float = 0.42
    current_rapid_change_threshold: float = 0.20

    # 最后更新时间
    last_updated: Optional[str] = None

    def get_trading_params(self) -> Dict[str, float]:
        """获取交易参数"""
        return {
            "fusion_threshold": self.current_fusion_threshold,
            "stop_loss_percent": self.current_stop_loss_percent,
            "stop_loss_profit_percent": self.current_stop_loss_profit_percent,
            "position_multiplier": self.current_position_multiplier,
            "buy_rsi_threshold": self.current_buy_rsi_threshold,
            "buy_trend_strength": self.current_buy_trend_strength,
            # === 新增 ===
            "oversold_rsi_max": self.current_oversold_rsi_max,
            "oversold_momentum_min": self.current_oversold_momentum_min,
            "oversold_trend_strength_min": self.current_oversold_trend_strength_min,
            "oversold_bb_position_max": self.current_oversold_bb_position_max,
            "oversold_position_factor": self.current_oversold_position_factor,
            "support_price_position_max": self.current_support_price_position_max,
            "support_position_factor": self.current_support_position_factor,
            "confidence_floor": self.current_confidence_floor,
            "rapid_change_threshold": self.current_rapid_change_threshold,
        }

    def apply_adjustments(self, adjustments: Dict[str, float]) -> None:
        """应用调整"""
        # 融合阈值
        if "fusion_threshold" in adjustments:
            self.current_fusion_threshold = adjustments["fusion_threshold"]

        # 止损比例
        if "stop_loss_percent" in adjustments:
            self.current_stop_loss_percent = adjustments["stop_loss_percent"]

        # 盈利止损
        if "stop_loss_profit_percent" in adjustments:
            self.current_stop_loss_profit_percent = adjustments["stop_loss_profit_percent"]

        # 仓位乘数
        if "position_multiplier" in adjustments:
            self.current_position_multiplier = adjustments["position_multiplier"]

        # 买入RSI阈值
        if "buy_rsi_threshold" in adjustments:
            self.current_buy_rsi_threshold = adjustments["buy_rsi_threshold"]

        # 趋势强度阈值
        if "buy_trend_strength" in adjustments:
            self.current_buy_trend_strength = adjustments["buy_trend_strength"]

        # === 新增：adaptive_buy_condition 参数 ===
        if "oversold_rsi_max" in adjustments:
            self.current_oversold_rsi_max = adjustments["oversold_rsi_max"]
        if "oversold_momentum_min" in adjustments:
            self.current_oversold_momentum_min = adjustments["oversold_momentum_min"]
        if "oversold_trend_strength_min" in adjustments:
            self.current_oversold_trend_strength_min = adjustments["oversold_trend_strength_min"]
        if "oversold_bb_position_max" in adjustments:
            self.current_oversold_bb_position_max = adjustments["oversold_bb_position_max"]
        if "oversold_position_factor" in adjustments:
            self.current_oversold_position_factor = adjustments["oversold_position_factor"]
        if "support_price_position_max" in adjustments:
            self.current_support_price_position_max = adjustments["support_price_position_max"]
        if "support_position_factor" in adjustments:
            self.current_support_position_factor = adjustments["support_position_factor"]

        # === 新增：signal_optimizer 参数 ===
        if "confidence_floor" in adjustments:
            self.current_confidence_floor = adjustments["confidence_floor"]
        if "rapid_change_threshold" in adjustments:
            self.current_rapid_change_threshold = adjustments["rapid_change_threshold"]

        self.last_updated = datetime.now().isoformat()

    def reset_to_base(self) -> None:
        """重置为基础配置"""
        self.current_fusion_threshold = self.base_fusion_threshold
        self.current_stop_loss_percent = self.base_stop_loss_percent
        self.current_stop_loss_profit_percent = self.base_stop_loss_profit_percent
        self.current_position_multiplier = self.base_position_multiplier
        self.current_buy_rsi_threshold = self.base_buy_rsi_threshold
        self.current_buy_trend_strength = self.base_buy_trend_strength
        # === 新增 ===
        self.current_oversold_rsi_max = self.base_oversold_rsi_max
        self.current_oversold_momentum_min = self.base_oversold_momentum_min
        self.current_oversold_trend_strength_min = self.base_oversold_trend_strength_min
        self.current_oversold_bb_position_max = self.base_oversold_bb_position_max
        self.current_oversold_position_factor = self.base_oversold_position_factor
        self.current_support_price_position_max = self.base_support_price_position_max
        self.current_support_position_factor = self.base_support_position_factor
        self.current_confidence_floor = self.base_confidence_floor
        self.current_rapid_change_threshold = self.base_rapid_change_threshold
        self.last_updated = datetime.now().isoformat()


class AdaptiveParameterManager:
    """
    参数自适应管理器

    核心组件，整合所有自适应功能
    """

    def __init__(
        self,
        base_config: Optional[AdaptiveConfig] = None,
        enable_logging: bool = True,
    ):
        """
        初始化管理器

        Args:
            base_config: 基础配置
            enable_logging: 是否启用日志
        """
        from .market_regime import MarketRegimeDetector
        from .performance_tracker import PerformanceTracker
        from .rules_engine import AdaptiveRulesEngine

        self.config = base_config or AdaptiveConfig()
        self.enable_logging = enable_logging

        # 组件
        self.regime_detector = MarketRegimeDetector()
        self.performance_tracker = PerformanceTracker()
        self.rules_engine = AdaptiveRulesEngine()

        # 日志
        if self.enable_logging:
            logger.info(
                f"[自适应] 初始化完成, 基础阈值: {self.config.base_fusion_threshold}"
            )

    def analyze_and_adjust(
        self,
        market_data: Dict[str, Any],
        recent_performance: Optional[Dict[str, Any]] = None,
    ) -> AdaptiveConfig:
        """
        分析市场环境并调整参数

        Args:
            market_data: 市场数据
            recent_performance: 最近表现数据（可选）

        Returns:
            调整后的配置
        """
        # 1. 检测市场环境
        market_state = self.regime_detector.detect(market_data)

        # 2. 获取绩效指标
        performance = self.performance_tracker.get_performance_metrics()

        # 3. 合并表现数据
        if recent_performance:
            # 合并最近表现
            pass

        # 4. 应用规则
        result = self.rules_engine.evaluate_all(market_state, performance)

        # 5. 应用调整
        if result["adjustments"]:
            self.config.apply_adjustments(result["adjustments"])
            if self.enable_logging:
                logger.info(
                    f"[自适应] 触发 {len(result['triggered_rules'])} 个规则: "
                    f"{result['triggered_rules']}"
                )
                logger.info(f"[自适应] 调整参数: {result['adjustments']}")
        else:
            # 无规则触发，重置为基础值
            self.config.reset_to_base()
            if self.enable_logging:
                logger.info("[自适应] 无规则触发，使用基础配置")

        # 6. 记录市场状态用于后续分析
        self._last_market_state = market_state

        return self.config

    def get_current_params(self) -> Dict[str, float]:
        """获取当前交易参数"""
        return self.config.get_trading_params()

    def record_trade(
        self,
        entry_time: str,
        entry_price: float,
        side: str,
        confidence: float,
        signal_type: str,
    ) -> None:
        """记录开仓"""
        market_state = getattr(self, "_last_market_state", None)
        regime = market_state.regime.value if market_state else "unknown"

        self.performance_tracker.record_trade(
            entry_time=entry_time,
            entry_price=entry_price,
            side=side,
            confidence=confidence,
            signal_type=signal_type,
            market_regime=regime,
            used_threshold=self.config.current_fusion_threshold,
            used_stop_loss=self.config.current_stop_loss_percent,
        )

    def close_trade(
        self,
        exit_time: str,
        exit_price: float,
        reason: str = "signal",
    ) -> None:
        """记录平仓"""
        self.performance_tracker.close_trade(exit_time, exit_price, reason)

    def get_performance_report(self) -> Dict[str, Any]:
        """获取表现报告"""
        return {
            "metrics": self.performance_tracker.get_performance_metrics().__dict__,
            "regime_performance": self.performance_tracker.get_regime_performance(),
            "recent_performance": self.performance_tracker.get_recent_performance(),
            "last_market_state": (
                self._last_market_state.__dict__
                if hasattr(self, "_last_market_state")
                else None
            ),
            "current_params": self.config.get_trading_params(),
            "active_rules": self.rules_engine.get_rule_summary(),
        }

    def get_regime_distribution(self) -> Dict[str, int]:
        """获取市场环境分布"""
        return self.performance_tracker.get_recent_performance().get(
            "regime_distribution", {}
        )

    def reset(self) -> None:
        """重置所有状态"""
        self.regime_detector.reset()
        self.performance_tracker.reset()
        self.config.reset_to_base()
