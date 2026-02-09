"""
优化版 Prompt 构建器 - 针对趋势感知的 AI 交易决策
解决原 Prompt 的三大核心问题：
1. 缺乏市场趋势识别
2. 静态决策框架不灵活
3. AI 信号过于保守

核心优化：
- 动态市场状态分类 (uptrend/downtrend/sideways)
- 趋势强度 + 动量双重判断
- 针对不同市场的差异化决策框架
- 明确的顺势/逆势交易规则
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    """市场状态分类"""

    STRONG_UPTREND = "strong_uptrend"  # 强上涨趋势
    WEAK_UPTREND = "weak_uptrend"  # 弱上涨趋势
    SIDEWAYS = "sideways"  # 震荡整理
    WEAK_DOWNTREND = "weak_downtrend"  # 弱下跌趋势
    STRONG_DOWNTREND = "strong_downtrend"  # 强下跌趋势


class MomentumStrength(Enum):
    """动量强度分类"""

    STRONG_POSITIVE = "strong_positive"  # 强动量上涨
    WEAK_POSITIVE = "weak_positive"  # 弱动量上涨
    NEUTRAL = "neutral"  # 无明显动量
    WEAK_NEGATIVE = "weak_negative"  # 弱动量下跌
    STRONG_NEGATIVE = "strong_negative"  # 强动量下跌


@dataclass
class MarketContext:
    """市场上下文信息"""

    regime: MarketRegime = MarketRegime.SIDEWAYS
    momentum: MomentumStrength = MomentumStrength.NEUTRAL
    momentum_percent: float = 0.0
    trend_strength: float = 0.0
    confidence: float = 0.5

    # 额外上下文
    consecutive_direction: int = 0  # 连续同向周期数
    volatility_level: str = "normal"  # high/normal/low
    recent_high: float = 0.0
    recent_low: float = 0.0
    price_position: float = 0.5  # 0-1，价格在近期区间的位置


@dataclass
class PromptConfig:
    """Prompt 配置参数"""

    # 趋势相关
    strong_trend_threshold: float = 0.6
    weak_trend_threshold: float = 0.3

    # 动量相关
    strong_momentum_threshold: float = 0.005  # 0.5%
    weak_momentum_threshold: float = 0.002  # 0.2%

    # 置信度调整
    base_confidence_boost: float = 0.1
    trend_aligned_boost: float = 0.15
    trend_counter_discount: float = 0.25

    # 仓位调整
    strong_trend_position_multiplier: float = 1.3
    weak_trend_position_multiplier: float = 1.0


class OptimizedPromptBuilder:
    """
    优化版 Prompt 构建器

    核心思路：
    1. 先分析市场状态 (regime + momentum)
    2. 根据市场状态选择对应的决策框架
    3. 给出明确的顺势/逆势交易规则
    4. 动态调整置信度和仓位建议
    """

    def __init__(self, config: Optional[PromptConfig] = None):
        self.config = config or PromptConfig()
        self._cache: Dict[str, str] = {}

    def build(
        self,
        market_data: Dict[str, Any],
        market_context: Optional[MarketContext] = None,
    ) -> str:
        """构建完整的优化 Prompt"""

        # 分析市场状态（如果没有提供）
        if market_context is None:
            market_context = self._analyze_market_context(market_data)

        # 根据市场状态选择模板
        template = self._get_template(market_context)

        # 填充模板数据
        filled_prompt = self._fill_template(template, market_data, market_context)

        return filled_prompt

    def _analyze_market_context(self, market_data: Dict[str, Any]) -> MarketContext:
        """分析市场状态"""

        technical = market_data.get("technical", {})
        current_price = market_data.get("price", 0)
        recent_change = market_data.get("recent_change_percent", 0)

        # 提取技术指标
        trend_strength = technical.get("trend_strength", 0.5)
        trend_direction = technical.get("trend_direction", "neutral")
        rsi = technical.get("rsi", 50)
        adx = technical.get("adx", 25)
        atr_pct = technical.get("atr_percent", 2.0)

        # 趋势强度判断
        if trend_direction == "up":
            if trend_strength >= self.config.strong_trend_threshold:
                regime = MarketRegime.STRONG_UPTREND
            else:
                regime = MarketRegime.WEAK_UPTREND
        elif trend_direction == "down":
            if trend_strength >= self.config.strong_trend_threshold:
                regime = MarketRegime.STRONG_DOWNTREND
            else:
                regime = MarketRegime.WEAK_DOWNTREND
        else:
            regime = MarketRegime.SIDEWAYS

        # 动量判断
        if recent_change > self.config.strong_momentum_threshold:
            momentum = MomentumStrength.STRONG_POSITIVE
        elif recent_change > self.config.weak_momentum_threshold:
            momentum = MomentumStrength.WEAK_POSITIVE
        elif recent_change < -self.config.strong_momentum_threshold:
            momentum = MomentumStrength.STRONG_NEGATIVE
        elif recent_change < -self.config.weak_momentum_threshold:
            momentum = MomentumStrength.WEAK_NEGATIVE
        else:
            momentum = MomentumStrength.NEUTRAL

        # 波动率水平
        if atr_pct > 4.0:
            volatility = "high"
        elif atr_pct < 1.5:
            volatility = "low"
        else:
            volatility = "normal"

        # 计算置信度
        confidence = min(0.95, 0.5 + abs(recent_change) * 10 + trend_strength * 0.3)

        return MarketContext(
            regime=regime,
            momentum=momentum,
            momentum_percent=recent_change,
            trend_strength=trend_strength,
            confidence=confidence,
            volatility_level=volatility,
            price_position=technical.get("bb_position", 0.5),
        )

    def _get_template(self, context: MarketContext) -> str:
        """根据市场状态选择对应的决策模板"""

        templates = {
            MarketRegime.STRONG_UPTREND: self._template_strong_uptrend,
            MarketRegime.WEAK_UPTREND: self._template_weak_uptrend,
            MarketRegime.SIDEWAYS: self._template_sideways,
            MarketRegime.WEAK_DOWNTREND: self._template_weak_downtrend,
            MarketRegime.STRONG_DOWNTREND: self._template_strong_downtrend,
        }

        return templates.get(context.regime, self._template_sideways)()

    def _fill_template(
        self, template: str, market_data: Dict[str, Any], context: MarketContext
    ) -> str:
        """填充模板数据"""

        technical = market_data.get("technical", {})
        position = market_data.get("position", {})

        # 提取关键数据
        data = {
            "current_price": market_data.get("price", 0),
            "price_change_1h": market_data.get("recent_change_percent", 0) * 100,
            "regime": context.regime.value,
            "momentum": context.momentum.value,
            "momentum_percent": context.momentum_percent * 100,
            "trend_strength": context.trend_strength,
            "rsi": technical.get("rsi", 50),
            "macd_hist": technical.get("macd_histogram", 0),
            "adx": technical.get("adx", 25),
            "atr_pct": technical.get("atr_percent", 2.0),
            "bb_position": technical.get("bb_position", 0.5) * 100,
            "volatility": context.volatility_level,
            "position_side": position.get("side", "none"),
            "position_pnl": position.get("unrealized_pnl", 0),
        }

        return template.format(**data)

    def _template_strong_uptrend(self) -> str:
        """强上涨趋势模板"""
        return """你是一个专业的加密货币量化交易决策引擎。

