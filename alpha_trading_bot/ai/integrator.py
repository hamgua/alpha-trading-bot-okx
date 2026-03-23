"""
AI信号优化集成器

集成所有信号优化模块，提供统一的接口：
1. AdaptiveBuyCondition - 自适应买入条件
2. SignalOptimizer - 信号优化器
3. HighPriceBuyOptimizer - 高位买入优化器
4. BTCPriceLevelDetector - BTC价格水平检测
5. SustainedDeclineDetector - 持续下跌检测

使用方式：
from alpha_trading_bot.ai.integrator import AISignalIntegrator

integrator = AISignalIntegrator()
result = integrator.process(market_data)
"""

import logging
import traceback
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
from .sustained_decline_detector import (
    SustainedDeclineDetector,
    SustainedDeclineConfig,
    DeclineDetectionResult,
)
from .integrator_config import IntegrationConfig, SignalThresholdsConfig

logger = logging.getLogger(__name__)


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
    sustained_decline_result: Optional[DeclineDetectionResult] = None  # 新增

    # 最终结果
    final_signal: str = "HOLD"
    final_confidence: float = 0.50

    # 元数据
    price_level: str = "mid"
    is_high_risk: bool = False
    is_low_opportunity: bool = False
    is_sustained_decline: bool = False  # 新增：是否检测到持续下跌
    adjustments_made: list = None


