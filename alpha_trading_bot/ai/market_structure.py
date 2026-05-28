"""
市场结构分析器 - 资深交易员视角

功能:
1. 判断趋势结构 (Higher High/Higher Low = 上涨结构)
2. 识别关键支撑阻力位
3. 计算风险收益比 (R/R Ratio)
4. 识别市场结构突破/破位

设计理念:
- 资深交易员做决策的第一步就是看市场结构
- 市场结构决定了交易方向和策略选择
- 支撑阻力位是止损止盈的核心依据

作者: AI Trading System
日期: 2026-05-20
"""

import logging
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MarketStructureResult:
    """市场结构分析结果"""

    # 趋势结构
    structure: str  # bullish(上涨) | bearish(下跌) | sideways(震荡)
    structure_detail: str  # 人类可读的结构描述

    # 关键价位
    nearest_support: float  # 最近支撑位
    nearest_resistance: float  # 最近阻力位
    current_price: float  # 当前价格

    # 风险收益比
    risk_reward_ratio: float  # R/R比
    rr_quality: str  # excellent | good | marginal | poor

    # 结构状态
    is_breakout: bool  # 是否正在突破
    is_breakdown: bool  # 是否正在破位
    structure_change: str  # 无变化 | 转多 | 转空 | 震荡持续

    # 交易建议
    suggested_direction: str  # long | short | none
    position_size_factor: float  # 仓位系数 0.0-1.0

    # 详细数据
    swing_highs: List[float]  # 摆动高点列表
    swing_lows: List[float]  # 摆动低点列表


