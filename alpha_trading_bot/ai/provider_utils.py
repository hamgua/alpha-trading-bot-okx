"""AI provider 工具函数。"""

import os
from typing import List, Optional

from alpha_trading_bot.config.models import AIConfig


def get_runtime_fusion_providers(
    fallback: Optional[List[str]] = None,
) -> List[str]:
    """获取运行时融合 provider 列表。

    优先读取环境变量中的 ``AI_FUSION_PROVIDERS``，若为空则回退到传入
    fallback（默认 ``["deepseek", "kimi", "gemini"]``）。
    """
    default_providers = fallback or ["deepseek", "kimi", "gemini"]

    configured_providers = os.getenv("AI_FUSION_PROVIDERS")
    if configured_providers and configured_providers.strip():
        providers = AIConfig.from_env().fusion_providers
    else:
        providers = default_providers

    if not providers:
        providers = default_providers

    deduplicated: List[str] = []
    seen = set()
    for provider in providers:
        normalized = provider.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduplicated.append(normalized)

    return deduplicated if deduplicated else default_providers
