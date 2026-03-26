"""
AI提供商配置
"""

# AI提供商配置
PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-chat",
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
    "minimax": {
        "base_url": "https://api.minimaxi.com/v1/chat/completions",
        "model": "MiniMax-M2.7",
    },
}


def get_provider_config(provider: str) -> dict:
    """获取提供商配置"""
    return PROVIDERS.get(provider, PROVIDERS["deepseek"])
