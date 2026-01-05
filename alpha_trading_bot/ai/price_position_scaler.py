"""
价格位置因子衰减器
根据综合价格位置动态调整AI信号强度和风险控制
"""

import math
from typing import Dict, Tuple

class PricePositionScaler:
    """价格位置缩放器 - 实现价格越高信号越弱，价格越低信号越强"""

    def __init__(self):
        # 价格位置区间定义
        self.EXTREME_LOW = 15    # 极低位 < 15%
        self.LOW = 35            # 低位 15-35%
        self.MODERATE_LOW = 45   # 偏低 35-45%
        self.NEUTRAL = 55        # 中性 45-55%
        self.MODERATE_HIGH = 65  # 偏高 55-65%
        self.HIGH = 75           # 高位 65-75%
        self.EXTREME_HIGH = 95   # 极高位 > 95% (从85%调整到95%)

        # 动态阈值配置（基于趋势强度）
        self.DYNAMIC_THRESHOLDS = {
            'strong_trend': {
                'extreme_high': 98,  # 强势趋势时极高位阈值放宽至98%
                'high': 85,          # 高位阈值放宽至85%
                'extreme_low': 12    # 极低位保持严格
            },
            'moderate_trend': {
                'extreme_high': 95,  # 中等趋势时95%
                'high': 80,          # 高位80%
                'extreme_low': 15
            },
            'weak_trend': {
                'extreme_high': 90,  # 弱趋势时保持严格90%
                'high': 75,          # 高位75%
                'extreme_low': 20
            }
        }

        # 信号强度衰减系数
        self.SIGNAL_ATTENUATION = {
            'extreme_low': 1.3,    # 极低位 - 信号增强30%
            'low': 1.2,            # 低位 - 信号增强20%
            'moderate_low': 1.1,   # 偏低 - 信号增强10%
            'neutral': 1.0,        # 中性 - 无调整
            'moderate_high': 0.85, # 偏高 - 信号减弱15%
            'high': 0.7,           # 高位 - 信号减弱30%
            'extreme_high': 0.5    # 极高位 - 信号减弱50%
        }

        # 风险控制系数
        self.RISK_COEFFICIENTS = {
            'extreme_low': 0.8,    # 极低位 - 降低风险要求
            'low': 0.85,           # 低位 - 稍微降低风险
            'moderate_low': 0.9,   # 偏低 - 轻微降低
            'neutral': 1.0,        # 中性 - 标准风险
            'moderate_high': 1.2,  # 偏高 - 提高风险要求
            'high': 1.5,           # 高位 - 大幅提高风险要求
            'extreme_high': 2.0    # 极高位 - 极高风险要求
        }

    def get_price_position_level(self, composite_position: float, trend_strength: float = 0.0) -> str:
        """根据综合价格位置获取级别 - 支持动态阈值"""
        # 根据趋势强度选择阈值
        if trend_strength >= 0.6:
            thresholds = self.DYNAMIC_THRESHOLDS['strong_trend']
        elif trend_strength >= 0.3:
            thresholds = self.DYNAMIC_THRESHOLDS['moderate_trend']
        else:
            thresholds = self.DYNAMIC_THRESHOLDS['weak_trend']

        # 使用动态阈值判断级别
        if composite_position < self.EXTREME_LOW:
            return 'extreme_low'
        elif composite_position < self.LOW:
            return 'low'
        elif composite_position < self.MODERATE_LOW:
            return 'moderate_low'
        elif composite_position < self.NEUTRAL:
            return 'neutral'
        elif composite_position < self.MODERATE_HIGH:
            return 'moderate_high'
        elif composite_position < thresholds['high']:  # 动态高位阈值
            return 'high'
        elif composite_position < thresholds['extreme_high']:  # 动态极高位阈值
            return 'extreme_high'
        else:
            # 超过动态极高位阈值，保持中性处理（避免过度惩罚）
            return 'high' if trend_strength >= 0.6 else 'extreme_high'

    def calculate_signal_adjustment(self, base_confidence: float,
                                  composite_position: float,
                                  trend_strength: float = 0.0) -> float:
        """计算信号调整系数 - 支持趋势强度

        Args:
            base_confidence: 基础置信度 (0.0-1.0)
            composite_position: 综合价格位置 (0.0-100.0)
            trend_strength: 趋势强度 (0.0-1.0)

        Returns:
            调整后的置信度
        """
        level = self.get_price_position_level(composite_position, trend_strength)
        attenuation = self.SIGNAL_ATTENUATION[level]

        # 应用衰减系数
        adjusted_confidence = base_confidence * attenuation

        # 确保在合理范围内
        return max(0.0, min(1.0, adjusted_confidence))

    def calculate_risk_adjustment(self, base_risk_score: float,
                                 composite_position: float) -> float:
        """计算风险调整系数

        Args:
            base_risk_score: 基础风险评分 (0.0-1.0)
            composite_position: 综合价格位置 (0.0-100.0)

        Returns:
            调整后的风险评分
        """
        level = self.get_price_position_level(composite_position)
        coefficient = self.RISK_COEFFICIENTS[level]

        # 应用风险系数
        adjusted_risk = base_risk_score * coefficient

        # 确保在合理范围内
        return max(0.0, min(1.0, adjusted_risk))

    def get_buy_signal_threshold_adjustment(self, composite_position: float) -> Dict[str, float]:
        """获取买入信号阈值调整

        Args:
            composite_position: 综合价格位置

        Returns:
            调整后的阈值字典
        """
        level = self.get_price_position_level(composite_position)

        # 基础阈值
        base_thresholds = {
            'strong_buy': 0.8,
            'weak_buy': 0.65,
            'hold': 0.45,
            'weak_sell': 0.35,
            'strong_sell': 0.2
        }

        # 根据价格位置调整阈值
        if level in ['extreme_high', 'high']:
            # 高位时提高买入门槛
            return {
                'strong_buy': 0.9,      # 提高到0.9
                'weak_buy': 0.8,        # 提高到0.8
                'hold': 0.6,            # 提高到0.6
                'weak_sell': 0.4,       # 保持
                'strong_sell': 0.2      # 保持
            }
        elif level in ['extreme_low', 'low']:
            # 低位时降低买入门槛
            return {
                'strong_buy': 0.7,      # 降低到0.7
                'weak_buy': 0.55,       # 降低到0.55
                'hold': 0.4,            # 降低到0.4
                'weak_sell': 0.3,       # 保持
                'strong_sell': 0.15     # 降低到0.15
            }
        else:
            return base_thresholds

    def get_position_recommendation(self, composite_position: float) -> str:
        """根据价格位置给出操作建议"""
        level = self.get_price_position_level(composite_position)

        recommendations = {
            'extreme_low': "🔥 极低位区域 - 强烈关注买入机会，可适度提高仓位",
            'low': "📈 低位区域 - 积极寻找买入机会，分批建仓",
            'moderate_low': "👀 偏低位置 - 可考虑逐步建仓，但需要其他信号确认",
            'neutral': "⚖️ 中性位置 - 等待更明确信号，保持标准策略",
            'moderate_high': "⚠️ 偏高位置 - 谨慎操作，降低买入意愿",
            'high': "🚨 高位区域 - 严格控制买入，优先考虑卖出",
            'extreme_high': "❌ 极高位区域 - 避免买入，考虑减仓或卖出"
        }

        return recommendations[level]

    def calculate_size_adjustment(self, base_size: float,
                                composite_position: float) -> float:
        """计算仓位大小调整

        Args:
            base_size: 基础仓位大小
            composite_position: 综合价格位置

        Returns:
            调整后的仓位大小
        """
        level = self.get_price_position_level(composite_position)

        # 仓位调整系数
        size_multipliers = {
            'extreme_low': 1.5,     # 极低位可加大50%仓位
            'low': 1.3,             # 低位可加大30%仓位
            'moderate_low': 1.1,    # 偏低可加大10%仓位
            'neutral': 1.0,         # 中性保持标准仓位
            'moderate_high': 0.7,   # 偏高减少30%仓位
            'high': 0.4,            # 高位减少60%仓位
            'extreme_high': 0.2     # 极高位减少80%仓位
        }

        multiplier = size_multipliers[level]
        adjusted_size = base_size * multiplier

        # 确保在合理范围内
        return max(0.0, min(1.0, adjusted_size))

    def handle_breakout_scenario(self, current_price: float, historical_high: float,
                                volume_ratio: float, trend_strength: float) -> Dict:
        """处理突破历史高点的场景

        Args:
            current_price: 当前价格
            historical_high: 历史最高价（通常使用24h最高价）
            volume_ratio: 当前成交量/平均成交量比率
            trend_strength: 趋势强度（0.0-1.0）

        Returns:
            突破处理配置字典
        """
        breakout_threshold = 1.002  # 0.2%突破确认
        if current_price > historical_high * breakout_threshold:
            # 价格突破历史高点
            if volume_ratio > 1.2 and trend_strength > 0.4:
                # 量能确认 + 趋势确认 = 降低价格位置权重，允许适度追高
                return {
                    'is_breakout': True,
                    'price_position_weight': 0.3,  # 从正常0.55降低
                    'required_confidence': 0.7,    # 降低置信度要求
                    'risk_penalty': 0.1,           # 减少风险惩罚
                    'signal_multiplier': 0.8,      # 减少价格位置惩罚
                    'breakout_strength': min(1.0, (current_price / historical_high - 1) * 1000)
                }
            else:
                # 突破但缺乏确认 = 谨慎处理
                return {
                    'is_breakout': True,
                    'price_position_weight': 0.7,  # 适度降低权重
                    'required_confidence': 0.8,
                    'risk_penalty': 0.2,
                    'signal_multiplier': 0.9
                }
        return {'is_breakout': False}

    def get_dynamic_thresholds(self, trend_strength: float) -> Dict[str, int]:
        """根据趋势强度获取动态阈值"""
        if trend_strength >= 0.6:
            return self.DYNAMIC_THRESHOLDS['strong_trend']
        elif trend_strength >= 0.3:
            return self.DYNAMIC_THRESHOLDS['moderate_trend']
        else:
            return self.DYNAMIC_THRESHOLDS['weak_trend']

    def get_detailed_analysis(self, composite_position: float, trend_strength: float = 0.0) -> Dict:
        """获取详细分析信息 - 支持趋势强度"""
        level = self.get_price_position_level(composite_position, trend_strength)

        return {
            'price_position': composite_position,
            'level': level,
            'signal_multiplier': self.SIGNAL_ATTENUATION[level],
            'risk_multiplier': self.RISK_COEFFICIENTS[level],
            'recommendation': self.get_position_recommendation(composite_position),
            'threshold_adjustment': self.get_buy_signal_threshold_adjustment(composite_position)
        }