【当前市场状态：强上涨趋势】
⚠️ 当前处于明确的上涨趋势中，趋势强度高，动量强劲
这是顺势交易的最佳时机，应该更加积极地参与

【关键指标】
- 当前价格: {current_price}
- 1小时涨跌幅: {price_change_1h:.2f}%
- 趋势强度: {trend_strength:.2f} (强趋势)
- 动量状态: {momentum} ({momentum_percent:.2f}%)
- RSI: {rsi:.1f}
- MACD Histogram: {macd_hist:+.4f}
- ADX: {adx:.1f}
- ATR波动率: {atr_pct:.2f}%
- 布林带位置: {bb_position:.1f}%

【当前持仓】
- 持仓方向: {position_side}
- 浮盈/亏: {position_pnl:.2f}%

【顺势交易策略 - 强上涨趋势】

🎯 核心原则：顺势而为，积极参与

买入规则（满足任一条件）:
1. 价格回踩重要支撑位（布林带 < 50%）+ RSI < 65
2. 动量持续为正（1h涨幅 > 0.3%）
3. 趋势强度保持 > 0.5
4. 轻微超买可忽略（RSI < 75），强趋势中追涨风险较低

减仓/卖出规则（满足任一）:
1. 趋势强度明显减弱（< 0.4）
2. 动量由正转负
3. RSI > 80 严重超买
4. 价格跌破重要均线

