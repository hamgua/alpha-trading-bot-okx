"""
AIClient × Jev 快车道集成单元测试
（走真实 _call_ai HTTP 路径，aiohttp mock 记录 prompt；
get_signal 全链路返回大写信号，断言按大写惯例）
"""

from typing import Any, Dict, List, Optional

import pytest

from alpha_trading_bot.ai.client import AIClient
from alpha_trading_bot.ai.jev.fast_lane import FastLaneResult
from alpha_trading_bot.config.models import AIConfig


class _FakeBreakerView:
    def get_stats(self) -> Dict[str, Any]:
        return {"circuit_state": "closed", "consecutive_failures": 0}


class _FakeConfig:
    mode = "on"


class _FakeFastLane:
    """Mock 快车道：可控 adopt/escalate，记录 decide 调用。"""

    def __init__(self, result: FastLaneResult) -> None:
        self._result = result
        self.decide_calls = 0
        self.breaker = _FakeBreakerView()
        self.config = _FakeConfig()

    async def decide(self, market_data: Dict[str, Any]) -> FastLaneResult:
        self.decide_calls += 1
        return self._result

    def get_stats(self) -> Dict[str, int]:
        return {
            "fast_lane_adopted": 0,
            "fast_lane_escalated": 0,
            "fast_lane_errors": 0,
        }


class _FakeResponse:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload
        self.status = 200

    async def json(self) -> Dict[str, Any]:
        return self._payload

    async def text(self) -> str:
        return "fake"


class _FakeResponseCtx:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(self, *args: Any) -> bool:
        return False


class _CapturingSession:
    """mock aiohttp session：记录 post 次数与 prompt 内容。"""

    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload
        self.calls = 0
        self.prompts: List[str] = []

    async def __aenter__(self) -> "_CapturingSession":
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False

    def post(
        self, url: str, headers: Any = None, json: Any = None, timeout: Any = None
    ) -> _FakeResponseCtx:
        self.calls += 1
        if json and "messages" in json:
            self.prompts.append(json["messages"][0]["content"])
        return _FakeResponseCtx(_FakeResponse(self._payload))


LLM_PAYLOAD = {"choices": [{"message": {"content": "buy confidence:80%"}}]}

MARKET_DATA: Dict[str, Any] = {
    "symbol": "BTC-USDT",
    "price": 118000.0,
    "high": 119000.0,
    "low": 116000.0,
    "volume": 1000.0,
    "change_percent": 1.0,
    "technical": {
        "rsi": 55.0,
        "macd_hist": 1.0,
        "trend_direction": "up",
        "trend_strength": 0.2,
        "adx": 18.0,
        "atr_percent": 2.0,
        "bb_position": 0.6,
    },
    "recent_drop_percent": 0.0,
    "short_term_drop_percent": 0.0,
    "short_term_rise_percent": 0.5,
    "price_history": [117500.0 + i for i in range(20)],
    "hourly_changes": [0.001] * 12,
}


def make_client(
    fast_lane: Optional[_FakeFastLane],
    monkeypatch: pytest.MonkeyPatch,
    llm_session: _CapturingSession,
    enable_cache: bool = False,
) -> AIClient:
    config = AIConfig(
        mode="single", default_provider="deepseek", api_keys={"deepseek": "k"}
    )
    monkeypatch.setattr("aiohttp.ClientSession", lambda *a, **k: llm_session)
    return AIClient(config=config, fast_lane=fast_lane, enable_cache=enable_cache)


@pytest.mark.asyncio
async def test_adopted_signal_skips_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Jev adopted：LLM HTTP 不被调用，信号仍走下游集成器。Review Focus #4。"""
    monkeypatch.setenv("AI_FAST_LANE", "off")
    session = _CapturingSession(LLM_PAYLOAD)
    fast_lane = _FakeFastLane(
        FastLaneResult(adopted=True, signal="buy", confidence=0.9, reason="adopt")
    )
    client = make_client(fast_lane, monkeypatch, session)

    market_data = dict(MARKET_DATA)
    signal = await client.get_signal(market_data)

    assert session.calls == 0  # LLM 未被调用
    assert fast_lane.decide_calls == 1
    # 终态仍来自集成器（快车道不绕过下游安全层）
    assert "ai_final_confidence" in market_data
    # get_signal 全链路大写信号惯例
    assert signal in ("BUY", "HOLD", "SELL", "SHORT")


