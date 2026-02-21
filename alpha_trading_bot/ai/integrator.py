"""
AI信号优化集成器

集成所有信号优化模块，提供统一的接口：
1. AdaptiveBuyCondition - 自适应买入条件
2. SignalOptimizer - 信号优化器
3. HighPriceBuyOptimizer - 高位买入优化器
4. BTCPriceLevelDetector - BTC价格水平检测

使用方式：
from alpha_trading_bot.ai.integrator import AISignalIntegrator

integrator = AISignalIntegrator()
result = integrator.process(market_data)
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

from .adaptive_buy_condition import (
    AdaptiveBuyCondition,
    BuyConditions,
    BuyConditionResult,
)
from .signal_optimizer import SignalOptimizer, OptimizerConfig, OptimizedSignal
from .high_price_buy_optimizer import HighPriceBuyOptimizer, HighPriceBuyConfig
from .btc_price_detector import BTCPriceLevelDetector, BTCPriceLevelConfig

logger = logging.getLogger(__name__)


@dataclass
class IntegrationConfig:
    """集成器配置"""

    # 是否启用各模块
    enable_adaptive_buy: bool = True
    enable_signal_optimizer: bool = True
    enable_high_price_filter: bool = True
    enable_btc_detector: bool = True

    # AdaptiveBuyCondition配置
    adaptive_buy_config: Optional[BuyConditions] = None

    # SignalOptimizer配置
    signal_optimizer_config: Optional[OptimizerConfig] = None

    # HighPriceBuyOptimizer配置
    high_price_config: Optional[HighPriceBuyConfig] = None

    # BTC价格检测配置
    btc_detector_config: Optional[BTCPriceLevelConfig] = None


@dataclass
class IntegratedSignalResult:
    """集成后的信号结果"""

    original_signal: str
    original_confidence: float

    # 各阶段结果
    buy_condition_result: Optional[BuyConditionResult] = None
    optimized_signal: Optional[OptimizedSignal] = None
    high_price_result: Optional[Dict] = None
    btc_level_result: Optional[Dict] = None

    # 最终结果
    final_signal: str = "HOLD"
    final_confidence: float = 0.50

    # 元数据
    price_level: str = "mid"
    is_high_risk: bool = False
    is_low_opportunity: bool = False
    adjustments_made: list = None


class AISignalIntegrator:
    """
    AI信号优化集成器

    信号处理流程：
    1. AdaptiveBuyCondition → 判断是否应该买入
    2. SignalOptimizer → 优化信号和置信度
    3. HighPriceBuyOptimizer → 高位信号过滤
    4. BTCPriceLevelDetector → 价格水平检测

    最终输出优化后的信号
    """

    def __init__(self, config: Optional[IntegrationConfig] = None):
        """
        初始化集成器

        Args:
            config: 集成配置，如果为None则使用默认配置
        """
        self.config = config or IntegrationConfig()
        self._init_modules()

        logger.info("[AI信号集成器] 初始化完成")
        logger.info(f"  - 自适应买入: {self.config.enable_adaptive_buy}")
        logger.info(f"  - 信号优化: {self.config.enable_signal_optimizer}")
        logger.info(f"  - 高位过滤: {self.config.enable_high_price_filter}")
        logger.info(f"  - BTC检测: {self.config.enable_btc_detector}")

    def _init_modules(self):
        """初始化各模块"""
        # AdaptiveBuyCondition
        if self.config.enable_adaptive_buy:
            adaptive_config = self.config.adaptive_buy_config or BuyConditions()
            self.adaptive_buy = AdaptiveBuyCondition(adaptive_config)
        else:
            self.adaptive_buy = None

        # SignalOptimizer
        if self.config.enable_signal_optimizer:
            optimizer_config = self.config.signal_optimizer_config or OptimizerConfig()
            self.signal_optimizer = SignalOptimizer(optimizer_config)
        else:
            self.signal_optimizer = None

        # HighPriceBuyOptimizer
        if self.config.enable_high_price_filter:
            high_config = self.config.high_price_config or HighPriceBuyConfig()
            self.high_price_optimizer = HighPriceBuyOptimizer(high_config)
        else:
            self.high_price_optimizer = None

        # BTCPriceLevelDetector
        if self.config.enable_btc_detector:
            btc_config = self.config.btc_detector_config or BTCPriceLevelConfig()
            self.btc_detector = BTCPriceLevelDetector(btc_config)
        else:
            self.btc_detector = None

    def process(
        self,
        market_data: Dict[str, Any],
        original_signal: str = "HOLD",
        original_confidence: float = 0.50,
    ) -> IntegratedSignalResult:
        """
        处理信号

        Args:
            market_data: 市场数据
                {
                    "price": float,
                    "recent_change_percent": float,
                    "technical": {
                        "rsi": float,
                        "macd_hist": float,
                        "bb_position": float,
                        "trend_direction": str,
                        "trend_strength": float,
                        "adx": float,
                        "price_position": float,
                    },
                    "price_history": List[float],
                    "hourly_changes": List[float],
                }
            original_signal: 原始信号
            original_confidence: 原始置信度

        Returns:
            IntegratedSignalResult: 集成后的信号结果
        """
        result = IntegratedSignalResult(
            original_signal=original_signal,
            original_confidence=original_confidence,
            adjustments_made=[],
        )

        # 置信度范围校验: 确保 confidence 在 0-1 范围内
        if original_confidence > 1:
            logger.warning(
                f"[信号集成] 置信度 {original_confidence} 超出 0-1 范围，自动归一化"
            )
            original_confidence = original_confidence / 100.0

        # ========== 诊断日志：记录每个阶段的置信度 ==========
        conf_history = [(0, "原始", original_confidence)]

        # 1. AdaptiveBuyCondition
        if self.adaptive_buy and self.config.enable_adaptive_buy:
            try:
                buy_result = self.adaptive_buy.should_buy(market_data=market_data)
                result.buy_condition_result = buy_result

                # 如果买入条件判断可以买入，提高置信度
                if buy_result.can_buy:
                    original_confidence = max(
                        original_confidence, buy_result.confidence
                    )
                    original_signal = "BUY"
                    result.adjustments_made.append(
                        f"自适应买入: {buy_result.mode}模式通过"
                    )

                result.price_level = buy_result.mode
                conf_history.append((1, "AdaptiveBuy", original_confidence))

            except Exception as e:
                logger.warning(f"AdaptiveBuyCondition处理失败: {e}")

        # 2. SignalOptimizer
        if self.signal_optimizer and self.config.enable_signal_optimizer:
            try:
                price = market_data.get("price", 0)
                optimized = self.signal_optimizer.optimize(
                    signal=original_signal,
                    confidence=original_confidence,
                    price=price,
                    market_data=market_data,
                )

                if optimized.signal != original_signal:
                    original_signal = optimized.signal
                    result.adjustments_made.append(
                        f"信号优化: {original_signal} → {optimized.signal}"
                    )

                original_confidence = optimized.confidence
                result.optimized_signal = optimized
                conf_history.append((2, "SignalOptimizer", original_confidence))

                # 更新价格历史
                self.signal_optimizer.update_price_history(price)

            except Exception as e:
                logger.warning(f"SignalOptimizer处理失败: {e}")

        # 3. BTC价格水平检测
        if self.btc_detector and self.config.enable_btc_detector:
            try:
                price = market_data.get("price", 0)
                btc_result = self.btc_detector.detect_level(price)

                result.btc_level_result = {
                    "level": btc_result.level,
                    "is_high_risk": btc_result.is_high_risk,
                    "is_low_opportunity": btc_result.is_low_opportunity,
                    "distance_to_high": btc_result.distance_to_high,
                    "distance_to_low": btc_result.distance_to_low,
                }

                result.price_level = btc_result.level
                result.is_high_risk = btc_result.is_high_risk
                result.is_low_opportunity = btc_result.is_low_opportunity

                # 如果是高风险，降低置信度
                if btc_result.is_high_risk and original_signal == "BUY":
                    old_conf = original_confidence
                    original_confidence *= 0.7
                    result.adjustments_made.append(
                        f"BTC检测: 高位风险，置信度降低30% ({old_conf:.0%}→{original_confidence:.0%})"
                    )
                    conf_history.append((3, "BTC高位", original_confidence))

                # 如果是低机会，增加置信度
                if btc_result.is_low_opportunity and original_signal == "BUY":
                    old_conf = original_confidence
                    original_confidence *= 1.15
                    result.adjustments_made.append(
                        f"BTC检测: 低位机会，置信度增加15% ({old_conf:.0%}→{original_confidence:.0%})"
                    )
                    conf_history.append((3, "BTC低位", original_confidence))

            except Exception as e:
                logger.warning(f"BTC价格检测处理失败: {e}")

        # 4. HighPriceBuyOptimizer
        if self.high_price_optimizer and self.config.enable_high_price_filter:
            try:
                optimized = self.high_price_optimizer.optimize_high_price_buy(
                    market_data=market_data,
                    original_confidence=original_confidence,
                    original_can_buy=(original_signal == "BUY"),
                    buy_mode=result.price_level,
                    original_signal=original_signal,
                )

                result.high_price_result = {
                    "adjusted_confidence": optimized.adjusted_confidence,
                    "should_buy": optimized.should_buy,
                    "price_level": optimized.price_level,
                    "adjustment_reason": optimized.adjustment_reason,
                }

                # 如果优化器说不要买入，改为HOLD
                if not optimized.should_buy and original_signal == "BUY":
                    original_signal = "HOLD"
                    result.adjustments_made.append(
                        f"高位过滤: 不建议买入 - {optimized.adjustment_reason[:50]}..."
                    )

                original_confidence = optimized.adjusted_confidence
                conf_history.append((4, "HighPrice", original_confidence))

            except Exception as e:
                logger.warning(f"HighPriceBuyOptimizer处理失败: {e}")

        # 5. 最终结果
        result.final_signal = original_signal
        result.final_confidence = min(max(original_confidence, 0.35), 0.95)

        # 记录置信度变化历史
        conf_history.append((5, "最终", result.final_confidence))

        # 打印诊断日志
        logger.info("[信号诊断] 置信度变化流程:")
        for stage, name, conf in conf_history:
            logger.info(f"  [{stage}] {name}: {conf:.1%}")

        # 记录最终结果
        logger.info(
            f"[AI信号集成] "
            f"原始={result.original_signal}({result.original_confidence:.0%}) → "
            f"最终={result.final_signal}({result.final_confidence:.0%})"
        )

        if result.adjustments_made:
            for adj in result.adjustments_made:
                logger.info(f"  - {adj}")

        return result

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = {}

        if self.signal_optimizer:
            stats["signal_optimizer"] = self.signal_optimizer.get_statistics()

        if self.btc_detector:
            stats["btc_detector"] = self.btc_detector.get_info()

        return stats

    def reset(self):
        """重置所有模块"""
        if self.signal_optimizer:
            self.signal_optimizer.reset()
        logger.info("[AI信号集成器] 已重置")


def create_integrator(
    mode: str = "standard",
) -> AISignalIntegrator:
    """
    创建集成器的快捷函数

    Args:
        mode: 模式
            - "standard": 标准模式，所有模块启用
            - "high_price_filter": 重点高位过滤
            - "btc_focused": BTC重点模式
            - "minimal": 最小配置

    Returns:
        AISignalIntegrator: 集成器实例
    """
    configs = {
        "standard": IntegrationConfig(
            enable_adaptive_buy=True,
            enable_signal_optimizer=True,
            enable_high_price_filter=True,
            enable_btc_detector=True,
        ),
        "high_price_filter": IntegrationConfig(
            enable_adaptive_buy=True,
            enable_signal_optimizer=True,
            enable_high_price_filter=True,
            enable_btc_detector=False,
        ),
        "btc_focused": IntegrationConfig(
            enable_adaptive_buy=True,
            enable_signal_optimizer=True,
            enable_high_price_filter=True,
            enable_btc_detector=True,
            btc_detector_config=BTCPriceLevelConfig(
                high_threshold=0.99,  # 更保守
                low_threshold=0.01,  # 更敏感
            ),
        ),
        "minimal": IntegrationConfig(
            enable_adaptive_buy=True,
            enable_signal_optimizer=False,
            enable_high_price_filter=False,
            enable_btc_detector=False,
        ),
    }

    config = configs.get(mode, IntegrationConfig())
    return AISignalIntegrator(config)