⚠️ 特别提醒：
- 强趋势中不要轻易做空
- 不要因为轻微回调就恐慌卖出
- 趋势强度 > 0.6 时可以适当追涨

【决策优先级】
1. 优先考虑买入/加仓（顺势）
2. 只有在明确转弱信号时才考虑减仓
3. 绝对禁止逆势做空

【输出要求】
最终输出格式（只输出这一行）：
buy | confidence: XX%
或
hold | confidence: XX%
或
sell | confidence: XX%

【置信度参考】（内心推理）
买入置信度:
- 基础60% + 趋势明确向上(+20%) + RSI < 60(+10%) + 动量正向(+10%) = 最高100%
- 趋势强度 > 0.6 时整体置信度 +15%

卖出置信度:
- 基础50% + 趋势转弱(+25%) + RSI > 75(+15%) + 动量转负(+10%) = 最高100%

持有置信度:
- 基础55% + 趋势稳定(+15%) + 等待明确信号(+15%) = 最高85%"""

    def _template_weak_uptrend(self) -> str:
        """弱上涨趋势模板"""
        return """你是一个专业的加密货币量化交易决策引擎。

【当前市场状态：弱上涨趋势】
⚠️ 当前处于上涨趋势中，但趋势强度中等
需要更加谨慎，等待更好的入场时机

【关键指标】
- 当前价格: {current_price}
- 1小时涨跌幅: {price_change_1h:.2f}%
- 趋势强度: {trend_strength:.2f} (弱趋势)
- 动量状态: {momentum} ({momentum_percent:.2f}%)
- RSI: {rsi:.1f}
- MACD Histogram: {macd_hist:+.4f}
- ADX: {adx:.1f}
- ATR波动率: {atr_pct:.2f}%
- 布林带位置: {bb_position:.1f}%

【当前持仓】
- 持仓方向: {position_side}
- 浮盈/亏: {position_pnl:.2f}%

【谨慎追涨策略 - 弱上涨趋势】

🎯 核心原则：逢低买入，不追高

买入规则（须同时满足）:
1. 价格回调至支撑位（布林带 < 40%）
2. RSI < 55（非超买）
3. MACD Histogram > 0（多头动能）
4. 动量保持正向
5. 趋势强度 > 0.25

⚠️ 禁止买入条件:
- RSI > 65（超买区域）
- 布林带位置 > 60%（价格过高）
- 动量减弱或转负
- 趋势强度 < 0.25

减仓/卖出规则:
1. 趋势强度明显减弱
2. 动量由正转负
3. RSI > 70 超买
4. 价格跌破中轨

【决策优先级】
1. 优先等待回调买入机会
2. 不轻易追涨
3. 有持仓可继续持有，但不加仓
4. 趋势转弱信号出现时考虑减仓

【输出要求】
最终输出格式（只输出这一行）：
buy | confidence: XX%
或
hold | confidence: XX%
或
sell | confidence: XX%

【置信度参考】（内心推理）
买入置信度:
- 基础50% + 回调支撑位(+20%) + RSI < 55(+15%) + 动量正向(+15%) = 最高100%
- 不满足条件时强制转为HOLD

持有置信度:
- 基础60% + 趋势未确认(+15%) + 等待信号(+15%) = 最高90%

卖出置信度:
- 基础50% + 趋势转弱(+25%) + 动量转负(+15%) + RSI > 70(+10%) = 最高100%"""

    def _template_sideways(self) -> str:
        """震荡整理模板"""
        return """你是一个专业的加密货币量化交易决策引擎。

【当前市场状态：震荡整理】
⚠️ 当前无明显趋势方向，市场处于整理阶段
应该保持观望或高抛低吸，不宜追涨杀跌

【关键指标】
- 当前价格: {current_price}
- 1小时涨跌幅: {price_change_1h:.2f}%
- 趋势强度: {trend_strength:.2f} (无趋势)
- 动量状态: {momentum} ({momentum_percent:.2f}%)
- RSI: {rsi:.1f}
- MACD Histogram: {macd_hist:+.4f}
- ADX: {adx:.1f}
- ATR波动率: {atr_pct:.2f}%
- 布林带位置: {bb_position:.1f}%