@pytest.mark.asyncio
async def test_escalated_injects_jev_context_into_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """升级路径：LLM 被调用且 prompt 含 Jev 初读。"""
    monkeypatch.setenv("AI_FAST_LANE", "off")
    session = _CapturingSession(LLM_PAYLOAD)
    fast_lane = _FakeFastLane(
        FastLaneResult(
            adopted=False,
            reason="low_confidence",
            jev_context="[Jev初读] 倾向=BUY (置信 0.62) ...",
        )
    )
    client = make_client(fast_lane, monkeypatch, session)

    await client.get_signal(dict(MARKET_DATA))

    assert session.calls == 1
    assert len(session.prompts) == 1
    assert "[Jev初读]" in session.prompts[0]


@pytest.mark.asyncio
async def test_escalated_without_context_keeps_prompt_plain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """升级但 jev_context=None（如 shadow 模式）：LLM prompt 与旧版一致。"""
    monkeypatch.setenv("AI_FAST_LANE", "off")
    session = _CapturingSession(LLM_PAYLOAD)
    fast_lane = _FakeFastLane(FastLaneResult(adopted=False, reason="shadow"))
    client = make_client(fast_lane, monkeypatch, session)

    await client.get_signal(dict(MARKET_DATA))

    assert session.calls == 1
    assert "快速模型初读" not in session.prompts[0]


@pytest.mark.asyncio
async def test_no_fast_lane_behavior_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """回归：fast_lane=None（AI_FAST_LANE=off）→ 纯 LLM 旧路径。"""
    monkeypatch.setenv("AI_FAST_LANE", "off")
    session = _CapturingSession(LLM_PAYLOAD)
    client = make_client(None, monkeypatch, session)
    assert client._fast_lane is None

    await client.get_signal(dict(MARKET_DATA))

    assert session.calls == 1
    assert "[Jev初读]" not in session.prompts[0]


@pytest.mark.asyncio
async def test_cache_hit_skips_both_jev_and_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """缓存命中：Jev decide 与 LLM 均被跳过。"""
    monkeypatch.setenv("AI_FAST_LANE", "off")
    session = _CapturingSession(LLM_PAYLOAD)
    fast_lane = _FakeFastLane(
        FastLaneResult(adopted=False, reason="low_confidence", jev_context="ctx")
    )
    config = AIConfig(
        mode="single", default_provider="deepseek", api_keys={"deepseek": "k"}
    )
    monkeypatch.setattr("aiohttp.ClientSession", lambda *a, **k: session)
    client = AIClient(config=config, fast_lane=fast_lane, enable_cache=True)

    await client.get_signal(dict(MARKET_DATA))
    await client.get_signal(dict(MARKET_DATA))

    assert fast_lane.decide_calls == 1  # 第二次缓存命中，Jev 未再调用
    assert session.calls == 1


def test_get_metrics_includes_fast_lane_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_FAST_LANE", "off")
    session = _CapturingSession(LLM_PAYLOAD)
    fast_lane = _FakeFastLane(FastLaneResult(adopted=False, reason="low_confidence"))
    client = make_client(fast_lane, monkeypatch, session)
    metrics = client.get_metrics()
    assert metrics["fast_lane_adopted"] == 0
    assert metrics["fast_lane_escalated"] == 0
    assert metrics["fast_lane_errors"] == 0
    assert metrics["fast_lane_circuit_open"] == 0


@pytest.mark.asyncio
async def test_init_fast_lane_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_init_fast_lane：AI_FAST_LANE=on 时自建（生产可达性）；off 时 None。"""
    monkeypatch.setenv("AI_FAST_LANE", "off")
    config = AIConfig(
        mode="single", default_provider="deepseek", api_keys={"deepseek": "k"}
    )
    client = AIClient(config=config, api_keys=config.api_keys, enable_cache=False)
    assert client._fast_lane is None

    monkeypatch.setenv("AI_FAST_LANE", "on")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    client2 = AIClient(config=config, api_keys=config.api_keys, enable_cache=False)
    assert client2._fast_lane is not None
    assert client2._fast_lane.config.mode == "on"
    assert client2._fast_lane.config.api_key == "test-key"
