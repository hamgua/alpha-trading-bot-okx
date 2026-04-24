"""Gemini 接入与融合契约测试。"""

import pytest

from alpha_trading_bot.ai.client import AIClient
from alpha_trading_bot.ai.fusion.base import get_fusion_strategy
from alpha_trading_bot.ai.providers import get_provider_config
from alpha_trading_bot.ai.response_parser import parse_response
from alpha_trading_bot.config.models import AIConfig
from alpha_trading_bot.utils.observability import get_runtime_metrics


def test_provider_registry_contains_gemini() -> None:
    """Gemini 必须在 provider 注册表中。"""
    config = get_provider_config("gemini")
    assert "base_url" in config
    assert "model" in config


def test_provider_fallback_is_controllable() -> None:
    """未知 provider 在禁用回退时必须报错。"""
    with pytest.raises(ValueError):
        get_provider_config("unknown-provider", allow_fallback=False)


def test_ai_config_includes_gemini_provider() -> None:
    """AIConfig 的合法 provider 列表必须包含 Gemini。"""
    assert "gemini" in AIConfig.VALID_PROVIDERS


def test_ai_config_auto_completes_and_normalizes_weights(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """当权重缺项时应自动补齐并归一化。"""
    monkeypatch.setenv("AI_MODE", "fusion")
    monkeypatch.setenv("AI_FUSION_PROVIDERS", "deepseek,kimi,gemini")
    monkeypatch.setenv("AI_FUSION_WEIGHTS", "deepseek:0.7")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "a")

    config = AIConfig.from_env()

    assert set(config.fusion_weights.keys()) == {"deepseek", "kimi", "gemini"}
    assert pytest.approx(sum(config.fusion_weights.values()), abs=1e-6) == 1.0


def test_gemini_api_key_priority_prefers_google_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同时存在时必须优先读取 GOOGLE_API_KEY。"""
    monkeypatch.setenv("GOOGLE_API_KEY", "google-priority")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secondary")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "dummy")

    config = AIConfig.from_env()

    assert config.api_keys["gemini"] == "google-priority"


def test_all_fusion_strategies_return_uniform_contract() -> None:
    """所有融合策略都必须返回统一的 FusionResult 语义。"""
    signals = [
        {"provider": "deepseek", "signal": "buy", "confidence": 0.7},
        {"provider": "kimi", "signal": "buy", "confidence": 0.65},
        {"provider": "gemini", "signal": "hold", "confidence": 0.55},
    ]
    weights = {"deepseek": 0.4, "kimi": 0.3, "gemini": 0.3}
    confidences = {"deepseek": 0.7, "kimi": 0.65, "gemini": 0.55}

    for strategy_name in [
        "weighted",
        "majority",
        "consensus",
        "confidence",
        "consensus_boosted",
    ]:
        strategy = get_fusion_strategy(strategy_name)
        result = strategy.fuse(
            signals,
            weights,
            0.5,
            confidences=confidences,
            market_data={"technical": {"rsi": 50, "trend_direction": "neutral"}},
        )
        assert hasattr(result, "signal")
        assert hasattr(result, "confidence")
        assert result.signal in {"buy", "hold", "sell", "short"}
        assert isinstance(result.confidence, float)


def test_response_parser_supports_gemini_json_output() -> None:
    """Gemini 结构化输出应可被解析。"""
    signal, confidence = parse_response('{"signal": "buy", "confidence": 0.73}')
    assert signal == "buy"
    assert confidence == 73


def test_gemini_timeout_mapping() -> None:
    """Gemini 需要独立的超时映射。"""
    config = AIConfig(
        mode="single", default_provider="gemini", api_keys={"gemini": "k"}
    )
    client = AIClient(config=config, api_keys=config.api_keys)
    timeout = client._get_timeout_config("gemini")
    assert timeout.total == 75


@pytest.mark.asyncio
async def test_single_mode_routes_to_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    """single 模式下默认 provider=gemini 时必须路由到 Gemini。"""
    config = AIConfig(
        mode="single", default_provider="gemini", api_keys={"gemini": "k"}
    )
    client = AIClient(config=config, api_keys=config.api_keys, enable_cache=False)

    calls = {"provider": ""}

    async def fake_call(provider: str, market_data: dict, api_key: str) -> str:
        calls["provider"] = provider
        return "buy | confidence: 72%"

    monkeypatch.setattr(client, "_call_ai_with_retry", fake_call)

    signal, confidence = await client._get_single_signal({"technical": {"rsi": 45}})
    assert calls["provider"] == "gemini"
    assert signal == "buy"
    assert confidence == pytest.approx(0.72)


@pytest.mark.asyncio
async def test_fusion_all_failed_triggers_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fusion 主链路全失败时必须触发 fallback，不得直接静默 hold。"""
    config = AIConfig(
        mode="fusion",
        fusion_providers=["gemini", "deepseek"],
        fusion_strategy="weighted",
        fusion_weights={"gemini": 0.5, "deepseek": 0.5},
        api_keys={"gemini": "k1", "deepseek": "k2", "openai": "k3"},
    )
    client = AIClient(config=config, api_keys=config.api_keys, enable_cache=False)

    async def always_fail(provider: str, market_data: dict, api_key: str) -> str:
        raise RuntimeError(f"{provider} down")

    async def fallback_ok(market_data: dict) -> tuple:
        return "sell", 0.66

    monkeypatch.setattr(client, "_call_ai_with_retry", always_fail)
    monkeypatch.setattr(client, "_fallback_fusion", fallback_ok)

    signal, confidence = await client._get_fusion_signal({"technical": {"rsi": 60}})
    assert signal == "sell"
    assert confidence == pytest.approx(0.66)


@pytest.mark.asyncio
async def test_gemini_metrics_record_failure_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gemini HTTP错误应计入失败指标。"""
    config = AIConfig(
        mode="single", default_provider="gemini", api_keys={"gemini": "k"}
    )
    client = AIClient(config=config, api_keys=config.api_keys, enable_cache=False)

    async def fake_call(provider: str, market_data: dict, api_key: str) -> str:
        if provider == "gemini":
            from alpha_trading_bot.utils.observability import record_gemini_request

            record_gemini_request(False)
        raise ValueError("AI[gemini]HTTP 500")

    monkeypatch.setattr(client, "_call_ai_with_retry", fake_call)

    with pytest.raises(ValueError):
        await client._get_single_signal({"technical": {"rsi": 45}})

    metrics = get_runtime_metrics()
    assert metrics["gemini_failure_total"] >= 1