class MarketStructureAnalyzer:
    """
    市场结构分析器

    资深交易员分析市场结构的核心方法：
    1. 识别摆动高点(Swing High)和摆动低点(Swing Low)
    2. 判断结构类型：
       - HH + HL = 上涨结构(Bullish)
       - LH + LL = 下跌结构(Bearish)
       - 其他 = 震荡结构(Sideways)
    3. 计算关键支撑阻力位
    4. 评估风险收益比
    5. 检测结构突破/破位
    """

    # 默认配置
    DEFAULT_SWING_WINDOW = 3  # 摆动点识别窗口
    DEFAULT_MIN_RR = 1.5  # 最低可接受R/R比
    DEFAULT_GOOD_RR = 2.0  # 良好R/R比
    DEFAULT_EXCELLENT_RR = 3.0  # 优质R/R比

    def __init__(
        self,
        swing_window: int = 3,
        min_rr: float = 1.5,
        good_rr: float = 2.0,
        excellent_rr: float = 3.0,
    ):
        """
        初始化市场结构分析器

        Args:
            swing_window: 摆动点识别窗口大小
            min_rr: 最低可接受R/R比
            good_rr: 良好R/R比
            excellent_rr: 优质R/R比
        """
        self.swing_window = swing_window
        self.min_rr = min_rr
        self.good_rr = good_rr
        self.excellent_rr = excellent_rr

        logger.info(
            f"[市场结构分析器] 初始化完成: "
            f"swing_window={swing_window}, "
            f"R/R阈值: 最低={min_rr}, 良好={good_rr}, 优质={excellent_rr}"
        )

    def analyze(
        self,
        price_history: List[float],
        current_price: float,
        atr_percent: float = 0.0,
    ) -> MarketStructureResult:
        """
        分析市场结构

        Args:
            price_history: 历史价格列表（从最近到最远）
            current_price: 当前价格
            atr_percent: ATR百分比（用于动态调整参数）

        Returns:
            MarketStructureResult: 市场结构分析结果
        """
        if len(price_history) < 5:
            logger.debug("[市场结构] 价格数据不足，返回中性结构")
            return self._create_neutral_result(current_price)

        # 1. 识别摆动高低点
        swing_highs, swing_lows = self._find_swing_points(price_history)

        if not swing_highs or not swing_lows:
            logger.debug("[市场结构] 无法识别摆动点，返回中性结构")
            return self._create_neutral_result(current_price)

        # 2. 判断市场结构
        structure, structure_detail = self._determine_structure(
            swing_highs, swing_lows
        )

        # 3. 计算支撑阻力位
        nearest_support = self._find_nearest_support(swing_lows, current_price)
        nearest_resistance = self._find_nearest_resistance(
            swing_highs, current_price
        )

        # 4. 计算风险收益比
        rr_ratio, rr_quality = self._calculate_risk_reward(
            current_price, nearest_support, nearest_resistance
        )

        # 5. 检测结构突破/破位
        is_breakout, is_breakdown, structure_change = self._detect_structure_change(
            structure, current_price, nearest_resistance, nearest_support, price_history
        )

        # 6. 生成交易建议
        suggested_direction, position_size_factor = self._generate_trading_advice(
            structure, rr_ratio, is_breakout, is_breakdown, atr_percent
        )

        result = MarketStructureResult(
            structure=structure,
            structure_detail=structure_detail,
            nearest_support=nearest_support,
            nearest_resistance=nearest_resistance,
            current_price=current_price,
            risk_reward_ratio=rr_ratio,
            rr_quality=rr_quality,
            is_breakout=is_breakout,
            is_breakdown=is_breakdown,
            structure_change=structure_change,
            suggested_direction=suggested_direction,
            position_size_factor=position_size_factor,
            swing_highs=swing_highs,
            swing_lows=swing_lows,
        )

        logger.info(
            f"[市场结构] 结构={structure}, "
            f"支撑={nearest_support:.2f}, 阻力={nearest_resistance:.2f}, "
            f"R/R={rr_ratio:.2f}({rr_quality}), "
            f"方向={suggested_direction}, 仓位系数={position_size_factor:.2f}"
        )

        return result

    def _find_swing_points(
        self, price_history: List[float]
    ) -> Tuple[List[float], List[float]]:
        """
        识别摆动高低点

        算法：对于每个点，检查其前后window个点，
        如果都高于/低于相邻点，则为摆动高/低点

        Args:
            price_history: 历史价格列表

        Returns:
            (swing_highs, swing_lows): 摆动高点和低点列表
        """
        swing_highs: List[float] = []
        swing_lows: List[float] = []
        window = self.swing_window

        # 反转以从远到近处理
        prices = list(reversed(price_history))

        if len(prices) < 2 * window + 1:
            # 数据不足，使用简单方法
            if len(prices) >= 3:
                swing_highs.append(max(prices))
                swing_lows.append(min(prices))
            return swing_highs, swing_lows

        for i in range(window, len(prices) - window):
            is_high = True
            is_low = True

            for j in range(i - window, i + window + 1):
                if j == i:
                    continue
                if prices[j] >= prices[i]:
                    is_high = False
                if prices[j] <= prices[i]:
                    is_low = False

            if is_high:
                swing_highs.append(prices[i])
            if is_low:
                swing_lows.append(prices[i])

        return swing_highs, swing_lows

    def _determine_structure(
        self, swing_highs: List[float], swing_lows: List[float]
    ) -> Tuple[str, str]:
        """
        判断市场结构

        规则:
        - HH(Higher High) + HL(Higher Low) = 上涨结构
        - LH(Lower High) + LL(Lower Low) = 下跌结构
        - 其他 = 震荡结构

        Args:
            swing_highs: 摆动高点列表
            swing_lows: 摆动低点列表

        Returns:
            (structure, detail): 结构类型和描述
        """
        # 取最近2-3个摆动点判断
        recent_highs = swing_highs[-3:] if len(swing_highs) >= 3 else swing_highs
        recent_lows = swing_lows[-3:] if len(swing_lows) >= 3 else swing_lows

        # 判断HH/HL/LH/LL
        has_hh = False
        has_hl = False
        has_lh = False
        has_ll = False

        if len(recent_highs) >= 2:
            if recent_highs[-1] > recent_highs[-2]:
                has_hh = True
            elif recent_highs[-1] < recent_highs[-2]:
                has_lh = True

        if len(recent_lows) >= 2:
            if recent_lows[-1] > recent_lows[-2]:
                has_hl = True
            elif recent_lows[-1] < recent_lows[-2]:
                has_ll = True

        # 综合判断
        if has_hh and has_hl:
            return "bullish", "上涨结构(HH+HL): 更高的高点+更高的低点"
        elif has_lh and has_ll:
            return "bearish", "下跌结构(LH+LL): 更低的高点+更低的低点"
        elif has_hh and has_ll:
            return "sideways", "扩张结构(HH+LL): 波动放大，方向不明"
        elif has_lh and has_hl:
            return "sideways", "收敛结构(LH+HL): 波动缩小，可能酝酿突破"
        elif has_hh:
            return "bullish", "偏多结构(HH): 高点抬升，低点待确认"
        elif has_ll:
            return "bearish", "偏空结构(LL): 低点下移，高点待确认"
        else:
            return "sideways", "震荡结构: 方向不明确"

    def _find_nearest_support(
        self, swing_lows: List[float], current_price: float
    ) -> float:
        """
        找到最近的支撑位

        支撑位 = 当前价格下方最近的摆动低点

        Args:
            swing_lows: 摆动低点列表
            current_price: 当前价格

        Returns:
            float: 最近支撑位价格
        """
        # 找到当前价格下方的支撑
        below_lows = [low for low in swing_lows if low < current_price]
        if below_lows:
            return max(below_lows)  # 最近的支撑

        # 当前价低于所有摆动低点：使用最低点减去ATR缓冲作为保护性支撑
        if swing_lows:
            lowest = min(swing_lows)
            # 当前价已跌破历史低点，使用1%缓冲作为支撑
            buffer = lowest * 0.01
            return lowest - buffer

        return current_price * 0.97

    def _find_nearest_resistance(
        self, swing_highs: List[float], current_price: float
    ) -> float:
        """
        找到最近的阻力位

        阻力位 = 当前价格上方最近的摆动高点

        Args:
            swing_highs: 摆动高点列表
            current_price: 当前价格

        Returns:
            float: 最近阻力位价格
        """
        # 找到当前价格上方的阻力
        above_highs = [high for high in swing_highs if high > current_price]
        if above_highs:
            return min(above_highs)  # 最近的阻力

        # 当前价高于所有摆动高点：使用最高点加上1%缓冲作为保护性阻力
        if swing_highs:
            highest = max(swing_highs)
            buffer = highest * 0.01
            return highest + buffer

        return current_price * 1.03

    def _calculate_risk_reward(
        self,
        current_price: float,
        support: float,
        resistance: float,
    ) -> Tuple[float, str]:
        """
        计算风险收益比

        做多场景:
        - 风险(止损距离) = 当前价 - 支撑位
        - 收益(止盈距离) = 阻力位 - 当前价
        - R/R = 收益/风险

        Args:
            current_price: 当前价格
            support: 支撑位
            resistance: 阻力位

        Returns:
            (rr_ratio, quality): R/R比和质量评级
        """
        risk = current_price - support
        reward = resistance - current_price

        # 防止除零
        if risk <= 0:
            return 0.0, "poor"

        rr_ratio = reward / risk

        if rr_ratio >= self.excellent_rr:
            quality = "excellent"
        elif rr_ratio >= self.good_rr:
            quality = "good"
        elif rr_ratio >= self.min_rr:
            quality = "marginal"
        else:
            quality = "poor"

        return rr_ratio, quality

    def _detect_structure_change(
        self,
        structure: str,
        current_price: float,
        resistance: float,
        support: float,
        price_history: List[float],
    ) -> Tuple[bool, bool, str]:
        """
        检测市场结构突破/破位

        突破: 价格突破阻力位
        破位: 价格跌破支撑位

        Args:
            structure: 当前市场结构
            current_price: 当前价格
            resistance: 阻力位
            support: 支撑位
            price_history: 价格历史

        Returns:
            (is_breakout, is_breakdown, structure_change)
        """
        is_breakout = False
        is_breakdown = False
        structure_change = "无变化"

        # 突破检测: 当前价接近或突破阻力位
        breakout_threshold = resistance * 0.998  # 0.2%容差
        if current_price >= breakout_threshold:
            is_breakout = True
            if structure != "bullish":
                structure_change = "转多"

        # 破位检测: 当前价接近或跌破支撑位
        breakdown_threshold = support * 1.002  # 0.2%容差
        if current_price <= breakdown_threshold:
            is_breakdown = True
            if structure != "bearish":
                structure_change = "转空"

        return is_breakout, is_breakdown, structure_change

    def _generate_trading_advice(
        self,
        structure: str,
        rr_ratio: float,
        is_breakout: bool,
        is_breakdown: bool,
        atr_percent: float,
    ) -> Tuple[str, float]:
        """
        生成交易建议

        规则:
        - 上涨结构 + R/R >= 2.0 → 做多，正常仓位
        - 上涨结构 + R/R >= 1.5 → 做多，减仓
        - 上涨结构 + R/R < 1.5 → 不做
        - 下跌结构 → 考虑做空或观望
        - 震荡结构 → 保守，小仓位
        - 突破/破位 → 根据方向决定

        Args:
            structure: 市场结构
            rr_ratio: 风险收益比
            is_breakout: 是否突破
            is_breakdown: 是否破位
            atr_percent: ATR百分比

        Returns:
            (suggested_direction, position_size_factor)
        """
        suggested_direction = "none"
        position_size_factor = 0.0

        # 高波动环境降低仓位
        volatility_factor = 1.0
        if atr_percent > 0.05:
            volatility_factor = 0.6
        elif atr_percent > 0.03:
            volatility_factor = 0.8

        if structure == "bullish":
            if rr_ratio >= self.excellent_rr:
                suggested_direction = "long"
                position_size_factor = 1.0 * volatility_factor
            elif rr_ratio >= self.good_rr:
                suggested_direction = "long"
                position_size_factor = 0.8 * volatility_factor
            elif rr_ratio >= self.min_rr:
                suggested_direction = "long"
                position_size_factor = 0.5 * volatility_factor
            else:
                suggested_direction = "none"
                position_size_factor = 0.0
                logger.info(
                    f"[市场结构] 上涨结构但R/R={rr_ratio:.2f}不足，等待更好入场"
                )

        elif structure == "bearish":
            if rr_ratio >= self.good_rr:
                # 做空的风险收益比（反向计算）
                suggested_direction = "short"
                position_size_factor = 0.7 * volatility_factor
            elif is_breakdown:
                suggested_direction = "short"
                position_size_factor = 0.5 * volatility_factor
            else:
                suggested_direction = "none"
                position_size_factor = 0.0

        else:  # sideways
            if is_breakout and rr_ratio >= self.good_rr:
                suggested_direction = "long"
                position_size_factor = 0.5 * volatility_factor
            elif is_breakdown and rr_ratio >= self.good_rr:
                suggested_direction = "short"
                position_size_factor = 0.5 * volatility_factor
            else:
                suggested_direction = "none"
                position_size_factor = 0.0

        return suggested_direction, position_size_factor

    def _create_neutral_result(self, current_price: float) -> MarketStructureResult:
        """创建中性结构结果（数据不足时的默认返回）"""
        return MarketStructureResult(
            structure="sideways",
            structure_detail="数据不足，无法判断市场结构",
            nearest_support=current_price * 0.97,
            nearest_resistance=current_price * 1.03,
            current_price=current_price,
            risk_reward_ratio=1.0,
            rr_quality="poor",
            is_breakout=False,
            is_breakdown=False,
            structure_change="无变化",
            suggested_direction="none",
            position_size_factor=0.0,
            swing_highs=[],
            swing_lows=[],
        )