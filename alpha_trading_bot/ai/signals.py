"""
信号生成器 - 基于AI信号生成交易建议
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..core.base import BaseComponent, BaseConfig
from ..core.exceptions import AIProviderError

logger = logging.getLogger(__name__)

class SignalGeneratorConfig(BaseConfig):
    """信号生成器配置"""
    min_confidence_threshold: float = 0.3
    max_signal_age: int = 300  # 5分钟
    enable_signal_validation: bool = True
    enable_pattern_recognition: bool = True
    enable_sentiment_analysis: bool = True

class SignalGenerator(BaseComponent):
    """信号生成器"""

    def __init__(self, config: Optional[SignalGeneratorConfig] = None):
        super().__init__(config or SignalGeneratorConfig())
        self.signal_history: List[Dict[str, Any]] = []
        self.pattern_cache: Dict[str, Any] = {}

    async def initialize(self) -> bool:
        """初始化信号生成器"""
        logger.info("正在初始化信号生成器...")
        self._initialized = True
        return True

    async def cleanup(self) -> None:
        """清理资源"""
        pass

    async def generate_trading_signals(self, market_data: Dict[str, Any], ai_signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """生成交易信号"""
        try:
            signals = []

            # 1. 处理AI信号
            for ai_signal in ai_signals:
                if ai_signal.get('confidence', 0) >= self.config.min_confidence_threshold:
                    trading_signal = await self._convert_ai_signal(ai_signal, market_data)
                    if trading_signal:
                        signals.append(trading_signal)

            # 2. 生成技术指标信号
            if self.config.enable_pattern_recognition:
                pattern_signals = await self._generate_pattern_signals(market_data)
                signals.extend(pattern_signals)

            # 3. 生成情绪分析信号
            if self.config.enable_sentiment_analysis:
                sentiment_signals = await self._generate_sentiment_signals(market_data)
                signals.extend(sentiment_signals)

            # 4. 验证信号
            if self.config.enable_signal_validation:
                signals = await self._validate_signals(signals, market_data)

            # 5. 记录信号历史
            self._record_signals(signals)

            logger.info(f"生成了 {len(signals)} 个交易信号")
            return signals

        except Exception as e:
            logger.error(f"生成交易信号失败: {e}")
            return []

    async def _convert_ai_signal(self, ai_signal: Dict[str, Any], market_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """转换AI信号为交易信号"""
        try:
            signal_type = ai_signal.get('signal', 'HOLD')
            confidence = ai_signal.get('confidence', 0.5)
            reason = ai_signal.get('reason', 'AI分析')
            provider = ai_signal.get('provider', 'unknown')

            # 生成交易信号
            if signal_type in ['BUY', 'SELL']:
                return {
                    'type': signal_type.lower(),
                    'confidence': confidence,
                    'reason': f"{provider}: {reason}",
                    'source': 'ai',
                    'provider': provider,
                    'timestamp': datetime.now(),
                    'market_data': market_data,
                    'ai_signal': ai_signal,
                    'priority': self._calculate_signal_priority(ai_signal)
                }
            elif signal_type == 'HOLD':
                return {
                    'type': 'hold',
                    'confidence': confidence,
                    'reason': f"{provider}: {reason}",
                    'source': 'ai',
                    'provider': provider,
                    'timestamp': datetime.now(),
                    'market_data': market_data,
                    'ai_signal': ai_signal,
                    'priority': self._calculate_signal_priority(ai_signal)
                }

            return None

        except Exception as e:
            logger.error(f"转换AI信号失败: {e}")
            return None

    async def _generate_pattern_signals(self, market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """生成模式识别信号"""
        try:
            signals = []
            price = market_data.get('price', 0)
            high = market_data.get('high', price)
            low = market_data.get('low', price)
            volume = market_data.get('volume', 0)

            # 简单的价格模式识别
            if price > 0 and high > low:
                price_position = (price - low) / (high - low)

                # 超买信号
                if price_position > 0.85:
                    signals.append({
                        'type': 'sell',
                        'confidence': 0.6,
                        'reason': '价格处于超买区域',
                        'source': 'pattern',
                        'pattern': 'overbought',
                        'timestamp': datetime.now(),
                        'priority': 2
                    })

                # 超卖信号
                elif price_position < 0.15:
                    signals.append({
                        'type': 'buy',
                        'confidence': 0.6,
                        'reason': '价格处于超卖区域',
                        'source': 'pattern',
                        'pattern': 'oversold',
                        'timestamp': datetime.now(),
                        'priority': 2
                    })

                # 成交量异常
                if volume > 0:
                    avg_volume = self._get_average_volume()
                    if volume > avg_volume * 2:
                        signals.append({
                            'type': 'hold',
                            'confidence': 0.7,
                            'reason': '成交量异常放大',
                            'source': 'pattern',
                            'pattern': 'volume_spike',
                            'timestamp': datetime.now(),
                            'priority': 1
                        })

            return signals

        except Exception as e:
            logger.error(f"生成模式信号失败: {e}")
            return []

    async def _generate_sentiment_signals(self, market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """生成情绪分析信号"""
        try:
            signals = []

            # 基于价格变化的简单情绪分析
            current_price = market_data.get('price', 0)
            open_price = market_data.get('open', current_price)

            if current_price > 0 and open_price > 0:
                price_change = (current_price - open_price) / open_price

                # 强势上涨
                if price_change > 0.03:
                    signals.append({
                        'type': 'buy',
                        'confidence': 0.65,
                        'reason': '市场情绪积极，价格上涨超过3%',
                        'source': 'sentiment',
                        'sentiment': 'bullish',
                        'timestamp': datetime.now(),
                        'priority': 3
                    })

                # 强势下跌
                elif price_change < -0.03:
                    signals.append({
                        'type': 'sell',
                        'confidence': 0.65,
                        'reason': '市场情绪消极，价格下跌超过3%',
                        'source': 'sentiment',
                        'sentiment': 'bearish',
                        'timestamp': datetime.now(),
                        'priority': 3
                    })

            return signals

        except Exception as e:
            logger.error(f"生成情绪信号失败: {e}")
            return []

    async def _validate_signals(self, signals: List[Dict[str, Any]], market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """验证信号"""
        validated_signals = []

        for signal in signals:
            try:
                # 检查信号年龄
                if self._is_signal_stale(signal):
                    continue

                # 检查信号完整性
                if not self._is_signal_valid(signal):
                    continue

                # 检查市场条件是否仍然适用
                if await self._check_market_conditions(signal, market_data):
                    validated_signals.append(signal)

            except Exception as e:
                logger.error(f"验证信号失败: {e}")
                continue

        return validated_signals

    def _calculate_signal_priority(self, ai_signal: Dict[str, Any]) -> int:
        """计算信号优先级"""
        confidence = ai_signal.get('confidence', 0.5)
        provider = ai_signal.get('provider', 'unknown')

        # 基础优先级（置信度越高，优先级越高）
        base_priority = int(confidence * 10)

        # 提供商加成
        provider_bonus = {
            'kimi': 2,
            'deepseek': 2,
            'qwen': 2,
            'openai': 1,
            'fallback': 0
        }

        bonus = provider_bonus.get(provider, 0)
        return base_priority + bonus

    def _is_signal_stale(self, signal: Dict[str, Any]) -> bool:
        """检查信号是否过期"""
        try:
            timestamp = signal.get('timestamp')
            if not timestamp:
                return True

            if isinstance(timestamp, datetime):
                age = (datetime.now() - timestamp).total_seconds()
            else:
                # 假设是ISO格式字符串
                signal_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                age = (datetime.now() - signal_time).total_seconds()

            return age > self.config.max_signal_age

        except Exception:
            return True

    def _is_signal_valid(self, signal: Dict[str, Any]) -> bool:
        """检查信号是否有效"""
        required_fields = ['type', 'confidence', 'reason', 'source']
        return all(field in signal for field in required_fields)

    async def _check_market_conditions(self, signal: Dict[str, Any], market_data: Dict[str, Any]) -> bool:
        """检查市场条件"""
        try:
            # 简单的价格验证
            current_price = market_data.get('price', 0)
            if current_price == 0:
                return False

            # 可以添加更复杂的市场条件检查
            return True

        except Exception:
            return False

    def _record_signals(self, signals: List[Dict[str, Any]]) -> None:
        """记录信号历史"""
        self.signal_history.extend(signals)

        # 限制历史记录长度
        max_history = 1000
        if len(self.signal_history) > max_history:
            self.signal_history = self.signal_history[-max_history//2:]

    def _get_average_volume(self) -> float:
        """获取平均成交量（简化实现）"""
        # 这里应该实现真实的平均成交量计算
        return 1000.0

    def get_signal_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取信号历史"""
        return self.signal_history[-limit:]

    def get_signal_stats(self) -> Dict[str, Any]:
        """获取信号统计"""
        total_signals = len(self.signal_history)
        if total_signals == 0:
            return {
                'total_signals': 0,
                'buy_signals': 0,
                'sell_signals': 0,
                'hold_signals': 0,
                'avg_confidence': 0.0
            }

        buy_signals = len([s for s in self.signal_history if s.get('type') == 'buy'])
        sell_signals = len([s for s in self.signal_history if s.get('type') == 'sell'])
        hold_signals = len([s for s in self.signal_history if s.get('type') == 'hold'])

        avg_confidence = sum(s.get('confidence', 0) for s in self.signal_history) / total_signals

        return {
            'total_signals': total_signals,
            'buy_signals': buy_signals,
            'sell_signals': sell_signals,
            'hold_signals': hold_signals,
            'avg_confidence': avg_confidence
        }

    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        base_status = super().get_status()
        base_status.update({
            'signal_history_size': len(self.signal_history),
            'signal_stats': self.get_signal_stats()
        })
        return base_status

