"""
AIClient 快车道接线测试

覆盖:
- 采用路径: 跳过 LLM（_call_ai 不被调用），返回大写信号（与其他路径一致）
- 升级路径: jev_context 透传到 _call_ai
- 无快车道: 行为完全不变
- get_metrics 新增计数
"""

from typing import Any, Dict, Optional

import pytest

from alpha_trading_bot.ai.client import AIClient
from alpha_trading_bot.config.models import AIConfig

MARKET_DATA: Dict[str, Any] = {
    "symbol": "BTC-USDT",
    "price": 118000.0,
    "technical": {"rsi": 50.0},
    "price_history": [117000.0 + i for i in range(30)],
}


class FakeLaneResult:
    def __init__(
        self,
        adopted: bool,
        signal: str = "",
        confidence: float = 0.0,
        jev_context: Optional[str] = None,
    ) -> None:
        self.adopted = adopted
        self.signal = signal
        self.confidence = confidence
        self.probabilities: Dict[str, float] = {}
        self.jev_context = jev_context
        self.reason = "test"
        self.latency_ms = 10.0


class FakeFastLane:
    def __init__(self, result: FakeLaneResult) -> None:
        self._result = result
        self.calls = 0

    async def decide(self, market_data: Dict[str, Any]) -> FakeLaneResult:
        self.calls += 1
        return self._result


def make_client(fast_lane: Optional[FakeFastLane], mode: str = "single") -> AIClient:
    config = AIConfig(
        mode=mode, default_provider="deepseek", api_keys={"deepseek": "k"}
    )
    return AIClient(
        config=config,
        api_keys=config.api_keys,
        enable_cache=False,
        fast_lane=fast_lane,
    )


@pytest.mark.asyncio
async def test_adopted_signal_skips_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review Focus #4: 采用路径必须跳过 LLM（_call_ai 零调用）。"""

    async def failing_call_ai(*args: Any, **kwargs: Any) -> str:
        raise AssertionError("LLM 不应被调用（Jev 已采用）")

    monkeypatch.setattr(AIClient, "_call_ai", failing_call_ai)

    lane = FakeFastLane(FakeLaneResult(adopted=True, signal="buy", confidence=0.9))
    client = make_client(lane)
    signal = await client.get_signal(dict(MARKET_DATA))
    # get_signal 统一返回大写信号（与其他路径一致）
    assert signal == "BUY"
    assert lane.calls == 1


@pytest.mark.asyncio
async def test_escalation_passes_jev_context_to_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: Dict[str, Any] = {}

    async def fake_call_ai(
        self,
        provider: str,
        market_data: Dict[str, Any],
        api_key: str,
        jev_context: Optional[str] = None,
    ) -> str:
        captured["provider"] = provider
        captured["jev_context"] = jev_context
        return '{"signal": "buy", "confidence": 90}'

    monkeypatch.setattr(AIClient, "_call_ai", fake_call_ai)

    lane = FakeFastLane(
        FakeLaneResult(
            adopted=False,
            signal="buy",
            confidence=0.6,
            jev_context="[Jev初读] signal=buy conf=0.60",
        )
    )
    client = make_client(lane)
    signal = await client.get_signal(dict(MARKET_DATA))
    assert signal == "BUY"
    assert captured["provider"] == "deepseek"
    assert captured["jev_context"] == "[Jev初读] signal=buy conf=0.60"


@pytest.mark.asyncio
async def test_escalation_without_context_sends_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """升级但无 jev_context（如 shadow 模式）→ _call_ai 收到 None（旧行为）。"""
    captured: Dict[str, Any] = {}

    async def fake_call_ai(
        self,
        provider: str,
        market_data: Dict[str, Any],
        api_key: str,
        jev_context: Optional[str] = None,
    ) -> str:
        captured["jev_context"] = jev_context
        return '{"signal": "hold", "confidence": 50}'

    monkeypatch.setattr(AIClient, "_call_ai", fake_call_ai)

    lane = FakeFastLane(FakeLaneResult(adopted=False, signal="buy", confidence=0.9))
    client = make_client(lane)
    signal = await client.get_signal(dict(MARKET_DATA))
    assert signal == "HOLD"
    assert captured["jev_context"] is None


@pytest.mark.asyncio
async def test_no_fast_lane_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """无快车道：_call_ai 正常调用且 jev_context 参数为 None（默认值）。"""
    captured: Dict[str, Any] = {}

    async def fake_call_ai(
        self,
        provider: str,
        market_data: Dict[str, Any],
        api_key: str,
        jev_context: Optional[str] = None,
    ) -> str:
        captured["jev_context"] = jev_context
        return '{"signal": "buy", "confidence": 90}'

    monkeypatch.setattr(AIClient, "_call_ai", fake_call_ai)

    client = make_client(None)
    signal = await client.get_signal(dict(MARKET_DATA))
    assert signal == "BUY"
    assert captured["jev_context"] is None


@pytest.mark.asyncio
async def test_get_metrics_includes_fast_lane_counters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_call_ai(*args: Any, **kwargs: Any) -> str:
        raise AssertionError("LLM 不应被调用")

    monkeypatch.setattr(AIClient, "_call_ai", failing_call_ai)

    lane = FakeFastLane(FakeLaneResult(adopted=True, signal="buy", confidence=0.9))
    client = make_client(lane)
    await client.get_signal(dict(MARKET_DATA))
    metrics = client.get_metrics()
    assert metrics["fast_lane_adopted"] == 1
    assert metrics["fast_lane_escalated"] == 0
    assert metrics["fast_lane_errors"] == 0