【当前持仓】
- 持仓方向: {position_side}
- 浮盈/亏: {position_pnl:.2f}%

【震荡整理策略】

🎯 核心原则：高抛低吸，保持中性

买入规则（须同时满足）:
1. 价格接近区间底部（布林带 < 25%）
2. RSI < 35（超卖区域）
3. MACD 未明显转空
4. 动量不是强负向
5. 有明确支撑位

卖出规则（须同时满足）:
1. 价格接近区间顶部（布林带 > 75%）
2. RSI > 65（超买区域）
3. MACD 转空头
4. 动量不是强正向

⚠️ 特别提醒：
- 震荡市中不要追涨杀跌
- 等待价格到区间边缘再操作
- 保持仓位中性或空仓

【决策优先级】
1. 优先保持观望（HOLD）
2. 只有价格到强支撑/压力位才操作
3. 有持仓时采用网格交易思维
4. 严格止损，不幻想

【输出要求】
最终输出格式（只输出这一行）：
buy | confidence: XX%
或
hold | confidence: XX%
或
sell | confidence: XX%

【置信度参考】（内心推理）
买入置信度:
- 基础40% + 接近底部(+25%) + RSI超卖(+20%) + 支撑位明确(+15%) = 最高100%
- 震荡市中买入置信度整体降低20%

持有置信度:
- 基础65% + 无趋势(+15%) + 等待信号(+15%) = 最高95%

卖出置信度:
- 基础40% + 接近顶部(+25%) + RSI超买(+20%) + 压力位明确(+15%) = 最高100%"""

    def _template_weak_downtrend(self) -> str:
        """弱下跌趋势模板"""
        return """你是一个专业的加密货币量化交易决策引擎。

【当前市场状态：弱下跌趋势】
⚠️ 当前处于下跌趋势中，但趋势强度中等
应该保持谨慎，避免逆势抄底

【关键指标】
- 当前价格: {current_price}
- 1小时涨跌幅: {price_change_1h:.2f}%
- 趋势强度: {trend_strength:.2f} (弱趋势)
- 动量状态: {momentum} ({momentum_percent:.2f}%)
- RSI: {rsi:.1f}
- MACD Histogram: {macd_hist:+.4f}
- ADX: {adx:.1f}
- ATR波动率: {atr_pct:.2f}%
- 布林带位置: {bb_position:.1f}%

【当前持仓】
- 持仓方向: {position_side}
- 浮盈/亏: {position_pnl:.2f}%

【防御性策略 - 弱下跌趋势】

🎯 核心原则：轻仓观望，尝试反弹

买入规则（须同时满足）:
1. 价格接近强支撑位（布林带 < 20%）
2. RSI < 30（极度超卖）
3. 动量不是强负向
4. 下跌动能在减弱
5. 趋势强度 < 0.4
6. 严格控制仓位（正常仓位50%以下）

⚠️ 禁止买入条件:
- 趋势强度 > 0.5
- 动量为强负向
- RSI > 45
- 价格跌破重要支撑位

卖出/止损规则:
1. 价格跌破支撑位
2. 动量由弱转强负向
3. 趋势强度 > 0.5
4. RSI < 25（可能加速下跌）

【决策优先级】
1. 优先保持观望（HOLD）
2. 只有超卖+强支撑才考虑轻仓买入
3. 绝对禁止重仓抄底
4. 有持仓时设置严格止损

【输出要求】
最终输出格式（只输出这一行）：
buy | confidence: XX%
或
hold | confidence: XX%
或
sell | confidence: XX%

【置信度参考】（内心推理）
买入置信度:
- 基础35% + 极度超卖(+25%) + 强支撑(+20%) + 跌势趋缓(+15%) = 最高95%
- 逆势操作置信度整体降低25%

持有置信度:
- 基础70% + 趋势向下(+15%) + 等待信号(+10%) = 最高95%

卖出置信度:
- 基础55% + 趋势向下(+20%) + 动量负向(+15%) = 最高90%"""

    def _template_strong_downtrend(self) -> str:
        """强下跌趋势模板"""
        return """你是一个专业的加密货币量化交易决策引擎。

【当前市场状态：强下跌趋势】
⚠️ 警告：当前处于明确的下跌趋势中，动能强劲
这是高风险时期，应该保持防御

