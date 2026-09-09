"""C3: 降级 AI BUY 阻断（dream 2026-09-09-okx-loss-optimization）。

覆盖 task-card AC-3.1..AC-3.5。
"""

import asyncio
from types import SimpleNamespace
from typing import Any, Dict

import pytest

from alpha_trading_bot.ai.client import AIClient
from alpha_trading_bot.config.models import AIConfig


def _make_client(
    monkeypatch: pytest.MonkeyPatch,
    final_signal: str,
    degraded: bool,
    block: bool = True,
) -> AIClient:
    config = AIConfig(
        mode="single",
        default_provider="deepseek",
        api_keys={"deepseek": "k"},
        block_degraded_buy=block,
    )
    client = AIClient(config=config, api_keys=config.api_keys, enable_cache=False)

    async def fake_call(provider: str, market_data: Dict[str, Any], api_key: str) -> str:
        if degraded:
            client._last_signal_degraded = True  # 模拟 _call_ai reasoning 提取置位
        return "buy | confidence: 70%"

    def fake_process(market_data, original_signal, original_confidence):
        return SimpleNamespace(
            final_signal=final_signal,
            final_confidence=0.5,
            is_high_risk=False,
            price_level="neutral",
            is_low_opportunity=False,
            adjustments_made=[],
        )

    monkeypatch.setattr(client, "_call_ai_with_retry", fake_call)
    monkeypatch.setattr(client.integrator, "process", fake_process)
    return client


# ---- get_signal 阻断语义 ----


@pytest.mark.asyncio
async def test_c3_g01_degraded_buy_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-3.1: 降级 + 终态 BUY → HOLD 且打 market_data 标记。"""
    client = _make_client(monkeypatch, "BUY", degraded=True)
    md = {"technical": {"rsi": 45}}
    assert await client.get_signal(md) == "HOLD"
    assert md["ai_degraded_buy_blocked"] is True


@pytest.mark.asyncio
async def test_c3_g02_degraded_sell_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-3.4: 降级 + 终态 SELL → 不变（保护性平仓不受影响）。"""
    client = _make_client(monkeypatch, "SELL", degraded=True)
    md = {"technical": {"rsi": 45}}
    assert await client.get_signal(md) == "SELL"
    assert "ai_degraded_buy_blocked" not in md


@pytest.mark.asyncio
async def test_c3_g03_degraded_short_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-3.4: 降级 + 终态 SHORT → 不变。"""
    client = _make_client(monkeypatch, "SHORT", degraded=True)
    md = {"technical": {"rsi": 45}}
    assert await client.get_signal(md) == "SHORT"
    assert "ai_degraded_buy_blocked" not in md


@pytest.mark.asyncio
async def test_c3_g04_degraded_hold_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-3.4: 降级 + 终态 HOLD → 不变（无标记）。"""
    client = _make_client(monkeypatch, "HOLD", degraded=True)
    md = {"technical": {"rsi": 45}}
    assert await client.get_signal(md) == "HOLD"
    assert "ai_degraded_buy_blocked" not in md


@pytest.mark.asyncio
async def test_c3_g05_normal_buy_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-3.5: 非降级 BUY → 不变。"""
    client = _make_client(monkeypatch, "BUY", degraded=False)
    md = {"technical": {"rsi": 45}}
    assert await client.get_signal(md) == "BUY"
    assert "ai_degraded_buy_blocked" not in md


@pytest.mark.asyncio
async def test_c3_g06_kill_switch_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-3.1(开关): block_degraded_buy=False → 不阻断。"""
    client = _make_client(monkeypatch, "BUY", degraded=True, block=False)
    md = {"technical": {"rsi": 45}}
    assert await client.get_signal(md) == "BUY"
    assert "ai_degraded_buy_blocked" not in md