class AISignalIntegrator:
    """
    AI信号优化集成器

    信号处理流程：
    1. SustainedDeclineDetector → 检测持续下跌趋势（新增，最先执行）
    2. AdaptiveBuyCondition → 判断是否应该买入
    3. SignalOptimizer → 优化信号和置信度
    4. BTCPriceLevelDetector → 价格水平检测
    5. HighPriceBuyOptimizer → 高位信号过滤

    最终输出优化后的信号
    """

    _thresholds: SignalThresholdsConfig = SignalThresholdsConfig()

    def _t(self) -> SignalThresholdsConfig:
        """获取阈值配置"""
        return self._thresholds

    def __init__(
        self,
        config: Optional[IntegrationConfig] = None,
        thresholds: Optional[SignalThresholdsConfig] = None,
    ):
        self.config = config or IntegrationConfig()
        if thresholds is not None:
            self._thresholds = thresholds
        self._init_modules()

        logger.info("[AI信号集成器] 初始化完成")
        logger.info(f"  - 自适应买入: {self.config.enable_adaptive_buy}")
        logger.info(f"  - 信号优化: {self.config.enable_signal_optimizer}")
        logger.info(f"  - 高位过滤: {self.config.enable_high_price_filter}")
        logger.info(f"  - BTC检测: {self.config.enable_btc_detector}")
        logger.info(
            f"  - 持续下跌检测: {self.config.enable_sustained_decline_detector}"
        )

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
            if self.config.btc_detector_config:
                btc_config = self.config.btc_detector_config
            else:
                btc_config = BTCPriceLevelConfig(
                    high_threshold=self._thresholds.btc_high_threshold,
                    low_threshold=self._thresholds.btc_low_threshold,
                )
            self.btc_detector = BTCPriceLevelDetector(btc_config)
        else:
            self.btc_detector = None

        # SustainedDeclineDetector - 持续下跌检测
        if self.config.enable_sustained_decline_detector:
            decline_config = (
                self.config.sustained_decline_config or SustainedDeclineConfig()
            )
            self.sustained_decline_detector = SustainedDeclineDetector(decline_config)
        else:
            self.sustained_decline_detector = None

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
                    "cycle_start_price": float,  # 新增：周期开始价格
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

        # ===== 0. 持续下跌检测 (新增，最先执行) =====
        decline_result = None
        if (
            self.sustained_decline_detector
            and self.config.enable_sustained_decline_detector
        ):
            try:
                decline_result = self.sustained_decline_detector.detect(
                    market_data=market_data
                )
                result.sustained_decline_result = decline_result
                result.is_sustained_decline = decline_result.is_detected

                # 如果检测到持续下跌，根据结果调整信号
                if decline_result.is_detected:
                    # 记录检测到的下跌级别
                    if decline_result.decline_level == "severe":
                        logger.warning(
                            f"[持续下跌检测] ⚠️ 检测到严重下跌趋势: "
                            f"累积跌幅{decline_result.metrics.cumulative_decline_percent:.2f}% "
                            f"(严重级别)"
                        )
                    elif decline_result.decline_level == "moderate":
                        logger.warning(
                            f"[持续下跌检测] ⚠️ 检测到中度下跌趋势: "
                            f"累积跌幅{decline_result.metrics.cumulative_decline_percent:.2f}%"
                        )
                    else:
                        logger.info(
                            f"[持续下跌检测] ℹ️ 检测到轻度下跌趋势: "
                            f"累积跌幅{decline_result.metrics.cumulative_decline_percent:.2f}%"
                        )

                    # 根据下跌级别调整信号
                    if decline_result.should_block_buy:
                        # 严重下跌，完全阻断BUY信号
                        if original_signal == "BUY":
                            original_signal = "HOLD"
                            result.adjustments_made.append(
                                "持续下跌检测: 严重下跌趋势，完全阻断BUY信号"
                            )
                            logger.warning("[持续下跌检测] 🚫 完全阻断BUY信号")
                    else:
                        # 非完全阻断情况下，降低BUY置信度或增加SELL置信度
                        if original_signal == "BUY" and decline_result.buy_penalty > 0:
                            old_conf = original_confidence
                            original_confidence = max(
                                original_confidence - decline_result.buy_penalty,
                                self._t().confidence_floor,
                            )
                            result.adjustments_made.append(
                                f"持续下跌检测: BUY信号置信度降低{decline_result.buy_penalty:.0%} "
                                f"({old_conf:.0%}→{original_confidence:.0%})"
                            )
                            conf_history.append(
                                (
                                    self._t().confidence_base,
                                    "下跌检测",
                                    original_confidence,
                                )
                            )

                        # 如果是SELL信号，增加置信度
                        if original_signal == "SELL" and decline_result.sell_boost > 0:
                            old_conf = original_confidence
                            original_confidence = min(
                                original_confidence + decline_result.sell_boost,
                                self._t().confidence_ceiling,
                            )
                            result.adjustments_made.append(
                                f"持续下跌检测: SELL信号置信度增加{decline_result.sell_boost:.0%} "
                                f"({old_conf:.0%}→{original_confidence:.0%})"
                            )
                            conf_history.append(
                                (
                                    self._t().confidence_base,
                                    "下跌检测",
                                    original_confidence,
                                )
                            )

            except Exception as e:
                logger.warning(
                    f"持续下跌检测处理失败: {e}, 位置: {traceback.format_exc(limit=3)}"
                )

        # ===== 0.5. SHORT信号专用处理 =====
        if original_signal.upper() == "SHORT":
            logger.info("[信号集成] 检测到 SHORT 信号（趋势下跌苗头），应用做空优化...")

            # 获取市场数据
            technical = market_data.get("technical", {})
            trend_direction = technical.get("trend_direction", "neutral")
            trend_strength = technical.get("trend_strength", 0)
            price_position = technical.get("price_position", 0.5)

            # SHORT 信号的风险检查
            # 1. 趋势检查：SHORT 信号需要趋势向下
            if trend_direction not in ["down", "neutral"]:
                logger.warning("[SHORT优化] 趋势向上时做空风险高，降低置信度")
                old_conf = original_confidence
                original_confidence *= self._t().short_trend_up_penalty
                result.adjustments_made.append(
                    f"SHORT优化: 趋势非下跌，置信度降低{int((1 - self._t().short_trend_up_penalty) * 100)}% ({old_conf:.0%}→{original_confidence:.0%})"
                )

            # 2. 价格位置检查：价格太低时不建议做空（接近支撑位）
            if price_position < self._t().short_very_low_price_threshold:
                logger.warning(
                    f"[SHORT优化] 价格位置过低（<{int(self._t().short_very_low_price_threshold * 100)}%），做空风险高"
                )
                old_conf = original_confidence
                original_confidence *= self._t().short_very_low_price_penalty
                result.adjustments_made.append(
                    f"SHORT优化: 低价位做空风险高，置信度降低{int((1 - self._t().short_very_low_price_penalty) * 100)}% ({old_conf:.0%}→{original_confidence:.0%})"
                )
            elif price_position < self._t().short_low_price_threshold:
                old_conf = original_confidence
                original_confidence *= self._t().short_low_price_penalty
                result.adjustments_made.append(
                    f"SHORT优化: 价格偏低（<{int(self._t().short_low_price_threshold * 100)}%），置信度降低{int((1 - self._t().short_low_price_penalty) * 100)}% ({old_conf:.0%}→{original_confidence:.0%})"
                )

            # 3. 如果在持续下跌趋势中，SHORT 信号应该增强（这是顺势）
            if decline_result and decline_result.is_detected:
                old_conf = original_confidence
                original_confidence = min(
                    original_confidence * self._t().short_decline_boost,
                    self._t().short_decline_boost_ceiling,
                )
                result.adjustments_made.append(
                    f"SHORT优化: 持续下跌趋势中，置信度增加{int((self._t().short_decline_boost - 1) * 100)}% ({old_conf:.0%}→{original_confidence:.0%})"
                )

            conf_history.append(
                (self._t().confidence_base, "SHORT优化", original_confidence)
            )

            # ===== 0.6. 下跌趋势中 HOLD 转 SHORT =====
            # 只有在明确的下跌趋势中才转换 HOLD → SHORT
            # 条件：趋势强度 >= 0.30 + 显著跌幅 + 持续下跌确认 + RSI 确认
            if original_signal.upper() == "HOLD":
                technical = market_data.get("technical", {})
                trend_direction = technical.get("trend_direction", "neutral")
                trend_strength = technical.get("trend_strength", 0)
                price_position = technical.get("price_position", 0.5)

                # 获取短期跌幅（最近3根K线约15分钟）
                short_term_drop = market_data.get("short_term_drop_percent", 0)

                # RSI 条件：下跌趋势中 RSI 应该偏弱（<55）
                rsi = technical.get("rsi", 50)

                # 检查是否满足做空条件（严格条件）
                is_downtrend = trend_direction == "down"
                has_strong_strength = (
                    trend_strength >= self._t().strong_trend_strength
                )  # 必须有明显下跌趋势
                has_significant_drop = (
                    short_term_drop < self._t().short_term_drop
                )  # 短期跌幅 >= 1.5%
                not_too_low = (
                    price_position > self._t().price_position_too_low
                )  # 不在极低位（>30%）
                is_sustained_decline = decline_result and decline_result.is_detected
                rsi_confirms_down = rsi < self._t().strong_trend_rsi  # RSI 确认下跌

                # 严格条件：必须同时满足
                # 1. 明确下跌趋势（趋势强度 >= 0.30）
                # 2. 显著短期跌幅（>= 1.5%）或持续下跌确认
                # 3. 价格不在极低位（> 30%）
                # 4. RSI 确认下跌（< 55）
                should_convert = (
                    is_downtrend
                    and has_strong_strength
                    and (has_significant_drop or is_sustained_decline)
                    and not_too_low
                    and rsi_confirms_down
                )

                if should_convert:
                    logger.info(
                        f"[信号转换] HOLD→SHORT: 趋势向下(强度{trend_strength:.2f}), "
                        f"短期跌幅{short_term_drop:.2f}%, 价格位置{price_position * 100:.0f}%, "
                        f"RSI={rsi:.1f}, 持续下跌={is_sustained_decline}"
                    )
                    original_signal = "SHORT"
                    # 设置置信度
                    if is_sustained_decline and has_significant_drop:
                        original_confidence = (
                            self._t().confidence_dual_confirm
                        )  # 双重确认
                    elif is_sustained_decline:
                        original_confidence = (
                            self._t().confidence_sustained
                        )  # 持续下跌确认
                    else:
                        original_confidence = self._t().confidence_general  # 一般情况
                    result.adjustments_made.append(f"信号转换: HOLD→SHORT (强下跌趋势)")
                    conf_history.append(
                        (
                            self._t().confidence_sustained,
                            "强下跌转换",
                            original_confidence,
                        )
                    )

            # ===== 下跌趋势中 HOLD 转 SHORT (价格位置检查) =====
            # 严格条件：趋势强度 >= 0.30 + RSI 确认
            if original_signal.upper() == "HOLD":
                technical = market_data.get("technical", {})
                trend_direction = technical.get("trend_direction", "neutral")
                trend_strength = technical.get("trend_strength", 0)
                price_position = technical.get("price_position", 0.5)
                rsi = technical.get("rsi", 50)

                is_downtrend = trend_direction == "down"
                has_strong_strength = trend_strength >= self._t().strong_trend_strength
                not_too_low = price_position > self._t().price_position_too_low
                is_sustained_decline = decline_result and decline_result.is_detected
                rsi_confirms_down = rsi < self._t().strong_trend_rsi

                should_convert = (
                    is_downtrend
                    and has_strong_strength
                    and is_sustained_decline
                    and not_too_low
                    and rsi_confirms_down
                )

                if should_convert:
                    logger.info(
                        f"[信号转换] HOLD→SHORT: 趋势向下(强度{trend_strength:.2f}), "
                        f"价格位置{price_position * 100:.0f}%, RSI={rsi:.1f}, 持续下跌={is_sustained_decline}"
                    )
                    original_signal = "SHORT"
                    original_confidence = self._t().confidence_sustained
                    result.adjustments_made.append(f"信号转换: HOLD→SHORT (强下跌趋势)")
                    conf_history.append(
                        (
                            self._t().confidence_sustained,
                            "强下跌转换",
                            original_confidence,
                        )
                    )

            # 检查是否满足做空条件
            is_downtrend = trend_direction == "down"
            has_strength = trend_strength > self._t().weak_trend_strength
            not_too_low = price_position > self._t().price_position_low
            is_sustained_decline = decline_result and decline_result.is_detected

            # 下跌趋势 + 有一定强度 + 不是极低位 → 转换为 SHORT
            if is_downtrend and has_strength and not_too_low:
                logger.info(
                    f"[信号转换] HOLD→SHORT: 趋势向下(强度{trend_strength:.2f}), "
                    f"价格位置{price_position * 100:.0f}%, 持续下跌={is_sustained_decline}"
                )
                original_signal = "SHORT"
                # 设置一个基础置信度
                if is_sustained_decline:
                    original_confidence = self._t().confidence_sustained
                else:
                    original_confidence = self._t().confidence_base
                result.adjustments_made.append(f"信号转换: HOLD→SHORT (下跌趋势)")
                conf_history.append(
                    (self._t().confidence_sustained, "下跌转换", original_confidence)
                )

        # 1. AdaptiveBuyCondition
        # 1. AdaptiveBuyCondition
        if self.adaptive_buy and self.config.enable_adaptive_buy:
            try:
                buy_result = self.adaptive_buy.should_buy(market_data=market_data)
                result.buy_condition_result = buy_result

                # 如果买入条件判断可以买入，提高置信度
                if buy_result.can_buy:
                    # 检查是否在持续下跌趋势中，如果是则谨慎对待
                    if (
                        decline_result
                        and decline_result.is_detected
                        and not decline_result.should_block_buy
                    ):
                        # 持续下跌趋势中，降低买入条件的置信度加成
                        adjusted_buy_conf = buy_result.confidence * (
                            1 - decline_result.buy_penalty
                        )
                        original_confidence = max(
                            original_confidence, adjusted_buy_conf
                        )
                        if adjusted_buy_conf < buy_result.confidence:
                            result.adjustments_made.append(
                                f"自适应买入: {buy_result.mode}模式通过，但持续下跌趋势降低权重"
                            )
                    else:
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
                logger.warning(
                    f"AdaptiveBuyCondition处理失败: {e}, 位置: {traceback.format_exc(limit=3)}"
                )

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
                logger.warning(
                    f"SignalOptimizer处理失败: {e}, 位置: {traceback.format_exc(limit=3)}"
                )

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
                    # 如果已经在持续下跌中，风险更大
                    penalty = (
                        self._t().btc_high_risk_penalty
                        if (decline_result and decline_result.is_detected)
                        else self._t().btc_high_risk_penalty_no_decline
                    )
                    old_conf = original_confidence
                    original_confidence *= 1 - penalty
                    result.adjustments_made.append(
                        f"BTC检测: 高位风险+持续下跌，置信度降低{penalty * 100:.0f}% ({old_conf:.0%}→{original_confidence:.0%})"
                    )
                    conf_history.append((3, "BTC高位", original_confidence))
                elif btc_result.is_high_risk and original_signal == "BUY":
                    old_conf = original_confidence
                    original_confidence *= self._t().btc_high_risk_penalty_no_decline
                    result.adjustments_made.append(
                        f"BTC检测: 高位风险，置信度降低{int((1 - self._t().btc_high_risk_penalty_no_decline) * 100)}% ({old_conf:.0%}→{original_confidence:.0%})"
                    )
                    conf_history.append((3, "BTC高位", original_confidence))

                # 如果是低机会，增加置信度
                if btc_result.is_low_opportunity and original_signal == "BUY":
                    old_conf = original_confidence
                    original_confidence *= self._t().btc_low_opportunity_boost
                    result.adjustments_made.append(
                        f"BTC检测: 低位机会，置信度增加{int((self._t().btc_low_opportunity_boost - 1) * 100)}% ({old_conf:.0%}→{original_confidence:.0%})"
                    )
                    conf_history.append((3, "BTC低位", original_confidence))

                # SHORT 信号的特殊处理：低位是风险，高位是机会
                if original_signal == "SHORT":
                    # 低位做空是风险
                    if btc_result.is_low_opportunity:
                        old_conf = original_confidence
                        original_confidence *= self._t().btc_short_penalty
                        result.adjustments_made.append(
                            f"BTC检测: SHORT+低价位风险高，置信度降低{int((1 - self._t().btc_short_penalty) * 100)}% ({old_conf:.0%}→{original_confidence:.0%})"
                        )
                        conf_history.append((3, "BTC低位SHORT", original_confidence))
                    # 高位做空是机会
                    elif btc_result.is_high_risk:
                        old_conf = original_confidence
                        original_confidence *= self._t().btc_short_boost
                        result.adjustments_made.append(
                            f"BTC检测: SHORT+高位机会，置信度增加{int((self._t().btc_short_boost - 1) * 100)}% ({old_conf:.0%}→{original_confidence:.0%})"
                        )
                        conf_history.append((3, "BTC高位SHORT", original_confidence))

            except Exception as e:
                logger.warning(
                    f"BTC价格检测处理失败: {e}, 位置: {traceback.format_exc(limit=3)}"
                )

        # 4. HighPriceBuyOptimizer
        if self.high_price_optimizer and self.config.enable_high_price_filter:
            try:
                # 传递持续下跌检测结果给高位优化器
                market_data_with_decline = dict(market_data)
                if decline_result:
                    market_data_with_decline["sustained_decline"] = {
                        "is_detected": decline_result.is_detected,
                        "decline_level": decline_result.decline_level,
                        "buy_penalty": decline_result.buy_penalty,
                    }

                optimized = self.high_price_optimizer.optimize_high_price_buy(
                    market_data=market_data_with_decline,
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
                logger.warning(
                    f"HighPriceBuyOptimizer处理失败: {e}, 位置: {traceback.format_exc(limit=3)}"
                )

        # 5. 最终结果
        result.final_signal = original_signal
        result.final_confidence = min(
            max(original_confidence, self._t().confidence_floor),
            self._t().confidence_ceiling,
        )

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

        if self.sustained_decline_detector:
            stats["sustained_decline_detector"] = (
                self.sustained_decline_detector.get_info()
            )

        return stats

    def reset(self):
        """重置所有模块"""
        if self.signal_optimizer:
            self.signal_optimizer.reset()
        if self.sustained_decline_detector:
            self.sustained_decline_detector.reset_cycle()
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
            enable_sustained_decline_detector=True,
        ),
        "high_price_filter": IntegrationConfig(
            enable_adaptive_buy=True,
            enable_signal_optimizer=True,
            enable_high_price_filter=True,
            enable_btc_detector=False,
            enable_sustained_decline_detector=True,
        ),
        "btc_focused": IntegrationConfig(
            enable_adaptive_buy=True,
            enable_signal_optimizer=True,
            enable_high_price_filter=True,
            enable_btc_detector=True,
            enable_sustained_decline_detector=True,
        ),
        "minimal": IntegrationConfig(
            enable_adaptive_buy=True,
            enable_signal_optimizer=False,
            enable_high_price_filter=False,
            enable_btc_detector=False,
            enable_sustained_decline_detector=False,
        ),
    }

    config = configs.get(mode, IntegrationConfig())
    return AISignalIntegrator(config)
