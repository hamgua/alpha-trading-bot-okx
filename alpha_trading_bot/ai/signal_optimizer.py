"""
AI信号优化器 - 优化qwen和deepseek的信号生成
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import numpy as np

logger = logging.getLogger(__name__)


class SignalOptimizer:
    """AI信号优化器"""

    def __init__(self):
        # 动态权重配置
        self.provider_weights = {
            'qwen': 0.6,
            'deepseek': 0.4
        }
        self.performance_history = {
            'qwen': [],
            'deepseek': []
        }
        self.min_hold_threshold = 0.55  # 降低HOLD信号阈值
        self.signal_strength_thresholds = {
            'strong_buy': 0.8,
            'weak_buy': 0.65,
            'hold': 0.45,
            'weak_sell': 0.35,
            'strong_sell': 0.2
        }

    def optimize_signals(self, signals: List[Dict[str, Any]],
                        market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        优化AI信号

        Args:
            signals: AI提供商的原始信号列表
            market_data: 市场数据

        Returns:
            优化后的信号列表
        """
        if not signals:
            return signals

        optimized_signals = []

        for signal in signals:
            provider = signal.get('provider', 'unknown')
            original_confidence = signal.get('confidence', 0.5)

            # 1. 应用提供商特定的优化
            if provider in ['qwen', 'deepseek']:
                optimized_signal = self._optimize_provider_signal(
                    signal, market_data, provider
                )
            else:
                optimized_signal = signal

            # 2. 应用通用优化
            optimized_signal = self._apply_general_optimizations(
                optimized_signal, market_data
            )

            # 3. 增强信号理由
            optimized_signal = self._enhance_signal_reason(
                optimized_signal, market_data
            )

            optimized_signals.append(optimized_signal)

            # 记录优化前后的对比
            if original_confidence != optimized_signal.get('confidence', original_confidence):
                logger.info(f"🔧 {provider.upper()} 信号优化: "
                           f"信心 {original_confidence:.2f} → "
                           f"{optimized_signal.get('confidence', original_confidence):.2f}")

        return optimized_signals

    def _optimize_provider_signal(self, signal: Dict[str, Any],
                                 market_data: Dict[str, Any],
                                 provider: str) -> Dict[str, Any]:
        """针对特定提供商优化信号"""
        optimized = signal.copy()

        # 获取当前信号类型和信心
        signal_type = signal.get('signal', 'HOLD').upper()
        confidence = signal.get('confidence', 0.5)
        reason = signal.get('reason', '')

        # qwen特定优化
        if provider == 'qwen':
            optimized = self._optimize_qwen_signal(signal, market_data)

        # deepseek特定优化
        elif provider == 'deepseek':
            optimized = self._optimize_deepseek_signal(signal, market_data)

        # kimi特定优化
        elif provider == 'kimi':
            optimized = self._optimize_kimi_signal(signal, market_data)

        # openai特定优化
        elif provider == 'openai':
            optimized = self._optimize_openai_signal(signal, market_data)

        return optimized

    def _optimize_qwen_signal(self, signal: Dict[str, Any],
                             market_data: Dict[str, Any]) -> Dict[str, Any]:
        """优化qwen信号"""
        optimized = signal.copy()
        signal_type = signal.get('signal', 'HOLD').upper()
        confidence = signal.get('confidence', 0.5)
        reason = signal.get('reason', '')

        # 1. 增强对微小变化的敏感性
        technical_data = market_data.get('technical_data', {})
        price_position = technical_data.get('price_position', 0.5)
        rsi = technical_data.get('rsi', 50)

        # 如果价格处于极端位置且有微小变化，提高信号强度
        if (price_position < 0.2 or price_position > 0.8) and abs(confidence - 0.65) < 0.1:
            if signal_type == 'BUY' and price_position < 0.2:
                optimized['confidence'] = min(confidence + 0.1, 0.85)
                optimized['reason'] += " | 低位增强信号"
            elif signal_type == 'SELL' and price_position > 0.8:
                optimized['confidence'] = min(confidence + 0.1, 0.85)
                optimized['reason'] += " | 高位增强信号"

        # 2. 改进累积变化为0的问题
        if "累积变化为0.00%" in reason and confidence > 0.6:
            # 检查实际的价格变化
            change_percent = market_data.get('change_percent', 0)
            if abs(change_percent) > 0.01:  # 如果有实际变化
                optimized['reason'] = reason.replace("累积变化为0.00%", f"当前变化{change_percent:+.2f}%")

        # 3. 增强连续涨跌识别
        if "连续涨跌次数为0" in reason:
            # 检查最近的价格趋势
            close_prices = market_data.get('close_prices', [])
            if len(close_prices) >= 3:
                recent_trend = self._calculate_recent_trend(close_prices[-3:])
                if recent_trend != 0:
                    optimized['reason'] = reason.replace("连续涨跌次数为0", f"连续{recent_trend}个周期同向变化")

        return optimized

    def _optimize_deepseek_signal(self, signal: Dict[str, Any],
                                 market_data: Dict[str, Any]) -> Dict[str, Any]:
        """优化deepseek信号"""
        optimized = signal.copy()
        signal_type = signal.get('signal', 'HOLD').upper()
        confidence = signal.get('confidence', 0.5)
        reason = signal.get('reason', '')

        # 1. 平衡过度谨慎的信号
        if signal_type == 'HOLD' and confidence == 0.65:
            # 检查是否有更强的趋势信号
            technical_data = market_data.get('technical_data', {})
            trend_strength = technical_data.get('trend_strength', 0)
            adx = technical_data.get('adx', 0)

            if trend_strength > 0.4 and adx > 25:  # 强趋势
                if "价格处于" in reason and "区间" in reason:
                    # 如果ADX显示强趋势，降低HOLD倾向
                    optimized['confidence'] = 0.55  # 降低HOLD信心
                    optimized['reason'] += " | 但ADX显示强趋势，建议谨慎持仓"

        # 2. 增强卖出信号
        if signal_type == 'SELL' and confidence >= 0.8:
            # deepseek的SELL信号通常较准确，可以进一步增强
            optimized['confidence'] = min(confidence + 0.05, 0.9)
            optimized['reason'] += " | 高位确认信号"

        # 3. 优化区间位置判断
        if "价格处于" in reason and "区间" in reason:
            # 添加更精确的位置描述
            technical_data = market_data.get('technical_data', {})
            price_position = technical_data.get('price_position', 0.5)
            if price_position > 0.9:
                optimized['reason'] += " | 极度高位区域"
            elif price_position < 0.1:
                optimized['reason'] += " | 极度低位区域"

        return optimized

    def _apply_general_optimizations(self, signal: Dict[str, Any],
                                   market_data: Dict[str, Any]) -> Dict[str, Any]:
        """应用通用优化"""
        optimized = signal.copy()
        signal_type = signal.get('signal', 'HOLD').upper()
        confidence = signal.get('confidence', 0.5)

        # 1. 基于市场波动率调整信号强度
        atr_percentage = market_data.get('atr_percentage', 0)
        if atr_percentage < 0.2:  # 低波动
            # 在低波动市场，降低信号强度要求
            if signal_type in ['BUY', 'SELL']:
                optimized['confidence'] = max(confidence - 0.05, 0.3)
        elif atr_percentage > 2.0:  # 高波动
            # 在高波动市场，提高信号强度
            if signal_type in ['BUY', 'SELL']:
                optimized['confidence'] = min(confidence + 0.05, 0.9)

        # 2. 基于价格位置优化
        technical_data = market_data.get('technical_data', {})
        price_position = technical_data.get('price_position', 0.5)
        rsi = technical_data.get('rsi', 50)

        # 极端位置增强信号
        if price_position < 0.15 and rsi < 35 and signal_type == 'BUY':
            optimized['confidence'] = min(confidence + 0.1, 0.85)
        elif price_position > 0.85 and rsi > 65 and signal_type == 'SELL':
            optimized['confidence'] = min(confidence + 0.1, 0.85)

        return optimized

    def _enhance_signal_reason(self, signal: Dict[str, Any],
                              market_data: Dict[str, Any]) -> Dict[str, Any]:
        """增强信号理由"""
        enhanced = signal.copy()
        reason = signal.get('reason', '')

        # 添加动态缓存信息
        atr_percentage = market_data.get('atr_percentage', 0)
        cache_duration = 300 if atr_percentage > 2.0 else 600 if atr_percentage > 1.0 else 900

        enhanced['reason'] += f" | 缓存:{cache_duration}s"

        # 添加时间戳
        enhanced['timestamp'] = datetime.now().isoformat()

        return enhanced

    def _calculate_recent_trend(self, prices: List[float]) -> int:
        """计算近期价格趋势"""
        if len(prices) < 2:
            return 0

        trend_count = 0
        direction = 0  # 1上涨, -1下跌

        for i in range(1, len(prices)):
            current_direction = 1 if prices[i] > prices[i-1] else -1

            if direction == 0:
                direction = current_direction
                trend_count = 1
            elif current_direction == direction:
                trend_count += 1
            else:
                break  # 趋势改变

        return trend_count if direction == 1 else -trend_count

    def _check_timeframe_consistency(self, multi_timeframe: Dict[str, Any]) -> float:
        """检查多时间框架一致性"""
        if not multi_timeframe:
            return 0.0

        # 提取各时间框架的趋势信号
        trends = []
        for tf, data in multi_timeframe.items():
            if isinstance(data, list) and len(data) >= 2:
                # 简单的趋势判断：最新值 vs 前一个值
                latest = data[-1][4] if isinstance(data[-1], list) else data[-1]  # 收盘价
                previous = data[-2][4] if isinstance(data[-2], list) else data[-2]
                trend = 1 if latest > previous else -1 if latest < previous else 0
                trends.append(trend)

        if not trends:
            return 0.0

        # 计算一致性（相同趋势的占比）
        if len(trends) == 1:
            return 1.0

        majority_trend = max(set(trends), key=trends.count)
        consistency = trends.count(majority_trend) / len(trends)
        return consistency

    def update_provider_performance(self, provider: str,
                                  signal_accuracy: float) -> None:
        """更新提供商表现历史"""
        if provider in self.performance_history:
            self.performance_history[provider].append(signal_accuracy)
            # 只保留最近100次记录
            if len(self.performance_history[provider]) > 100:
                self.performance_history[provider].pop(0)

            # 动态调整权重
            self._adjust_provider_weights()

        # 初始化kimi和openai的权重
        if 'kimi' not in self.provider_weights:
            self.provider_weights['kimi'] = 0.5
        if 'openai' not in self.provider_weights:
            self.provider_weights['openai'] = 0.5
        if 'kimi' not in self.performance_history:
            self.performance_history['kimi'] = []
        if 'openai' not in self.performance_history:
            self.performance_history['openai'] = []

    def _adjust_provider_weights(self) -> None:
        """动态调整提供商权重"""
        # 计算所有有历史记录的提供商的准确率
        active_providers = [p for p in self.performance_history if self.performance_history[p]]
        if len(active_providers) < 2:
            return

        # 计算最近准确率（最多20次）
        accuracies = {}
        for provider in active_providers:
            recent_history = self.performance_history[provider][-20:]
            if recent_history:
                accuracies[provider] = np.mean(recent_history)

        if len(accuracies) < 2:
            return

        # 根据准确率调整权重
        total_accuracy = sum(accuracies.values())
        if total_accuracy > 0:
            for provider in accuracies:
                self.provider_weights[provider] = accuracies[provider] / total_accuracy

        # 记录权重调整
        weight_info = ", ".join([f"{p}={self.provider_weights[p]:.2f}" for p in self.provider_weights if p in accuracies])
        logger.info(f"动态权重调整: {weight_info}")

    def get_optimization_stats(self) -> Dict[str, Any]:
        """获取优化统计信息"""
        return {
            'provider_weights': self.provider_weights.copy(),
            'performance_history_lengths': {
                provider: len(history)
                for provider, history in self.performance_history.items()
            },
            'min_hold_threshold': self.min_hold_threshold,
            'signal_strength_thresholds': self.signal_strength_thresholds.copy()
        }