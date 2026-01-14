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
from .model_selector import model_selector, ModelSelector
from .dynamic_cache import DynamicCacheManager, cache_manager
from .cache_monitor import cache_monitor
from .signal_optimizer import SignalOptimizer
from .buy_signal_optimizer import BuySignalOptimizer
from .dynamic_signal_tier import dynamic_signal_tier
from .self_learning_optimizer import self_learning_optimizer
from .high_price_protection import high_price_protection, check_high_price_protection
from ..utils.price_calculator import PriceCalculator
from .signal_generator import AISignalGenerator
from .cache_manager import AICacheManager
from .fusion_engine import AIFusionEngine
from dataclasses import dataclass
from datetime import datetime

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
    enable_dynamic_model_selection: bool = True
    default_deepseek_model: str = "deepseek-chat"
    default_kimi_model: str = "moonshot-v1-32k"
    enable_dynamic_cache: bool = True  # 启用动态缓存
    enable_signal_optimization: bool = True  # 启用信号优化


class AIManager(BaseComponent):
    """AI管理器 - 重构后使用组件化架构"""

    def __init__(self, config: Optional[AIManagerConfig] = None):
        # 如果没有提供配置，创建默认配置
        if config is None:
            config = AIManagerConfig(name="AIManager")
        super().__init__(config)

        # 初始化核心组件
        self.ai_client = AIClient()

        # 重构后的专用组件
        self.signal_generator = AISignalGenerator(self.ai_client)
        self.cache_manager = AICacheManager(config)
        self.fusion_engine = AIFusionEngine()

        # 初始化动态缓存（修复 AttributeError）
        try:
            from .dynamic_cache import cache_manager

            self.dynamic_cache = cache_manager
            logger.info("✅ 动态缓存初始化成功")
        except Exception as e:
            logger.warning(f"动态缓存初始化失败: {e}，将使用传统缓存")
            self.dynamic_cache = None

        # 初始化传统缓存（修复 'cache' 属性错误）
        self.cache: Dict[str, Any] = {}
        logger.info("✅ 缓存系统初始化成功")

        # 初始化原有组件以保持兼容性
        self.ai_fusion = AIFusion()  # 修复ai_fusion属性错误
        self.cache: Dict[str, Any] = {}  # 传统缓存

        # 保留一些原有的引用以兼容性
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
                    logger.warning(
                        f"配置的融合提供商 {fusion_providers} 没有可用的API密钥，将使用回退模式"
                    )
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
                    logger.warning(
                        f"默认提供商 {default_provider} 未配置API密钥，将使用回退模式"
                    )
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

    async def generate_signals(
        self, market_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """生成AI交易信号"""
        try:
            # 🛡️ 高位保护检查 - 在信号生成前进行保护评估
            protection_summary = high_price_protection.get_protection_summary(
                market_data
            )
            logger.info(
                f"🛡️ 高位保护检查 - 价格位置: {protection_summary['price_position_pct']}, "
                f"级别: {protection_summary['price_level']}, "
                f"建议信心度: {protection_summary['required_confidence']}, "
                f"是否可买: {protection_summary['can_buy']}"
            )

            # 检查缓存 - 支持动态缓存和传统缓存
            if self.config.enable_dynamic_cache:
                # 使用动态缓存系统
                cache_key = self.dynamic_cache.generate_cache_key_v2(market_data)
                atr_percentage = market_data.get("atr_percentage", 0)

                # 🎯 综合缓存时长计算：ATR波动率 + 价格位置
                price_position = (
                    market_data.get("composite_price_position", 50.0) / 100.0
                )
                volatility_duration = self.dynamic_cache.get_dynamic_cache_duration(
                    atr_percentage
                )
                price_protection_duration = high_price_protection.get_cache_duration(
                    price_position
                )

                # 取两者较小值，确保高位时更频繁更新
                dynamic_duration = min(volatility_duration, price_protection_duration)

                logger.info(
                    f"🔄 使用动态缓存系统 - ATR: {atr_percentage:.2f}%, "
                    f"波动率缓存: {volatility_duration}秒, 高位保护缓存: {price_protection_duration}秒, "
                    f"综合缓存时间: {dynamic_duration}秒"
                )
            else:
                # 使用传统缓存系统
                cache_key = self._generate_cache_key(market_data)
                dynamic_duration = self.config.cache_duration

            # 检查缓存是否存在且未过期
            if cache_key in self.cache:
                cached_result = self.cache[cache_key]
                cache_duration = (
                    dynamic_duration
                    if self.config.enable_dynamic_cache
                    else self.config.cache_duration
                )

                if (
                    datetime.now() - cached_result["timestamp"]
                ).seconds < cache_duration:
                    logger.info("使用缓存的AI信号")
                    self.dynamic_cache.record_cache_hit()  # 记录缓存命中
                    cache_monitor.record_hit(cache_key, 0.0)  # 记录到性能监控器

                    # 检查是否应该使缓存失效（智能失效机制）
                    if self.config.enable_dynamic_cache:
                        should_invalidate, reason = (
                            self.dynamic_cache.should_invalidate_cache(
                                market_data, cached_result.get("market_snapshot", {})
                            )
                        )
                        if should_invalidate:
                            logger.info(f"🔄 智能缓存失效: {reason}")
                            del self.cache[cache_key]  # 删除失效缓存
                            self.dynamic_cache.record_cache_eviction()
                            cache_monitor.record_eviction(
                                cache_key, reason
                            )  # 记录失效到性能监控器
                        else:
                            # 如果有缓存的统计信息，直接使用它
                            if "success_count" in cached_result:
                                success_count = cached_result["success_count"]
                                fail_count = cached_result["fail_count"]
                                success_providers = cached_result["success_providers"]
                                total = success_count + fail_count
                                logger.info(
                                    f"📊 多AI信号获取统计: 成功={success_count}, 失败={fail_count}, 总计={total}"
                                )
                                logger.info(
                                    f"✅ 成功提供商: {success_providers if success_providers else '无'}"
                                )
                            # 返回信号并标记为缓存结果
                            signals = cached_result["signals"]
                            for signal in signals:
                                signal["_from_cache"] = (
                                    True  # 添加标记表示这是缓存的信号
                                )
                            return signals
                    else:
                        # 传统缓存逻辑
                        if "success_count" in cached_result:
                            success_count = cached_result["success_count"]
                            fail_count = cached_result["fail_count"]
                            success_providers = cached_result["success_providers"]
                            total = success_count + fail_count
                            logger.info(
                                f"📊 多AI信号获取统计: 成功={success_count}, 失败={fail_count}, 总计={total}"
                            )
                            logger.info(
                                f"✅ 成功提供商: {success_providers if success_providers else '无'}"
                            )
                        # 返回信号并标记为缓存结果
                        signals = cached_result["signals"]
                        for signal in signals:
                            signal["_from_cache"] = True  # 添加标记表示这是缓存的信号
                        return signals

            self.dynamic_cache.record_cache_miss()  # 记录缓存未命中
            cache_monitor.record_miss(cache_key)  # 记录到性能监控器

            # 记录当前AI决策模式
            from ..config import load_config

            config = load_config()
            ai_mode = "融合模式" if config.ai.use_multi_ai_fusion else "单一模式"
            logger.info(f"🤖 AI决策模式: {ai_mode} (提供商: {self.providers})")

            # 动态模型选择
            if self.config.enable_dynamic_model_selection:
                logger.info("🔍 正在基于市场条件选择最优模型...")
                optimal_models = model_selector.select_models(market_data)

                # 记录选择的模型（但不更新配置，因为模型名称是硬编码在客户端的）
                for provider, model in optimal_models.items():
                    if provider != "reason" and provider in self.providers:
                        logger.info(f"  {provider.upper()} 使用模型: {model}")

                # 显示成本估算
                estimated_cost = model_selector.get_cost_estimate(optimal_models)
                logger.info(f"  预估API成本: ${estimated_cost:.4f}/次")

            signals = []
            results = []
            success_count = 0
            fail_count = 0
            success_providers = []

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
                    results = [signal]
                    success_count = 1
                    success_providers = [provider]

            # 缓存结果 - 存储个体信号和最终信号
            cache_data = {
                "individual_signals": results,  # 保存个体提供商信号
                "signals": signals,  # 保存最终信号（可能包含融合信号）
                "success_count": success_count,
                "fail_count": fail_count,
                "success_providers": success_providers,
                "timestamp": datetime.now(),
            }

            # 如果使用动态缓存，保存市场快照用于智能失效检测
            if self.config.enable_dynamic_cache and hasattr(self, "market_snapshot"):
                cache_data["market_snapshot"] = self.market_snapshot

            self.cache[cache_key] = cache_data

            return signals

        except Exception as e:
            logger.error(f"生成AI信号失败: {e}")
            # 使用回退信号
            return await self._generate_fallback_signals(market_data)

    async def _generate_single_ai_signal(
        self, market_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
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
                action = signal.get("signal", signal.get("action", "UNKNOWN"))
                confidence = signal.get("confidence", 0)
                reason = signal.get("reason", "")

                # 添加信号理由到日志
                if reason:
                    logger.info(
                        f"✅ {provider.upper()} 成功: {action} (信心: {confidence:.2f}) - {reason}"
                    )
                else:
                    logger.info(
                        f"✅ {provider.upper()} 成功: {action} (信心: {confidence:.2f})"
                    )

                # 记录API调用成本到监控器
                estimated_cost = 0.001  # 估算每次API调用成本
                cache_monitor.record_api_call(provider, estimated_cost)
            else:
                logger.error(f"❌ {provider.upper()} 返回空信号")

            return signal

        except Exception as e:
            logger.error(f"生成单AI信号失败: {e}")
            if self.config.fallback_enabled:
                return await self._generate_fallback_signal(market_data)
            return None

    async def _generate_multi_ai_signals(
        self, market_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """生成多AI信号 - 添加趋势确认"""
        try:
            # 获取市场趋势信息
            trend_direction = market_data.get("trend_direction", "neutral")
            trend_strength = market_data.get("trend_strength", "normal")

            # 添加趋势过滤警告
            if trend_strength in ["strong", "extreme"]:
                if trend_direction == "down":
                    logger.warning(
                        f"🚨 检测到强势下跌趋势({trend_strength})，将严格过滤买入信号"
                    )
                elif trend_direction == "up":
                    logger.warning(
                        f"🚨 检测到强势上涨趋势({trend_strength})，将严格过滤卖出信号"
                    )

            # 🛡️ 优化：统一获取自学习优化参数，避免重复
            adaptive_params = None
            if (
                hasattr(self, "self_learning_optimizer")
                and self.self_learning_optimizer
            ):
                try:
                    # 在AI Manager层面统一获取优化参数
                    adaptive_params = (
                        await self.self_learning_optimizer.get_adaptive_parameters(
                            market_data
                        )
                    )
                    logger.debug("统一获取自学习优化参数成功")
                except Exception as e:
                    logger.warning(f"获取自学习优化参数失败: {e}")

            # 将优化参数添加到市场数据中，供所有AI提供商使用
            if adaptive_params:
                market_data = dict(market_data)  # 创建副本避免修改原始数据
                market_data["adaptive_params"] = adaptive_params

            # 并行获取所有提供商的信号
            tasks = []
            for provider in self.providers:
                if provider == "fallback":
                    task = asyncio.create_task(
                        self._generate_fallback_signal(market_data)
                    )
                else:
                    task = asyncio.create_task(
                        self.ai_client.generate_signal(provider, market_data)
                    )
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
                        confidence = signal.get("confidence", 0)

                        # 应用价格位置因子衰减
                        if confidence > 0:  # 只有有信心的信号才需要调整
                            scaled_signal = await self._apply_price_position_scaling(
                                signal, market_data
                            )
                            if scaled_signal:
                                signal = scaled_signal
                                confidence = signal.get("confidence", confidence)

                        # 动态置信度阈值调整 - 基于价格位置
                        dynamic_threshold = (
                            await self._calculate_dynamic_confidence_threshold(
                                market_data
                            )
                        )

                        if confidence >= dynamic_threshold:
                            # 强化AI信号一致性检查 - 如果分析文本包含谨慎/等待建议，降低置信度
                            analysis_text = (
                                signal.get("reason", "").lower()
                                + signal.get("analysis_text", "").lower()
                            )
                            # 保存原始原因用于日志输出
                            original_reason = signal.get("reason", "")

                            # 关键词列表 - 只保留明确的否定/等待信号
                            # 移除信号类型描述（保守买入、谨慎量能、弱趋势）
                            # 移除策略建议（等待回调、等待突破）
                            cautious_keywords = [
                                "建议等待",  # ✅ 明确建议等待
                                "继续观察",  # ✅ 明确建议等待
                                "避免买入",  # ✅ 明确禁止买入
                                "不宜买入",  # ✅ 明确禁止买入
                                "不宜追高",  # ✅ 明确否定追高
                                "风险显著",  # ✅ 明确风险警告
                                "缺乏支撑",  # ✅ 技术面否定
                                "缺乏动能",  # ✅ 技术面否定
                                "缺乏确认",  # ✅ 技术面否定
                                "缺乏突破",  # ✅ 技术面否定
                            ]

                            if any(
                                keyword in analysis_text
                                for keyword in cautious_keywords
                            ):
                                signal["confidence"] *= 0.5
                                if signal["confidence"] < 0.6:
                                    signal["signal"] = "HOLD"
                                    signal["reason"] = (
                                        f"系统对信号一致性优化后：AI分析建议等待，信号降级为观望。原始信号：{original_reason}"
                                    )

                            signal["provider"] = provider
                            results.append(signal)
                            success_count += 1
                            success_providers.append(provider)

                            # 记录详细的信号信息
                            action = signal.get(
                                "signal", signal.get("action", "UNKNOWN")
                            )
                            reason = signal.get("reason", "")
                            if reason:
                                logger.info(
                                    f"✅ {provider.upper()} 成功: {action} (信心: {confidence:.2f}) - {reason}"
                                )
                            else:
                                logger.info(
                                    f"✅ {provider.upper()} 成功: {action} (信心: {confidence:.2f})"
                                )

                            # 记录API调用成本到监控器
                            estimated_cost = 0.001  # 估算每次API调用成本
                            cache_monitor.record_api_call(provider, estimated_cost)
                        else:
                            logger.warning(
                                f"⚠️  {provider.upper()} 置信度不足: {confidence:.2f} < {self.config.min_confidence}"
                            )
                            fail_count += 1
                    else:
                        logger.error(f"❌ {provider.upper()} 返回空信号")
                        fail_count += 1

                except Exception as e:
                    logger.error(f"❌ {provider.upper()} 信号生成失败: {e}")
                    fail_count += 1

            # 记录统计信息 - 这是实际提供商的统计
            total = success_count + fail_count
            logger.info(
                f"📊 多AI信号获取统计: 成功={success_count}, 失败={fail_count}, 总计={total}"
            )
            logger.info(
                f"✅ 成功提供商: {success_providers if success_providers else '无'}"
            )

            # 保存市场快照到实例变量（用于智能失效检测）
            self.market_snapshot = {
                "price": market_data.get("price", 0),
                "volume": market_data.get("volume", 0),
                "atr": market_data.get("atr", 0),
                "atr_percentage": market_data.get("atr_percentage", 0),
                "technical_data": market_data.get("technical_data", {}),
            }

            # 如果启用了融合，进行信号融合
            # 只要有至少1个成功的信号，就进行融合（部分失败不影响融合决策）
            if self.config.fusion_enabled and len(results) >= 1:
                # 记录部分失败的情况
                if fail_count > 0:
                    logger.info(
                        f"⚠️  部分提供商失败: {fail_count}/{total}，使用{len(results)}个成功信号进行融合"
                    )

                # 在融合前优化信号
                if (
                    self.config.enable_signal_optimization
                    and hasattr(self, "signal_optimizer")
                    and self.signal_optimizer
                ):
                    logger.info("🔧 开始信号优化...")
                    optimized_results = await self._optimize_signals(
                        results, market_data
                    )
                    if optimized_results:
                        results = optimized_results
                        logger.info(f"✅ 信号优化完成，优化了 {len(results)} 个信号")

                # 专项优化BUY信号
                if hasattr(self, "buy_optimizer") and self.buy_optimizer:
                    logger.info("🎯 开始BUY信号专项优化...")
                    buy_optimized_results = self.buy_optimizer.optimize_buy_signals(
                        results, market_data
                    )
                    if buy_optimized_results:
                        # 比较优化前后的变化
                        buy_changes = self._compare_buy_changes(
                            results, buy_optimized_results
                        )
                        if buy_changes["changed_count"] > 0:
                            logger.info(
                                f"🎯 BUY信号优化: {buy_changes['changed_count']}个信号被优化"
                            )
                            if buy_changes["buy_to_hold_count"] > 0:
                                logger.info(
                                    f"🔄 {buy_changes['buy_to_hold_count']}个BUY转为HOLD"
                                )
                            if buy_changes["confidence_changes"] > 0:
                                logger.info(
                                    f"📊 {buy_changes['confidence_changes']}个信号信心度调整"
                                )
                        results = buy_optimized_results

                from ..config import load_config

                config = load_config()

                # 获取融合配置
                fusion_strategy = config.ai.ai_fusion_strategy
                fusion_threshold = config.ai.ai_fusion_threshold
                fusion_weights = config.ai.ai_fusion_weights

                logger.info(
                    f"🔧 开始信号融合 - 策略: {fusion_strategy}, 阈值: {fusion_threshold}"
                )
                if fusion_weights:
                    logger.info(f"⚖️  融合权重: {fusion_weights}")

                # 构建市场上下文信息用于趋势过滤
                market_context = {
                    "trend_direction": market_data.get("trend_direction", "neutral"),
                    "trend_strength": market_data.get("trend_strength", "normal"),
                    "adx": market_data.get("technical_data", {}).get("adx", 0),
                    "macd": market_data.get("technical_data", {}).get("macd", 0),
                    "price_position": market_data.get("composite_price_position", 50),
                }

                fused_signal = await self.ai_fusion.fuse_signals(
                    results,
                    strategy=fusion_strategy,
                    threshold=fusion_threshold,
                    weights=fusion_weights,
                    market_context=market_context,
                )
                if fused_signal:
                    action = fused_signal.get(
                        "signal", fused_signal.get("action", "UNKNOWN")
                    )
                    confidence = fused_signal.get("confidence", 0)
                    logger.info(f"🔮 融合结果: {action} (置信度: {confidence:.2f})")
                    return [fused_signal]
                else:
                    logger.warning("⚠️  信号融合失败，返回原始信号")

            return results

        except Exception as e:
            logger.error(f"生成多AI信号失败: {e}")
            return await self._generate_fallback_signals(market_data)

    async def _calculate_dynamic_confidence_threshold(
        self, market_data: Dict[str, Any]
    ) -> float:
        """计算动态置信度阈值 - 基于价格位置调整

        逻辑：
        - 价格位置越高，置信度阈值越低（更容易通过）
        - 价格位置越低，置信度阈值越高（更严格）
        - 在极高位时适当放宽，避免过度过滤信号
        """
        try:
            # 获取综合价格位置
            composite_position = market_data.get("composite_price_position", 50.0)

            # 确保composite_position是浮点数
            try:
                composite_position = float(composite_position)
                logger.debug(
                    f"calculate_dynamic_threshold: composite_position转换成功: {composite_position} (类型: {type(composite_position)})"
                )
            except (ValueError, TypeError) as e:
                logger.warning(
                    f"calculate_dynamic_threshold: composite_position类型错误: {composite_position} (类型: {type(composite_position)})，使用默认值50.0，错误: {e}"
                )
                composite_position = 50.0

            # 基础阈值
            base_threshold = self.config.min_confidence

            # 确保composite_position是float类型，避免类型比较错误
            try:
                composite_position = float(composite_position)
            except (ValueError, TypeError):
                logger.warning(
                    f"calculate_dynamic_threshold: 强制转换composite_position失败，使用默认值50.0"
                )
                composite_position = 50.0

            # 价格位置因子 - 高位时降低阈值
            if composite_position >= 85:  # 极高位
                # 极高位时适当放宽，避免过滤掉所有信号
                position_factor = 0.7
            elif composite_position >= 75:  # 高位
                position_factor = 0.8
            elif composite_position >= 65:  # 偏高
                position_factor = 0.9
            elif composite_position <= 15:  # 极低位
                # 极低位时保持严格，避免虚假信号
                position_factor = 1.0
            elif composite_position <= 25:  # 低位
                position_factor = 0.95
            elif composite_position <= 35:  # 偏低
                position_factor = 0.9
            else:  # 中性区域
                position_factor = 1.0

            # 计算动态阈值
            dynamic_threshold = base_threshold * position_factor

            # 确保阈值在合理范围内
            dynamic_threshold = max(0.15, min(0.5, dynamic_threshold))  # 15%-50%范围

            logger.debug(
                f"动态置信度阈值计算: 价格位置={composite_position:.1f}%, 基础阈值={base_threshold}, 动态阈值={dynamic_threshold:.2f}"
            )

            return dynamic_threshold

        except Exception as e:
            logger.error(f"计算动态置信度阈值失败: {e}")
            return self.config.min_confidence  # 回退到基础阈值

    async def _generate_fallback_signals(
        self, market_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """生成回退信号"""
        try:
            signal = await self._generate_fallback_signal(market_data)
            return [signal] if signal else []

        except Exception as e:
            logger.error(f"生成回退信号失败: {e}")
            return []

    async def _generate_fallback_signal(
        self, market_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """生成回退信号（基于简单规则）"""
        try:
            # 基于价格的简单策略
            current_price = market_data.get("price", 0)
            high = market_data.get("high", current_price)
            low = market_data.get("low", current_price)

            if current_price == 0:
                return {
                    "signal": "HOLD",
                    "confidence": 0.5,
                    "reason": "价格数据无效",
                    "timestamp": datetime.now().isoformat(),
                    "provider": "fallback",
                }

            # 计算价格位置（0-1）
            # 使用统一的价格位置计算器
            price_position_result = PriceCalculator.calculate_price_position(
                current_price=current_price, daily_high=high, daily_low=low
            )
            price_position = price_position_result.daily_position / 100  # 转换为0-1范围

            # 生成信号
            if price_position > 0.8:
                signal = "SELL"
                confidence = 0.6
                reason = "价格接近当日高点"
            elif price_position < 0.2:
                signal = "BUY"
                confidence = 0.6
                reason = "价格接近当日低点"
            else:
                signal = "HOLD"
                confidence = 0.5
                reason = "价格处于中间区域"

            return {
                "signal": signal,
                "confidence": confidence,
                "reason": reason,
                "timestamp": datetime.now().isoformat(),
                "provider": "fallback",
            }

        except Exception as e:
            logger.error(f"回退信号生成失败: {e}")
            return {
                "signal": "HOLD",
                "confidence": 0.3,
                "reason": f"回退信号生成失败: {str(e)}",
                "timestamp": datetime.now().isoformat(),
                "provider": "fallback",
            }

    def _compare_buy_changes(
        self, original_signals: List[Dict], optimized_signals: List[Dict]
    ) -> Dict[str, int]:
        """比较BUY信号优化前后的变化"""
        changed_count = 0
        buy_to_hold_count = 0
        confidence_changes = 0

        for orig, opt in zip(original_signals, optimized_signals):
            # 只统计BUY信号的变化
            if orig.get("signal", "HOLD").upper() == "BUY":
                # 检查信号是否改变
                if orig.get("signal") != opt.get("signal"):
                    changed_count += 1
                    # 统计BUY转HOLD
                    if opt.get("signal", "HOLD").upper() == "HOLD":
                        buy_to_hold_count += 1

                # 检查信心度是否改变
                orig_conf = orig.get("confidence", 0.5)
                opt_conf = opt.get("confidence", 0.5)
                if abs(orig_conf - opt_conf) > 0.01:  # 允许微小浮点误差
                    confidence_changes += 1

        return {
            "changed_count": changed_count,
            "buy_to_hold_count": buy_to_hold_count,
            "confidence_changes": confidence_changes,
        }

    def _generate_cache_key(self, market_data: Dict[str, Any]) -> str:
        """生成缓存键 - 基于价格区间而非精确值，提高缓存命中率"""
        # 获取关键数据
        price = market_data.get("price", 0)
        volume = market_data.get("volume", 0)

        # 使用动态缓存管理器的分桶策略（如果启用）
        if self.config.enable_dynamic_cache and hasattr(self, "dynamic_cache"):
            # 使用更细粒度的价格分桶
            price_bucket = self.dynamic_cache.calculate_price_bucket(
                price, bucket_size=50.0
            )
        else:
            # 将价格四舍五入到最近的100美元，减少缓存键数量
            price_bucket = round(float(price) / 100) * 100 if price > 0 else 0

        # 将成交量四舍五入到最近的合理单位
        if volume > 1000000:
            volume_bucket = round(volume / 100000) * 100000
        elif volume > 100000:
            volume_bucket = round(volume / 10000) * 10000
        else:
            volume_bucket = round(volume / 1000) * 1000

        # 当前时间的小时（不是精确时间），允许1小时内的缓存复用
        current_hour = datetime.now().hour

        # 获取趋势信息用于缓存键
        trend_direction = market_data.get("trend_direction", "neutral")
        trend_strength = market_data.get("trend_strength", "normal")

        # 生成缓存键 - 添加趋势信息确保一致性
        cache_key = f"ai_signal_v2_{price_bucket}_{volume_bucket}_{current_hour}_{trend_direction}_{trend_strength}"

        logger.debug(
            f"生成缓存键: {cache_key} (价格桶: {price_bucket}, 成交量桶: {volume_bucket}, 小时: {current_hour}, 趋势: {trend_direction}_{trend_strength})"
        )
        return cache_key

    def get_provider_status(self) -> Dict[str, Any]:
        """获取提供商状态"""
        # 获取缓存监控统计
        cache_stats = cache_monitor.get_cache_stats()
        dynamic_cache_stats = (
            self.dynamic_cache.get_cache_stats()
            if hasattr(self, "dynamic_cache")
            else {}
        )

        return {
            "available_providers": self.providers,
            "primary_provider": self.config.primary_provider,
            "multi_ai_enabled": self.config.use_multi_ai,
            "fallback_enabled": self.config.fallback_enabled,
            "cache_size": len(self.cache),
            "dynamic_cache_enabled": self.config.enable_dynamic_cache,
            "cache_hit_rate": cache_stats.get("hit_rate", 0),
            "dynamic_cache_stats": dynamic_cache_stats,
        }

    def clear_cache(self) -> None:
        """清除缓存"""
        self.cache.clear()
        logger.info("AI信号缓存已清除")

    def get_cache_report(self) -> Dict[str, Any]:
        """获取缓存性能报告"""
        return cache_monitor.generate_report()

    def save_cache_report(self, filename: Optional[str] = None) -> str:
        """保存缓存性能报告"""
        return cache_monitor.save_report(filename)

    async def _optimize_signals(
        self, signals: List[Dict[str, Any]], market_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """优化AI信号"""
        try:
            # 使用信号优化器优化信号
            optimized_signals = self.signal_optimizer.optimize_signals(
                signals, market_data
            )

            # 记录优化统计
            optimization_stats = self.signal_optimizer.get_optimization_stats()
            logger.info(
                f"📊 信号优化器统计信息（仅用于显示，不影响融合权重）: {optimization_stats}"
            )

            return optimized_signals
        except Exception as e:
            logger.error(f"信号优化失败: {e}")
            return signals  # 如果优化失败，返回原始信号

    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        base_status = super().get_status()

        # 获取当前模型配置
        current_models = {}
        # 预定义的模型映射
        provider_models = {
            "kimi": "moonshot-v1-32k",
            "deepseek": "deepseek-chat",
            "qwen": "qwen-turbo",
            "openai": "gpt-3.5-turbo",
        }

        for provider in self.providers:
            if provider in provider_models:
                current_models[provider] = provider_models[provider]
            else:
                current_models[provider] = "unknown"

        base_status.update(
            {
                "providers": self.providers,
                "use_multi_ai": self.config.use_multi_ai,
                "cache_size": len(self.cache),
                "provider_status": self.get_provider_status(),
                "dynamic_model_selection": self.config.enable_dynamic_model_selection,
                "current_models": current_models,
                "model_selection_stats": model_selector.get_selection_stats(),
            }
        )
        return base_status

    async def _apply_price_position_scaling(
        self, signal: Dict[str, Any], market_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """应用价格位置因子缩放 - 集成自学习优化器

        Args:
            signal: AI生成的信号
            market_data: 市场数据

        Returns:
            缩放后的信号，如果信号被过滤则返回None
        """
        try:
            from .price_position_scaler import PricePositionScaler
            from ..strategies.low_price_strategy import LowPriceStrategy

            # 获取当前市场条件用于自学习优化
            from .self_learning_optimizer import MarketCondition

            current_market = MarketCondition(
                trend_strength=market_data.get("trend_strength", 0.0),
                volatility=market_data.get("volatility", 0.0),
                volume_ratio=market_data.get("volume_ratio", 1.0),
                price_position=market_data.get("composite_price_position", 50.0),
                market_state=self._determine_market_state(market_data),
            )

            # 获取自学习优化的参数
            optimal_params = self_learning_optimizer.get_optimal_parameters(
                current_market
            )

            # 应用优化参数到价格位置缩放器
            if optimal_params:
                logger.info(f"🧠 应用自学习优化参数: {optimal_params}")
                # 这里可以动态调整缩放器的参数

            # 获取综合价格位置
            composite_position = market_data.get("composite_price_position", 50.0)

            # 确保composite_position是浮点数
            try:
                composite_position = float(composite_position)
                logger.debug(
                    f"_apply_price_position_scaling: composite_position转换成功: {composite_position} (类型: {type(composite_position)})"
                )
            except (ValueError, TypeError) as e:
                logger.warning(
                    f"_apply_price_position_scaling: composite_position类型错误: {composite_position} (类型: {type(composite_position)})，使用默认值50.0，错误: {e}"
                )
                composite_position = 50.0

            # 首先应用低价格位置策略（如果适用）- 添加趋势过滤
            trend_direction = market_data.get("trend_direction", "neutral")
            trend_strength = market_data.get("trend_strength", "normal")

            if composite_position < 35 and not (
                trend_direction == "down" and trend_strength in ["strong", "extreme"]
            ):
                # 只在非强势下跌趋势中应用低价格策略
                low_price_strategy = LowPriceStrategy()
                enhanced_signal = low_price_strategy.enhance_signal_for_low_price(
                    signal, market_data
                )
                signal = enhanced_signal
            elif (
                composite_position < 35
                and trend_direction == "down"
                and trend_strength in ["strong", "extreme"]
            ):
                # 强势下跌趋势中，即使价格位置低也降低信号强度
                logger.warning(
                    f"🚨 强势下跌趋势中，低价格位置信号被抑制 (位置: {composite_position:.1f}%)"
                )
                signal["confidence"] = signal.get("confidence", 0.5) * 0.7  # 降低30%

            # 创建缩放器
            scaler = PricePositionScaler()

            # 获取趋势强度用于动态阈值
            trend_strength = market_data.get("trend_strength", "normal")
            trend_direction = market_data.get("trend_direction", "neutral")

            # 将字符串趋势强度转换为数值进行评估
            trend_strength_numeric = {"normal": 0.3, "strong": 0.6, "extreme": 0.9}.get(
                trend_strength, 0.3
            )

            # 添加强势下跌趋势强制过滤 - 关键修复
            if trend_strength_numeric < -0.3 and trend_direction == "down":
                logger.warning(
                    f"🚨 检测到强势下跌趋势(强度:{trend_strength}, 数值:{trend_strength_numeric:.2f})，强制过滤买入信号"
                )
                if signal.get("signal") == "BUY":
                    # 强制将买入信号降级为HOLD
                    signal["signal"] = "HOLD"
                    signal["reason"] = (
                        f"🚨 强势下跌趋势中禁止买入 - {signal.get('reason', '')}"
                    )
                    signal["confidence"] = min(
                        signal.get("confidence", 0.5), 0.4
                    )  # 降低置信度
                    logger.error(f"🚫 买入信号被强制过滤：强势下跌趋势中禁止买入")
                    return signal  # 直接返回，跳过后续的价格位置增强

            # 检查是否突破历史高点
            current_price = market_data.get("current_price", 0)
            high_24h = market_data.get("high_24h", 0)
            volume_ratio = market_data.get("volume_ratio", 1.0)

            # 突破检测
            breakout_config = scaler.handle_breakout_scenario(
                current_price, high_24h, volume_ratio, trend_strength_numeric
            )

            # 如果使用突破模式，调整价格位置权重
            if breakout_config["is_breakout"]:
                logger.info(
                    f"🚀 检测到突破行情 - 突破强度: {breakout_config.get('breakout_strength', 0):.2f}"
                )
                # 临时降低价格位置的影响权重
                original_composite_position = composite_position
                composite_position = (
                    composite_position * breakout_config["signal_multiplier"]
                )
                composite_position = min(100.0, max(0.0, composite_position))
                logger.info(
                    f"📍 价格位置调整: {original_composite_position:.1f}% → {composite_position:.1f}%"
                )

            # 获取详细分析（传入趋势强度）
            analysis = scaler.get_detailed_analysis(
                composite_position, trend_strength_numeric
            )

            # 如果突破，更新分析中的级别
            if breakout_config["is_breakout"]:
                analysis["breakout_mode"] = True
                analysis["breakout_config"] = breakout_config

            # 记录价格位置分析
            logger.info(
                f"📍 价格位置分析 - 综合位置: {composite_position:.1f}%, 级别: {analysis['level']}"
            )
            if analysis.get("breakout_mode"):
                logger.info(f"🚀 突破模式激活 - 价格位置权重降低")
            logger.info(f"📍 操作建议: {analysis['recommendation']}")

            # 严格趋势确认机制 - 在所有处理之前执行
            trend_direction = market_data.get("trend_direction", "neutral")
            trend_strength = market_data.get("trend_strength", "normal")
            technical_data = market_data.get("technical_data", {})

            # 将字符串趋势强度转换为数值
            trend_strength_numeric = {"normal": 0.3, "strong": 0.6, "extreme": 0.9}.get(
                trend_strength, 0.3
            )

            # 多重趋势确认
            trend_confirmed = True
            trend_reasons = []

            # 1. 市场机制趋势确认
            if trend_direction == "down" and trend_strength in ["strong", "extreme"]:
                trend_confirmed = False
                trend_reasons.append(f"强势下跌趋势({trend_strength})")

            # 2. ADX趋势强度确认
            adx = technical_data.get("adx", 0)
            if adx > 25 and trend_direction == "down":
                trend_confirmed = False
                trend_reasons.append(f"ADX强势({adx:.1f})")

            # 3. MACD趋势确认
            macd = technical_data.get("macd", 0)
            macd_signal = technical_data.get("macd_signal", 0)
            if macd < macd_signal and trend_direction == "down":
                trend_confirmed = False
                trend_reasons.append("MACD死叉")

            # 4. 价格动量确认
            price_change_24h = market_data.get("change_percent_24h", 0)
            if price_change_24h < -2 and signal.get("signal") == "BUY":
                trend_confirmed = False
                trend_reasons.append(f"24h跌幅过大({price_change_24h:.1f}%)")

            # 🚀 关键优化：强趋势时减少价格位置影响
            # 当趋势强度 > 0.6 且趋势方向为上涨时，减少价格位置的负面影响
            if (
                trend_strength_numeric >= 0.6
                and trend_direction == "up"
                and composite_position > 80
            ):
                # 强上涨趋势中，价格位置权重降低50%
                original_position = composite_position
                composite_position = min(
                    80.0,  # 最高按80%处理
                    composite_position * 0.5,
                )  # 降低价格位置的计算权重
                logger.info(
                    f"🚀 强趋势价格位置调整: {original_position:.1f}% → {composite_position:.1f}% (趋势强度: {trend_strength_numeric:.2f}, 趋势方向: {trend_direction})"
                )

            # 调整信号置信度（传入趋势强度）
            original_confidence = signal.get("confidence", 0.5)
            adjusted_confidence = scaler.calculate_signal_adjustment(
                original_confidence, composite_position, trend_strength_numeric
            )

            # 应用动态分层信号系统
            tier_name = dynamic_signal_tier.evaluate_signal_tier(signal, market_data)
            signal = dynamic_signal_tier.apply_tier_adjustments(
                signal, tier_name, market_data
            )

            # 记录分层信息
            logger.info(
                f"📊 信号分层: {tier_name} - {dynamic_signal_tier.SIGNAL_TIERS[tier_name]['description']}"
            )

            # 检查是否应覆盖价格位置限制
            if dynamic_signal_tier.should_override_price_position(
                tier_name, breakout_config.get("is_breakout", False)
            ):
                logger.info(f"🎯 分层信号覆盖价格位置限制 - 等级: {tier_name}")
                # 降低价格位置的影响
                adjusted_confidence = min(1.0, adjusted_confidence * 1.1)
                signal["confidence"] = adjusted_confidence
                signal["reason"] = f"🎯 分层信号覆盖 - {signal.get('reason', '')}"

            # 调整买入信号阈值
            if signal.get("signal") == "BUY":
                # 获取调整后的阈值
                adjusted_thresholds = scaler.get_buy_signal_threshold_adjustment(
                    composite_position
                )

                # 如果置信度低于调整后的阈值，降级信号
                if adjusted_confidence < adjusted_thresholds["weak_buy"]:
                    # 降级为HOLD
                    signal["signal"] = "HOLD"
                    signal["reason"] = (
                        f"{signal.get('reason', '')} [价格位置过高({composite_position:.1f}%), 降级为观望]"
                    )
                    adjusted_confidence = min(adjusted_confidence, 0.5)
                elif (
                    adjusted_confidence < adjusted_thresholds["strong_buy"]
                    and original_confidence >= 0.8
                ):
                    # 从强买降级为弱买
                    signal["reason"] = (
                        f"{signal.get('reason', '')} [价格位置偏高({composite_position:.1f}%), 降低买入强度]"
                    )

                # 严格趋势过滤 - 如果趋势未确认，强制降级
                if not trend_confirmed and trend_reasons:
                    logger.warning(f"🚨 严格趋势确认失败: {', '.join(trend_reasons)}")
                    signal["signal"] = "HOLD"
                    signal["reason"] = (
                        f"{signal.get('reason', '')} [趋势确认失败: {', '.join(trend_reasons)}]"
                    )
                    adjusted_confidence = min(adjusted_confidence, 0.4)
                    logger.warning(
                        f"买入信号已强制降级为HOLD - 综合价格位置: {composite_position:.1f}%"
                    )

                logger.info(
                    f"📍 买入信号调整 - 原始信心: {original_confidence:.2f} → 调整后: {adjusted_confidence:.2f}"
                )
                logger.info(f"📍 价格位置因子: {analysis['signal_multiplier']:.2f}x")
                if trend_reasons:
                    logger.info(f"📍 趋势确认问题: {', '.join(trend_reasons)}")

            # 更新信号
            signal["confidence"] = adjusted_confidence
            signal["price_position_analysis"] = analysis
            # 最终确保composite_position是float类型，避免最后的比较错误
            try:
                composite_position = float(composite_position)
            except (ValueError, TypeError):
                logger.warning(
                    f"_apply_price_position_scaling最终composite_position类型检查失败，使用默认值50.0"
                )
                composite_position = 50.0

            # 如果是高风险位置，添加额外警告
            if composite_position > 80:
                signal["reason"] = (
                    f"⚠️ 高风险位置({composite_position:.1f}%) - {signal.get('reason', '')}"
                )
            elif composite_position < 20:
                signal["reason"] = (
                    f"🔥 低位机会({composite_position:.1f}%) - {signal.get('reason', '')}"
                )

            # 记录信号历史（用于时间衰减）
            from datetime import datetime

            signal_id = (
                f"{signal.get('provider', 'unknown')}_{int(datetime.now().timestamp())}"
            )
            dynamic_signal_tier.record_signal(signal_id, signal, tier_name)

            # 记录交易数据用于自学习（如果是真实交易）
            from ..config import load_config

            config = load_config()
            if not config.trading.test_mode and signal.get("signal") == "BUY":
                self._record_trade_for_learning(signal, market_data)

            return signal

        except Exception as e:
            logger.error(f"价格位置缩放失败: {e}")
            return signal  # 如果缩放失败，返回原始信号

    def _determine_market_state(self, market_data: Dict[str, Any]) -> str:
        """确定市场状态"""
        trend_strength = market_data.get("trend_strength", 0.0)
        volatility = market_data.get("volatility", 0.0)

        if trend_strength > 0.5:
            return "bull"
        elif trend_strength < -0.3:
            return "bear"
        else:
            return "sideways"

    def _record_trade_for_learning(
        self, signal: Dict[str, Any], market_data: Dict[str, Any]
    ):
        """记录交易数据用于自学习"""
        try:
            # 构建交易数据
            trade_data = {
                "entry_price": market_data.get("current_price", 0),
                "exit_price": None,  # 将在平仓时更新
                "holding_period_hours": 0,  # 将在平仓时更新
                "market_conditions": {
                    "state": self._determine_market_state(market_data),
                    "trend_strength": market_data.get("trend_strength", 0.0),
                    "volatility": market_data.get("volatility", 0.0),
                    "volume_ratio": market_data.get("volume_ratio", 1.0),
                    "price_position": market_data.get("composite_price_position", 50.0),
                },
                "parameters_used": {
                    "signal_confidence": signal.get("confidence", 0.5),
                    "price_position": market_data.get("composite_price_position", 50.0),
                    "trend_strength": market_data.get("trend_strength", 0.0),
                },
                "signal_id": f"{signal.get('provider', 'unknown')}_{int(datetime.now().timestamp())}",
                "timestamp": datetime.now().isoformat(),
            }

            # 存储交易数据（这里只是记录入口，实际表现需要在平仓时更新）
            logger.info(
                f"🧠 记录交易数据用于自学习 - 信号ID: {trade_data['signal_id']}"
            )
            # 可以在这里存储到数据库或缓存中

        except Exception as e:
            logger.error(f"记录交易数据失败: {e}")

    async def update_learning_from_trades(self, trades_data: List[Dict[str, Any]]):
        """从交易数据更新学习"""
        try:
            if len(trades_data) >= 20:  # 至少20笔交易才更新
                self_learning_optimizer.continuous_learning_update(trades_data)
                logger.info(f"🧠 自学习优化器已更新 - 分析了{len(trades_data)}笔交易")

                # 导出优化报告
                report_path = f"data/optimization_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                self_learning_optimizer.export_optimization_report(report_path)

        except Exception as e:
            logger.error(f"更新自学习失败: {e}")


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
        fusion_enabled=config.ai.use_multi_ai_fusion,  # 融合模式与多AI模式保持一致
        enable_signal_optimization=config.ai.enable_signal_optimization,  # 信号优化配置
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
        """应用价格位置因子缩放

        Args:
            signal: AI生成的信号
            market_data: 市场数据

        Returns:
            缩放后的信号，如果信号被过滤则返回None
        """
        try:
            from .price_position_scaler import PricePositionScaler

            # 获取综合价格位置 - 优先从signal中获取，其次从market_data获取
            composite_position_signal = signal.get("composite_price_position")
            composite_position_market = market_data.get(
                "composite_price_position", 50.0
            )

            logger.warning(
                f"DEBUG: signal composite_position = {composite_position_signal} (类型: {type(composite_position_signal)})"
            )
            logger.warning(
                f"DEBUG: market_data composite_position = {composite_position_market} (类型: {type(composite_position_market)})"
            )

            composite_position = (
                composite_position_signal
                if composite_position_signal is not None
                else composite_position_market
            )

            # 确保composite_position是浮点数，避免类型比较错误
            try:
                composite_position = float(composite_position)
                logger.debug(
                    f"composite_position转换成功: {composite_position} (类型: {type(composite_position)})"
                )
            except (ValueError, TypeError) as e:
                logger.warning(
                    f"composite_position类型错误: {composite_position} (类型: {type(composite_position)})，使用默认值50.0，错误: {e}"
                )
                composite_position = 50.0

            # 创建缩放器
            scaler = PricePositionScaler()

            # 获取详细分析
            analysis = scaler.get_detailed_analysis(composite_position)

            # 记录价格位置分析
            logger.info(
                f"📍 价格位置分析 - 综合位置: {composite_position:.1f}%, 级别: {analysis['level']}"
            )
            logger.info(f"📍 操作建议: {analysis['recommendation']}")

            # 调整信号置信度
            original_confidence = signal.get("confidence", 0.5)
            adjusted_confidence = scaler.calculate_signal_adjustment(
                original_confidence, composite_position
            )

            # 调整买入信号阈值
            if signal.get("signal") == "BUY":
                # 获取调整后的阈值
                adjusted_thresholds = scaler.get_buy_signal_threshold_adjustment(
                    composite_position
                )

                # 如果置信度低于调整后的阈值，降级信号
                if adjusted_confidence < adjusted_thresholds["weak_buy"]:
                    # 降级为HOLD
                    signal["signal"] = "HOLD"
                    signal["reason"] = (
                        f"{signal.get('reason', '')} [价格位置过高({composite_position:.1f}%), 降级为观望]"
                    )
                    adjusted_confidence = min(adjusted_confidence, 0.5)
                elif (
                    adjusted_confidence < adjusted_thresholds["strong_buy"]
                    and original_confidence >= 0.8
                ):
                    # 从强买降级为弱买
                    signal["reason"] = (
                        f"{signal.get('reason', '')} [价格位置偏高({composite_position:.1f}%), 降低买入强度]"
                    )

                # 严格趋势过滤 - 如果趋势未确认，强制降级
                if not trend_confirmed and trend_reasons:
                    logger.warning(f"🚨 严格趋势确认失败: {', '.join(trend_reasons)}")
                    signal["signal"] = "HOLD"
                    signal["reason"] = (
                        f"{signal.get('reason', '')} [趋势确认失败: {', '.join(trend_reasons)}]"
                    )
                    adjusted_confidence = min(adjusted_confidence, 0.4)
                    logger.warning(
                        f"买入信号已强制降级为HOLD - 综合价格位置: {composite_position:.1f}%"
                    )

                logger.info(
                    f"📍 买入信号调整 - 原始信心: {original_confidence:.2f} → 调整后: {adjusted_confidence:.2f}"
                )
                logger.info(f"📍 价格位置因子: {analysis['signal_multiplier']:.2f}x")
                if trend_reasons:
                    logger.info(f"📍 趋势确认问题: {', '.join(trend_reasons)}")

            # 更新信号
            signal["confidence"] = adjusted_confidence
            signal["price_position_analysis"] = analysis

            # 最终确保composite_position是float类型，避免最后的比较错误
            try:
                composite_position = float(composite_position)
            except (ValueError, TypeError):
                logger.warning(
                    f"_apply_price_position_scaling最终composite_position类型检查失败，使用默认值50.0"
                )
                composite_position = 50.0

            # 如果是高风险位置，添加额外警告
            if composite_position > 80:
                signal["reason"] = (
                    f"⚠️ 高风险位置({composite_position:.1f}%) - {signal.get('reason', '')}"
                )
            elif composite_position < 20:
                signal["reason"] = (
                    f"🔥 低位机会({composite_position:.1f}%) - {signal.get('reason', '')}"
                )

            # 记录信号历史（用于时间衰减）
            from datetime import datetime

            signal_id = (
                f"{signal.get('provider', 'unknown')}_{int(datetime.now().timestamp())}"
            )
            dynamic_signal_tier.record_signal(signal_id, signal, tier_name)

            # 记录交易数据用于自学习（如果是真实交易）
            from ..config import load_config

            config = load_config()
            if not config.trading.test_mode and signal.get("signal") == "BUY":
                self._record_trade_for_learning(signal, market_data)

            return signal

        except Exception as e:
            logger.error(f"价格位置缩放失败: {e}")
            return signal  # 如果缩放失败，返回原始信号
