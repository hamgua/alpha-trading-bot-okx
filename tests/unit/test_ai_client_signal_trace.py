"""AIClient 信号溯源测试（P1 决策日志的数据源）"""

from typing import Any, Dict

import pytest

from alpha_trading_bot.ai.client import AIClient
from alpha_trading_bot.ai.jev.fast_lane import FastLaneResult
from alpha_trading_bot.config.models import AIConfig


class _FakeFastLane:
    def __init__(self, result: FastLaneResult) -> None:
        self._result = result

    async def decide(self, market_data: Dict[str, Any]) -> FastLaneResult:
        return self._result

    def get_stats(self) -> Dict[str, int]:
        return {"fast_lane_adopted": 0, "fast_lane_escalated": 0, "fast_lane_errors": 0}

    @property
    def breaker(self):
        class _V:
            def get_stats(self) -> Dict[str, Any]:
                return {"circuit_state": "closed"}

        return _V()

    @property
    def config(self):
        class _C:
            mode = "on"

        return _C()


def _make_client(result: FastLaneResult, llm_signal: str = "hold") -> AIClient:
    client = AIClient(
        config=AIConfig(),
        api_keys={"qwen38": "fake-key"},
        enable_cache=False,
        fast_lane=_FakeFastLane(result),
    )

    async def _fake_llm(market_data, jev_context=None):
        return llm_signal, 0.5

    client._get_llm_signal = _fake_llm  # type: ignore[assignment]
    return client


MARKET = {"symbol": "BTC/USDT:USDT", "price": 84000.0, "price_history": [84000.0] * 20}


def _adopted_result() -> FastLaneResult:
    return FastLaneResult(
        adopted=True,
        signal="hold",
        confidence=0.95,
        probabilities={"hold": 0.95},
        reason="adopt",
        latency_ms=180.0,
        risk_noul=0.2,
        choppy_noul=0.5,
    )


def _escalated_result() -> FastLaneResult:
    return FastLaneResult(
        adopted=False,
        signal="buy",
        confidence=0.4,
        probabilities={"buy": 0.5, "hold": 0.4},
        reason="low_confidence",
        latency_ms=190.0,
        jev_context="[Jev初读] ...",
        risk_noul=0.1,
        choppy_noul=0.6,
    )


class _FakeIntegratorResult:
    """mock 集成器结果：final=BUY（用于触发 degraded-buy 改写）。"""

    def __init__(self) -> None:
        self.final_signal = "BUY"
        self.final_confidence = 0.5
        self.is_high_risk = False
        self.is_low_opportunity = False
        self.price_level = "mid"
        self.adjustments_made: list = []


class _FakeIntegrator:
    """mock 集成器：process 返回固定 final=BUY 的结果。"""

    def process(
        self,
        market_data: Dict[str, Any] = None,
        original_signal: str = "",
        original_confidence: float = 0.5,
    ) -> _FakeIntegratorResult:
        return _FakeIntegratorResult()


@pytest.mark.asyncio
async def test_adopted_trace_has_jev_no_llm() -> None:
    client = _make_client(_adopted_result())
    await client.get_signal(dict(MARKET))
    t = client.get_last_signal_trace()
    assert t["cache_hit"] is False
    assert t["jev"]["choice"] == "hold"
    assert t["jev"]["confidence"] == 0.95
    assert t["jev"]["reason"] == "adopt"
    assert t["jev"]["risk_noul"] == 0.2
    assert t["llm"] is None
    assert t["integrator"]["final_signal"].upper() in ("HOLD", "BUY", "SELL", "SHORT")


@pytest.mark.asyncio
async def test_escalated_trace_has_jev_and_llm() -> None:
    client = _make_client(_escalated_result())
    await client.get_signal(dict(MARKET))
    t = client.get_last_signal_trace()
    assert t["jev"]["choice"] == "buy"
    assert t["jev"]["reason"] == "low_confidence"
    assert t["llm"]["signal"] == "hold"
    assert t["llm"]["confidence"] == 0.5
    assert t["llm"]["jev_context_injected"] is True
    assert t["llm"]["provider"]  # 非空


def test_trace_empty_before_any_call() -> None:
    client = _make_client(_adopted_result())
    assert client.get_last_signal_trace() == {}


@pytest.mark.asyncio
async def test_no_fast_lane_regression() -> None:
    """fast_lane=None（AI_FAST_LANE=off）：trace 无 jev 段，行为回归不变。"""
    client = AIClient(
        config=AIConfig(),
        api_keys={"qwen38": "fake-key"},
        enable_cache=False,
        fast_lane=None,
    )

    async def _fake_llm(market_data, jev_context=None):
        return "hold", 0.5

    client._get_llm_signal = _fake_llm  # type: ignore[assignment]
    await client.get_signal(dict(MARKET))
    t = client.get_last_signal_trace()
    assert t["jev"] is None
    assert t["llm"] is not None


@pytest.mark.asyncio
async def test_degraded_buy_trace_final_matches_return() -> None:
    """降级路径：final=BUY 被改写为 HOLD，trace 的 final_signal 必须等于实际返回。"""
    client = AIClient(
        config=AIConfig(),
        api_keys={"qwen38": "fake-key"},
        enable_cache=False,
        fast_lane=None,
    )
    client.integrator = _FakeIntegrator()  # type: ignore[assignment]

    async def _fake_llm(market_data, jev_context=None):
        # 模拟 provider 从 reasoning_content 提取信号（降级标记）
        client._last_signal_degraded = True
        return "buy", 0.5

    client._get_llm_signal = _fake_llm  # type: ignore[assignment]
    signal = await client.get_signal(dict(MARKET))
    t = client.get_last_signal_trace()
    assert signal == "HOLD"
    assert t["integrator"]["final_signal"] == signal
    assert t["integrator"]["final_signal"] == "HOLD"
