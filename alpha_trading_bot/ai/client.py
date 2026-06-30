"""
AI客户端 - 支持单AI/多AI融合

功能增强：
- 指数退避重试机制
- 信号分布统计监控
- 动态阈值可视化
- 备用提供商自动切换
- 信号优化集成 (AISignalIntegrator)
- 信号缓存机制
"""

import asyncio
import hashlib
import importlib
import logging
import re
import time
from typing import Any, Dict, Optional, Tuple
from collections import defaultdict

from alpha_trading_bot.config.models import AIConfig
from .providers import get_provider_config
from .prompt_builder import build_prompt
from .response_parser import parse_response
from .integrator import AISignalIntegrator
from .integrator_config import IntegrationConfig
from alpha_trading_bot.utils.observability import (
    record_fallback_invocation,
    record_gemini_request,
)

logger = logging.getLogger(__name__)


SENSITIVE_PATTERNS = [
    re.compile(r"(bearer\s+)[a-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"(api[_-]?key\s*[:=]\s*)[a-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"(google[_-]?api[_-]?key\s*[:=]\s*)[a-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"(gemini[_-]?api[_-]?key\s*[:=]\s*)[a-z0-9._\-]+", re.IGNORECASE),
]


def _redact_sensitive_text(text: str, max_length: int = 240) -> str:
    """对错误文本做脱敏并限制长度，避免日志泄露敏感信息。"""
    sanitized = text
    for pattern in SENSITIVE_PATTERNS:
        sanitized = pattern.sub(r"\1[REDACTED]", sanitized)
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length] + "..."
    return sanitized


# 信号分布统计（全局计数器）- 用于监控信号多样性
_signal_distribution: Dict[str, Dict[str, int]] = defaultdict(
    lambda: {"buy": 0, "hold": 0, "sell": 0, "short": 0, "total": 0}
)
_signal_distribution_lock = asyncio.Lock()


class SignalCache:
    """AI信号缓存"""

    def __init__(self, ttl_seconds: int = 900):
        self._cache: Dict[str, Tuple[str, float, float]] = {}
        self._ttl = ttl_seconds

    def _generate_key(self, market_data: Dict[str, Any]) -> str:
        """生成缓存键"""
        technical = market_data.get("technical", {})
        key_data = {
            "price": market_data.get("price", 0),
            "rsi": technical.get("rsi", 50),
            "trend": technical.get("trend_direction", ""),
            "trend_strength": round(float(technical.get("trend_strength", 0)), 2),
            "price_position": round(float(technical.get("price_position", 0.5)), 2),
            "macd_hist": round(float(technical.get("macd_hist", 0)), 4),
        }
        key_str = str(sorted(key_data.items()))
        return hashlib.sha256(key_str.encode()).hexdigest()

    def get(self, market_data: Dict[str, Any]) -> Optional[str]:
        """获取缓存的信号"""
        key = self._generate_key(market_data)
        if key in self._cache:
            entry = self._cache[key]
            signal, timestamp, confidence = entry[0], entry[1], entry[2]
            entry_ttl = entry[3] if len(entry) > 3 else self._ttl
            if time.time() - timestamp < entry_ttl:
                logger.info(f"[AI缓存] 命中缓存: {signal} (置信度: {confidence:.0%})")
                return signal
        return None

    def set(self, market_data: Dict[str, Any], signal: str, confidence: float) -> None:
        """设置缓存，HOLD信号使用更短的TTL以避免掩盖新交易机会"""
        key = self._generate_key(market_data)
        hold_ttl = 60  # HOLD信号缓存60秒，更快发现新交易机会（原120→60）
        entry_ttl = self._ttl if signal.upper() != "HOLD" else hold_ttl
        self._cache[key] = (signal, time.time(), confidence, entry_ttl)
        logger.debug(f"[AI缓存] 已缓存信号: {signal}, TTL={entry_ttl}s")

    def clear(self) -> None:
        """清除缓存"""
        self._cache.clear()
        logger.info("[AI缓存] 已清除")

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        valid_count = sum(
            1
            for _, entry in self._cache.items()
            if time.time() - entry[1] < (entry[3] if len(entry) > 3 else self._ttl)
        )
        return {
            "total_entries": len(self._cache),
            "valid_entries": valid_count,
            "ttl_seconds": self._ttl,
        }


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

    # 缓存配置
    DEFAULT_CACHE_TTL = 900  # 默认缓存时间：15分钟

    def __init__(
        self,
        config: Optional["AIConfig"] = None,
        api_keys: Optional[Dict[str, str]] = None,
        integrator_mode: str = "standard",
        cache_ttl: int = DEFAULT_CACHE_TTL,
        enable_cache: bool = True,
    ):
        from .fusion.base import get_fusion_strategy

        if config is None:
            config = AIConfig.from_env()

        self.config = config
        self.api_keys = api_keys or {}
        self._get_fusion_strategy = get_fusion_strategy

        # 初始化缓存
        self._enable_cache = enable_cache
        self._cache = SignalCache(ttl_seconds=cache_ttl) if enable_cache else None

        # 初始化信号集成器 - 平衡模式：保留风控但放宽限制
        self.integrator = AISignalIntegrator(
            IntegrationConfig(
                enable_adaptive_buy=True,
                enable_signal_optimizer=True,
                enable_high_price_filter=True,  # 开启但放宽阈值
                enable_btc_detector=True,  # 开启但放宽阈值
            )
        )

        self._metrics: Dict[str, int] = {
            "max_tokens_truncated": 0,
            "reasoning_fallback_hits": 0,
            "reasoning_fallback_misses": 0,
        }

    def _get_normalized_fusion_weights(self) -> Dict[str, float]:
        """返回融合提供商完整且归一化的权重。"""
        providers = self.config.fusion_providers or ["deepseek", "kimi"]
        configured = self.config.fusion_weights or {}

        candidate: Dict[str, float] = {}
        for provider in providers:
            value = configured.get(provider, 0.0)
            candidate[provider] = value if value > 0 else 0.0

        positive_total = sum(candidate.values())
        if positive_total <= 0:
            equal = 1.0 / len(providers)
            return {provider: equal for provider in providers}

        normalized = {
            provider: value / positive_total for provider, value in candidate.items()
        }
        return normalized

    def update_integrator_config(self, params: Dict[str, float]) -> None:
        """更新集成器配置（用于自适应参数调整）

        Args:
            params: 参数字典，包含 adaptive_buy_condition 和 signal_optimizer 参数
        """
        # 更新 AdaptiveBuyCondition 配置
        if self.integrator.adaptive_buy:
            adaptive_cfg = self.integrator.adaptive_buy.conditions

            if "oversold_rsi_max" in params:
                adaptive_cfg.oversold_rsi_max = params["oversold_rsi_max"]
            if "oversold_momentum_min" in params:
                adaptive_cfg.oversold_momentum_min = params["oversold_momentum_min"]
            if "oversold_trend_strength_min" in params:
                adaptive_cfg.oversold_trend_strength_min = params[
                    "oversold_trend_strength_min"
                ]
            if "oversold_bb_position_max" in params:
                adaptive_cfg.oversold_bb_position_max = params[
                    "oversold_bb_position_max"
                ]
            if "oversold_position_factor" in params:
                adaptive_cfg.oversold_position_factor = params[
                    "oversold_position_factor"
                ]
            if "support_price_position_max" in params:
                adaptive_cfg.support_price_position_max = params[
                    "support_price_position_max"
                ]
            if "support_position_factor" in params:
                adaptive_cfg.support_position_factor = params["support_position_factor"]

        # 更新 SignalOptimizer 配置
        if self.integrator.signal_optimizer:
            optimizer_cfg = self.integrator.signal_optimizer.config

            if "confidence_floor" in params:
                optimizer_cfg.confidence_floor = params["confidence_floor"]
            if "rapid_change_threshold" in params:
                optimizer_cfg.rapid_change_threshold = params["rapid_change_threshold"]

        logger.info(f"[AIClient] 集成器配置已更新: {list(params.keys())}")

    async def get_signal(self, market_data: Dict[str, Any]) -> str:
        """获取交易信号，返回: buy / hold / sell"""
        # 检查缓存
        if self._enable_cache and self._cache:
            cached_signal = self._cache.get(market_data)
            if cached_signal:
                return cached_signal

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
        # 注意：融合器返回的 confidence 已经是 0-1 范围，不需要再除以 100
        confidence_float = original_confidence if original_confidence else 0.50
        result = self.integrator.process(
            market_data=market_data,
            original_signal=original_signal,
            original_confidence=confidence_float,
        )
        market_data["ai_final_confidence"] = result.final_confidence
        market_data["final_confidence"] = result.final_confidence
        market_data["is_high_risk"] = result.is_high_risk
        market_data["is_low_opportunity"] = result.is_low_opportunity
        market_data["price_level"] = result.price_level

        # 记录集成过程
        if result.adjustments_made:
            for adj in result.adjustments_made:
                logger.info(f"  [集成优化] {adj}")

        # 写入缓存
        if self._enable_cache and self._cache:
            self._cache.set(market_data, result.final_signal, result.final_confidence)

        return result.final_signal

    async def _get_single_signal(self, market_data: Dict[str, Any]) -> tuple:
        """单AI模式，返回 (signal, confidence)"""
        provider = self.config.default_provider
        api_key = self.api_keys.get(provider, "")
        logger.info(f"[AI请求] 单AI模式, 提供商: {provider}")

        # 使用带重试的调用
        response = await self._call_ai_with_retry(provider, market_data, api_key)
        signal, confidence = parse_response(response)

        # 归一化置信度: parse_response 返回 0-100 整数，统一转为 0-1 浮点数
        confidence_normalized = (
            confidence / 100.0
            if confidence is not None and confidence > 1
            else confidence
        )

        await log_signal_distribution(signal, source=provider)
        logger.info(
            f"[AI响应] 提供商={provider}, 信号={signal}, "
            f"置信度={confidence}% (归一化={confidence_normalized})"
        )
        return signal, confidence_normalized

    async def _get_fusion_signal(self, market_data: Dict[str, Any]) -> tuple:
        """多AI融合模式 - 并行调用多个AI并融合结果"""
        providers = self.config.fusion_providers
        fusion_weights = self._get_normalized_fusion_weights()
        logger.info(f"[AI请求] 多AI融合模式, 提供商列表: {providers}")

        # 并行调用（带重试机制）
        tasks = []
        for provider in providers:
            api_key = self.api_keys.get(provider, "")
            tasks.append(self._call_ai_with_retry(provider, market_data, api_key))

        logger.info(f"[AI请求] 开始并行调用 {len(tasks)} 个AI提供商...")
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        signals = []
        confidences: Dict[str, float] = {}
        failed_providers = []

        for provider, response in zip(providers, responses):
            if isinstance(response, Exception):
                logger.error(f"[AI错误] {provider} 调用失败: {response}")
                failed_providers.append(provider)
                continue

            if not isinstance(response, str):
                logger.error(f"[AI错误] {provider} 响应类型异常: {type(response)}")
                failed_providers.append(provider)
                continue

            try:
                signal, confidence = parse_response(response)
                # 归一化置信度: parse_response 返回 0-100 整数，统一转为 0-1 浮点数
                confidence_normalized = (
                    confidence / 100.0
                    if confidence is not None and confidence > 1
                    else confidence
                )
                logger.debug(f"[AI原始响应] {provider}: {response}")
                signals.append(
                    {
                        "provider": provider,
                        "signal": signal,
                        "confidence": confidence_normalized,
                    }
                )
                if confidence_normalized is not None:
                    confidences[provider] = confidence_normalized
                conf_str = (
                    f"{confidence}% (归一化={confidence_normalized})"
                    if confidence is not None
                    else "N/A"
                )
                # 强制要求标准置信度：None 时使用默认 0.50 而非保留 None
                if confidence_normalized is None:
                    confidence_normalized = 0.50
                    logger.warning(f"[AI响应] {provider}: 置信度解析失败，使用默认0.50")
                logger.info(f"[AI响应] {provider}: 信号={signal}, 置信度={conf_str}")
            except Exception as e:
                logger.error(f"[AI解析错误] {provider}: {e}")
                failed_providers.append(provider)

        # 记录失败的提供商
        if failed_providers:
            logger.warning(
                "[AI融合] 以下提供商调用失败: "
                f"{failed_providers}, 成功: "
                f"{[p for p in providers if p not in failed_providers]}"
            )

        # 如果所有提供商都失败，直接返回默认HOLD信号，不再尝试备用方案
        if not signals:
            logger.warning("[AI融合] 所有AI提供商都失败，尝试 fallback 提供商")
            return await self._fallback_fusion(market_data)

        # 使用融合策略
        strategy = self._get_fusion_strategy(self.config.fusion_strategy)

        # 传递market_data以支持动态阈值计算
        fused_signal = strategy.fuse(
            signals,
            fusion_weights,
            self.config.fusion_threshold,
            confidences=confidences,
            market_data=market_data,
        )

        # 使用融合结果中的标准评分输出，避免与具体策略实现解耦失效
        max_score = max(fused_signal.scores.values()) if fused_signal.scores else 0.0
        is_valid = fused_signal.is_valid

        logger.info(
            f"[AI融合] 结果: {fused_signal.signal} "
            f"(信号值:{max_score:.2f}, 阈值:{fused_signal.threshold:.2f}, 有效:{is_valid}, "
            f"策略:{fused_signal.strategy_used})"
        )

        # 记录信号分布
        await log_signal_distribution(fused_signal.signal, source="fusion")

        # 返回信号和置信度
        return fused_signal.signal, fused_signal.confidence

    async def _fallback_fusion(self, market_data: Dict[str, Any]) -> tuple:
        """备用融合方案 - 当主提供商失败时使用"""
        record_fallback_invocation()
        preferred_order = ["gemini", "qwen", "openai", "deepseek", "kimi", "minimax"]
        seen = set()
        fallback_providers = []

        # 优先使用不在主融合链路中的 provider，避免重复失败路径
        for provider in preferred_order:
            if provider in seen:
                continue
            seen.add(provider)
            if provider in self.config.fusion_providers:
                continue
            fallback_providers.append(provider)

        for provider in self.config.fusion_providers:
            if provider not in seen:
                fallback_providers.append(provider)
                seen.add(provider)

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
                # 归一化置信度: parse_response 返回 0-100 整数，统一转为 0-1 浮点数
                confidence_normalized = (
                    confidence / 100.0
                    if confidence is not None and confidence > 1
                    else confidence
                )
                logger.info(
                    f"[AI融合-备用] {provider}: 信号={signal}, "
                    f"置信度={confidence}% (归一化={confidence_normalized})"
                )
                await log_signal_distribution(signal, source=f"fallback_{provider}")
                return signal, confidence_normalized if confidence_normalized else 0.40
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

        if last_error is None:
            raise RuntimeError(f"AI[{provider}] 调用失败，且未捕获到明确异常")

        raise last_error

    def _should_retry_error(
        self, error: Exception, provider: str, attempt: int
    ) -> bool:
        """判断是否应该重试"""
        error_str = str(error).lower()

        # 不重试的错误（客户端问题或服务器过载，不会因重试而解决）
        no_retry_keywords = [
            "余额不足",
            "insufficient balance",
            "quota",
            "limit",
            "engine_overloaded",
        ]

        for keyword in no_retry_keywords:
            if keyword in error_str:
                logger.info(f"[AI重试] {provider} 遇到不需重试的错误: {keyword}")
                return False

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
        aiohttp_module = importlib.import_module("aiohttp")

        # 获取提供商配置
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

        # MiniMax / DeepSeek 使用推理模型，思考过程长，需要更多 output tokens
        # DeepSeek Thinking Mode 的 max_tokens 包含 CoT（链式思考）部分
        # 原800tokens导致reasoning消耗完全部配额，content为空 → 默认hold
        if provider in ("minimax", "deepseek"):
            data["max_tokens"] = 3000  # 2000→3000，确保推理后仍有足够空间输出答案

        # 根据提供商类型设置不同的超时时间
        timeout_config = self._get_timeout_config(provider)

        try:
            async with aiohttp_module.ClientSession() as session:
                async with session.post(
                    config["base_url"],
                    headers=headers,
                    json=data,
                    timeout=timeout_config,
                ) as response:
                    # 检查HTTP状态码
                    if response.status != 200:
                        response_text = await response.text()
                        sanitized_body = _redact_sensitive_text(response_text, 200)
                        logger.error(
                            f"AI[{provider}]HTTP错误: status={response.status}, "
                            f"body={sanitized_body}"
                        )
                        if provider == "gemini":
                            record_gemini_request(False)
                        raise ValueError(f"AI[{provider}]HTTP {response.status}")
                    result = await response.json()
                    # 检查响应是否包含有效的choices字段
                    if "choices" not in result or not result["choices"]:
                        error_info = result.get("error", {})
                        error_msg = error_info.get("message", str(result))
                        error_type = error_info.get("type", "unknown")

                        if (
                            "balance" in error_msg.lower()
                            or "insufficient" in error_msg.lower()
                        ):
                            logger.error(
                                f"AI[{provider}]余额不足: "
                                f"{_redact_sensitive_text(error_msg)}"
                            )
                            raise ValueError(
                                f"AI[{provider}]余额不足，请检查API账户余额"
                            )
                        elif error_msg:
                            sanitized_error = _redact_sensitive_text(error_msg)
                            # Gemini 常见鉴权错误映射
                            if provider == "gemini" and (
                                "api key" in error_msg.lower()
                                or "permission" in error_msg.lower()
                                or "invalid" in error_msg.lower()
                            ):
                                record_gemini_request(False)
                                raise ValueError(
                                    "AI[gemini]鉴权失败，请检查 "
                                    "GEMINI_API_KEY/GOOGLE_API_KEY"
                                )
                            logger.error(
                                f"AI[{provider}]API错误 [{error_type}]: "
                                f"{sanitized_error}"
                            )
                            if provider == "gemini":
                                record_gemini_request(False)
                            raise ValueError(f"AI[{provider}]请求失败 [{error_type}]")
                        else:
                            logger.error(f"AI[{provider}]响应格式错误: {result}")
                            if provider == "gemini":
                                record_gemini_request(False)
                            raise ValueError(
                                f"AI[{provider}]响应缺少choices字段: " f"{result}"
                            )
                    message = result["choices"][0]["message"]
                    content = message.get("content", "") or ""
                    # DeepSeek Thinking Mode: content 可能为空，
                    # 推理内容在 reasoning_content 中
                    if not content.strip() and message.get("reasoning_content"):
                        reasoning_text = message.get("reasoning_content", "")
                        self._metrics["max_tokens_truncated"] += 1
                        logger.warning(
                            f"AI[{provider}] content为空但存在reasoning_content，"
                            "Thinking Mode可能因max_tokens不足导致最终答案被截断"
                        )
                        # 尝试从reasoning_content末尾提取信号决策
                        extracted = self._extract_signal_from_reasoning(reasoning_text)
                        if extracted:
                            content = extracted
                            self._metrics["reasoning_fallback_hits"] += 1
                            logger.info(
                                f"AI[{provider}] 从reasoning_content提取到信号文本: "
                                f"{content[:100]}"
                            )
                        else:
                            self._metrics["reasoning_fallback_misses"] += 1
                            logger.warning(
                                f"AI[{provider}] reasoning_content中也无法提取信号，"
                                "将触发重试"
                            )
                    if provider == "gemini":
                        record_gemini_request(True)
                    return content.strip()

        except ValueError:
            raise
        except aiohttp_module.ClientError as e:
            logger.error(f"AI[{provider}]网络错误: {type(e).__name__}: {e}")
            if provider == "gemini":
                record_gemini_request(False)
            raise ValueError(f"AI[{provider}]网络错误: {e}") from e
        except asyncio.TimeoutError:
            logger.error(f"AI[{provider}]请求超时")
            if provider == "gemini":
                record_gemini_request(False)
            raise ValueError(f"AI[{provider}]请求超时")
        except Exception as e:
            logger.error(f"AI[{provider}]调用失败: {type(e).__name__}: {e}")
            if provider == "gemini":
                record_gemini_request(False)
            raise

    def _get_timeout_config(self, provider: str) -> Any:
        """获取提供商特定超时配置"""
        aiohttp_module = importlib.import_module("aiohttp")
        timeout_map = {
            "kimi": 90,  # Kimi 晚间慢，增加到 90 秒
            "deepseek": 60,
            "openai": 60,
            "qwen": 45,
            "gemini": 75,
            "minimax": 120,  # MiniMax 可能需要更长超时
        }

        timeout_seconds = timeout_map.get(provider, 60)
        return aiohttp_module.ClientTimeout(total=timeout_seconds)

    @staticmethod
    def _extract_signal_from_reasoning(reasoning_text: str) -> str:
        """从reasoning_content末尾提取信号决策文本。

        DeepSeek Thinking Mode在max_tokens不足时，最终答案可能
        只存在于reasoning_content的推理链末尾而非content字段。
        """
        if not reasoning_text or not reasoning_text.strip():
            return ""

        tail = reasoning_text[-500:] if len(reasoning_text) > 500 else reasoning_text
        tail_lower = tail.lower()

        signal_keywords = [
            ("buy", r"\bbuy\b"),
            ("sell", r"\bsell\b"),
            ("hold", r"\bhold\b"),
            ("short", r"\bshort\b"),
            ("buy", r"买入"),
            ("sell", r"卖出"),
            ("hold", r"持有|观望"),
        ]
        for signal, pattern in signal_keywords:
            if re.search(pattern, tail_lower):
                return f"{signal} confidence:70%"

        return ""

    def get_metrics(self) -> Dict[str, int]:
        """返回当前累计的监控指标快照（用于诊断和报告）。"""
        return dict(self._metrics)


async def get_signal(market_data: Dict[str, Any], mode: str = "single") -> str:
    """便捷函数"""
    client = AIClient()
    return await client.get_signal(market_data)
