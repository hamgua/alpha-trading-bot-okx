"""
AI客户端 - 支持单AI/多AI融合

功能增强：
- 指数退避重试机制
- 信号分布统计监控
- 动态阈值可视化
- 备用提供商自动切换
- 信号优化集成 (AISignalIntegrator)
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional
from collections import defaultdict
from datetime import datetime

from .providers import get_provider_config
from .prompt_builder import build_prompt
from .response_parser import parse_response
from .integrator import AISignalIntegrator, IntegrationConfig

logger = logging.getLogger(__name__)


# 信号分布统计（全局计数器）- 用于监控信号多样性
_signal_distribution: Dict[str, Dict[str, int]] = defaultdict(
    lambda: {"buy": 0, "hold": 0, "sell": 0, "total": 0}
)
_signal_distribution_lock = asyncio.Lock()


async def log_signal_distribution(signal: str, source: str = "fusion") -> None:
    """记录信号分布（用于信号多样性监控）"""
    async with _signal_distribution_lock:
        _signal_distribution[source][signal] += 1
        _signal_distribution[source]["total"] += 1


async def get_signal_distribution() -> Dict[str, Dict[str, int]]:
    """获取信号分布统计"""
    async with _signal_distribution_lock:
        return dict(_signal_distribution)


async def log_signal_distribution_summary() -> None:
    """输出信号分布摘要日志"""
    async with _signal_distribution_lock:
        dist = dict(_signal_distribution)
        logger.info("[信号分布统计] 当前信号分布:")
        for source, counts in dist.items():
            total = counts["total"]
            if total > 0:
                buy_pct = counts["buy"] / total * 100
                hold_pct = counts["hold"] / total * 100
                sell_pct = counts["sell"] / total * 100
                logger.info(
                    f"  {source}: BUY={counts['buy']}({buy_pct:.1f}%), "
                    f"HOLD={counts['hold']}({hold_pct:.1f}%), "
                    f"SELL={counts['sell']}({sell_pct:.1f}%), "
                    f"总计={total}"
                )


class AIClient:
    """AI信号客户端 - 支持单AI/多AI融合"""

    # 重试配置
    MAX_RETRIES = 3
    BASE_DELAY = 1.0  # 基础延迟（秒）
    MAX_DELAY = 10.0  # 最大延迟（秒）
    BACKOFF_FACTOR = 2.0  # 退避因子

    def __init__(
        self,
        config: Optional["AIConfig"] = None,
        api_keys: Optional[Dict[str, str]] = None,
        integrator_mode: str = "standard",
    ):
        from alpha_trading_bot.config.models import AIConfig
        from .fusion.base import get_fusion_strategy

        if config is None:
            config = AIConfig.from_env()

        self.config = config
        self.api_keys = api_keys or {}
        self._get_fusion_strategy = get_fusion_strategy

        # 初始化信号集成器
        self.integrator = AISignalIntegrator(
            IntegrationConfig(
                enable_adaptive_buy=True,
                enable_signal_optimizer=True,
                enable_high_price_filter=True,
                enable_btc_detector=True,
            )
        )

    async def get_signal(self, market_data: Dict[str, Any]) -> str:
        """获取交易信号，返回: buy / hold / sell"""
        # 获取原始信号
        if self.config.mode == "single":
            original_signal, original_confidence = await self._get_single_signal(
                market_data
            )
        else:
            original_signal, original_confidence = await self._get_fusion_signal(
                market_data
            )

        # 使用集成器优化信号
        confidence_float = (
            float(original_confidence) / 100 if original_confidence else 0.50
        )
        result = self.integrator.process(
            market_data=market_data,
            original_signal=original_signal,
            original_confidence=confidence_float,
        )

        # 记录集成过程
        if result.adjustments_made:
            for adj in result.adjustments_made:
                logger.info(f"  [集成优化] {adj}")

        return result.final_signal

    async def _get_single_signal(self, market_data: Dict[str, Any]) -> tuple:
        """单AI模式，返回 (signal, confidence)"""
        provider = self.config.default_provider
        api_key = self.api_keys.get(provider, "")
        logger.info(f"[AI请求] 单AI模式, 提供商: {provider}")

        # 使用带重试的调用
        response = await self._call_ai_with_retry(provider, market_data, api_key)
        signal, confidence = parse_response(response)

        await log_signal_distribution(signal, source=provider)
        logger.info(f"[AI响应] 提供商={provider}, 信号={signal}, 置信度={confidence}%")
        return signal, confidence

    async def _get_fusion_signal(self, market_data: Dict[str, Any]) -> tuple:
        """多AI融合模式 - 并行调用多个AI并融合结果"""
        providers = self.config.fusion_providers
        logger.info(f"[AI请求] 多AI融合模式, 提供商列表: {providers}")

        # 并行调用（带重试机制）
        tasks = []
        for provider in providers:
            api_key = self.api_keys.get(provider, "")
            tasks.append(self._call_ai_with_retry(provider, market_data, api_key))

        logger.info(f"[AI请求] 开始并行调用 {len(tasks)} 个AI提供商...")
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        signals = []
        confidences: Dict[str, int] = {}
        failed_providers = []

        for provider, response in zip(providers, responses):
            if isinstance(response, Exception):
                logger.error(f"[AI错误] {provider} 调用失败: {response}")
                failed_providers.append(provider)
                continue

            try:
                signal, confidence = parse_response(response)
                logger.debug(f"[AI原始响应] {provider}: {response}")
                signals.append(
                    {"provider": provider, "signal": signal, "confidence": confidence}
                )
                if confidence is not None:
                    confidences[provider] = confidence
                conf_str = f"{confidence}%" if confidence is not None else "N/A"
                logger.info(f"[AI响应] {provider}: 信号={signal}, 置信度={conf_str}")
            except Exception as e:
                logger.error(f"[AI解析错误] {provider}: {e}")
                failed_providers.append(provider)

        # 记录失败的提供商
        if failed_providers:
            logger.warning(
                f"[AI融合] 以下提供商调用失败: {failed_providers}, 成功: {[p for p in providers if p not in failed_providers]}"
            )

        # 如果所有提供商都失败，尝试备用方案
        if not signals:
            logger.warning("[AI融合] 所有AI提供商都失败，尝试备用方案...")
            return await self._fallback_fusion(market_data)

        # 使用融合策略
        strategy = self._get_fusion_strategy(self.config.fusion_strategy)

        # 传递market_data以支持动态阈值计算
        fused_signal = strategy.fuse(
            signals,
            self.config.fusion_weights,
            self.config.fusion_threshold,
            confidences=confidences,
            market_data=market_data,
        )

        # 获取各信号得分
        weighted_scores = {"buy": 0, "hold": 0, "sell": 0}
        for s in signals:
            weight = self.config.fusion_weights.get(s["provider"], 1.0)
            weighted_scores[s["signal"]] += weight

        total = sum(weighted_scores.values())
        if total > 0:
            for sig in weighted_scores:
                weighted_scores[sig] = weighted_scores[sig] / total

        # 计算信号值
        max_score = max(weighted_scores.values())
        max_signal = max(weighted_scores, key=weighted_scores.get)

        # 信号有效性判断
        is_valid = max_score >= self.config.fusion_threshold

        logger.info(
            f"[AI融合] 结果: {max_signal} (信号值:{max_score:.2f}, 阈值:{self.config.fusion_threshold}, 有效:{is_valid})"
        )

        # 记录信号分布
        await log_signal_distribution(fused_signal.signal, source="fusion")

        # 返回信号和置信度
        return fused_signal.signal, fused_signal.confidence

    async def _fallback_fusion(self, market_data: Dict[str, Any]) -> tuple:
        """备用融合方案 - 当主提供商失败时使用"""
        fallback_providers = ["qwen", "openai", "deepseek"]
        available = []

        for provider in fallback_providers:
            if provider in self.api_keys:
                available.append(provider)

        if not available:
            logger.warning("[AI融合-备用] 无可用备用提供商，返回默认HOLD信号")
            return "hold", 0.40

        logger.info(f"[AI融合-备用] 使用备用提供商: {available}")

        for provider in available:
            try:
                api_key = self.api_keys.get(provider, "")
                response = await self._call_ai_with_retry(
                    provider, market_data, api_key
                )
                signal, confidence = parse_response(response)
                logger.info(
                    f"[AI融合-备用] {provider}: 信号={signal}, 置信度={confidence}%"
                )
                await log_signal_distribution(signal, source=f"fallback_{provider}")
                return signal, confidence if confidence else 0.40
            except Exception as e:
                logger.error(f"[AI融合-备用] {provider} 失败: {e}")
                continue

        return "hold", 0.40

    async def _call_ai_with_retry(
        self, provider: str, market_data: Dict[str, Any], api_key: str
    ) -> str:
        """带指数退避重试的AI调用"""
        last_error = None

        for attempt in range(self.MAX_RETRIES):
            try:
                return await self._call_ai(provider, market_data, api_key)
            except Exception as e:
                last_error = e

                # 计算延迟时间（指数退避）
                delay = min(
                    self.BASE_DELAY * (self.BACKOFF_FACTOR**attempt), self.MAX_DELAY
                )

                # 判断是否应该重试
                should_retry = self._should_retry_error(e, provider, attempt)

                if should_retry and attempt < self.MAX_RETRIES - 1:
                    logger.warning(
                        f"[AI重试] {provider} 第{attempt + 1}次失败: {e}, "
                        f"{delay:.1f}秒后重试..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"[AI重试] {provider} 最终失败 (尝试{attempt + 1}次): {e}"
                    )
                    break

        raise last_error

    def _should_retry_error(
        self, error: Exception, provider: str, attempt: int
    ) -> bool:
        """判断是否应该重试"""
        error_str = str(error).lower()

        # 始终重试的错误类型
        retry_keywords = [
            "connection",
            "timeout",
            "reset by peer",
            "network",
            "ssl",
            "certificate",
            "temporary",
            "too many requests",
            "429",
        ]

        for keyword in retry_keywords:
            if keyword in error_str:
                return True

        # Kimi API 特定优化 - 晚间时段更容易连接失败
        if provider == "kimi" and attempt < 2:
            logger.debug(f"[AI重试] Kimi API 第{attempt + 1}次尝试，支持重试")
            return True

        return False

    async def _call_ai(
        self, provider: str, market_data: Dict[str, Any], api_key: str
    ) -> str:
        """调用单个AI - 差异化"""
        import aiohttp

        # 获取提供商配置
        from .providers import get_provider_config

        config = get_provider_config(provider)

        # 根据 provider 生成差异化 prompt
        prompt = build_prompt(market_data, provider=provider)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        data = {
            "model": config["model"],
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 100,
        }

        # 根据提供商类型设置不同的超时时间
        timeout_config = self._get_timeout_config(provider)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    config["base_url"],
                    headers=headers,
                    json=data,
                    timeout=timeout_config,
                ) as response:
                    result = await response.json()
                    content = result["choices"][0]["message"]["content"]
                    return content.strip()

        except Exception as e:
            logger.error(f"AI[{provider}]调用失败: {e}")
            raise

    def _get_timeout_config(self, provider: str) -> "aiohttp.ClientTimeout":
        """获取提供商特定超时配置"""
        import aiohttp

        timeout_map = {
            "kimi": 90,  # Kimi 晚间慢，增加到 90 秒
            "deepseek": 60,
            "openai": 60,
            "qwen": 45,
        }

        timeout_seconds = timeout_map.get(provider, 60)
        return aiohttp.ClientTimeout(total=timeout_seconds)


async def get_signal(market_data: Dict[str, Any], mode: str = "single") -> str:
    """便捷函数"""
    client = AIClient()
    return await client.get_signal(market_data)