【关键指标】
- 当前价格: {current_price}
- 1小时涨跌幅: {price_change_1h:.2f}%
- 趋势强度: {trend_strength:.2f} (强趋势)
- 动量状态: {momentum} ({momentum_percent:.2f}%)
- RSI: {rsi:.1f}
- MACD Histogram: {macd_hist:+.4f}
- ADX: {adx:.1f}
- ATR波动率: {atr_pct:.2f}%
- 布林带位置: {bb_position:.1f}%

【当前持仓】
- 持仓方向: {position_side}
- 浮盈/亏: {position_pnl:.2f}%

【绝对防御策略 - 强下跌趋势】

🎯 核心原则：现金为王，禁令买入

⚠️ 绝对禁止买入条件：
- 任何情况下都禁止买入
- 绝对禁止逆势抄底
- 绝对不要接飞刀

卖出/减仓规则（满足任一）:
1. 有持仓应该优先减仓/止损
2. 趋势强度 > 0.6 应该大幅减仓
3. 动量为强负向应该清仓
4. 价格跌破任何支撑位
5. RSI < 20 可能加速下跌

持仓策略:
1. 如果持仓且浮盈：设置移动止盈保护利润
2. 如果持仓且浮亏：考虑止损或减仓
3. 如果持仓但趋势极弱：清仓观望

【决策优先级】
1. 绝对禁止买入
2. 优先减仓/清仓
3. 保持现金仓位
4. 等待趋势反转信号

【输出要求】
最终输出格式（只输出这一行）：
buy | confidence: XX%
或
hold | confidence: XX%
或
sell | confidence: XX%

【特别说明】
在强下跌趋势中：
- 买入置信度强制为0%
- 卖出置信度基础60% + 趋势向下(+25%) + 动量强负(+15%) = 最高100%
- 持有置信度只有10%，强烈建议卖出

【置信度参考】（内心推理）
买入置信度: 0%（强趋势禁止买入）

持有置信度:
- 基础20% + 趋势向下(+15%) + 动量强负(+15%) = 最高50%
- 强烈建议卖出或减仓

卖出置信度:
- 基础60% + 趋势明确向下(+25%) + 动量强负(+15%) = 最高100%"""


class AdaptivePromptSelector:
    """
    自适应 Prompt 选择器

    根据历史表现动态选择最优的 prompt 策略
    """

    def __init__(self):
        self._builder = OptimizedPromptBuilder()
        self._performance_history: Dict[str, List[Dict]] = {}

    def select_prompt_type(
        self,
        market_context: MarketContext,
        historical_performance: Optional[Dict[str, float]] = None,
    ) -> str:
        """
        根据市场状态和历史表现选择最优 prompt 类型

        Returns:
            prompt_type: "aggressive" / "moderate" / "conservative"
        """

        # 基于市场状态选择基础类型
        if market_context.regime in [
            MarketRegime.STRONG_UPTREND,
            MarketRegime.WEAK_UPTREND,
        ]:
            base_type = "aggressive"
        elif market_context.regime == MarketRegime.SIDEWAYS:
            base_type = "moderate"
        else:
            base_type = "conservative"

        # 根据历史表现调整
        if historical_performance:
            adjusted_type = self._adjust_for_performance(
                base_type, historical_performance, market_context.regime
            )
            return adjusted_type

        return base_type

    def _adjust_for_performance(
        self, base_type: str, performance: Dict[str, float], regime: MarketRegime
    ) -> str:
        """根据历史表现调整策略类型"""

        regime_key = regime.value
        regime_performance = performance.get(regime_key, 0.5)

        # 如果该市场类型历史表现差，降低风险等级
        if regime_performance < 0.4:
            if base_type == "aggressive":
                return "moderate"
            elif base_type == "moderate":
                return "conservative"

        # 如果该市场类型历史表现好，可以更激进
        if regime_performance > 0.6:
            if base_type == "conservative":
                return "moderate"
            elif base_type == "moderate":
                return "aggressive"

        return base_type


def build_optimized_prompt(
    market_data: Dict[str, Any], context: Optional[MarketContext] = None
) -> str:
    """便捷函数：构建优化版 Prompt"""
    builder = OptimizedPromptBuilder()
    return builder.build(market_data, context)
