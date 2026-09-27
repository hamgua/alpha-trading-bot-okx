"""
TypeSafe 类型化问答与响应解析单元测试
"""

import pytest

from alpha_trading_bot.ai.jev.typesafe_client import (
    ChoiceAnswer,
    JevChoiceQuestion,
    JevNoulQuestion,
    JevScoreQuestion,
    NoulAnswer,
    ScoreAnswer,
    SystemOneResponse,
    TypeSafeAPIError,
    _redact,
    parse_system_one_response,
)


def test_question_payloads_match_api_contract() -> None:
    """to_payload 输出符合官方 API 请求格式。"""
    choice = JevChoiceQuestion(
        instructions="判断交易方向",
        criteria={"buy": "看多", "hold": "观望"},
    )
    score = JevScoreQuestion(instructions="动量强度", criteria=["弱", "强"])
    noul = JevNoulQuestion(instructions="风险陈述是否成立")

    assert choice.to_payload() == {
        "type": "choice",
        "instructions": "判断交易方向",
        "criteria": {"buy": "看多", "hold": "观望"},
    }
    assert score.to_payload() == {
        "type": "score",
        "instructions": "动量强度",
        "criteria": ["弱", "强"],
    }
    assert noul.to_payload() == {
        "type": "noul",
        "instructions": "风险陈述是否成立",
    }


def test_parse_full_response() -> None:
    """正常响应：choice/score/noul 三类均解析为类型化答案。"""
    payload = {
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
            "momentum": {
                "type": "score",
                "score": 1.43,
                "probabilities": {"0": 0.0, "1": 0.57, "2": 0.43},
                "confidence": 0.35,
                "legend": {"0": "弱", "1": "中", "2": "强"},
            },
            "is_risky": {"type": "noul", "noul": 0.31},
        }
    }
    response = parse_system_one_response(payload)
    assert isinstance(response, SystemOneResponse)

    decision = response.answers["trade_decision"]
    assert isinstance(decision, ChoiceAnswer)
    assert decision.choice == "buy"
    assert decision.probabilities["buy"] == 0.8
    assert decision.confidence == 0.78

    momentum = response.answers["momentum"]
    assert isinstance(momentum, ScoreAnswer)
    assert momentum.score == 1.43
    assert momentum.legend["1"] == "中"

    risky = response.answers["is_risky"]
    assert isinstance(risky, NoulAnswer)
    assert risky.noul == 0.31


def test_parse_missing_confidence_defaults_to_zero() -> None:
    """confidence 缺失 → 0.0（等价于强制升级 LLM，永不采用）。Review Focus #1。"""
    payload = {
        "answers": {
            "trade_decision": {
                "type": "choice",
                "choice": "buy",
                "probabilities": {"buy": 0.9},
            }
        }
    }
    decision = parse_system_one_response(payload).answers["trade_decision"]
    assert isinstance(decision, ChoiceAnswer)
    assert decision.confidence == 0.0
    assert decision.probabilities == {"buy": 0.9}


def test_parse_missing_probabilities_defaults_to_empty() -> None:
    """probabilities 缺失 → 空 dict（调用方按 confidence 判断）。"""
    payload = {
        "answers": {
            "trade_decision": {
                "type": "choice",
                "choice": "hold",
                "confidence": 0.6,
            }
        }
    }
    decision = parse_system_one_response(payload).answers["trade_decision"]
    assert isinstance(decision, ChoiceAnswer)
    assert decision.probabilities == {}


def test_parse_missing_answers_field_raises() -> None:
    with pytest.raises(TypeSafeAPIError):
        parse_system_one_response({"foo": "bar"})


def test_parse_unknown_answer_type_raises() -> None:
    with pytest.raises(TypeSafeAPIError):
        parse_system_one_response({"answers": {"q": {"type": "wat", "wat": 1}}})


def test_parse_choice_without_choice_field_raises() -> None:
    with pytest.raises(TypeSafeAPIError):
        parse_system_one_response(
            {"answers": {"q": {"type": "choice", "confidence": 0.5}}}
        )


def test_redact_masks_keys() -> None:
    """错误文本脱敏：Bearer/sk- 令牌不明文出现在日志。"""
    text = "error: Bearer abc.def-123 and sk-abcdefghijklmnopqrstuvwxyz leaked"
    redacted = _redact(text)
    assert "abc.def-123" not in redacted
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in redacted
    assert "[REDACTED]" in redacted
