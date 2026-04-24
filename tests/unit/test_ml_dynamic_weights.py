"""ML 动态权重去硬编码回归测试。"""

import os

from alpha_trading_bot.ai.ml.adaptive_fusion import AdaptiveFusionStrategy
from alpha_trading_bot.ai.ml.adaptive_weight_optimizer import AdaptiveWeightOptimizer
from alpha_trading_bot.ai.ml.learning_integrator import MLLearningIntegrator
from alpha_trading_bot.ai.ml.ml_data_manager import MLDataManager
from alpha_trading_bot.ai.ml.performance_tracker import get_performance_summary
from alpha_trading_bot.ai.ml.signal_backtest import SignalBacktestLearner
from alpha_trading_bot.ai.ml.weight_optimizer import WeightOptimizer
from alpha_trading_bot.ai.provider_utils import get_runtime_fusion_providers


def test_adaptive_fusion_default_weights_include_gemini() -> None:
    strategy = AdaptiveFusionStrategy()
    for regime, weights in strategy.weight_map.items():
        assert "gemini" in weights, regime
        assert abs(sum(weights.values()) - 1.0) < 1e-6


def test_weight_optimizer_default_regime_weights_include_gemini() -> None:
    optimizer = WeightOptimizer(data_dir="/tmp/weight-history-test")
    weights = optimizer.get_weights("strong_uptrend")
    assert "gemini" in weights
    assert abs(sum(weights.values()) - 1.0) < 1e-6


def test_ml_data_manager_default_weights_include_gemini() -> None:
    manager = MLDataManager(db_path="/tmp/not-exist.db")
    weights = manager._default_weights()
    assert set(weights.keys()) == {"deepseek", "kimi", "gemini"}
    assert abs(sum(weights.values()) - 1.0) < 1e-6


def test_adaptive_weight_optimizer_default_weights_include_gemini() -> None:
    optimizer = AdaptiveWeightOptimizer(db_path="/tmp/not-exist.db")
    weights = optimizer._default_weights()
    assert set(weights.keys()) == {"deepseek", "kimi", "gemini"}
    assert abs(sum(weights.values()) - 1.0) < 1e-6


def test_learning_integrator_default_weights_include_gemini() -> None:
    integrator = MLLearningIntegrator(db_path="/tmp/not-exist.db")
    weights = integrator._default_weights()
    assert set(weights.keys()) == {"deepseek", "kimi", "gemini"}
    assert abs(sum(weights.values()) - 1.0) < 1e-6


def test_signal_backtest_default_weights_include_gemini() -> None:
    learner = SignalBacktestLearner(db_path="/tmp/not-exist.db")
    weights = learner._default_weights()
    assert set(weights.keys()) == {"deepseek", "kimi", "gemini"}
    assert abs(sum(weights.values()) - 1.0) < 1e-6


def test_performance_summary_default_providers_include_gemini() -> None:
    summary = get_performance_summary()
    assert "gemini" in summary["provider_stats"]


def test_runtime_fusion_providers_respects_env_order() -> None:
    original = os.environ.get("AI_FUSION_PROVIDERS")
    os.environ["AI_FUSION_PROVIDERS"] = "openai, gemini, deepseek"
    try:
        providers = get_runtime_fusion_providers()
        assert providers == ["openai", "gemini", "deepseek"]
    finally:
        if original is None:
            del os.environ["AI_FUSION_PROVIDERS"]
        else:
            os.environ["AI_FUSION_PROVIDERS"] = original
