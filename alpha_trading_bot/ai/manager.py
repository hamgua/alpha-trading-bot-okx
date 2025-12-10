"""
AI管理器 - 管理多个AI提供商的信号生成
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..core.base import BaseComponent, BaseConfig
from ..core.exceptions import AIProviderError
from .client import AIClient
from .fusion import AIFusion
from .signals import SignalGenerator
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class AIManagerConfig(BaseConfig):
    """AI管理器配置"""
    use_multi_ai: bool = False
    primary_provider: str = "kimi"
    fallback_enabled: bool = True
    cache_duration: int = 900
    min_confidence: float = 0.3
    fusion_enabled: bool = True

class AIManager(BaseComponent):
    """AI管理器"""

    def __init__(self, config: Optional[AIManagerConfig] = None):
        super().__init__(config or AIManagerConfig())
        self.ai_client = AIClient()
        self.ai_fusion = AIFusion()
        self.signal_generator = SignalGenerator()
        self.cache: Dict[str, Any] = {}
        self.providers: List[str] = []

    async def initialize(self) -> bool:
        """初始化AI管理器"""
        try:
            logger.info("正在初始化AI管理器...")

            # 初始化AI客户端
            await self.ai_client.initialize()

            # 获取可用的AI提供商
            from ..config import load_config
            config = load_config()
            self.providers = list(config.ai.models.keys())

            if not self.providers:
                logger.warning("未配置任何AI提供商，将使用回退模式")
                self.providers = ["fallback"]

            # 初始化信号生成器
            await self.signal_generator.initialize()

            self._initialized = True
            logger.info(f"AI管理器初始化成功，可用提供商: {self.providers}")
            return True

        except Exception as e:
            logger.error(f"AI管理器初始化失败: {e}")
            return False

    async def cleanup(self) -> None:
        """清理资源"""
        await self.ai_client.cleanup()

    async def generate_signals(self, market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """生成AI交易信号"""
        try:
            # 检查缓存
            cache_key = self._generate_cache_key(market_data)
            if cache_key in self.cache:
                cached_result = self.cache[cache_key]
                if (datetime.now() - cached_result['timestamp']).seconds < self.config.cache_duration:
                    logger.info("使用缓存的AI信号")
                    return cached_result['signals']

            signals = []

            if self.config.use_multi_ai and len(self.providers) > 1:
                # 多AI模式
                signals = await self._generate_multi_ai_signals(market_data)
            else:
                # 单AI模式
                signal = await self._generate_single_ai_signal(market_data)
                if signal:
                    signals = [signal]

            # 缓存结果
            self.cache[cache_key] = {
                'signals': signals,
                'timestamp': datetime.now()
            }

            return signals

        except Exception as e:
            logger.error(f"生成AI信号失败: {e}")
            # 使用回退信号
            return await self._generate_fallback_signals(market_data)

    async def _generate_single_ai_signal(self, market_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """生成单个AI信号"""
        try:
            # 选择提供商
            provider = self.config.primary_provider
            if provider not in self.providers and self.providers:
                provider = self.providers[0]

            # 生成信号
            if provider == "fallback":
                signal = await self._generate_fallback_signal(market_data)
            else:
                signal = await self.ai_client.generate_signal(provider, market_data)

            return signal

        except Exception as e:
            logger.error(f"生成单AI信号失败: {e}")
            if self.config.fallback_enabled:
                return await self._generate_fallback_signal(market_data)
            return None

    async def _generate_multi_ai_signals(self, market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """生成多AI信号"""
        try:
            # 并行获取所有提供商的信号
            tasks = []
            for provider in self.providers:
                if provider == "fallback":
                    task = asyncio.create_task(self._generate_fallback_signal(market_data))
                else:
                    task = asyncio.create_task(self.ai_client.generate_signal(provider, market_data))
                tasks.append((provider, task))

            # 等待所有任务完成
            results = []
            for provider, task in tasks:
                try:
                    signal = await task
                    if signal and signal.get('confidence', 0) >= self.config.min_confidence:
                        signal['provider'] = provider
                        results.append(signal)
                except Exception as e:
                    logger.error(f"提供商 {provider} 信号生成失败: {e}")

            # 如果启用了融合，进行信号融合
            if self.config.fusion_enabled and len(results) > 1:
                fused_signal = await self.ai_fusion.fuse_signals(results)
                if fused_signal:
                    return [fused_signal]

            return results

        except Exception as e:
            logger.error(f"生成多AI信号失败: {e}")
            return await self._generate_fallback_signals(market_data)

    async def _generate_fallback_signals(self, market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """生成回退信号"""
        try:
            signal = await self._generate_fallback_signal(market_data)
            return [signal] if signal else []

        except Exception as e:
            logger.error(f"生成回退信号失败: {e}")
            return []

    async def _generate_fallback_signal(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """生成回退信号（基于简单规则）"""
        try:
            # 基于价格的简单策略
            current_price = market_data.get('price', 0)
            high = market_data.get('high', current_price)
            low = market_data.get('low', current_price)

            if current_price == 0:
                return {
                    'signal': 'HOLD',
                    'confidence': 0.5,
                    'reason': '价格数据无效',
                    'timestamp': datetime.now().isoformat(),
                    'provider': 'fallback'
                }

            # 计算价格位置（0-1）
            if high > low:
                price_position = (current_price - low) / (high - low)
            else:
                price_position = 0.5

            # 生成信号
            if price_position > 0.8:
                signal = 'SELL'
                confidence = 0.6
                reason = '价格接近当日高点'
            elif price_position < 0.2:
                signal = 'BUY'
                confidence = 0.6
                reason = '价格接近当日低点'
            else:
                signal = 'HOLD'
                confidence = 0.5
                reason = '价格处于中间区域'

            return {
                'signal': signal,
                'confidence': confidence,
                'reason': reason,
                'timestamp': datetime.now().isoformat(),
                'provider': 'fallback'
            }

        except Exception as e:
            logger.error(f"回退信号生成失败: {e}")
            return {
                'signal': 'HOLD',
                'confidence': 0.3,
                'reason': f'回退信号生成失败: {str(e)}',
                'timestamp': datetime.now().isoformat(),
                'provider': 'fallback'
            }

    def _generate_cache_key(self, market_data: Dict[str, Any]) -> str:
        """生成缓存键"""
        # 基于市场数据生成唯一键
        price = market_data.get('price', 0)
        volume = market_data.get('volume', 0)
        timestamp = market_data.get('timestamp', datetime.now())
        return f"ai_signal_{price}_{volume}_{timestamp}"

    def get_provider_status(self) -> Dict[str, Any]:
        """获取提供商状态"""
        return {
            'available_providers': self.providers,
            'primary_provider': self.config.primary_provider,
            'multi_ai_enabled': self.config.use_multi_ai,
            'fallback_enabled': self.config.fallback_enabled,
            'cache_size': len(self.cache)
        }

    def clear_cache(self) -> None:
        """清除缓存"""
        self.cache.clear()
        logger.info("AI信号缓存已清除")

    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        base_status = super().get_status()
        base_status.update({
            'providers': self.providers,
            'use_multi_ai': self.config.use_multi_ai,
            'cache_size': len(self.cache),
            'provider_status': self.get_provider_status()
        })
        return base_status

# 创建AI管理器的工厂函数
async def create_ai_manager() -> AIManager:
    """创建AI管理器实例"""
    from ..config import load_config
    config = load_config()

    ai_config = AIManagerConfig(
        name="AlphaAIManager",
        use_multi_ai=config.ai.use_multi_ai,
        primary_provider=config.ai.ai_provider,
        fallback_enabled=config.ai.fallback_enabled,
        cache_duration=config.ai.cache_duration,
        min_confidence=config.ai.min_confidence_threshold
    )

    manager = AIManager(ai_config)
    await manager.initialize()
    return manager