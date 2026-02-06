"""
AI客户端 - 支持单AI/多AI融合
"""

import asyncio
import logging
from typing import Dict, Any, Optional

from .providers import get_provider_config
from .prompt_builder import build_prompt
from .response_parser import parse_response

logger = logging.getLogger(__name__)


class AIClient:
    """AI信号客户端 - 支持单AI/多AI融合"""

    def __init__(
        self,
        config: Optional["AIConfig"] = None,
        api_keys: Optional[Dict[str, str]] = None,
    ):
        from alpha_trading_bot.config.models import AIConfig
        from .fusion.base import get_fusion_strategy

        if config is None:
            config = AIConfig.from_env()

        self.config = config
        self.api_keys = api_keys or {}
        self._get_fusion_strategy = get_fusion_strategy

    async def get_signal(self, market_data: Dict[str, Any]) -> str:
        """
        获取交易信号
        返回: buy / hold / sell
        """
        if self.config.mode == "single":
            return await self._get_single_signal(market_data)
        else:
            return await self._get_fusion_signal(market_data)

    async def _get_single_signal(self, market_data: Dict[str, Any]) -> str:
        """单AI模式"""
        provider = self.config.default_provider
        api_key = self.api_keys.get(provider, "")
        logger.info(f"[AI请求] 单AI模式, 提供商: {provider}")
        response = await self._call_ai(provider, market_data, api_key)
        signal, confidence = parse_response(response)
        logger.info(f"[AI响应] 提供商={provider}, 信号={signal}, 置信度={confidence}%")
        return signal

    async def _get_fusion_signal(self, market_data: Dict[str, Any]) -> str:
        """多AI融合模式 - 并行调用多个AI并融合结果"""
        providers = self.config.fusion_providers
        logger.info(f"[AI请求] 多AI融合模式, 提供商列表: {providers}")

        tasks = []
        for provider in providers:
            api_key = self.api_keys.get(provider, "")
            tasks.append(self._call_ai(provider, market_data, api_key))

        logger.info(f"[AI请求] 开始并行调用 {len(tasks)} 个AI提供商...")
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        signals = []
        confidences: Dict[str, int] = {}
        for provider, response in zip(providers, responses):
            if isinstance(response, Exception):
                logger.error(f"[AI错误] {provider} 调用失败: {response}")
                continue
            signal, confidence = parse_response(response)
            logger.debug(f"[AI原始响应] {provider}: {response}")
            signals.append(
                {"provider": provider, "signal": signal, "confidence": confidence}
            )
            if confidence is not None:
                confidences[provider] = confidence
            conf_str = f"{confidence}%" if confidence is not None else "N/A"
            logger.info(f"[AI响应] {provider}: 信号={signal}, 置信度={conf_str}")

        if not signals:
            logger.warning("[AI融合] 所有AI提供商都失败，返回默认HOLD信号")
            return "hold"

        # 使用融合策略
        strategy_name = self.config.fusion_strategy
        threshold = self.config.fusion_threshold

        strategy = self._get_fusion_strategy(self.config.fusion_strategy)

        # 传递market_data以支持动态阈值计算
        fused_signal = strategy.fuse(
            signals,
            self.config.fusion_weights,
            self.config.fusion_threshold,
            confidences=confidences,
            market_data=market_data,  # 新增：支持动态阈值
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

        # 计算信号值（最大得分的信号作为最终信号）
        max_score = max(weighted_scores.values())
        max_signal = max(weighted_scores, key=weighted_scores.get)

        # 信号有效性判断
        is_valid = max_score >= threshold

        logger.info(
            f"[AI融合] 结果: {max_signal} (信号值:{max_score:.2f}, 阈值:{threshold}, 有效:{is_valid})"
        )

        # 返回字符串信号，而不是 FusionResult
        return fused_signal.signal

    async def _call_ai(
        self, provider: str, market_data: Dict[str, Any], api_key: str
    ) -> str:
        """调用单个AI"""
        import aiohttp

        config = get_provider_config(provider)
        prompt = build_prompt(market_data)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        data = {
            "model": config["model"],
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 100,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    config["base_url"],
                    headers=headers,
                    json=data,
                    timeout=60,
                ) as response:
                    result = await response.json()
                    content = result["choices"][0]["message"]["content"]
                    return content.strip()

        except Exception as e:
            logger.error(f"AI[{provider}]调用失败: {e}")
            raise


async def get_signal(market_data: Dict[str, Any], mode: str = "single") -> str:
    """便捷函数"""
    client = AIClient()
    return await client.get_signal(market_data)
