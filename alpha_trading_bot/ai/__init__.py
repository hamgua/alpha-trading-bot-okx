"""
AI模块 - 处理AI信号生成和管理
"""

from .manager import AIManager, create_ai_manager, get_ai_manager, cleanup_ai_manager
from .client import AIClient
from .fusion import AIFusion
from .signals import SignalGenerator, create_signal_generator
from .providers import (
    BaseAIProvider,
    KimiProvider,
    DeepSeekProvider,
    QwenProvider,
    OpenAIProvider
)

__all__ = [
    # AI管理器
    'AIManager',
    'create_ai_manager',
    'get_ai_manager',
    'cleanup_ai_manager',

    # AI客户端
    'AIClient',

    # AI融合
    'AIFusion',

    # 信号生成器
    'SignalGenerator',
    'create_signal_generator',

    # AI提供商
    'BaseAIProvider',
    'KimiProvider',
    'DeepSeekProvider',
    'QwenProvider',
    'OpenAIProvider'
]