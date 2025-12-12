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
        # 如果没有提供配置，创建默认配置
        if config is None:
            config = AIManagerConfig(name="AIManager")
        super().__init__(config)
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

            # 获取配置
            from ..config import load_config
            config = load_config()

            # 根据AI模式选择提供商
            if config.ai.use_multi_ai_fusion:
                # 多AI融合模式 - 只使用配置的融合提供商
                available_providers = set(config.ai.models.keys())
                fusion_providers = set(config.ai.ai_fusion_providers)

                # 只保留同时有API密钥且在融合配置中的提供商
                self.providers = list(available_providers & fusion_providers)

                if not self.providers:
                    logger.warning(f"配置的融合提供商 {fusion_providers} 没有可用的API密钥，将使用回退模式")
                    self.providers = ["fallback"]
                else:
                    logger.info(f"AI融合模式已启用，使用提供商: {self.providers}")
            else:
                # 单一AI模式 - 只使用默认提供商
                default_provider = config.ai.ai_default_provider
                if default_provider in config.ai.models:
                    self.providers = [default_provider]
                    logger.info(f"单一AI模式，使用提供商: {default_provider}")
                else:
                    logger.warning(f"默认提供商 {default_provider} 未配置API密钥，将使用回退模式")
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
                    # 如果有缓存的统计信息，直接使用它
                    if 'success_count' in cached_result:
                        success_count = cached_result['success_count']
                        fail_count = cached_result['fail_count']
                        success_providers = cached_result['success_providers']
                        total = success_count + fail_count
                        logger.info(f"📊 多AI信号获取统计: 成功={success_count}, 失败={fail_count}, 总计={total}")
                        logger.info(f"✅ 成功提供商: {success_providers if success_providers else '无'}")
                    # 返回信号并标记为缓存结果
                    signals = cached_result['signals']
                    for signal in signals:
                        signal['_from_cache'] = True  # 添加标记表示这是缓存的信号
                    return signals

            # 记录当前AI决策模式
            from ..config import load_config
            config = load_config()
            ai_mode = "融合模式" if config.ai.use_multi_ai_fusion else "单一模式"
            logger.info(f"🤖 AI决策模式: {ai_mode} (提供商: {self.providers})")

            signals = []

            if self.config.use_multi_ai and len(self.providers) > 1:
                # 多AI模式
                logger.info(f"🚀 并行获取多AI信号: {self.providers}")
                signals = await self._generate_multi_ai_signals(market_data)
            else:
                # 单AI模式
                provider = self.providers[0] if self.providers else "fallback"
                logger.info(f"🎯 使用单一AI信号: {provider}")
                signal = await self._generate_single_ai_signal(market_data)
                if signal:
                    signals = [signal]

            # 缓存结果 - 存储个体信号和最终信号
            self.cache[cache_key] = {
                'individual_signals': results,  # 保存个体提供商信号
                'signals': signals,  # 保存最终信号（可能包含融合信号）
                'success_count': success_count,
                'fail_count': fail_count,
                'success_providers': success_providers,
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
            from ..config import load_config
            config = load_config()

            # 选择提供商 - 优先使用配置中的默认提供商
            provider = config.ai.ai_default_provider
            if provider not in self.providers and self.providers:
                provider = self.providers[0]

            # 生成信号
            if provider == "fallback":
                logger.info(f"🔄 使用回退信号策略")
                signal = await self._generate_fallback_signal(market_data)
            else:
                logger.info(f"📡 请求 {provider.upper()} 信号...")
                signal = await self.ai_client.generate_signal(provider, market_data)

            # 记录信号详情
            if signal:
                # AI提供商使用 'signal' 字段，不是 'action'
                action = signal.get('signal', signal.get('action', 'UNKNOWN'))
                confidence = signal.get('confidence', 0)
                logger.info(f"✅ {provider.upper()} 成功: {action} (信心: {confidence:.2f})")
            else:
                logger.error(f"❌ {provider.upper()} 返回空信号")

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

            # 等待所有任务完成并记录结果
            results = []
            success_count = 0
            fail_count = 0
            success_providers = []

            for provider, task in tasks:
                try:
                    signal = await task
                    if signal:
                        # 检查置信度阈值
                        confidence = signal.get('confidence', 0)
                        if confidence >= self.config.min_confidence:
                            signal['provider'] = provider
                            results.append(signal)
                            success_count += 1
                            success_providers.append(provider)

                            # 记录详细的信号信息
                            action = signal.get('signal', signal.get('action', 'UNKNOWN'))
                            logger.info(f"✅ {provider.upper()} 成功: {action} (信心: {confidence:.2f})")
                        else:
                            logger.warning(f"⚠️  {provider.upper()} 置信度不足: {confidence:.2f} < {self.config.min_confidence}")
                            fail_count += 1
                    else:
                        logger.error(f"❌ {provider.upper()} 返回空信号")
                        fail_count += 1

                except Exception as e:
                    logger.error(f"❌ {provider.upper()} 信号生成失败: {e}")
                    fail_count += 1

            # 记录统计信息 - 这是实际提供商的统计
            total = success_count + fail_count
            logger.info(f"📊 多AI信号获取统计: 成功={success_count}, 失败={fail_count}, 总计={total}")
            logger.info(f"✅ 成功提供商: {success_providers if success_providers else '无'}")

            # 如果启用了融合，进行信号融合
            # 只要有至少1个成功的信号，就进行融合（部分失败不影响融合决策）
            if self.config.fusion_enabled and len(results) >= 1:
                # 记录部分失败的情况
                if fail_count > 0:
                    logger.info(f"⚠️  部分提供商失败: {fail_count}/{total}，使用{len(results)}个成功信号进行融合")
                from ..config import load_config
                config = load_config()

                # 获取融合配置
                fusion_strategy = config.ai.ai_fusion_strategy
                fusion_threshold = config.ai.ai_fusion_threshold
                fusion_weights = config.ai.ai_fusion_weights

                logger.info(f"🔧 开始信号融合 - 策略: {fusion_strategy}, 阈值: {fusion_threshold}")
                if fusion_weights:
                    logger.info(f"⚖️  融合权重: {fusion_weights}")

                fused_signal = await self.ai_fusion.fuse_signals(
                    results,
                    strategy=fusion_strategy,
                    threshold=fusion_threshold,
                    weights=fusion_weights
                )
                if fused_signal:
                    action = fused_signal.get('signal', fused_signal.get('action', 'UNKNOWN'))
                    confidence = fused_signal.get('confidence', 0)
                    logger.info(f"🔮 融合结果: {action} (置信度: {confidence:.2f})")
                    return [fused_signal]
                else:
                    logger.warning("⚠️  信号融合失败，返回原始信号")

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

# 全局AI管理器实例
_ai_manager_instance: Optional[AIManager] = None

# 创建AI管理器的工厂函数
async def create_ai_manager() -> AIManager:
    """创建AI管理器实例"""
    global _ai_manager_instance

    from ..config import load_config
    config = load_config()

    ai_config = AIManagerConfig(
        name="AlphaAIManager",
        use_multi_ai=config.ai.use_multi_ai_fusion,  # 使用新的 fusion 模式判断
        primary_provider=config.ai.ai_default_provider,  # 使用新的默认提供商参数
        fallback_enabled=config.ai.fallback_enabled,
        cache_duration=config.ai.cache_duration,
        min_confidence=config.ai.min_confidence_threshold,
        fusion_enabled=config.ai.use_multi_ai_fusion  # 融合模式与多AI模式保持一致
    )

    _ai_manager_instance = AIManager(ai_config)
    await _ai_manager_instance.initialize()
    return _ai_manager_instance

async def get_ai_manager() -> AIManager:
    """获取全局AI管理器实例"""
    global _ai_manager_instance

    if _ai_manager_instance is None:
        raise RuntimeError("AI管理器尚未初始化，请先调用 create_ai_manager()")

    return _ai_manager_instance

async def cleanup_ai_manager() -> None:
    """清理全局AI管理器实例"""
    global _ai_manager_instance

    if _ai_manager_instance is not None:
        await _ai_manager_instance.cleanup()
        _ai_manager_instance = None