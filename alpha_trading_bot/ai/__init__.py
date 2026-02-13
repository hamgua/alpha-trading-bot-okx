"""
AI模块 - 支持单AI/多AI融合

包含：
- 客户端：单AI/多AI调用
- 提供商：多AI提供商支持
- Prompt构建：动态生成AI Prompt
- 响应解析：AI信号解析
- 融合策略：多AI信号融合
- 自适应买入条件：动态调整买入阈值
- 信号优化器：信号过滤和优化
- 高位买入优化器：高位信号过滤
- BTC价格检测器：针对BTC高波动的价格水平检测
- 信号集成器：统一接口，集成所有优化模块
"""

from .client import AIClient, get_signal
from .providers import PROVIDERS, get_provider_config
from .prompt_builder import PromptBuilder, build_prompt
from .response_parser import ResponseParser, parse_response, extract_signal
from .fusion import (
    FusionStrategy,
    WeightedFusion,
    MajorityFusion,
    ConsensusFusion,
    ConfidenceFusion,
)
from .adaptive_buy_condition import (
    AdaptiveBuyCondition,
    BuyConditions,
    BuyConditionResult,
)
from .signal_optimizer import SignalOptimizer, OptimizerConfig, OptimizedSignal
from .high_price_buy_optimizer import (
    HighPriceBuyOptimizer,
    HighPriceBuyConfig,
    HighPriceBuyResult,
)
from .btc_price_detector import (
    BTCPriceLevelConfig,
    BTCPriceLevelDetector,
    PriceLevelResult,
    EnhancedBuyConfig,
    EnhancedBuyOptimizer,
)
from .integrator import (
    AISignalIntegrator,
    IntegrationConfig,
    IntegratedSignalResult,
    create_integrator,
)

__version__ = "1.0.0"

__all__ = [
    # 客户端
    "AIClient",
    "get_signal",
    # 提供商
    "PROVIDERS",
    "get_provider_config",
    # Prompt构建
    "PromptBuilder",
    "build_prompt",
    # 响应解析
    "ResponseParser",
    "parse_response",
    "extract_signal",
    # 融合策略
    "FusionStrategy",
    "WeightedFusion",
    "MajorityFusion",
    "ConsensusFusion",
    "ConfidenceFusion",
    # 自适应买入条件
    "AdaptiveBuyCondition",
    "BuyConditions",
    "BuyConditionResult",
    # 信号优化器
    "SignalOptimizer",
    "OptimizerConfig",
    "OptimizedSignal",
    # 高位买入优化器
    "HighPriceBuyOptimizer",
    "HighPriceBuyConfig",
    "HighPriceBuyResult",
    # BTC价格检测器
    "BTCPriceLevelConfig",
    "BTCPriceLevelDetector",
    "PriceLevelResult",
    "EnhancedBuyConfig",
    "EnhancedBuyOptimizer",
    # 信号集成器
    "AISignalIntegrator",
    "IntegrationConfig",
    "IntegratedSignalResult",
    "create_integrator",
]
