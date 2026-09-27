"""
JevFastLane 决策矩阵单元测试（mock JevClient）
"""

import logging
from typing import Any, Dict, Optional

import pytest

from alpha_trading_bot.ai.jev.config import JevFastLaneConfig
from alpha_trading_bot.ai.jev.fast_lane import JevFastLane
from alpha_trading_bot.ai.jev.typesafe_client import (
    ChoiceAnswer,
    NoulAnswer,
    SystemOneResponse,
    TypeSafeAPIError,
    TypeSafeAuthError,
    TypeSafeTimeoutError,
)

MARKET_DATA: Dict[str, Any] = {
    "symbol": "BTC-USDT",
    "price": 118000.0,
    "technical": {"rsi": 55.0},
}


class _FakeJevClient:
    """Mock JevClient：返回固定响应或抛固定异常。"""

    def __init__(
        self,
        response: Optional[SystemOneResponse] = None,
        error: Optional[Exception] = None,
    ) -> None:
        self._response = response
        self._error = error
        self.calls = 0

    async def system_one(
        self, state: str, questions: Dict[str, Any]
    ) -> SystemOneResponse:
        self.calls += 1
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def make_response(
    choice: str = "buy",
    confidence: float = 0.9,
    risk: float = 0.2,
    choppy: float = 0.3,
) -> SystemOneResponse:
    probabilities = {choice: confidence, "hold": round(1.0 - confidence, 2)}
    return SystemOneResponse(
        answers={
            "trade_decision": ChoiceAnswer(
                choice=choice, probabilities=probabilities, confidence=confidence
            ),
            "is_high_risk_reversal": NoulAnswer(noul=risk),
            "is_choppy_no_edge": NoulAnswer(noul=choppy),
        }
    )


def make_lane(fake_client: _FakeJevClient, **overrides: Any) -> JevFastLane:
    base = dict(mode="on", api_key="k", conf_buy=0.75, conf_sell=0.75, conf_hold=0.50)
    base.update(overrides)
    return JevFastLane(JevFastLaneConfig(**base), client=fake_client)


@pytest.mark.asyncio
async def test_adopt_high_confidence_buy() -> None:
    client = _FakeJevClient(response=make_response("buy", 0.9))
    lane = make_lane(client)
    result = await lane.decide(MARKET_DATA)
    assert result.adopted is True
    assert result.signal == "buy"
    assert result.reason == "adopt"
    assert result.confidence == 0.9
    assert client.calls == 1


@pytest.mark.asyncio
async def test_adopt_high_confidence_sell_and_short() -> None:
    for choice in ("sell", "short"):
        client = _FakeJevClient(response=make_response(choice, 0.8))
        lane = make_lane(client)
        result = await lane.decide(MARKET_DATA)
        assert result.adopted is True
        assert result.signal == choice


@pytest.mark.asyncio
async def test_adopt_hold_at_medium_confidence() -> None:
    """HOLD 是安全默认动作：中置信度(0.5)即可采用。"""
    client = _FakeJevClient(response=make_response("hold", 0.5))
    lane = make_lane(client)
    result = await lane.decide(MARKET_DATA)
    assert result.adopted is True
    assert result.signal == "hold"


@pytest.mark.asyncio
async def test_buy_below_threshold_escalates_with_context() -> None:
    client = _FakeJevClient(response=make_response("buy", 0.6))
    lane = make_lane(client)
    result = await lane.decide(MARKET_DATA)
    assert result.adopted is False
    assert result.reason == "low_confidence"
    assert result.jev_context is not None
    assert "[Jev初读]" in result.jev_context
    assert "buy=0.60" in result.jev_context


@pytest.mark.asyncio
async def test_hold_below_threshold_escalates() -> None:
    client = _FakeJevClient(response=make_response("hold", 0.4))
    lane = make_lane(client)
    result = await lane.decide(MARKET_DATA)
    assert result.adopted is False
    assert result.reason == "low_confidence"


@pytest.mark.asyncio
async def test_risk_gate_overrides_high_confidence() -> None:
    """安全旗标一票否决：高置信也强制升级 LLM。"""
    client = _FakeJevClient(response=make_response("buy", 0.99, risk=0.85))
    lane = make_lane(client, risk_noul_gate=0.70)
    result = await lane.decide(MARKET_DATA)
    assert result.adopted is False
    assert result.reason == "risk_gate"
    assert result.jev_context is not None


@pytest.mark.asyncio
async def test_shadow_never_adopts() -> None:
    """shadow 观察模式：永不采用，记录本应采用的信号，不改 LLM prompt。"""
    client = _FakeJevClient(response=make_response("buy", 0.99))
    lane = make_lane(client, mode="shadow")
    result = await lane.decide(MARKET_DATA)
    assert result.adopted is False
    assert result.reason == "shadow"
    assert result.signal == "buy"
    assert result.jev_context is None


@pytest.mark.asyncio
async def test_disabled_mode_makes_no_network_call() -> None:
    client = _FakeJevClient(response=make_response())
    lane = make_lane(client, mode="off")
    result = await lane.decide(MARKET_DATA)
    assert result.adopted is False
    assert result.reason == "disabled"
    assert client.calls == 0


@pytest.mark.asyncio
async def test_missing_key_makes_no_network_call_and_warns_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """mode=on 但 Key 为空：无网络调用、一次性 WARNING。Review Focus #3。"""
    caplog.set_level(logging.INFO)
    client = _FakeJevClient(response=make_response())
    lane = make_lane(client, api_key="")
    first = await lane.decide(MARKET_DATA)
    second = await lane.decide(MARKET_DATA)
    assert first.reason == "disabled"
    assert second.reason == "disabled"
    assert client.calls == 0
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1  # 只告警一次


@pytest.mark.asyncio
async def test_auth_error_opens_circuit_and_escalates() -> None:
    client = _FakeJevClient(error=TypeSafeAuthError("402"))
    lane = make_lane(client)
    result = await lane.decide(MARKET_DATA)
    assert result.adopted is False
    assert result.reason == "auth_error"
    # 第二次：熔断打开，不再发网络请求
    second = await lane.decide(MARKET_DATA)
    assert second.reason == "circuit_open"
    assert client.calls == 1
    assert lane.get_stats()["fast_lane_errors"] == 1


@pytest.mark.asyncio
async def test_timeout_escalates_and_counts_errors() -> None:
    client = _FakeJevClient(error=TypeSafeTimeoutError("timeout"))
    lane = make_lane(client, failure_threshold=99)  # 不触发熔断，验证升级路径
    result = await lane.decide(MARKET_DATA)
    assert result.adopted is False
    assert result.reason == "timeout"
    assert lane.get_stats()["fast_lane_errors"] == 1


@pytest.mark.asyncio
async def test_api_error_escalates() -> None:
    client = _FakeJevClient(error=TypeSafeAPIError("500", retryable=True))
    lane = make_lane(client, failure_threshold=99)
    result = await lane.decide(MARKET_DATA)
    assert result.adopted is False
    assert result.reason == "api_error"


@pytest.mark.asyncio
async def test_bad_response_shape_escalates() -> None:
    """主问题响应缺失/类型错 → bad_response 升级，不抛异常。"""
    client = _FakeJevClient(response=SystemOneResponse(answers={}))
    lane = make_lane(client)
    result = await lane.decide(MARKET_DATA)
    assert result.adopted is False
    assert result.reason == "bad_response"
