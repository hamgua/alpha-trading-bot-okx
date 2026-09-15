"""qwen38 (自建 Qwen3.8-27B, ninfer) 接入与契约测试。"""

import pytest

from alpha_trading_bot.ai.client import AIClient
from alpha_trading_bot.ai.providers import get_provider_config
from alpha_trading_bot.ai.response_parser import parse_response
from alpha_trading_bot.config.models import AIConfig


def test_provider_registry_contains_qwen38() -> None:
    """qwen38 必须在 provider 注册表中，指向自建 ninfer 服务。"""
    config = get_provider_config("qwen38")
    assert config["base_url"] == "http://140.206.177.114:16078/v1/chat/completions"
    assert config["model"] == "qwen3.8-27b"


def test_ai_config_includes_qwen38_provider() -> None:
    """AIConfig 的合法 provider 列表必须包含 qwen38。"""
    assert "qwen38" in AIConfig.VALID_PROVIDERS


def test_qwen38_api_key_defaults_to_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ninfer 服务不校验 key，未配置时默认占位 sk-anything。"""
    monkeypatch.delenv("QWEN38_API_KEY", raising=False)

    config = AIConfig.from_env()

    assert config.api_keys["qwen38"] == "sk-anything"


def test_qwen38_api_key_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """显式配置 QWEN38_API_KEY 时优先生效。"""
    monkeypatch.setenv("QWEN38_API_KEY", "sk-custom")

    config = AIConfig.from_env()

    assert config.api_keys["qwen38"] == "sk-custom"


def test_ai_config_accepts_qwen38_in_fusion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """qwen38 可作为 fusion provider 参与并自动补齐权重。"""
    monkeypatch.setenv("AI_MODE", "fusion")
    monkeypatch.setenv("AI_FUSION_PROVIDERS", "qwen38,kimi")
    monkeypatch.setenv("AI_FUSION_WEIGHTS", "qwen38:0.7")
    monkeypatch.setenv("QWEN38_API_KEY", "sk-anything")

    config = AIConfig.from_env()

    assert not config.validate()
    assert set(config.fusion_weights.keys()) == {"qwen38", "kimi"}
    assert pytest.approx(sum(config.fusion_weights.values()), abs=1e-6) == 1.0


def test_qwen38_timeout_mapping() -> None:
    """qwen38 推理模型需要独立的超时映射。"""
    config = AIConfig(
        mode="single", default_provider="qwen38", api_keys={"qwen38": "k"}
    )
    client = AIClient(config=config, api_keys=config.api_keys)
    timeout = client._get_timeout_config("qwen38")
    assert timeout.total == 90


@pytest.mark.asyncio
async def test_single_mode_routes_to_qwen38(monkeypatch: pytest.MonkeyPatch) -> None:
    """single 模式下默认 provider=qwen38 时必须路由到 qwen38。"""
    config = AIConfig(
        mode="single", default_provider="qwen38", api_keys={"qwen38": "k"}
    )
    client = AIClient(config=config, api_keys=config.api_keys, enable_cache=False)

    calls = {"provider": ""}

    async def fake_call(provider: str, market_data: dict, api_key: str) -> str:
        calls["provider"] = provider
        return '{"signal": "buy", "confidence": 0.72}'

    monkeypatch.setattr(client, "_call_ai_with_retry", fake_call)

    signal, confidence = await client._get_single_signal({"technical": {"rsi": 45}})
    assert calls["provider"] == "qwen38"
    assert signal == "buy"
    assert confidence == pytest.approx(0.72)


def test_qwen38_json_output_parses() -> None:
    """实测 ninfer 服务返回的标准 JSON 输出应可被解析。"""
    signal, confidence = parse_response('{"signal":"buy","confidence":62}')
    assert signal == "buy"
    assert confidence == 62


@pytest.mark.asyncio
async def test_qwen38_reasoning_fallback_extracts_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """qwen38 思考模式下 content 为空时应从 reasoning_content 提取信号。"""
    import aiohttp

    config = AIConfig(
        mode="single", default_provider="qwen38", api_keys={"qwen38": "sk-anything"}
    )
    client = AIClient(config=config, api_keys=config.api_keys, enable_cache=False)

    payload = {
        "choices": [
            {
                "finish_reason": "length",
                "message": {
                    "content": "",
                    "reasoning_content": (
                        "...推理链... Final decision: Signal buy with moderate confidence."
                    ),
                    "role": "assistant",
                },
            }
        ],
        "usage": {
            "completion_tokens": 3000,
            "completion_tokens_details": {"reasoning_tokens": 2990},
            "prompt_tokens": 119,
            "total_tokens": 3109,
        },
    }

    class _FakeResponse:
        status = 200

        async def text(self) -> str:
            return ""

        async def json(self) -> dict:
            return payload

        async def __aenter__(self) -> "_FakeResponse":
            return self

        async def __aexit__(self, *args) -> None:
            return None

    class _FakeSession:
        def post(self, *args, **kwargs) -> "_FakeResponse":
            return _FakeResponse()

        async def __aenter__(self) -> "_FakeSession":
            return self

        async def __aexit__(self, *args) -> None:
            return None

    monkeypatch.setattr(
        aiohttp, "ClientSession", lambda *a, **k: _FakeSession()
    )

    content = await client._call_ai("qwen38", {"technical": {"rsi": 45}}, "sk-anything")

    # reasoning_content 尾部信号提取兜底生效
    assert "buy" in content.lower()
    metrics = client.get_metrics()
    assert metrics["max_tokens_truncated"] >= 1
    assert metrics["reasoning_fallback_hits"] >= 1