# 创建信号生成器的工厂函数
async def create_signal_generator() -> SignalGenerator:
    """创建信号生成器实例"""
    from ..config import load_config
    config = load_config()

    sg_config = SignalGeneratorConfig(
        name="AlphaSignalGenerator",
        min_confidence_threshold=config.ai.min_confidence_threshold,
        enable_signal_validation=True,
        enable_pattern_recognition=True,
        enable_sentiment_analysis=True
    )

    generator = SignalGenerator(sg_config)
    await generator.initialize()
    return generator

# 向后兼容的函数
async def generate_enhanced_fallback_signal(market_data: Dict[str, Any], signal_history=None) -> Optional[Dict[str, Any]]:
    """生成增强的回退信号（向后兼容）"""
    try:
        generator = SignalGenerator()
        await generator.initialize()

        # 生成回退信号
        signals = await generator._generate_pattern_signals(market_data)

        if signals:
            return signals[0]

        # 如果没有模式信号，生成基础回退信号
        return {
            'signal': 'HOLD',
            'confidence': 0.5,
            'reason': '回退信号生成器',
            'timestamp': datetime.now().isoformat(),
            'provider': 'fallback'
        }

    except Exception as e:
        logger.error(f"生成增强回退信号失败: {e}")
        return {
            'signal': 'HOLD',
            'confidence': 0.3,
            'reason': f'回退信号生成失败: {str(e)}',
            'timestamp': datetime.now().isoformat(),
            'provider': 'fallback'
        }