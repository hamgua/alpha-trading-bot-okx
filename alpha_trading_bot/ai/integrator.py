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

from alpha_trading_bot.config.thresholds import (
    ADAPTIVE_BUY_HOLD_FLIP_MAX_HOLD_CONFIDENCE,
    ADAPTIVE_BUY_STRONG_MODE_MAX_HOLD_CONFIDENCE,
    EXTREME_OVERSOLD_RSI_MAX,
    SIGNAL_DISCOUNT_FLOOR,
    TECHNICAL_FLIP_CONFIDENCE_CAP,
)

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
from .market_structure import MarketStructureAnalyzer, MarketStructureResult
from .risk_reward_calculator import RiskRewardCalculator, RiskRewardResult

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
    sustained_decline_result: Optional[DeclineDetectionResult] = None
    market_structure_result: Optional[MarketStructureResult] = None  # 新增
    risk_reward_result: Optional[RiskRewardResult] = None  # 新增

    # 最终结果
    final_signal: str = "HOLD"
    final_confidence: float = 0.50

    # 元数据
    price_level: str = "mid"
    is_high_risk: bool = False
    is_low_opportunity: bool = False
    is_sustained_decline: bool = False
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

        # MarketStructureAnalyzer - 市场结构分析
        self.market_structure_analyzer = MarketStructureAnalyzer()

        # RiskRewardCalculator - 风险收益比计算器
        self.risk_reward_calculator = RiskRewardCalculator()

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

        # 统一信号为大写，避免大小写不一致导致比较逻辑遗漏
        original_signal = original_signal.upper()

        # 置信度范围校验: 确保 confidence 在 0-1 范围内
        if original_confidence > 1:
            logger.warning(
                f"[信号集成] 置信度 {original_confidence} 超出 0-1 范围，自动归一化"
            )
            original_confidence = original_confidence / 100.0

        # ========== 诊断日志：记录每个阶段的置信度 ==========
        conf_history = [(0, "原始", original_confidence)]

        # 2026-11 折扣下限追踪: 技术翻转 (HOLD→BUY) 后的基准置信度。
        # 后续 R/R 过滤 / 信号优化 / 高位过滤的累计折扣不得低于
        # SIGNAL_DISCOUNT_FLOOR 乘数 (防止门禁数学性不可达, 见 thresholds.py)。
        adaptive_flip_conf: Optional[float] = None

        # 2026-11-24 (P1-C): 技术翻转标记 (自适应买入 HOLD→BUY / 强下跌 HOLD→SHORT)。
        # 翻转产生的 BUY/SHORT 最终置信度封顶 TECHNICAL_FLIP_CONFIDENCE_CAP:
        # 规则加成 (如 high_price_buy_optimizer "+15% 严重超卖") 不应把技术
        # 翻转信号制造成高置信度。回放 11-24 13:43: AI HOLD 55% + 规则加成
        # → 61.8% 过放宽门禁 → 60685 抄底, 25 分钟 -0.42% (账户 -1.3%)。
        technically_flipped = False

        # 2026-11-24 (P0-3): 极端超卖标记 (RSI(1h) ≤ EXTREME_OVERSOLD_RSI_MAX)。
        # 提升到 process() 顶部: AdaptiveBuy 段 (翻转守卫豁免) 与 1.5 R/R 过滤段
        # 都需要引用, 且必须始终绑定 (adaptive_buy 未启用/异常时不可 NameError)。
        try:
            _extreme_rsi = float((market_data.get("technical") or {}).get("rsi"))
        except (TypeError, ValueError):
            _extreme_rsi = None
        extreme_oversold = (
            _extreme_rsi is not None and _extreme_rsi <= EXTREME_OVERSOLD_RSI_MAX
        )
        # 极端超卖 + oversold_rebound 模式命中 (翻转守卫豁免时置位,
        # R/R < 1.0 降级豁免复用同一标记)
        extreme_oversold_rebound = False

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
                    # 2026-11 衰竭反转: severe 下跌 + 显著反弹 + RSI 超卖 →
                    # 底部窗口, BUY 惩罚已解除并反哺, 不再是风险警告
                    _cum_decline = decline_result.metrics.cumulative_decline_percent
                    if getattr(decline_result, "exhaustion_reversal", False):
                        _rebound = decline_result.metrics.max_rebound_percent
                        logger.info(
                            "[持续下跌检测] 🔄 衰竭反转: 累积跌幅%.2f%% + "
                            "反弹%.2f%% + RSI超卖 → 解除BUY惩罚并加成, 底部抄底窗口",
                            _cum_decline,
                            _rebound,
                        )
                    # 记录检测到的下跌级别
                    elif decline_result.decline_level == "severe":
                        logger.warning(
                            "[持续下跌检测] ⚠️ 检测到严重下跌趋势: "
                            "累积跌幅%.2f%% (严重级别)",
                            _cum_decline,
                        )
                    elif decline_result.decline_level == "moderate":
                        logger.warning(
                            "[持续下跌检测] ⚠️ 检测到中度下跌趋势: " "累积跌幅%.2f%%",
                            _cum_decline,
                        )
                    else:
                        logger.info(
                            "[持续下跌检测] ℹ️ 检测到轻度下跌趋势: " "累积跌幅%.2f%%",
                            _cum_decline,
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
                penalty = self._t().short_trend_up_penalty
                penalty_floor = self._t().short_trend_up_penalty_floor
                new_conf = old_conf * penalty
                # 防止折扣后被永久封印 (task-card R1 + change-summary §3.3)
                if new_conf < penalty_floor and old_conf >= penalty_floor:
                    new_conf = penalty_floor
                original_confidence = new_conf
                result.adjustments_made.append(
                    f"SHORT优化: 趋势非下跌，置信度降低{int((1 - penalty) * 100)}% ({old_conf:.0%}→{original_confidence:.0%})"
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
                    technically_flipped = True
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
                    technically_flipped = True
                    original_confidence = self._t().confidence_sustained
                    result.adjustments_made.append(f"信号转换: HOLD→SHORT (强下跌趋势)")
                    conf_history.append(
                        (
                            self._t().confidence_sustained,
                            "强下跌转换",
                            original_confidence,
                        )
                    )

        # 1. AdaptiveBuyCondition
        # 1. AdaptiveBuyCondition
        if self.adaptive_buy and self.config.enable_adaptive_buy:
            try:
                buy_result = self.adaptive_buy.should_buy(market_data=market_data)
                result.buy_condition_result = buy_result

                # 2026-11-24 (P0-3): 极端超卖 + 抄底模式命中记录
                # (R/R < 1.0 降级豁免用; AI 直接 BUY 或技术翻转均受益)
                if extreme_oversold and buy_result.mode == "oversold_rebound":
                    extreme_oversold_rebound = True

                # 如果买入条件判断可以买入，提高置信度
                if buy_result.can_buy:
                    # dream 2026-09-16-loss-root-cause / R3: 翻转守卫。
                    # 原实现无条件把 HOLD/SELL 翻转为 BUY，导致 AI 明确 HOLD
                    # (56%) + 全策略 HOLD 时仍被技术规则翻转开仓并亏损
                    # (2026-09-13 05:17 案例)。修复:
                    # - SELL 永不翻转为 BUY (SELL 必须执行平仓, 翻转会导致反向开仓)
                    # - AI 明确 HOLD (置信度 >= 阈值) 时不翻转, 交由决策引擎
                    #   既有的高置信度策略覆盖路径 (HOLD_STRATEGY_BUY_MIN_CONFIDENCE=0.80) 裁决
                    # - 仅当 AI-HOLD 模糊 (<阈值) 时才允许技术规则翻转
                    # 2026-11 日志回放修复: 高可信技术模式 (oversold_rebound/
                    # pullback_buy) 上限放宽到 0.60——底部区 AI-HOLD 落在 55-65%
                    # 犹豫带时 (11-21 14:14 RSI=16 案例), 让技术规则说话;
                    # 其余模式保持 0.55 (零回归)。
                    allow_flip = True
                    flip_block_reason = ""
                    if original_signal == "SELL":
                        allow_flip = False
                        flip_block_reason = "AI SELL 信号, 禁止翻转为 BUY"
                    else:
                        max_hold_conf = ADAPTIVE_BUY_HOLD_FLIP_MAX_HOLD_CONFIDENCE
                        strong_mode_note = ""
                        if original_signal == "HOLD" and buy_result.mode in (
                            "oversold_rebound",
                            "pullback_buy",
                        ):
                            max_hold_conf = ADAPTIVE_BUY_STRONG_MODE_MAX_HOLD_CONFIDENCE
                            strong_mode_note = " (高可信模式放宽至 {:.0%})".format(
                                max_hold_conf
                            )
                        # 2026-11-24 回放 (P0-3): 极端超卖豁免——RSI(1h) <= 10 且
                        # oversold_rebound 通过时, 无视 AI HOLD 置信度允许翻转。
                        # 底部区 AI 中置信度 HOLD 多为犹豫带噪声, 技术条件已含
                        # RSI<=20 + 24h 低点区 (+ 执行层 1h 动量守卫/每日上限)。
                        if (
                            extreme_oversold
                            and original_signal == "HOLD"
                            and buy_result.mode == "oversold_rebound"
                        ):
                            allow_flip = True
                            flip_block_reason = ""
                            strong_mode_note = " (极端超卖 RSI<={:.0f} 豁免)".format(
                                EXTREME_OVERSOLD_RSI_MAX
                            )
                            result.adjustments_made.append(
                                f"极端超卖豁免: RSI(1h)={_extreme_rsi:.1f} ≤ "
                                f"{EXTREME_OVERSOLD_RSI_MAX:.0f}, AI HOLD "
                                f"{original_confidence:.0%} 不拦截 oversold_rebound"
                            )
                        elif (
                            original_signal == "HOLD"
                            and original_confidence >= max_hold_conf
                        ):
                            allow_flip = False
                            flip_block_reason = (
                                f"AI 明确 HOLD (置信度 {original_confidence:.0%} >= "
                                f"{max_hold_conf:.0%}), 技术买入条件不翻转信号"
                                f"{strong_mode_note}"
                            )

                    if allow_flip:
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

                        # 2026-11-24 (P1-C): 仅记录"真实翻转" (HOLD/SELL→BUY);
                        # AI 原生 BUY 不标记 (不受翻转置信度封顶约束)
                        flipped_from = original_signal
                        original_signal = "BUY"
                        adaptive_flip_conf = original_confidence
                        if flipped_from != "BUY":
                            technically_flipped = True
                        result.adjustments_made.append(
                            f"自适应买入: {buy_result.mode}模式通过"
                        )
                    else:
                        logger.info(
                            f"[信号集成] 自适应买入条件通过但信号未翻转: {flip_block_reason}"
                        )
                        result.adjustments_made.append(
                            f"自适应买入被阻止翻转: {flip_block_reason}"
                        )

                result.price_level = buy_result.mode
                # 2026-11-24 (P1-C): 暴露自适应买入模式供执行层使用
                # (oversold_rebound 翻转开仓用半仓, 与超卖抄底通道同口径)
                market_data["adaptive_buy_mode"] = buy_result.mode
                conf_history.append((1, "AdaptiveBuy", original_confidence))

            except Exception as e:
                logger.warning(
                    f"AdaptiveBuyCondition处理失败: {e}, 位置: {traceback.format_exc(limit=3)}"
                )

        # 1.5. 市场结构分析 + 风险收益比过滤（新增）
        try:
            price_history = market_data.get("price_history", [])
            current_price = market_data.get("price", 0)
            technical = market_data.get("technical", {})
            atr_percent = technical.get("atr_percent", 0)

            if price_history and current_price > 0:
                structure_result = self.market_structure_analyzer.analyze(
                    price_history=price_history,
                    current_price=current_price,
                    atr_percent=atr_percent,
                    # 2026-11-25: 24h/4h 一致性门槛 (防阴跌中逆势抄底);
                    # 0/缺失 → 门槛不启用 (零回归)
                    change_percent=float(market_data.get("change_percent", 0.0) or 0.0),
                )
                result.market_structure_result = structure_result

                # 将市场结构信息附加到 market_data 供决策引擎使用
                # （注意：必须操作原始 market_data 引用，确保外部可见）
                market_data["market_structure"] = structure_result.structure
                market_data["market_structure_htf"] = getattr(
                    structure_result, "htf_structure", "unknown"
                )
                market_data["market_structure_htf_note"] = getattr(
                    structure_result, "htf_note", ""
                )
                market_data["market_structure_direction"] = (
                    structure_result.suggested_direction
                )
                market_data["risk_reward_ratio"] = structure_result.risk_reward_ratio
                market_data["nearest_support"] = structure_result.nearest_support
                market_data["nearest_resistance"] = structure_result.nearest_resistance
                market_data["position_size_factor"] = (
                    structure_result.position_size_factor
                )
                short_rr_result = self.risk_reward_calculator.calculate_for_short(
                    current_price=current_price,
                    support=structure_result.nearest_support,
                    resistance=structure_result.nearest_resistance,
                    atr_percent=atr_percent,
                )
                market_data["short_risk_reward_ratio"] = short_rr_result.rr_ratio

                # 2026-11-24 (P0-B): 无条件计算 ATR 口径做多 R/R 并暴露给执行层。
                # 动态开仓门禁放宽改用本口径, 而非结构 R/R——底部区价格贴近支撑
                # 时分母极小, 结构 R/R 是几何伪影 (回放 11-24 13:43 R/R=4.03 /
                # 13:30 R/R=81.38 均放行错误抄底; 同周期 ATR 口径仅 1.27)。
                rr_result = None
                if (
                    structure_result.nearest_support > 0
                    and structure_result.nearest_resistance > 0
                ):
                    try:
                        rr_result = self.risk_reward_calculator.calculate_for_long(
                            current_price=current_price,
                            support=structure_result.nearest_support,
                            resistance=structure_result.nearest_resistance,
                            atr_percent=atr_percent,
                        )
                        market_data["long_risk_reward_ratio"] = rr_result.rr_ratio
                    except Exception as e:
                        logger.warning(f"做多R/R计算失败: {e}")

                # 风险收益比过滤 - 只对BUY信号生效
                if original_signal == "BUY" and structure_result.risk_reward_ratio > 0:
                    if rr_result is None:
                        # 支撑/阻力无效时的兜底 (保持旧行为)
                        rr_result = self.risk_reward_calculator.calculate_for_long(
                            current_price=current_price,
                            support=structure_result.nearest_support,
                            resistance=structure_result.nearest_resistance,
                            atr_percent=atr_percent,
                        )
                    result.risk_reward_result = rr_result

                    if not rr_result.should_trade:
                        if rr_result.rr_ratio <= 0:
                            # R/R计算因数据不足返回0，降低置信度但保留BUY信号
                            old_conf = original_confidence
                            original_confidence *= 0.70
                            result.adjustments_made.append(
                                f"R/R过滤: R/R数据不足(R/R=0)，"
                                f"置信度降低30%({old_conf:.0%}→{original_confidence:.0%})"
                            )
                            conf_history.append((2, "R/R数据不足", original_confidence))
                            logger.info(
                                f"[R/R过滤] BUY信号R/R数据不足(R/R=0)，降级但保留BUY"
                            )
                        elif rr_result.rr_ratio >= 1.0:
                            # R/R在1.0-1.5之间，降低置信度但保留BUY信号（精而准策略）
                            old_conf = original_confidence
                            original_confidence *= 0.80
                            result.adjustments_made.append(
                                f"R/R过滤: R/R={rr_result.rr_ratio:.2f}偏低，"
                                f"置信度降低20%({old_conf:.0%}→{original_confidence:.0%})"
                            )
                            conf_history.append((2, "R/R偏低", original_confidence))
                            logger.info(
                                f"[R/R过滤] BUY信号R/R={rr_result.rr_ratio:.2f}偏低，降低置信度"
                            )
                        else:
                            # R/R < 1.0，风险过高，降级为HOLD
                            # 2026-11-24 回放 (P0-3): 极端超卖豁免——底部结构 R/R
                            # 常因"上方阻力远"而偏低, RSI<=10 时保留 BUY 信号
                            # (执行层仍有每日上限/冷却/回撤总闸/ATR 止损兜底)。
                            if extreme_oversold_rebound:
                                result.adjustments_made.append(
                                    f"R/R过滤: R/R={rr_result.rr_ratio:.2f}偏低但"
                                    f"极端超卖(RSI<={EXTREME_OVERSOLD_RSI_MAX:.0f})豁免降级"
                                )
                                logger.info(
                                    f"[R/R过滤] R/R={rr_result.rr_ratio:.2f} < 1.0, "
                                    f"极端超卖豁免, 保留BUY"
                                )
                            else:
                                old_signal = original_signal
                                original_signal = "HOLD"
                                result.adjustments_made.append(
                                    f"R/R过滤: {old_signal}→HOLD, "
                                    f"R/R={rr_result.rr_ratio:.2f}不足(最低1.0)"
                                )
                                logger.info(
                                    f"[R/R过滤] {old_signal}→HOLD: R/R={rr_result.rr_ratio:.2f}不足"
                                )
                    elif rr_result.quality == "marginal":
                        # R/R勉强，降低置信度
                        old_conf = original_confidence
                        original_confidence *= 0.85
                        result.adjustments_made.append(
                            f"R/R过滤: R/R={rr_result.rr_ratio:.2f}勉强, "
                            f"置信度降低15%({old_conf:.0%}→{original_confidence:.0%})"
                        )
                        conf_history.append((2, "R/R过滤", original_confidence))
                    elif rr_result.quality == "excellent":
                        # R/R优质，小幅提升置信度
                        old_conf = original_confidence
                        original_confidence = min(
                            original_confidence * 1.05, self._t().confidence_ceiling
                        )
                        result.adjustments_made.append(
                            f"R/R过滤: R/R={rr_result.rr_ratio:.2f}优质, "
                            f"置信度提升5%({old_conf:.0%}→{original_confidence:.0%})"
                        )
                        conf_history.append((2, "R/R优质", original_confidence))

                # SHORT信号的R/R过滤
                elif (
                    original_signal == "SHORT"
                    and structure_result.risk_reward_ratio > 0
                ):
                    rr_result = short_rr_result
                    result.risk_reward_result = short_rr_result

                    if not rr_result.should_trade:
                        if rr_result.rr_ratio <= 0:
                            old_conf = original_confidence
                            original_confidence *= 0.70
                            result.adjustments_made.append(
                                f"R/R过滤: SHORT R/R数据不足(R/R=0)，"
                                f"置信度降低30%({old_conf:.0%}→{original_confidence:.0%})"
                            )
                        elif rr_result.rr_ratio >= 1.0:
                            old_conf = original_confidence
                            original_confidence *= 0.80
                            result.adjustments_made.append(
                                f"R/R过滤: SHORT R/R={rr_result.rr_ratio:.2f}偏低，"
                                f"置信度降低20%({old_conf:.0%}→{original_confidence:.0%})"
                            )
                        else:
                            old_signal = original_signal
                            original_signal = "HOLD"
                            result.adjustments_made.append(
                                f"R/R过滤: {old_signal}→HOLD, "
                                f"R/R={rr_result.rr_ratio:.2f}不足(最低1.0)"
                            )

                # HOLD信号时，市场结构确认（诊断增强，不修改逻辑）
                elif (
                    original_signal == "HOLD" and structure_result.risk_reward_ratio > 0
                ):
                    if structure_result.risk_reward_ratio < 1.5:
                        result.adjustments_made.append(
                            f"市场结构确认: R/R={structure_result.risk_reward_ratio:.2f}不足，"
                            f"HOLD决策合理"
                        )

        except Exception as e:
            logger.warning(
                f"市场结构/R/R分析失败: {e}, 位置: {traceback.format_exc(limit=3)}"
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
                    if decline_result and decline_result.is_detected:
                        penalty = self._t().btc_high_risk_penalty
                        old_conf = original_confidence
                        original_confidence *= 1 - penalty
                        result.adjustments_made.append(
                            f"BTC检测: 高位风险+持续下跌，置信度降低{penalty * 100:.0f}% ({old_conf:.0%}→{original_confidence:.0%})"
                        )
                        conf_history.append((3, "BTC高位", original_confidence))
                    else:
                        penalty = self._t().btc_high_risk_penalty_no_decline
                        old_conf = original_confidence
                        original_confidence *= penalty
                        result.adjustments_made.append(
                            f"BTC检测: 高位风险，置信度降低{int((1 - penalty) * 100)}% ({old_conf:.0%}→{original_confidence:.0%})"
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
        # HIGHPRICE-BUY-ONLY：本优化器仅作用于 BUY 信号；SHORT/SELL 跳过（task-card R2）。
        # 原惩罚（RSI/trend/价格位置快速上升等）是仅对 BUY 信号设计，不应作用于反方向信号。
        # SHORT 信号已由上面的 BTC 检测 + 自己的 SHORT 专用 block 处理；
        # SELL 信号无需 BUY 惩罚（仅用于平仓场景）。
        if (
            self.high_price_optimizer
            and self.config.enable_high_price_filter
            and original_signal == "BUY"
        ):
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
                    original_can_buy=True,
                    buy_mode=result.price_level,
                    original_signal=original_signal,
                )

                result.high_price_result = {
                    "adjusted_confidence": optimized.adjusted_confidence,
                    "should_buy": optimized.should_buy,
                    "price_level": optimized.price_level,
                    "adjustment_reason": optimized.adjustment_reason,
                    "penalty_applied": optimized.penalty_applied,
                }

                # 如果优化器说不要买入，改为HOLD
                if not optimized.should_buy:
                    original_signal = "HOLD"
                    result.adjustments_made.append(
                        f"高位过滤: 不建议买入 - {optimized.adjustment_reason[:50]}..."
                    )
                elif optimized.penalty_applied and optimized.adjusted_confidence < 0.40:
                    original_signal = "HOLD"
                    result.adjustments_made.append(
                        "高位过滤: BUY被压到低置信，降级HOLD继续评估策略"
                    )

                original_confidence = optimized.adjusted_confidence
                conf_history.append((4, "HighPrice", original_confidence))

            except Exception as e:
                logger.warning(
                    f"HighPriceBuyOptimizer处理失败: {e}, 位置: {traceback.format_exc(limit=3)}"
                )
        else:
            # SHORT/SELL/未启用快速路径：记录跳过原因，便于审计
            conf_history.append((4, "HighPrice(skip non-BUY)", original_confidence))

        # 5. 最终结果
        # 2026-11 折扣下限: 技术翻转的 BUY 信号, 后续各阶段 (R/R 过滤 /
        # 信号优化 / 高位过滤) 的累计折扣不得低于 SIGNAL_DISCOUNT_FLOOR。
        # 回放: 11-21 23:47 BUY 92% 被双重 0.85 压到 66.5% < 0.75 门禁——
        # 下限 0.70 时最终 ≥ 64.4%, 与降后的 0.65 门禁配合可放行。
        if (
            original_signal == "BUY"
            and adaptive_flip_conf is not None
            and original_confidence < adaptive_flip_conf * SIGNAL_DISCOUNT_FLOOR
        ):
            floored_conf = adaptive_flip_conf * SIGNAL_DISCOUNT_FLOOR
            logger.info(
                f"[信号集成] BUY折扣下限: {original_confidence:.1%} < "
                f"{adaptive_flip_conf:.1%}×{SIGNAL_DISCOUNT_FLOOR:.0%} → 提升回 {floored_conf:.1%}"
            )
            result.adjustments_made.append(
                f"BUY折扣下限: 累计折扣低于{SIGNAL_DISCOUNT_FLOOR:.0%}乘数, "
                f"{original_confidence:.1%}→{floored_conf:.1%}"
            )
            original_confidence = floored_conf

        # 2026-11-24 (P1-C): 技术翻转置信度封顶。
        # 技术翻转 (非 AI 原生) 的 BUY/SHORT 最终置信度不得超过
        # TECHNICAL_FLIP_CONFIDENCE_CAP; AI 原生信号不受限。
        if (
            technically_flipped
            and original_signal in ("BUY", "SHORT")
            and original_confidence > TECHNICAL_FLIP_CONFIDENCE_CAP
        ):
            capped = TECHNICAL_FLIP_CONFIDENCE_CAP
            logger.info(
                f"[信号集成] 技术翻转置信度封顶: {original_confidence:.1%} > "
                f"{capped:.0%} → {capped:.0%} (规则加成不制造高置信)"
            )
            result.adjustments_made.append(
                f"技术翻转置信度封顶: {original_confidence:.1%}→{capped:.1%}"
            )
            original_confidence = capped

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