@pytest.mark.asyncio
async def test_c3_g07_flag_resets_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-3.1: 标志每次 get_signal 复位，不跨调用残留。"""
    config = AIConfig(
        mode="single",
        default_provider="deepseek",
        api_keys={"deepseek": "k"},
        block_degraded_buy=True,
    )
    client = AIClient(config=config, api_keys=config.api_keys, enable_cache=False)
    state = {"degraded": True, "final": "BUY"}

    async def fake_call(provider, market_data, api_key):
        if state["degraded"]:
            client._last_signal_degraded = True
        return "buy | confidence: 70%"

    def fake_process(market_data, original_signal, original_confidence):
        return SimpleNamespace(
            final_signal=state["final"],
            final_confidence=0.5,
            is_high_risk=False,
            price_level="neutral",
            is_low_opportunity=False,
            adjustments_made=[],
        )

    monkeypatch.setattr(client, "_call_ai_with_retry", fake_call)
    monkeypatch.setattr(client.integrator, "process", fake_process)

    md1 = {"technical": {"rsi": 45}}
    assert await client.get_signal(md1) == "HOLD"
    assert md1["ai_degraded_buy_blocked"] is True

    state.update({"degraded": False, "final": "BUY"})
    md2 = {"technical": {"rsi": 46}}
    assert await client.get_signal(md2) == "BUY"
    assert "ai_degraded_buy_blocked" not in md2


@pytest.mark.asyncio
async def test_c3_g08_lowercase_buy_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-3.1 边界: 小写 buy（parse_response 透传形态）也被阻断。"""
    client = _make_client(monkeypatch, "buy", degraded=True)
    md = {"technical": {"rsi": 45}}
    assert await client.get_signal(md) == "HOLD"
    assert md["ai_degraded_buy_blocked"] is True


@pytest.mark.asyncio
async def test_c3_g09_concurrent_get_signal_does_not_reset_degraded_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """安全加固: 同一 AIClient 上并发 get_signal 被锁序列化，避免降级标志串扰。"""
    config = AIConfig(
        mode="single",
        default_provider="deepseek",
        api_keys={"deepseek": "k"},
        block_degraded_buy=True,
    )
    client = AIClient(config=config, api_keys=config.api_keys, enable_cache=False)
    gate = asyncio.Event()

    async def fake_single(market_data: Dict[str, Any]) -> tuple:
        # 模拟 _call_ai reasoning 提取成功后的降级状态，并挂起等待。
        client._last_signal_degraded = True
        await gate.wait()
        return "buy", 0.7

    def fake_process(market_data, original_signal, original_confidence):
        return SimpleNamespace(
            final_signal="BUY",
            final_confidence=0.5,
            is_high_risk=False,
            price_level="neutral",
            is_low_opportunity=False,
            adjustments_made=[],
        )

    monkeypatch.setattr(client, "_get_single_signal", fake_single)
    monkeypatch.setattr(client.integrator, "process", fake_process)

    md1 = {"technical": {"rsi": 45}}
    md2 = {"technical": {"rsi": 46}}

    task1 = asyncio.create_task(client.get_signal(md1))
    # 让 task1 先进入 get_signal 并持有锁，随后在 fake_single 中挂起。
    await asyncio.sleep(0.01)
    assert client._last_signal_degraded is True

    # task2 应等待锁，不能重置 task1 的降级标志。
    task2 = asyncio.create_task(client.get_signal(md2))
    await asyncio.sleep(0.01)
    assert client._last_signal_degraded is True

    gate.set()
    results = await asyncio.gather(task1, task2)

    assert results == ["HOLD", "HOLD"]
    assert md1.get("ai_degraded_buy_blocked") is True
    assert md2.get("ai_degraded_buy_blocked") is True


# ---- _extract_signal_from_reasoning 纯函数 ----


def test_c3_x01_extract_buy() -> None:
    """AC-3.2: 提取 buy（置信度固定 70，既有行为）。"""
    assert (
        AIClient._extract_signal_from_reasoning(
            "分析完毕。最终结论: buy confidence:80%"
        )
        == "buy confidence:70%"
    )


def test_c3_x03_extract_miss() -> None:
    """AC-3.2: 无关键词返回空串。"""
    assert AIClient._extract_signal_from_reasoning("") == ""
    assert AIClient._extract_signal_from_reasoning("   ") == ""
    assert AIClient._extract_signal_from_reasoning("没有明确结论") == ""


