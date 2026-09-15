"""
AI提供商配置
"""

# AI提供商配置
PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-v4-flash",
    },
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1/chat/completions",
        "model": "moonshot-v1-8k",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o-mini",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-turbo",
    },
    "gemini": {
        # 使用 Gemini OpenAI 兼容层，保持与现有调用链同构
        "base_url": (
            "https://generativelanguage.googleapis.com"
            "/v1beta/openai/chat/completions"
        ),
        "model": "gemini-2.5-flash",
    },
    "minimax": {
        "base_url": "https://api.minimaxi.com/v1/chat/completions",
        "model": "MiniMax-M2.7",
    },
    # 自建 Qwen3.8-27B (ninfer 部署，OpenAI 兼容接口)，默认替代 deepseek 使用
    # 注意: 模型默认开启思考模式 (reasoning_content)，max_tokens 需按推理模型处理
    "qwen38": {
        "base_url": "http://140.206.177.114:16078/v1/chat/completions",
        "model": "qwen3.8-27b",
    },
}


def get_provider_config(
    provider: str,
    *,
    allow_fallback: bool = True,
    fallback_provider: str = "deepseek",
) -> dict:
    """获取提供商配置。

    Args:
        provider: 提供商名称
        allow_fallback: 是否允许回退到 fallback_provider
        fallback_provider: 回退目标 provider

    Returns:
        提供商配置字典

    Raises:
        ValueError: 当 provider 未注册且禁用回退，或 fallback_provider 无效
    """
    if provider in PROVIDERS:
        return PROVIDERS[provider]

    if not allow_fallback:
        raise ValueError(f"未知AI提供商: {provider}")

    if fallback_provider not in PROVIDERS:
        raise ValueError(f"无效回退提供商: {fallback_provider}")

    return PROVIDERS[fallback_provider]
