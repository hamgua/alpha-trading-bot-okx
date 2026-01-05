"""
动态分层信号系统
根据市场条件动态调整信号强度等级
"""

from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class DynamicSignalTier:
    """动态信号分层系统"""

    def __init__(self):
        # 信号等级定义
        self.SIGNAL_TIERS = {
            'aggressive_buy': {
                'price_position_max': 98,  # 允许极高位置
                'trend_min': 0.5,
                'volume_min': 1.0,
                'rsi_max': 75,
                'confidence': 0.7,
                'description': '积极买入 - 强势趋势+突破确认'
            },
            'strong_buy': {
                'price_position_max': 90,
                'trend_min': 0.4,
                'volume_min': 0.9,
                'rsi_max': 70,
                'confidence': 0.75,
                'description': '强势买入 - 明显趋势+量能支持'
            },
            'moderate_buy': {
                'price_position_max': 80,
                'trend_min': 0.3,
                'volume_min': 0.8,
                'rsi_max': 65,
                'confidence': 0.8,
                'description': '适度买入 - 标准趋势+正常量能'
            },
            'conservative_buy': {
                'price_position_max': 70,
                'trend_min': 0.2,
                'volume_min': 0.6,
                'rsi_max': 60,
                'confidence': 0.85,
                'description': '保守买入 - 弱趋势+谨慎量能'
            }
        }

        # 时间衰减配置
        self.TIME_DECAY_CONFIG = {
            'half_life_hours': 4,  # 4小时半衰期
            'max_age_hours': 24,   # 最大24小时
            'min_weight': 0.3      # 最低权重
        }

        # 信号历史记录
        self.signal_history = {}

    def evaluate_signal_tier(self, signal: Dict[str, Any], market_data: Dict[str, Any]) -> str:
        """评估信号等级"""
        # 提取关键指标
        price_position = market_data.get('composite_price_position', 50.0)
        trend_strength = market_data.get('trend_strength', 0.0)
        volume_ratio = market_data.get('volume_ratio', 1.0)
        rsi = market_data.get('technical_data', {}).get('rsi', 50.0)

        # 按等级顺序检查（从激进到保守）
        for tier_name, tier_config in self.SIGNAL_TIERS.items():
            if (
                price_position <= tier_config['price_position_max'] and
                trend_strength >= tier_config['trend_min'] and
                volume_ratio >= tier_config['volume_min'] and
                rsi <= tier_config['rsi_max']
            ):
                return tier_name

        # 默认保守等级
        return 'conservative_buy'

    def apply_tier_adjustments(self, signal: Dict[str, Any],
                              tier_name: str,
                              market_data: Dict[str, Any]) -> Dict[str, Any]:
        """应用分层调整"""
        tier_config = self.SIGNAL_TIERS.get(tier_name, self.SIGNAL_TIERS['conservative_buy'])

        # 复制信号避免修改原数据
        adjusted_signal = signal.copy()

        # 调整置信度
        original_confidence = signal.get('confidence', 0.5)
        target_confidence = tier_config['confidence']

        # 根据等级调整置信度
        if tier_name == 'aggressive_buy':
            # 激进买入：显著增强信号
            adjusted_confidence = min(1.0, original_confidence * 1.2)
            adjusted_signal['confidence'] = max(target_confidence, adjusted_confidence)
            adjusted_signal['reason'] = f"🚀 {tier_config['description']} - {signal.get('reason', '')}"

        elif tier_name == 'strong_buy':
            # 强势买入：适度增强
            adjusted_confidence = min(1.0, original_confidence * 1.1)
            adjusted_signal['confidence'] = max(target_confidence, adjusted_confidence)
            adjusted_signal['reason'] = f"💪 {tier_config['description']} - {signal.get('reason', '')}"

        elif tier_name == 'moderate_buy':
            # 适度买入：标准处理
            adjusted_signal['confidence'] = max(target_confidence, original_confidence)
            adjusted_signal['reason'] = f"📈 {tier_config['description']} - {signal.get('reason', '')}"

        else:  # conservative_buy
            # 保守买入：确保足够高的置信度
            adjusted_signal['confidence'] = max(target_confidence, original_confidence)
            adjusted_signal['reason'] = f"🛡️ {tier_config['description']} - {signal.get('reason', '')}"

        # 添加等级信息
        adjusted_signal['signal_tier'] = tier_name
        adjusted_signal['tier_config'] = tier_config

        return adjusted_signal

    def apply_time_decay(self, signal_age_hours: float, initial_weight: float) -> float:
        """应用时间衰减"""
        config = self.TIME_DECAY_CONFIG

        # 超过最大年龄，返回最低权重
        if signal_age_hours >= config['max_age_hours']:
            return config['min_weight']

        # 指数衰减公式
        half_life = config['half_life_hours']
        decay_factor = 0.5 ** (signal_age_hours / half_life)

        # 确保不低于最低权重
        decayed_weight = max(config['min_weight'], initial_weight * decay_factor)

        return decayed_weight

    def record_signal(self, signal_id: str, signal: Dict[str, Any], tier_name: str):
        """记录信号历史"""
        self.signal_history[signal_id] = {
            'timestamp': datetime.now(),
            'tier': tier_name,
            'signal': signal.copy(),
            'confidence': signal.get('confidence', 0.5)
        }

    def get_signal_decay_weight(self, signal_id: str) -> float:
        """获取信号衰减权重"""
        if signal_id not in self.signal_history:
            return 1.0

        signal_info = self.signal_history[signal_id]
        age = datetime.now() - signal_info['timestamp']
        age_hours = age.total_seconds() / 3600

        # 应用时间衰减
        decay_weight = self.apply_time_decay(age_hours, 1.0)

        logger.info(f"⏰ 信号时间衰减 - ID: {signal_id}, 年龄: {age_hours:.1f}小时, 权重: {decay_weight:.2f}")

        return decay_weight

    def should_override_price_position(self, tier_name: str, breakout_detected: bool) -> bool:
        """判断是否应覆盖价格位置限制"""
        # 激进买入 + 突破检测 = 允许覆盖价格位置
        if tier_name == 'aggressive_buy' and breakout_detected:
            return True

        # 强势买入 + 强趋势 = 适度放宽
        if tier_name == 'strong_buy' and breakout_detected:
            return True

        return False

    def get_recommendation_summary(self) -> Dict[str, Any]:
        """获取建议摘要"""
        if not self.signal_history:
            return {'status': 'no_data', 'message': '暂无信号历史'}

        # 统计各等级信号频率
        tier_counts = {}
        recent_signals = [
            s for s in self.signal_history.values()
            if datetime.now() - s['timestamp'] < timedelta(hours=24)
        ]

        for signal_info in recent_signals:
            tier = signal_info['tier']
            tier_counts[tier] = tier_counts.get(tier, 0) + 1

        # 找出最频繁的等级
        if tier_counts:
            most_frequent = max(tier_counts, key=tier_counts.get)
            return {
                'status': 'active',
                'most_frequent_tier': most_frequent,
                'tier_distribution': tier_counts,
                'total_signals': len(recent_signals),
                'recommendation': f"最近24小时以{most_frequent}信号为主"
            }

        return {'status': 'insufficient_data', 'message': '24小时内信号不足'}

# 全局实例
dynamic_signal_tier = DynamicSignalTier()