def test_c3_x04_tail_only() -> None:
    """AC-3.2 边界: 仅看尾部 500 字符。"""
    text = "sell " * 200 + "buy"
    assert AIClient._extract_signal_from_reasoning(text) == "buy confidence:70%"


# ---- 配置 / env ----


def test_c3_k01_default_enabled() -> None:
    """AC-3.1: block_degraded_buy 默认 True。"""
    assert AIConfig().block_degraded_buy is True


def test_c3_k02_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-3.1: from_env 读取 AI_BLOCK_DEGRADED_BUY（仅 'true' 生效）。"""
    monkeypatch.setenv("AI_BLOCK_DEGRADED_BUY", "false")
    assert AIConfig.from_env().block_degraded_buy is False
    monkeypatch.setenv("AI_BLOCK_DEGRADED_BUY", "TRUE")
    assert AIConfig.from_env().block_degraded_buy is True
    monkeypatch.delenv("AI_BLOCK_DEGRADED_BUY", raising=False)
    assert AIConfig.from_env().block_degraded_buy is True


def test_c3_k03_from_env_one_is_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-3.1 边界: '1' 不识别为 true（记录现状）。"""
    monkeypatch.setenv("AI_BLOCK_DEGRADED_BUY", "1")
    assert AIConfig.from_env().block_degraded_buy is False


# ---- reasoning 提取置位标志（_call_ai 真实代码路径）----


class _FakeResponse:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload
        self.status = 200

    async def json(self) -> Dict[str, Any]:
        return self._payload


class _FakeResponseCtx:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(self, *args: Any) -> bool:
        return False


class _FakeSession:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False

    def post(self, *args: Any, **kwargs: Any) -> _FakeResponseCtx:
        return _FakeResponseCtx(_FakeResponse(self._payload))


@pytest.mark.asyncio
async def test_c3_e01_reasoning_extraction_sets_degraded_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-3.2: content 空 + reasoning 提取成功 → 置位 _last_signal_degraded。"""
    config = AIConfig(
        mode="single", default_provider="deepseek", api_keys={"deepseek": "k"}
    )
    client = AIClient(config=config, api_keys=config.api_keys, enable_cache=False)
    client._last_signal_degraded = False

    payload = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "reasoning_content": "...最终结论: buy confidence:80%",
                }
            }
        ]
    }

    def fake_client_session(*args: Any, **kwargs: Any) -> _FakeSession:
        return _FakeSession(payload)

    monkeypatch.setattr("aiohttp.ClientSession", fake_client_session)
    monkeypatch.setattr(
        "alpha_trading_bot.ai.client.build_prompt",
        lambda md, provider="default": "prompt",
    )

    result = await client._call_ai("deepseek", {"technical": {"rsi": 45}}, "k")

    assert result == "buy confidence:70%"
    assert client._last_signal_degraded is True
    assert client.get_metrics()["reasoning_fallback_hits"] >= 1


@pytest.mark.asyncio
async def test_c3_e02_normal_content_keeps_flag_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-3.2: 正常 content → 标志保持 False。"""
    config = AIConfig(
        mode="single", default_provider="deepseek", api_keys={"deepseek": "k"}
    )
    client = AIClient(config=config, api_keys=config.api_keys, enable_cache=False)
    client._last_signal_degraded = False

    payload = {
        "choices": [
            {"message": {"content": "buy | confidence: 70%", "reasoning_content": ""}}
        ]
    }

    def fake_client_session(*args: Any, **kwargs: Any) -> _FakeSession:
        return _FakeSession(payload)

    monkeypatch.setattr("aiohttp.ClientSession", fake_client_session)
    monkeypatch.setattr(
        "alpha_trading_bot.ai.client.build_prompt",
        lambda md, provider="default": "prompt",
    )

    result = await client._call_ai("deepseek", {"technical": {"rsi": 45}}, "k")

    assert result == "buy | confidence: 70%"
    assert client._last_signal_degraded is False
