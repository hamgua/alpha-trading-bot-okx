"""AI 重试策略测试：瞬态错误（超时/网络/5xx）必须重试，确定性错误不重试。

背景（2026-10-04 生产事故）：qwen38 自建端点 TCP 挂起 90s 超时，
_call_ai 抛出中文 ValueError("AI[qwen38]请求超时")，_should_retry_error
只匹配英文关键词（timeout/connection/429...）→ 重试逻辑（MAX_RETRIES=3
指数退避）对该类错误全部失效，"尝试1次" 即放弃，整周期中止。
同一缺陷也解释了 9/28 qwen38 HTTP 503 连发 42 周期中断（"HTTP 503"
不含任何重试关键词）。
"""

from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from alpha_trading_bot.ai.client import AIClient


def _make_client() -> AIClient:
    """最小 AIClient（不触发外部依赖）。"""
    return AIClient()


@pytest.mark.asyncio
async def test_timeout_error_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """中文超时错误（_call_ai 包装后）必须触发重试。"""
    client = _make_client()
    monkeypatch.setattr(AIClient, "BASE_DELAY", 0.01)

    calls: List[int] = []

    async def fake_call_ai(
        provider: str,
        market_data: Dict[str, Any],
        api_key: str,
        jev_context: Any = None,
    ) -> str:
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("AI[qwen38]请求超时")
        return "hold confidence:80%"

    monkeypatch.setattr(client, "_call_ai", fake_call_ai)

    result = await client._call_ai_with_retry("qwen38", {}, "sk-x")

    assert result == "hold confidence:80%"
    assert len(calls) == 3  # 前两次超时被重试，第三次成功


@pytest.mark.asyncio
async def test_http_503_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 503（服务端瞬时过载）必须触发重试。"""
    client = _make_client()
    monkeypatch.setattr(AIClient, "BASE_DELAY", 0.01)

    calls: List[int] = []

    async def fake_call_ai(
        provider: str,
        market_data: Dict[str, Any],
        api_key: str,
        jev_context: Any = None,
    ) -> str:
        calls.append(1)
        if len(calls) < 2:
            raise ValueError("AI[qwen38]HTTP 503")
        return "hold confidence:70%"

    monkeypatch.setattr(client, "_call_ai", fake_call_ai)

    result = await client._call_ai_with_retry("qwen38", {}, "sk-x")

    assert result == "hold confidence:70%"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_network_error_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """中文网络错误（aiohttp ClientError 包装后）必须触发重试。"""
    client = _make_client()
    monkeypatch.setattr(AIClient, "BASE_DELAY", 0.01)

    calls: List[int] = []

    async def fake_call_ai(
        provider: str,
        market_data: Dict[str, Any],
        api_key: str,
        jev_context: Any = None,
    ) -> str:
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("AI[qwen38]网络错误: ")
        return "hold confidence:60%"

    monkeypatch.setattr(client, "_call_ai", fake_call_ai)

    # aiohttp 异常 str 常为空，中文包装前缀"网络错误"本身必须是重试关键词
    result = await client._call_ai_with_retry("qwen38", {}, "sk-x")
    assert result == "hold confidence:60%"


@pytest.mark.asyncio
async def test_balance_error_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """余额不足是确定性错误，重试无意义——只尝试 1 次并抛出。"""
    client = _make_client()
    monkeypatch.setattr(AIClient, "BASE_DELAY", 0.01)

    calls: List[int] = []

    async def fake_call_ai(
        provider: str,
        market_data: Dict[str, Any],
        api_key: str,
        jev_context: Any = None,
    ) -> str:
        calls.append(1)
        raise ValueError("AI[qwen38]余额不足，请检查API账户余额")

    monkeypatch.setattr(client, "_call_ai", fake_call_ai)

    with pytest.raises(ValueError, match="余额不足"):
        await client._call_ai_with_retry("qwen38", {}, "sk-x")

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_retry_exhaustion_raises_last_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3 次全失败 → 抛出最后一次错误（行为与既有语义一致）。"""
    client = _make_client()
    monkeypatch.setattr(AIClient, "BASE_DELAY", 0.01)

    async def fake_call_ai(
        provider: str,
        market_data: Dict[str, Any],
        api_key: str,
        jev_context: Any = None,
    ) -> str:
        raise ValueError("AI[qwen38]请求超时")

    monkeypatch.setattr(client, "_call_ai", fake_call_ai)

    with pytest.raises(ValueError, match="请求超时"):
        await client._call_ai_with_retry("qwen38", {}, "sk-x")


def test_timeout_config_has_connect_deadline() -> None:
    """连接阶段必须有独立短超时（sock_connect），推理阶段仍用 total。

    端点 TCP 挂起时不应耗完整个 90s（含推理预算），否则 3 次重试
    在一个 15 分钟周期内根本排不下；连接 15s 失败 → 3 次尝试共约
    50s，瞬态故障可在周期内恢复。
    """
    client = _make_client()
    timeout = client._get_timeout_config("qwen38")
    assert timeout.total == 90  # 推理总预算不变
    assert timeout.sock_connect == 15  # 连接阶段 15s 快速失败


def test_all_providers_have_connect_deadline() -> None:
    """所有 provider 的连接超时统一 15s（健康端点连接 <1s，无行为影响）。"""
    client = _make_client()
    for provider in (
        "kimi",
        "deepseek",
        "openai",
        "qwen",
        "gemini",
        "minimax",
        "qwen38",
    ):
        timeout = client._get_timeout_config(provider)
        assert timeout.sock_connect == 15, provider
