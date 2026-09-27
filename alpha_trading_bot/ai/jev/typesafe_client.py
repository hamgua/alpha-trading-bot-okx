"""
TypeSafe (Jev) System One 客户端

- 异常: TypeSafeAuthError / TypeSafeAPIError / TypeSafeTimeoutError
- 类型化答案: ChoiceAnswer / ScoreAnswer / NoulAnswer
- 类型化问题: JevChoiceQuestion / JevScoreQuestion / JevNoulQuestion
- 响应解析: parse_system_one_response（纯函数，可单测）
- HTTP 客户端: JevClient（Task 4 追加）

设计约束（见 spec）：不引入 vendor SDK，aiohttp 直连
POST {base_url}/v1/systemone。
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Union

from alpha_trading_bot.core.exceptions import AIProviderError

logger = logging.getLogger(__name__)


# ---------- 异常（继承项目异常层次，AGENTS.md 要求） ----------


class TypeSafeError(AIProviderError):
    """TypeSafe API 通用异常基类"""


class TypeSafeAuthError(TypeSafeError):
    """鉴权失败 (401/402)：Key 无效 / 账户欠费 / 服务被封停"""


class TypeSafeAPIError(TypeSafeError):
    """API 错误 (429/5xx/其他 4xx、网络错误、响应解析失败)"""

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class TypeSafeTimeoutError(TypeSafeError):
    """请求超时"""


# ---------- 类型化答案 ----------


@dataclass
class ChoiceAnswer:
    """Choice 类型答案：选中项 + 全概率分布 + 置信度"""

    choice: str
    probabilities: Dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0


@dataclass
class ScoreAnswer:
    """Score 类型答案：分数（等级号数线上的位置）+ 概率分布 + 置信度"""

    score: float
    probabilities: Dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    legend: Dict[str, str] = field(default_factory=dict)


@dataclass
class NoulAnswer:
    """Noul 类型答案：单值（"是"的概率，0-1）"""

    noul: float


Answer = Union[ChoiceAnswer, ScoreAnswer, NoulAnswer]


@dataclass
class SystemOneResponse:
    """system_one 响应：每个问题 id 对应一个答案"""

    answers: Dict[str, Answer] = field(default_factory=dict)


# ---------- 类型化问题 ----------


@dataclass
class JevChoiceQuestion:
    """Choice 问题：从固定选项集合中选一个"""

    instructions: str
    criteria: Dict[str, str]

    def to_payload(self) -> Dict[str, Any]:
        return {
            "type": "choice",
            "instructions": self.instructions,
            "criteria": dict(self.criteria),
        }


@dataclass
class JevScoreQuestion:
    """Score 问题：谱系上的位置（criteria 有序数组，2-10 级）"""

    instructions: str
    criteria: List[str]

    def to_payload(self) -> Dict[str, Any]:
        return {
            "type": "score",
            "instructions": self.instructions,
            "criteria": list(self.criteria),
        }


@dataclass
class JevNoulQuestion:
    """Noul 问题：陈述是否成立（"是"的概率，0-1）"""

    instructions: str

    def to_payload(self) -> Dict[str, Any]:
        return {"type": "noul", "instructions": self.instructions}


JevQuestion = Union[JevChoiceQuestion, JevScoreQuestion, JevNoulQuestion]


# ---------- 响应解析（纯函数） ----------


def parse_system_one_response(payload: Dict[str, Any]) -> SystemOneResponse:
    """
    把 system_one 的原始 JSON payload 解析为类型化响应。

    Args:
        payload: HTTP 响应 body（{"answers": {id: answer}}）

    Returns:
        SystemOneResponse

    Raises:
        TypeSafeAPIError: 响应结构异常（answers 缺失/类型未知/必填字段缺失）
    """
    if not isinstance(payload, dict) or "answers" not in payload:
        raise TypeSafeAPIError(f"TypeSafe 响应缺少 answers 字段: {str(payload)[:200]}")
    raw_answers = payload["answers"]
    if not isinstance(raw_answers, dict):
        raise TypeSafeAPIError("TypeSafe 响应 answers 不是 dict")

    answers: Dict[str, Answer] = {}
    for qid, raw in raw_answers.items():
        answers[qid] = _parse_single_answer(raw)
    return SystemOneResponse(answers=answers)


def _parse_single_answer(raw: Any) -> Answer:
    """解析单个问题答案；优先 type 字段，缺失时按字段存在性回退判断。"""
    if not isinstance(raw, dict):
        raise TypeSafeAPIError(f"TypeSafe 答案结构异常: {str(raw)[:120]}")
    qtype = str(raw.get("type", "")).lower()
    if qtype == "choice" or "choice" in raw:
        choice = raw.get("choice")
        if not isinstance(choice, str):
            raise TypeSafeAPIError(f"Choice 答案缺少 choice 字段: {str(raw)[:120]}")
        return ChoiceAnswer(
            choice=choice,
            probabilities=_parse_probabilities(raw.get("probabilities")),
            confidence=_parse_confidence(raw.get("confidence")),
        )
    if qtype == "score" or "score" in raw:
        return ScoreAnswer(
            score=float(raw.get("score", 0.0)),
            probabilities=_parse_probabilities(raw.get("probabilities")),
            confidence=_parse_confidence(raw.get("confidence")),
            legend=_parse_legend(raw.get("legend")),
        )
    if qtype == "noul" or "noul" in raw:
        return NoulAnswer(noul=float(raw.get("noul", 0.0)))
    raise TypeSafeAPIError(
        f"未知 TypeSafe 答案类型: {qtype or '(缺失)'}: {str(raw)[:120]}"
    )


def _parse_probabilities(raw: Any) -> Dict[str, float]:
    """宽容解析概率分布：缺失/畸形 → 空 dict（调用方按 confidence 判断）。"""
    if not isinstance(raw, dict):
        return {}
    result: Dict[str, float] = {}
    for key, value in raw.items():
        try:
            result[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return result


def _parse_confidence(raw: Any) -> float:
    """宽容解析置信度：缺失/畸形 → 0.0（等价强制升级 LLM，永不采用）。"""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value))


def _parse_legend(raw: Any) -> Dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def _redact(text: str) -> str:
    """错误文本脱敏并截断（避免泄露 Key）。"""
    sanitized = re.sub(
        r"(bearer\s+)[a-z0-9._\-]+",
        r"\1[REDACTED]",
        text or "",
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"\bsk-[a-z0-9]{8,}\b", "[REDACTED]", sanitized, flags=re.IGNORECASE
    )
    return sanitized[:200]
