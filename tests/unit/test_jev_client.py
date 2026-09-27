"""
JevClient HTTP 客户端单元测试（aiohttp mock，沿用项目惯例）
"""

import asyncio
from typing import Any, Dict, List, Union

import pytest

from alpha_trading_bot.ai.jev.config import JevFastLaneConfig
from alpha_trading_bot.ai.jev.questions import JEV_QUESTIONS
from alpha_trading_bot.ai.jev.typesafe_client import (
    JevClient,
    TypeSafeAPIError,
    TypeSafeAuthError,
    TypeSafeTimeoutError,
)


class _FakeResponse:
    def __init__(self, payload: Any = None, status: int = 200) -> None:
        self._payload = payload
        self.status = status

    async def json(self) -> Any:
        return self._payload

    async def text(self) -> str:
        if isinstance(self._payload, str):
            return self._payload
        return "fake-body"


class _FakeResponseCtx:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(self, *args: Any) -> bool:
        return False


class _FakeSession:
    """按序回放响应/异常，并记录 post 调用。"""

    def __init__(self, sequence: List[Union[_FakeResponse, Exception]]) -> None:
        self._sequence = list(sequence)
        self.posts: List[Dict[str, Any]] = []

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False

    def post(
        self, url: str, headers: Any = None, json: Any = None, timeout: Any = None
    ) -> _FakeResponseCtx:
        self.posts.append(
            {"url": url, "headers": headers, "json": json, "timeout": timeout}
        )
        if not self._sequence:
            raise AssertionError("unexpected extra POST")
        item = self._sequence.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeResponseCtx(item)


OK_PAYLOAD = {
    "answers": {
        "trade_decision": {
            "type": "choice",
            "choice": "buy",
            "probabilities": {
                "buy": 0.8,
                "hold": 0.1,
                "sell": 0.08,
                "short": 0.02,
            },
            "confidence": 0.78,
        },
        "is_high_risk_reversal": {"type": "noul", "noul": 0.31},
        "is_choppy_no_edge": {"type": "noul", "noul": 0.6},
    }
}


def make_config(**overrides: Any) -> JevFastLaneConfig:
    base = dict(api_key="test-key", mode="on", timeout_seconds=2.0)
    base.update(overrides)
    return JevFastLaneConfig(**base)


def patch_session(monkeypatch: pytest.MonkeyPatch, session: _FakeSession) -> None:
    def factory(*args: Any, **kwargs: Any) -> _FakeSession:
        return session

    monkeypatch.setattr("aiohttp.ClientSession", factory)


@pytest.mark.asyncio
async def test_system_one_request_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """请求 URL/headers/body 符合官方契约。"""
    session = _FakeSession([_FakeResponse(OK_PAYLOAD)])
    patch_session(monkeypatch, session)

    client = JevClient(make_config())
    response = await client.system_one("state-text", JEV_QUESTIONS)

    assert len(session.posts) == 1
    post = session.posts[0]
    assert post["url"] == "https://api.typesafe.ai/v1/systemone"
    assert post["headers"]["Authorization"] == "Bearer test-key"
    body = post["json"]
    assert body["model"] == "jev-1.13.0"
    assert body["state"] == "state-text"
    assert set(body["questions"].keys()) == {
        "trade_decision",
        "is_high_risk_reversal",
        "is_choppy_no_edge",
    }
    assert body["questions"]["trade_decision"]["type"] == "choice"
    assert body["questions"]["is_high_risk_reversal"]["type"] == "noul"

    decision = response.answers["trade_decision"]
    assert decision.choice == "buy"
    assert decision.confidence == 0.78


@pytest.mark.asyncio
async def test_missing_api_key_raises_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Key 为空：不发网络请求，直接 AuthError。"""
    session = _FakeSession([])
    patch_session(monkeypatch, session)
    client = JevClient(make_config(api_key=""))
    with pytest.raises(TypeSafeAuthError):
        await client.system_one("s", JEV_QUESTIONS)
    assert session.posts == []


@pytest.mark.asyncio
async def test_401_raises_auth_error_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """401 不重试（欠费/封停由熔断器管冷却）。"""
    session = _FakeSession([_FakeResponse("invalid api key", status=401)])
    patch_session(monkeypatch, session)
    client = JevClient(make_config())
    with pytest.raises(TypeSafeAuthError):
        await client.system_one("s", JEV_QUESTIONS)
    assert len(session.posts) == 1


@pytest.mark.asyncio
async def test_500_retries_twice_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5xx 最多重试 2 次：500,500,200 → 成功，共 3 次调用。"""
    session = _FakeSession(
        [
            _FakeResponse("boom", status=500),
            _FakeResponse("boom", status=500),
            _FakeResponse(OK_PAYLOAD),
        ]
    )
    patch_session(monkeypatch, session)
    client = JevClient(make_config())
    client.BASE_DELAY = 0.0  # 跳过退避等待
    response = await client.system_one("s", JEV_QUESTIONS)
    assert response.answers["trade_decision"].choice == "buy"
    assert len(session.posts) == 3


@pytest.mark.asyncio
async def test_429_exhausts_retries_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """429 重试耗尽 → TypeSafeAPIError(retryable=True)，共 3 次调用。"""
    session = _FakeSession([_FakeResponse("slow down", status=429)] * 3)
    patch_session(monkeypatch, session)
    client = JevClient(make_config())
    client.BASE_DELAY = 0.0
    with pytest.raises(TypeSafeAPIError) as exc_info:
        await client.system_one("s", JEV_QUESTIONS)
    assert exc_info.value.retryable is True
    assert len(session.posts) == 3


@pytest.mark.asyncio
async def test_404_no_retry_raises_api_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """4xx（非 401/402）不重试。"""
    session = _FakeSession([_FakeResponse("not found", status=404)])
    patch_session(monkeypatch, session)
    client = JevClient(make_config())
    with pytest.raises(TypeSafeAPIError) as exc_info:
        await client.system_one("s", JEV_QUESTIONS)
    assert exc_info.value.retryable is False
    assert len(session.posts) == 1


@pytest.mark.asyncio
async def test_timeout_raises_timeout_error_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """超时不重试，抛 TypeSafeTimeoutError。"""
    session = _FakeSession([asyncio.TimeoutError()])
    patch_session(monkeypatch, session)
    client = JevClient(make_config())
    with pytest.raises(TypeSafeTimeoutError):
        await client.system_one("s", JEV_QUESTIONS)
    assert len(session.posts) == 1
