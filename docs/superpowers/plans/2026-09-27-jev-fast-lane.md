# Jev Fast Lane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 AI 信号获取增加 Jev（TypeSafe System One）快速车道：Jev 高置信时直接采用其结构化信号、跳过 LLM；低置信/风险旗标/超时/错误时升级 LLM 做最终裁决（Jev 初读注入 prompt 上下文）；Jev 账户故障（欠费/封停/瞬态）时熔断器自动降级为纯 LLM 架构。

**Architecture:** 新增 `alpha_trading_bot/ai/jev/` 包（config / HTTP client / questions / fast_lane+熔断器），在 `AIClient.get_signal` 的 LLM 分支之前插入 `fast_lane.decide()`：adopted → 直接采用；escalated → 走现有 single/fusion 路径并携带 `jev_context`。下游 `AISignalIntegrator`、风控、下单链路零改动。

**Tech Stack:** Python（mypy target 3.9），aiohttp（已有依赖，**不新增依赖**），pytest + pytest-asyncio，dataclasses。

**Spec:** `docs/superpowers/specs/2026-09-27-jev-fast-lane-design.md`

## Global Constraints

- 代码风格：black `line-length=88`；文件末尾必须有换行；无行尾空白；4 空格缩进。
- 类型系统：mypy strict（`disallow_untyped_defs`），所有函数必须有完整类型标注；禁止 `# type: ignore`；类型标注用 `from typing import ...` 风格（不依赖 `from __future__ import annotations`）。
- 异常：继承 `alpha_trading_bot.core.exceptions` 层次（TypeSafe 系列继承 `AIProviderError`）；禁止 bare except；raise 前先 `logger.error/warning`。
- HTTP：aiohttp 直连 `POST {base_url}/v1/systemone`；**禁止**引入 `typesafe-sdk` vendor SDK。
- 业务逻辑注释用中文；模块 docstring 用中文。
- 默认 `AI_FAST_LANE=off`：合入后行为零变化，现有全量测试必须保持绿色。
- 信号词表固定 `buy/hold/sell/short`（与 `alpha_trading_bot/ai/response_parser.py` 的 `VALID_SIGNALS` 一致）。
- 测试约定：pytest + `@pytest.mark.asyncio`；HTTP mock 沿用 `monkeypatch.setattr("aiohttp.ClientSession", ...)`（参照 `tests/unit/test_degraded_buy_block.py`）。
- TypeSafe API 契约：Header `Authorization: Bearer <TYPESAFE_API_KEY>`；body `{"model": ..., "state": ..., "questions": {id: {...}}}`；响应 `{"answers": {id: answer}}`；Choice 答案含 `choice`/`probabilities`/`confidence`，Noul 答案含 `noul`。
- 每个 commit 前运行本任务新增测试 + 对改动文件跑 `black --check`（装了 pre-commit 会自动修复格式）。

## Review Focus

spec 隐含但 happy-path 测试未覆盖的失败模式，各由所在任务的测试钉住：

1. **TypeSafe 响应缺 `confidence` 字段**（API 版本漂移）→ 解析为 0.0，快车道永不采用，强制升级 LLM。→ Task 2 `test_parse_missing_confidence_defaults_to_zero`。
2. **`market_data` 缺 `technical`/`position`/`price_history`**（上游数据服务降级）→ `build_state` 跳过缺键、不抛异常。→ Task 3 `test_build_state_missing_keys_no_error`。
3. **`AI_FAST_LANE=on/shadow` 但 `TYPESAFE_API_KEY` 为空** → 无网络调用、一次性 WARNING、LLM 路径不受影响。→ Task 6 `test_missing_key_makes_no_network_call_and_warns_once`。
4. **Jev adopted 信号绕过下游集成器/风控**（绝不能发生）→ adopted 路径照常走 `AISignalIntegrator`。→ Task 8 `test_adopted_signal_skips_llm`。
5. **half-open 探测失败且为瞬态错误** → 重新 OPEN 新冷却，不能卡死在 half_open。→ Task 5 `test_half_open_transient_failure_reopens`。

---

### Task 1: JevFastLaneConfig + 包骨架 + .env.example

**Files:**
- Create: `alpha_trading_bot/ai/jev/__init__.py`
- Create: `alpha_trading_bot/ai/jev/config.py`
- Modify: `.env.example`（QWEN38_API_KEY 行之后插入 Jev 配置块）
- Test: `tests/unit/test_jev_config.py`

**Interfaces:**
- Consumes: `alpha_trading_bot.config.models.AIConfig.from_env` 的 env 读取模式（参考，不 import）
- Produces:
  - `JevFastLaneConfig`（dataclass），字段：`mode: str = "off"`、`api_key: str = ""`、`model: str = "jev-1.13.0"`、`base_url: str = "https://api.typesafe.ai"`、`timeout_seconds: float = 5.0`、`conf_buy: float = 0.75`、`conf_sell: float = 0.75`、`conf_hold: float = 0.50`、`risk_noul_gate: float = 0.70`、`failure_threshold: int = 3`、`cooldown_seconds: int = 600`、`auth_cooldown_seconds: int = 21600`；类属性 `VALID_MODES = ("off", "shadow", "on")`
  - `JevFastLaneConfig.from_env() -> JevFastLaneConfig`
  - `JevFastLaneConfig.validate() -> List[str]`

- [ ] **Step 1: 写失败测试**

创建 `tests/unit/test_jev_config.py`：

```python
"""
Jev 快车道配置单元测试
"""

import pytest

from alpha_trading_bot.ai.jev.config import JevFastLaneConfig


def test_defaults_are_safe() -> None:
    """默认配置：off 模式、默认阈值、无 Key → 合入即零行为变化。"""
    config = JevFastLaneConfig()
    assert config.mode == "off"
    assert config.api_key == ""
    assert config.model == "jev-1.13.0"
    assert config.base_url == "https://api.typesafe.ai"
    assert config.timeout_seconds == 5.0
    assert config.conf_buy == 0.75
    assert config.conf_sell == 0.75
    assert config.conf_hold == 0.50
    assert config.risk_noul_gate == 0.70
    assert config.failure_threshold == 3
    assert config.cooldown_seconds == 600
    assert config.auth_cooldown_seconds == 21600
    assert config.validate() == []


def test_from_env_reads_all_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """from_env 读取各环境变量并归一化（mode 小写、Key 去空白、base_url 去尾部斜杠）。"""
    monkeypatch.setenv("AI_FAST_LANE", " SHADOW ")
    monkeypatch.setenv("TYPESAFE_API_KEY", " ts_key_123 ")
    monkeypatch.setenv("TYPESAFE_MODEL", "jev-latest")
    monkeypatch.setenv("TYPESAFE_BASE_URL", "https://api.typesafe.ai/")
    monkeypatch.setenv("JEV_TIMEOUT", "8.5")
    monkeypatch.setenv("JEV_CONF_BUY", "0.8")
    monkeypatch.setenv("JEV_CONF_SELL", "0.8")
    monkeypatch.setenv("JEV_CONF_HOLD", "0.6")
    monkeypatch.setenv("JEV_RISK_NOUL_GATE", "0.75")
    monkeypatch.setenv("JEV_CB_FAILURES", "5")
    monkeypatch.setenv("JEV_CB_COOLDOWN", "120")
    monkeypatch.setenv("JEV_CB_AUTH_COOLDOWN", "3600")

    config = JevFastLaneConfig.from_env()
    assert config.mode == "shadow"
    assert config.api_key == "ts_key_123"
    assert config.model == "jev-latest"
    assert config.base_url == "https://api.typesafe.ai"
    assert config.timeout_seconds == 8.5
    assert config.conf_buy == 0.8
    assert config.conf_sell == 0.8
    assert config.conf_hold == 0.6
    assert config.risk_noul_gate == 0.75
    assert config.failure_threshold == 5
    assert config.cooldown_seconds == 120
    assert config.auth_cooldown_seconds == 3600
    assert config.validate() == []


def test_from_env_invalid_values_produce_validation_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非法环境变量不被吞掉：validate 返回对应错误。"""
    monkeypatch.setenv("AI_FAST_LANE", "turbo")
    monkeypatch.setenv("JEV_CONF_BUY", "1.5")
    monkeypatch.setenv("JEV_TIMEOUT", "-1")
    monkeypatch.setenv("JEV_CB_FAILURES", "0")

    config = JevFastLaneConfig.from_env()
    errors = config.validate()
    assert any("mode" in e for e in errors)
    assert any("conf_buy" in e for e in errors)
    assert any("JEV_TIMEOUT" in e for e in errors)
    assert any("failure_threshold" in e for e in errors)
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_jev_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'alpha_trading_bot.ai.jev'`

- [ ] **Step 3: 最小实现**

创建 `alpha_trading_bot/ai/jev/config.py`：

```python
"""
Jev 快车道配置

从环境变量读取（对齐 AIConfig.from_env 模式）。
off/shadow/on 三档模式；默认 off 保证合入后零行为变化。
"""

import os
from dataclasses import dataclass
from typing import List


@dataclass
class JevFastLaneConfig:
    """Jev (TypeSafe System One) 快车道配置"""

    # off=关闭 / shadow=只观察(永不采用) / on=启用快车道
    mode: str = "off"
    api_key: str = ""
    # 官方建议 pin 固定版本，避免 jev-latest 移动指针漂移
    model: str = "jev-1.13.0"
    base_url: str = "https://api.typesafe.ai"

    # 快车道总超时（秒）；超时即升级 LLM
    timeout_seconds: float = 5.0

    # 非对称置信度阈值 (0-1)：BUY/SELL/SHORT 高门槛，HOLD 可更低
    conf_buy: float = 0.75
    conf_sell: float = 0.75
    conf_hold: float = 0.50

    # 安全旗标：反转风险 Noul 超过此值强制升级 LLM
    risk_noul_gate: float = 0.70

    # 熔断器
    failure_threshold: int = 3  # 连续瞬态失败 N 次后打开
    cooldown_seconds: int = 600  # 瞬态故障熔断冷却（秒）
    auth_cooldown_seconds: int = 21600  # 欠费/鉴权失败熔断冷却（秒，6h）

    VALID_MODES = ("off", "shadow", "on")

    def validate(self) -> List[str]:
        """验证配置，返回错误列表（空列表=有效）。"""
        errors: List[str] = []
        if self.mode not in self.VALID_MODES:
            errors.append(
                f"Jev快车道模式 '{self.mode}' 无效，可选: {list(self.VALID_MODES)}"
            )
        if self.timeout_seconds <= 0:
            errors.append(f"JEV_TIMEOUT {self.timeout_seconds} 必须 > 0")
        for name, value in (
            ("conf_buy", self.conf_buy),
            ("conf_sell", self.conf_sell),
            ("conf_hold", self.conf_hold),
        ):
            if not 0.0 < value <= 1.0:
                errors.append(f"{name} {value} 不在有效范围 (0, 1]")
        if not 0.0 < self.risk_noul_gate < 1.0:
            errors.append(f"risk_noul_gate {self.risk_noul_gate} 不在有效范围 (0, 1)")
        if self.failure_threshold < 1:
            errors.append(f"failure_threshold {self.failure_threshold} 必须 >= 1")
        if self.cooldown_seconds <= 0 or self.auth_cooldown_seconds <= 0:
            errors.append("熔断冷却秒数必须 > 0")
        return errors

    @classmethod
    def from_env(cls) -> "JevFastLaneConfig":
        """从环境变量读取（对齐 AIConfig.from_env 模式）。"""
        return cls(
            mode=os.getenv("AI_FAST_LANE", "off").strip().lower(),
            api_key=os.getenv("TYPESAFE_API_KEY", "").strip(),
            model=os.getenv("TYPESAFE_MODEL", "jev-1.13.0").strip() or "jev-1.13.0",
            base_url=os.getenv(
                "TYPESAFE_BASE_URL", "https://api.typesafe.ai"
            ).rstrip("/"),
            timeout_seconds=float(os.getenv("JEV_TIMEOUT", "5.0")),
            conf_buy=float(os.getenv("JEV_CONF_BUY", "0.75")),
            conf_sell=float(os.getenv("JEV_CONF_SELL", "0.75")),
            conf_hold=float(os.getenv("JEV_CONF_HOLD", "0.50")),
            risk_noul_gate=float(os.getenv("JEV_RISK_NOUL_GATE", "0.70")),
            failure_threshold=int(os.getenv("JEV_CB_FAILURES", "3")),
            cooldown_seconds=int(os.getenv("JEV_CB_COOLDOWN", "600")),
            auth_cooldown_seconds=int(os.getenv("JEV_CB_AUTH_COOLDOWN", "21600")),
        )
```

创建 `alpha_trading_bot/ai/jev/__init__.py`（本任务先只导出 config，后续任务逐步扩展）：

```python
"""
Jev (TypeSafe System One) 快车道

- config: JevFastLaneConfig（env 配置）
- typesafe_client: TypeSafe HTTP 客户端与类型化问答
- questions: 问题集与市场状态序列化
- fast_lane: 快车道决策（置信度门控 + 风险旗标 + 熔断器）
"""

from .config import JevFastLaneConfig

__all__ = [
    "JevFastLaneConfig",
]
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_jev_config.py -v`
Expected: 3 passed

- [ ] **Step 5: 更新 .env.example**

修改 `.env.example`，在 QWEN38_API_KEY 行之后插入 Jev 配置块（oldText 锚点为该行，替换为该行+新块）：

oldText:
```
QWEN38_API_KEY=sk-anything                               # 自建 Qwen3.8-27B (ninfer) API Key，不校验，占位即可
```

newText:
```
QWEN38_API_KEY=sk-anything                               # 自建 Qwen3.8-27B (ninfer) API Key，不校验，占位即可

# ---- Jev 快车道 (TypeSafe System One 模型) ----
AI_FAST_LANE=off                                         # Jev快车道模式: off=关闭(默认) / shadow=只观察不采用 / on=启用
TYPESAFE_API_KEY=                                        # TypeSafe API Key (Jev)，AI_FAST_LANE != off 时必填
TYPESAFE_MODEL=jev-1.13.0                                # Jev 模型版本（建议 pin 固定版本）
TYPESAFE_BASE_URL=https://api.typesafe.ai                # TypeSafe API 基础地址
JEV_TIMEOUT=5.0                                          # 快车道请求超时(秒)，超时升级LLM
JEV_CONF_BUY=0.75                                        # BUY 采用的最低置信度
JEV_CONF_SELL=0.75                                       # SELL/SHORT 采用的最低置信度
JEV_CONF_HOLD=0.50                                       # HOLD 采用的最低置信度（安全默认动作，可更低）
JEV_RISK_NOUL_GATE=0.70                                  # 反转风险Noul超过此值强制升级LLM
JEV_CB_FAILURES=3                                        # 连续瞬态失败N次后打开熔断
JEV_CB_COOLDOWN=600                                      # 瞬态故障熔断冷却(秒)
JEV_CB_AUTH_COOLDOWN=21600                               # 欠费/鉴权失败熔断冷却(秒, 6h)
```

- [ ] **Step 6: Commit**

```bash
git add alpha_trading_bot/ai/jev/ tests/unit/test_jev_config.py .env.example
git commit -m "feat(jev): JevFastLaneConfig env 配置与 .env.example"
```

---

### Task 2: TypeSafe 类型化问答 + 响应解析（typesafe_client.py 纯逻辑部分）

**Files:**
- Create: `alpha_trading_bot/ai/jev/typesafe_client.py`（本任务：异常 + 答案/问题 dataclass + 解析函数；Task 4 追加 HTTP 客户端类）
- Modify: `alpha_trading_bot/ai/jev/__init__.py`（导出新增符号）
- Test: `tests/unit/test_jev_types.py`

**Interfaces:**
- Consumes: `alpha_trading_bot.core.exceptions.AIProviderError`
- Produces:
  - `TypeSafeError(AIProviderError)`、`TypeSafeAuthError`（401/402）、`TypeSafeAPIError`（构造参数 `message: str, retryable: bool = False`）、`TypeSafeTimeoutError`
  - `ChoiceAnswer(choice: str, probabilities: Dict[str, float], confidence: float)`
  - `ScoreAnswer(score: float, probabilities: Dict[str, float], confidence: float, legend: Dict[str, str])`
  - `NoulAnswer(noul: float)`
  - `Answer = Union[ChoiceAnswer, ScoreAnswer, NoulAnswer]`
  - `SystemOneResponse(answers: Dict[str, Answer])`
  - `JevChoiceQuestion(instructions: str, criteria: Dict[str, str])`、`JevScoreQuestion(instructions: str, criteria: List[str])`、`JevNoulQuestion(instructions: str)`；均有 `to_payload() -> Dict[str, Any]`
  - `JevQuestion = Union[JevChoiceQuestion, JevScoreQuestion, JevNoulQuestion]`
  - `parse_system_one_response(payload: Dict[str, Any]) -> SystemOneResponse`
  - `_redact(text: str) -> str`（模块级函数，可被测试 import）

- [ ] **Step 1: 写失败测试**

创建 `tests/unit/test_jev_types.py`：

```python
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
                "probabilities": {"buy": 0.8, "hold": 0.1, "sell": 0.08, "short": 0.02},
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
            "trade_decision": {"type": "choice", "choice": "hold", "confidence": 0.6}
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
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_jev_types.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'alpha_trading_bot.ai.jev.typesafe_client'`

- [ ] **Step 3: 最小实现**

创建 `alpha_trading_bot/ai/jev/typesafe_client.py`：

```python
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
```

把 `alpha_trading_bot/ai/jev/__init__.py` 更新为（不含 `JevClient`，Task 4 完成后再补）：

```python
"""
Jev (TypeSafe System One) 快车道

- config: JevFastLaneConfig（env 配置）
- typesafe_client: TypeSafe HTTP 客户端与类型化问答
- questions: 问题集与市场状态序列化
- fast_lane: 快车道决策（置信度门控 + 风险旗标 + 熔断器）
"""

from .config import JevFastLaneConfig
from .typesafe_client import (
    ChoiceAnswer,
    NoulAnswer,
    ScoreAnswer,
    SystemOneResponse,
    TypeSafeAPIError,
    TypeSafeAuthError,
    TypeSafeError,
    TypeSafeTimeoutError,
)

__all__ = [
    "JevFastLaneConfig",
    "ChoiceAnswer",
    "NoulAnswer",
    "ScoreAnswer",
    "SystemOneResponse",
    "TypeSafeAPIError",
    "TypeSafeAuthError",
    "TypeSafeError",
    "TypeSafeTimeoutError",
]
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_jev_types.py tests/unit/test_jev_config.py -v`
Expected: 全部 PASS（10 passed）

- [ ] **Step 5: Commit**

```bash
git add alpha_trading_bot/ai/jev/ tests/unit/test_jev_types.py
git commit -m "feat(jev): TypeSafe 类型化问答与响应解析"
```

---
### Task 3: 问题集 + 市场状态序列化（questions.py）

**Files:**
- Create: `alpha_trading_bot/ai/jev/questions.py`
- Modify: `alpha_trading_bot/ai/jev/__init__.py`（导出 `JEV_QUESTIONS`、`build_state`）
- Test: `tests/unit/test_jev_questions.py`

**Interfaces:**
- Consumes: `JevChoiceQuestion`、`JevNoulQuestion`、`JevQuestion`（Task 2）
- Produces:
  - `TRADE_DECISION: JevChoiceQuestion`（4 选项：buy/hold/sell/short）
  - `IS_HIGH_RISK_REVERSAL: JevNoulQuestion`、`IS_CHOPPY_NO_EDGE: JevNoulQuestion`
  - `JEV_QUESTIONS: Dict[str, JevQuestion]`（键：`trade_decision`/`is_high_risk_reversal`/`is_choppy_no_edge`）
  - `build_state(market_data: Dict[str, Any]) -> str`

- [ ] **Step 1: 写失败测试**

创建 `tests/unit/test_jev_questions.py`：

```python
"""
Jev 问题集与状态序列化单元测试
"""

from alpha_trading_bot.ai.jev.questions import JEV_QUESTIONS, build_state
from alpha_trading_bot.ai.jev.typesafe_client import (
    JevChoiceQuestion,
    JevNoulQuestion,
)


def test_question_set_structure() -> None:
    """问题集：1 个主 Choice（4 选项对齐 VALID_SIGNALS）+ 2 个辅助 Noul。"""
    assert set(JEV_QUESTIONS.keys()) == {
        "trade_decision",
        "is_high_risk_reversal",
        "is_choppy_no_edge",
    }
    decision = JEV_QUESTIONS["trade_decision"]
    assert isinstance(decision, JevChoiceQuestion)
    assert set(decision.criteria.keys()) == {"buy", "hold", "sell", "short"}
    # 每个选项必须有判别性描述（官方最佳实践：描述用于区分选项）
    for description in decision.criteria.values():
        assert isinstance(description, str) and len(description) > 5
    assert isinstance(JEV_QUESTIONS["is_high_risk_reversal"], JevNoulQuestion)
    assert isinstance(JEV_QUESTIONS["is_choppy_no_edge"], JevNoulQuestion)


def test_build_state_includes_key_fields() -> None:
    market_data = {
        "symbol": "BTC-USDT",
        "price": 118000.5,
        "high": 119000.0,
        "low": 116000.0,
        "volume": 12345.6,
        "change_percent": 1.2,
        "technical": {
            "rsi": 55.5,
            "macd_hist": 12.3456,
            "trend_direction": "up",
            "trend_strength": 0.3,
            "adx": 18.0,
        },
        "recent_drop_percent": -0.1,
        "short_term_rise_percent": 0.8,
        "position": {"side": "long", "amount": 0.05, "entry_price": 115000.0},
        "price_history": [117000.0 + i for i in range(30)],
    }
    state = build_state(market_data)
    assert "BTC-USDT" in state
    assert "118000" in state
    assert "rsi=55.5" in state
    assert "trend_direction=up" in state
    assert "macd_hist=12.35" in state  # _fmt 用 .4g
    assert "持仓" in state
    assert "近20根收盘价" in state
    assert len(state) < 4000  # 紧凑状态，不塞整段价格历史


def test_build_state_missing_keys_no_error() -> None:
    """缺 technical/position/price_history（数据服务降级）→ 不抛错、输出已有字段。
    Review Focus #2。"""
    state = build_state({"symbol": "ETH-USDT", "price": 3500.0})
    assert "ETH-USDT" in state
    assert "3500" in state

    empty = build_state({})
    assert "UNKNOWN" in empty


def test_build_state_skips_empty_position_and_history() -> None:
    state = build_state(
        {"symbol": "X-USDT", "price": 1.0, "position": {}, "price_history": []}
    )
    assert "持仓:" not in state
    assert "近20根收盘价" not in state


def test_build_state_dedupes_macd_hist_keys() -> None:
    """macd_hist 与 macd_histogram 指向同一指标，不同时输出。"""
    state = build_state(
        {
            "symbol": "X-USDT",
            "price": 1.0,
            "technical": {"macd_hist": 1.5, "macd_histogram": 1.5},
        }
    )
    assert "macd_histogram" not in state
    assert "macd_hist=1.5" in state
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_jev_questions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'alpha_trading_bot.ai.jev.questions'`

- [ ] **Step 3: 最小实现**

创建 `alpha_trading_bot/ai/jev/questions.py`：

```python
"""
Jev 问题集与市场状态序列化

- build_state: 把 market_data 序列化成紧凑结构化 state（目标 400-600 tokens；
  Jev 按 input token 计费，保持精简）
- JEV_QUESTIONS: 1 个主 Choice + 2 个辅助 Noul（官方最佳实践：一次请求问全、
  每个问题原子化；辅助问题只用于路由/上下文，不直接产生交易信号）

问题文案集中在此文件，便于按 shadow 观察结果迭代调参。
"""

from typing import Any, Dict, List

from .typesafe_client import JevChoiceQuestion, JevNoulQuestion, JevQuestion

# 主问题：四选项对齐 response_parser.VALID_SIGNALS
TRADE_DECISION = JevChoiceQuestion(
    instructions=(
        "根据当前加密货币市场状态（价格、技术指标、趋势、持仓），"
        "判断最合适的交易方向。仅基于数据判断，无明确优势时选 hold。"
    ),
    criteria={
        "buy": "趋势与技术指标支持做多入场（明确的上行结构与动能）",
        "hold": "无明确交易优势，趋势不明或信号不足，建议观望",
        "sell": "趋势与指标支持平多/减仓（上行结构破坏）",
        "short": "明确的看空结构，支持做空入场（下行动能持续）",
    },
)

# 安全旗标：反转风险（超过 risk_noul_gate → 强制升级 LLM）
IS_HIGH_RISK_REVERSAL = JevNoulQuestion(
    instructions=(
        "当前价格行为暗示即将发生急涨或急跌的反转风险"
        "（极端超买/超卖、剧烈插针、急速拉升等异常波动）"
    ),
)

# 上下文旗标：震荡无方向（升级 LLM 时的参考上下文）
IS_CHOPPY_NO_EDGE = JevNoulQuestion(
    instructions="市场处于无明确方向的震荡行情，缺乏交易优势",
)

JEV_QUESTIONS: Dict[str, JevQuestion] = {
    "trade_decision": TRADE_DECISION,
    "is_high_risk_reversal": IS_HIGH_RISK_REVERSAL,
    "is_choppy_no_edge": IS_CHOPPY_NO_EDGE,
}

# state 中输出的技术指标键（按优先级；macd_hist 与 macd_histogram 去重）
_TECH_KEYS = (
    "rsi",
    "macd",
    "macd_hist",
    "macd_histogram",
    "trend_direction",
    "trend_strength",
    "adx",
    "atr_percent",
    "bb_position",
)

# 持仓上下文中值得输出的键（bot.py 注入的 position 结构可能更大）
_POSITION_KEYS = (
    "side",
    "position_side",
    "amount",
    "size",
    "entry_price",
    "avg_entry_price",
    "pnl",
    "unrealized_pnl",
)


def _fmt(value: Any) -> str:
    """格式化单个指标值（float 用 .4g 精简）。"""
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def build_state(market_data: Dict[str, Any]) -> str:
    """
    把市场快照序列化成 Jev 的紧凑 state 文本。

    只取已有键，缺失键跳过不报错（上游数据服务可能不含 position/technical）。

    Args:
        market_data: AIClient.get_signal 接收的市场数据 dict

    Returns:
        紧凑结构化文本（每行一个信息块）
    """
    lines: List[str] = []

    symbol = market_data.get("symbol", "UNKNOWN")
    price = market_data.get("price", 0)
    lines.append(f"交易对: {symbol}")
    lines.append(
        f"价格: {price} | 24h高低: {market_data.get('high', 0)}/"
        f"{market_data.get('low', 0)} | 24h涨跌: "
        f"{market_data.get('change_percent', 0)}% | 成交量: {market_data.get('volume', 0)}"
    )

    technical = market_data.get("technical") or {}
    parts: List[str] = []
    emitted_macd_hist = False
    for key in _TECH_KEYS:
        if key not in technical:
            continue
        if key == "macd_histogram" and emitted_macd_hist:
            continue  # macd_hist 与 macd_histogram 同指标，只取前者
        if key == "macd_hist":
            emitted_macd_hist = True
        parts.append(f"{key}={_fmt(technical[key])}")
    if parts:
        lines.append("技术指标: " + ", ".join(parts))

    for key, label in (
        ("recent_drop_percent", "最新跌幅"),
        ("short_term_drop_percent", "短期跌幅"),
        ("short_term_rise_percent", "短期涨幅"),
    ):
        value = market_data.get(key)
        if value is not None:
            lines.append(f"{label}: {value}%")

    position = market_data.get("position")
    if isinstance(position, dict) and position:
        pos_parts = [
            f"{key}={_fmt(position[key])}" for key in _POSITION_KEYS if key in position
        ]
        if pos_parts:
            lines.append("持仓: " + ", ".join(pos_parts))

    history = market_data.get("price_history") or []
    if isinstance(history, (list, tuple)) and history:
        recent = [float(p) for p in history[-20:] if isinstance(p, (int, float))]
        if recent:
            lines.append("近20根收盘价: " + " ".join(f"{p:g}" for p in recent))

    return "\n".join(lines)
```

把 `alpha_trading_bot/ai/jev/__init__.py` 更新为（在 Task 2 版本基础上追加 questions 导出）：

```python
"""
Jev (TypeSafe System One) 快车道

- config: JevFastLaneConfig（env 配置）
- typesafe_client: TypeSafe HTTP 客户端与类型化问答
- questions: 问题集与市场状态序列化
- fast_lane: 快车道决策（置信度门控 + 风险旗标 + 熔断器）
"""

from .config import JevFastLaneConfig
from .questions import JEV_QUESTIONS, build_state
from .typesafe_client import (
    ChoiceAnswer,
    NoulAnswer,
    ScoreAnswer,
    SystemOneResponse,
    TypeSafeAPIError,
    TypeSafeAuthError,
    TypeSafeError,
    TypeSafeTimeoutError,
)

__all__ = [
    "JevFastLaneConfig",
    "ChoiceAnswer",
    "NoulAnswer",
    "ScoreAnswer",
    "SystemOneResponse",
    "TypeSafeAPIError",
    "TypeSafeAuthError",
    "TypeSafeError",
    "TypeSafeTimeoutError",
    "JEV_QUESTIONS",
    "build_state",
]
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_jev_questions.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add alpha_trading_bot/ai/jev/ tests/unit/test_jev_questions.py
git commit -m "feat(jev): 问题集与市场状态序列化"
```

---

### Task 4: JevClient HTTP 客户端（重试/超时/错误分类/脱敏）

**Files:**
- Modify: `alpha_trading_bot/ai/jev/typesafe_client.py`（追加 `JevClient` 类 + 更新 import）
- Modify: `alpha_trading_bot/ai/jev/__init__.py`（补 `JevClient` 导出）
- Test: `tests/unit/test_jev_client.py`

**Interfaces:**
- Consumes: `JevFastLaneConfig`（Task 1）、`JevQuestion.to_payload` / `parse_system_one_response` / 异常（Task 2）、`JEV_QUESTIONS`（Task 3）
- Produces:
  - `JevClient(config: JevFastLaneConfig)`，类属性 `MAX_RETRIES = 2`、`BASE_DELAY = 0.5`
  - `async JevClient.system_one(state: str, questions: Dict[str, JevQuestion]) -> SystemOneResponse`

- [ ] **Step 1: 写失败测试**

创建 `tests/unit/test_jev_client.py`：

```python
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
            "probabilities": {"buy": 0.8, "hold": 0.1, "sell": 0.08, "short": 0.02},
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


def patch_session(
    monkeypatch: pytest.MonkeyPatch, session: _FakeSession
) -> None:
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
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_jev_client.py -v`
Expected: FAIL — `ImportError: cannot import name 'JevClient'`

- [ ] **Step 3: 实现 JevClient**

修改 `alpha_trading_bot/ai/jev/typesafe_client.py`：

1) import 块更新：

oldText:
```python
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Union

from alpha_trading_bot.core.exceptions import AIProviderError
```

newText:
```python
import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

import aiohttp

from alpha_trading_bot.core.exceptions import AIProviderError

from .config import JevFastLaneConfig
```

2) 文件末尾追加 `JevClient` 类：

```python
# ---------- HTTP 客户端 ----------


class JevClient:
    """TypeSafe System One 异步 HTTP 客户端。

    - 单次 POST {base_url}/v1/systemone（契约见 spec References）
    - 429/5xx: 指数退避重试，最多 MAX_RETRIES 次
    - 401/402（欠费/Key 无效/封停）: 不重试，抛 TypeSafeAuthError（熔断器管冷却）
    - 超时: 不重试，抛 TypeSafeTimeoutError（快车道价值在速度，超时即升级 LLM）
    """

    MAX_RETRIES = 2
    BASE_DELAY = 0.5  # 退避基础延迟（秒）；测试可置 0

    def __init__(self, config: JevFastLaneConfig) -> None:
        self.config = config

    async def system_one(
        self, state: str, questions: Dict[str, JevQuestion]
    ) -> SystemOneResponse:
        """发起一次 system_one 请求，返回类型化响应。

        Raises:
            TypeSafeAuthError: 401/402 或 Key 未配置
            TypeSafeTimeoutError: 请求超时
            TypeSafeAPIError: 其他 API/网络/解析错误
        """
        if not self.config.api_key:
            raise TypeSafeAuthError("TYPESAFE_API_KEY 未配置")

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.config.model,
            "state": state,
            "questions": {
                qid: question.to_payload() for qid, question in questions.items()
            },
        }

        last_error: Optional[TypeSafeAPIError] = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                return await self._post_once(headers, payload)
            except (TypeSafeAuthError, TypeSafeTimeoutError):
                # 鉴权失败/超时没有重试价值，直接抛出让熔断器处理
                raise
            except TypeSafeAPIError as e:
                last_error = e
                if e.retryable and attempt < self.MAX_RETRIES:
                    delay = self.BASE_DELAY * (2**attempt)
                    logger.warning(
                        f"[Jev] 请求失败 ({e})，{delay:.1f}s 后重试 (第{attempt + 1}次)"
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
        # 防御性兜底：循环正常结束意味着未抛错（理论不可达）
        if last_error is None:
            raise TypeSafeAPIError("TypeSafe 调用失败且未捕获到明确异常")
        raise last_error

    async def _post_once(
        self, headers: Dict[str, str], payload: Dict[str, Any]
    ) -> SystemOneResponse:
        """发起单次 HTTP 请求并分类错误；重试策略由 system_one 处理。"""
        url = f"{self.config.base_url}/v1/systemone"
        timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, headers=headers, json=payload, timeout=timeout
                ) as response:
                    if response.status in (401, 402):
                        body = await response.text()
                        logger.error(
                            f"[Jev] 鉴权/欠费失败 status={response.status} "
                            f"body={_redact(body)}"
                        )
                        raise TypeSafeAuthError(
                            f"TypeSafe HTTP {response.status}: {_redact(body)}"
                        )
                    if response.status != 200:
                        body = await response.text()
                        logger.error(
                            f"[Jev] HTTP错误 status={response.status} "
                            f"body={_redact(body)}"
                        )
                        raise TypeSafeAPIError(
                            f"TypeSafe HTTP {response.status}: {_redact(body)}",
                            retryable=response.status == 429
                            or response.status >= 500,
                        )
                    result = await response.json()
        except asyncio.TimeoutError:
            logger.error(f"[Jev] 请求超时 (>{self.config.timeout_seconds}s)")
            raise TypeSafeTimeoutError(
                f"TypeSafe 请求超时 (>{self.config.timeout_seconds}s)"
            )
        except aiohttp.ClientError as e:
            logger.error(f"[Jev] 网络错误: {type(e).__name__}: {e}")
            raise TypeSafeAPIError(
                f"TypeSafe 网络错误: {type(e).__name__}: {e}", retryable=True
            )

        return parse_system_one_response(result)
```

3) 把 `alpha_trading_bot/ai/jev/__init__.py` 更新为最终形态（在 Task 3 版本基础上补 `JevClient`）：在 `from .typesafe_client import (` 的列表中加入 `JevClient,`（按字母序放在 `ChoiceAnswer,` 之后），并在 `__all__` 列表中加入 `"JevClient",`。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_jev_client.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add alpha_trading_bot/ai/jev/ tests/unit/test_jev_client.py
git commit -m "feat(jev): TypeSafe 异步 HTTP 客户端（重试/错误分类/脱敏）"
```

---

### Task 5: 熔断器 `_CircuitBreaker`（fast_lane.py 第一部分）

**Files:**
- Create: `alpha_trading_bot/ai/jev/fast_lane.py`（本任务：模块头 + import + `_CircuitBreaker`；Task 6 追加 `FastLaneResult`/`JevFastLane`）
- Test: `tests/unit/test_jev_circuit_breaker.py`

**Interfaces:**
- Consumes: `JevFastLaneConfig`（Task 1）、`TypeSafeAuthError` / `TypeSafeAPIError` / `TypeSafeTimeoutError`（Task 2）
- Produces:
  - `_CircuitBreaker(config: JevFastLaneConfig, now: Optional[Callable[[], float]] = None)`
  - `is_open() -> bool`（冷却到期时 open 自动转 half_open 并返回 False）
  - `record_success() -> None`、`record_failure(error: Exception) -> None`
  - `state -> str`（property：closed/open/half_open）
  - `get_stats() -> Dict[str, Any]`

- [ ] **Step 1: 写失败测试**

创建 `tests/unit/test_jev_circuit_breaker.py`：

```python
"""
Jev 熔断器单元测试（注入时钟驱动）
"""

from alpha_trading_bot.ai.jev.config import JevFastLaneConfig
from alpha_trading_bot.ai.jev.fast_lane import _CircuitBreaker
from alpha_trading_bot.ai.jev.typesafe_client import (
    TypeSafeAPIError,
    TypeSafeAuthError,
    TypeSafeTimeoutError,
)


class _Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def make_breaker(clock: _Clock) -> _CircuitBreaker:
    return _CircuitBreaker(
        JevFastLaneConfig(
            failure_threshold=3,
            cooldown_seconds=600,
            auth_cooldown_seconds=21600,
        ),
        now=clock,
    )


def test_starts_closed() -> None:
    breaker = make_breaker(_Clock())
    assert breaker.is_open() is False
    assert breaker.state == "closed"


def test_transient_failures_open_after_threshold() -> None:
    clock = _Clock()
    breaker = make_breaker(clock)
    breaker.record_failure(TypeSafeTimeoutError("t"))
    breaker.record_failure(TypeSafeAPIError("500"))
    assert breaker.is_open() is False  # 2 次失败未达阈值
    breaker.record_failure(TypeSafeAPIError("500"))
    assert breaker.is_open() is True  # 连续 3 次 → OPEN
    assert breaker.state == "open"


def test_transient_cooldown_duration() -> None:
    clock = _Clock(1000.0)
    breaker = make_breaker(clock)
    for _ in range(3):
        breaker.record_failure(TypeSafeAPIError("500"))
    clock.t = 1599.9
    assert breaker.is_open() is True  # 冷却期内
    clock.t = 1600.0
    assert breaker.is_open() is False  # 冷却到期 → half_open 放行探测
    assert breaker.state == "half_open"


def test_auth_failure_opens_immediately_with_long_cooldown() -> None:
    """欠费/封停（AuthError）：单次即 OPEN，长冷却 6h。"""
    clock = _Clock(1000.0)
    breaker = make_breaker(clock)
    breaker.record_failure(TypeSafeAuthError("402 payment required"))
    assert breaker.is_open() is True
    clock.t = 1000.0 + 600 + 600  # 远超瞬态冷却，但远短于 6h
    assert breaker.is_open() is True
    clock.t = 1000.0 + 21600
    assert breaker.is_open() is False  # 6h 后才放行探测
    assert breaker.state == "half_open"


def test_half_open_success_closes_and_resets() -> None:
    clock = _Clock(1000.0)
    breaker = make_breaker(clock)
    for _ in range(3):
        breaker.record_failure(TypeSafeAPIError("500"))
    clock.t = 1600.0
    assert breaker.is_open() is False  # → half_open
    breaker.record_success()
    assert breaker.state == "closed"
    # 重置后需再连续 3 次瞬态失败才重新 OPEN
    breaker.record_failure(TypeSafeAPIError("500"))
    assert breaker.is_open() is False


def test_half_open_transient_failure_reopens() -> None:
    """探测失败（瞬态）→ 重新 OPEN 新冷却，不能卡死在 half_open。
    Review Focus #5。"""
    clock = _Clock(1000.0)
    breaker = make_breaker(clock)
    for _ in range(3):
        breaker.record_failure(TypeSafeAPIError("500"))
    clock.t = 1600.0
    assert breaker.is_open() is False  # → half_open
    breaker.record_failure(TypeSafeTimeoutError("timeout"))
    assert breaker.state == "open"
    # 冷却从探测失败时刻重新计算
    clock.t = 1600.0 + 599.9
    assert breaker.is_open() is True
    clock.t = 1600.0 + 600.0
    assert breaker.is_open() is False
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_jev_circuit_breaker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'alpha_trading_bot.ai.jev.fast_lane'`

- [ ] **Step 3: 最小实现**

创建 `alpha_trading_bot/ai/jev/fast_lane.py`（Task 6 会在此文件末尾追加 `FastLaneResult` 与 `JevFastLane`；import 块按最终需求一次写全）：

```python
"""
Jev 快车道：熔断器 + 决策矩阵

- _CircuitBreaker: Jev 账户故障（欠费/封停）或瞬态网络故障 → 自动关闭快车道，
  全量流量回落现有 LLM 路径；故障恢复后自动探测恢复
- JevFastLane.decide(): 置信度门控级联决策（adopt / escalate）（Task 6 追加）
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple

from .config import JevFastLaneConfig
from .questions import JEV_QUESTIONS, build_state
from .typesafe_client import (
    ChoiceAnswer,
    JevClient,
    NoulAnswer,
    SystemOneResponse,
    TypeSafeAPIError,
    TypeSafeAuthError,
    TypeSafeTimeoutError,
)

logger = logging.getLogger(__name__)


class _CircuitBreaker:
    """快车道熔断器。

    状态机: CLOSED --(失败达阈值)--> OPEN --(冷却到期)-->
    HALF-OPEN(放行单次探测) --成功--> CLOSED / --失败--> OPEN(新冷却)

    故障分类:
    - TypeSafeAuthError (401/402 欠费/Key 无效/封停): 单次即 OPEN，长冷却
    - Timeout/APIError (瞬态): 连续 N 次后 OPEN，短冷却

    冷却到期由 is_open() 自动转 half_open 并返回 False（放行探测）；
    探测结果通过 record_success/record_failure 反馈。
    内存态：进程重启即全量重置（bot 进程干净重启，可接受）。
    """

    def __init__(
        self,
        config: JevFastLaneConfig,
        now: Optional[Callable[[], float]] = None,
    ) -> None:
        self._failure_threshold = config.failure_threshold
        self._cooldown = config.cooldown_seconds
        self._auth_cooldown = config.auth_cooldown_seconds
        self._now = now or time.monotonic

        self._state = "closed"  # closed / open / half_open
        self._consecutive_failures = 0
        self._open_until = 0.0
        self._last_reason = ""

    def is_open(self) -> bool:
        """快车道是否应被跳过。

        注意副作用：冷却到期时 open 自动转 half_open（返回 False 放行探测）。
        """
        if self._state == "open" and self._now() >= self._open_until:
            self._state = "half_open"
            logger.info(
                "[Jev熔断] HALF-OPEN: 冷却结束(上次原因: %s)，放行探测",
                self._last_reason[:80],
            )
        return self._state == "open"

    def record_success(self) -> None:
        """探测/正常调用成功：关闭熔断并重置连续失败计数。"""
        if self._state != "closed":
            logger.info("[Jev熔断] CLOSED: 调用成功，快车道恢复")
        self._state = "closed"
        self._consecutive_failures = 0

    def record_failure(self, error: Exception) -> None:
        """记录一次失败并驱动状态机（任何快车道调用失败都调用）。"""
        if isinstance(error, TypeSafeAuthError):
            # 欠费/封停：高频重试无意义 → 立即 OPEN + 长冷却
            self._open(auth_cooldown=True, reason=str(error))
            return
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold:
            self._open(auth_cooldown=False, reason=str(error))

    def _open(self, auth_cooldown: bool, reason: str) -> None:
        cooldown = self._auth_cooldown if auth_cooldown else self._cooldown
        kind = "欠费/鉴权失败" if auth_cooldown else "瞬态故障"
        self._state = "open"
        self._open_until = self._now() + cooldown
        self._last_reason = reason
        if auth_cooldown:
            self._consecutive_failures = 0
        logger.warning(
            "[Jev熔断] OPEN: %s，冷却 %ds，原因=%s", kind, cooldown, reason[:120]
        )

    @property
    def state(self) -> str:
        """当前状态（closed/open/half_open），供测试与监控。"""
        return self._state

    def get_stats(self) -> Dict[str, Any]:
        return {
            "circuit_state": self._state,
            "consecutive_failures": self._consecutive_failures,
        }
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_jev_circuit_breaker.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add alpha_trading_bot/ai/jev/fast_lane.py tests/unit/test_jev_circuit_breaker.py
git commit -m "feat(jev): 快车道熔断器（欠费/封停自动降级 LLM）"
```

---
### Task 6: `JevFastLane` 决策矩阵（fast_lane.py 第二部分 + 包导出）

**Files:**
- Modify: `alpha_trading_bot/ai/jev/fast_lane.py`（追加 `FastLaneResult` + `JevFastLane`）
- Modify: `alpha_trading_bot/ai/jev/__init__.py`（导出 fast_lane 符号）
- Modify: `alpha_trading_bot/ai/__init__.py`（导出 jev 符号）
- Test: `tests/unit/test_jev_fast_lane.py`

**Interfaces:**
- Consumes: Task 1-5 全部产出
- Produces:
  - `FastLaneResult(adopted: bool, signal: Optional[str] = None, confidence: float = 0.0, probabilities: Dict[str, float] = <空dict>, jev_context: Optional[str] = None, reason: str = "", latency_ms: int = 0)`
  - `JevFastLane(config: JevFastLaneConfig, client: JevClient, now: Optional[Callable[[], float]] = None)`
  - `JevFastLane.from_env() -> JevFastLane`（classmethod）
  - `async JevFastLane.decide(market_data: Dict[str, Any]) -> FastLaneResult`
  - `JevFastLane.get_stats() -> Dict[str, int]`（键：`fast_lane_adopted`/`fast_lane_escalated`/`fast_lane_errors`）
  - 实例属性：`config`、`client`、`breaker`
  - reason 取值：`disabled`/`circuit_open`/`shadow`/`timeout`/`auth_error`/`api_error`/`risk_gate`/`adopt`/`low_confidence`/`bad_response`

- [ ] **Step 1: 写失败测试**

创建 `tests/unit/test_jev_fast_lane.py`：

```python
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
    base = dict(
        mode="on", api_key="k", conf_buy=0.75, conf_sell=0.75, conf_hold=0.50
    )
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
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_jev_fast_lane.py -v`
Expected: FAIL — `ImportError: cannot import name 'JevFastLane'`

- [ ] **Step 3: 实现 FastLaneResult + JevFastLane**

在 `alpha_trading_bot/ai/jev/fast_lane.py` 末尾（`_CircuitBreaker` 之后）追加：

```python
@dataclass
class FastLaneResult:
    """快车道决策结果。

    adopted=True: Jev 信号直接采用，跳过 LLM。
    adopted=False: 升级 LLM（jev_context 为注入 prompt 的初读摘要）；
                   或跳过快车道本身（disabled/circuit_open，jev_context 为 None）。
    """

    adopted: bool
    signal: Optional[str] = None  # adopted 时为 buy/hold/sell/short
    confidence: float = 0.0  # 主问题 confidence
    probabilities: Dict[str, float] = field(default_factory=dict)
    jev_context: Optional[str] = None
    reason: str = ""  # disabled/circuit_open/shadow/timeout/auth_error/api_error/
    #                 # risk_gate/adopt/low_confidence/bad_response
    latency_ms: int = 0


class JevFastLane:
    """Jev 快车道入口。

    在 AIClient 的 LLM 分支之前调用 decide()：
    - disabled/熔断打开 → 直接返回，无网络请求
    - 否则调用 TypeSafe → 决策矩阵（非对称置信阈值 + 风险旗标一票否决）
    """

    def __init__(
        self,
        config: JevFastLaneConfig,
        client: JevClient,
        now: Optional[Callable[[], float]] = None,
    ) -> None:
        self.config = config
        self.client = client
        self.breaker = _CircuitBreaker(config, now=now)
        self._stats: Dict[str, int] = {
            "fast_lane_adopted": 0,
            "fast_lane_escalated": 0,
            "fast_lane_errors": 0,
        }
        self._warned_missing_key = False

    @classmethod
    def from_env(cls) -> "JevFastLane":
        """从 env 配置构建（供 AIClient 未显式注入时自建）。"""
        config = JevFastLaneConfig.from_env()
        return cls(config=config, client=JevClient(config))

    async def decide(self, market_data: Dict[str, Any]) -> FastLaneResult:
        """执行一次快车道决策；任何异常都返回升级结果，绝不阻塞交易循环。"""
        if self.config.mode == "off":
            return FastLaneResult(adopted=False, reason="disabled")
        if not self.config.api_key:
            if not self._warned_missing_key:
                logger.warning(
                    "[Jev快车道] AI_FAST_LANE=%s 但 TYPESAFE_API_KEY 为空，"
                    "快车道不生效（请配置 Key 或将 AI_FAST_LANE 设为 off）",
                    self.config.mode,
                )
                self._warned_missing_key = True
            return FastLaneResult(adopted=False, reason="disabled")
        if self.breaker.is_open():
            logger.debug("[Jev快车道] 跳过: circuit_open")
            return FastLaneResult(adopted=False, reason="circuit_open")

        started = time.monotonic()
        try:
            state = build_state(market_data)
            response = await self.client.system_one(state, JEV_QUESTIONS)
        except TypeSafeAuthError as e:
            return self._handle_error(e, "auth_error", started)
        except TypeSafeTimeoutError as e:
            return self._handle_error(e, "timeout", started)
        except TypeSafeAPIError as e:
            return self._handle_error(e, "api_error", started)

        self.breaker.record_success()
        latency_ms = self._elapsed(started)

        decision = response.answers.get("trade_decision")
        if not isinstance(decision, ChoiceAnswer):
            self._stats["fast_lane_errors"] += 1
            logger.warning("[Jev快车道] 主问题响应异常，升级 LLM")
            return FastLaneResult(
                adopted=False, reason="bad_response", latency_ms=latency_ms
            )

        risk_value = self._noul_value(response, "is_high_risk_reversal")
        choppy_value = self._noul_value(response, "is_choppy_no_edge")
        context = self._build_context(decision, risk_value, choppy_value)

        if self.config.mode == "shadow":
            # 只观察：永不采用，记录"本会采用"的供 LLM 结果对比
            would_adopt, _ = self._evaluate(decision)
            self._stats["fast_lane_escalated"] += 1
            logger.info(
                "[Jev快车道][shadow] would_adopt=%s choice=%s conf=%.2f "
                "risk=%.2f latency=%dms (不采用, LLM 决策)",
                would_adopt,
                decision.choice,
                decision.confidence,
                risk_value,
                latency_ms,
            )
            return FastLaneResult(
                adopted=False,
                reason="shadow",
                signal=decision.choice if would_adopt else None,
                confidence=decision.confidence,
                probabilities=dict(decision.probabilities),
                jev_context=None,
                latency_ms=latency_ms,
            )

        # 安全旗标一票否决：反转风险高时即使高置信也强制升级 LLM
        if risk_value > self.config.risk_noul_gate:
            self._stats["fast_lane_escalated"] += 1
            logger.info(
                "[Jev快车道] 升级: reason=risk_gate 反转风险=%.2f 超阈 %.2f",
                risk_value,
                self.config.risk_noul_gate,
            )
            return FastLaneResult(
                adopted=False,
                reason="risk_gate",
                confidence=decision.confidence,
                probabilities=dict(decision.probabilities),
                jev_context=context,
                latency_ms=latency_ms,
            )

        adopted, reason = self._evaluate(decision)
        if adopted:
            self._stats["fast_lane_adopted"] += 1
            logger.info(
                "[Jev快车道] 采用: %s (conf=%.2f, latency=%dms)",
                decision.choice,
                decision.confidence,
                latency_ms,
            )
            return FastLaneResult(
                adopted=True,
                signal=decision.choice,
                confidence=decision.confidence,
                probabilities=dict(decision.probabilities),
                reason="adopt",
                latency_ms=latency_ms,
            )

        self._stats["fast_lane_escalated"] += 1
        logger.info(
            "[Jev快车道] 升级: reason=%s choice=%s conf=%.2f",
            reason,
            decision.choice,
            decision.confidence,
        )
        return FastLaneResult(
            adopted=False,
            reason=reason,
            confidence=decision.confidence,
            probabilities=dict(decision.probabilities),
            jev_context=context,
            latency_ms=latency_ms,
        )

    def _handle_error(
        self, error: Exception, reason: str, started: float
    ) -> FastLaneResult:
        """快车道调用失败统一处理：驱动熔断 + 计数 + 升级 LLM。"""
        self.breaker.record_failure(error)
        self._stats["fast_lane_errors"] += 1
        logger.warning("[Jev快车道] %s，升级 LLM: %s", reason, error)
        return FastLaneResult(
            adopted=False, reason=reason, latency_ms=self._elapsed(started)
        )

    def _evaluate(self, decision: ChoiceAnswer) -> Tuple[bool, str]:
        """非对称置信阈值：BUY/SELL/SHORT 高门槛，HOLD 可更低（安全默认动作）。"""
        confidence = decision.confidence
        choice = decision.choice
        if choice == "buy" and confidence >= self.config.conf_buy:
            return True, "adopt"
        if choice == "hold" and confidence >= self.config.conf_hold:
            return True, "adopt"
        if choice in ("sell", "short") and confidence >= self.config.conf_sell:
            return True, "adopt"
        return False, "low_confidence"

    @staticmethod
    def _noul_value(response: SystemOneResponse, question_id: str) -> float:
        """读 Noul 答案并 clamp 到 [0,1]；缺失/类型错按 0（无风险）处理。"""
        answer = response.answers.get(question_id)
        if isinstance(answer, NoulAnswer):
            return max(0.0, min(1.0, answer.noul))
        return 0.0

    @staticmethod
    def _build_context(
        decision: ChoiceAnswer, risk_value: float, choppy_value: float
    ) -> str:
        """生成 Jev 初读摘要（升级 LLM 时注入 prompt）。"""
        distribution = " ".join(
            f"{option}={probability:.2f}"
            for option, probability in sorted(
                decision.probabilities.items(), key=lambda kv: kv[1], reverse=True
            )
        ) or "缺失"
        return (
            f"[Jev初读] 倾向={decision.choice} (置信 {decision.confidence:.2f}) "
            f"分布: {distribution}\n"
            f"          反转风险={risk_value:.2f} "
            f"震荡无方向={choppy_value:.2f}\n"
            f"          快车道置信度不足未能直接决策，请基于完整市场数据"
            f"独立判断，不必与初读一致。"
        )

    @staticmethod
    def _elapsed(started: float) -> int:
        return int((time.monotonic() - started) * 1000)

    def get_stats(self) -> Dict[str, int]:
        """快车道计数（供 AIClient.get_metrics 合并）。"""
        return dict(self._stats)
```

把 `alpha_trading_bot/ai/jev/__init__.py` 更新为最终形态：

```python
"""
Jev (TypeSafe System One) 快车道

- config: JevFastLaneConfig（env 配置）
- typesafe_client: TypeSafe HTTP 客户端与类型化问答
- questions: 问题集与市场状态序列化
- fast_lane: 快车道决策（置信度门控 + 风险旗标 + 熔断器）
"""

from .config import JevFastLaneConfig
from .fast_lane import FastLaneResult, JevFastLane
from .questions import JEV_QUESTIONS, build_state
from .typesafe_client import (
    ChoiceAnswer,
    JevClient,
    NoulAnswer,
    ScoreAnswer,
    SystemOneResponse,
    TypeSafeAPIError,
    TypeSafeAuthError,
    TypeSafeError,
    TypeSafeTimeoutError,
)

__all__ = [
    "JevFastLaneConfig",
    "ChoiceAnswer",
    "JevClient",
    "NoulAnswer",
    "ScoreAnswer",
    "SystemOneResponse",
    "TypeSafeAPIError",
    "TypeSafeAuthError",
    "TypeSafeError",
    "TypeSafeTimeoutError",
    "JEV_QUESTIONS",
    "build_state",
    "FastLaneResult",
    "JevFastLane",
]
```

修改 `alpha_trading_bot/ai/__init__.py`：

1) 在 `from .backtest_validator import (...)` 块的结束 `)` 之后、`__version__ = "1.0.0"` 之前插入：

```python
from .jev import (
    FastLaneResult,
    JevClient,
    JevFastLane,
    JevFastLaneConfig,
)
```

2) 在 `__all__` 列表末尾（`"create_integrator",` 之后、`]` 之前）插入：

```python
    # Jev 快车道
    "JevFastLaneConfig",
    "JevClient",
    "JevFastLane",
    "FastLaneResult",
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_jev_fast_lane.py tests/unit/test_jev_circuit_breaker.py -v`
Expected: 18 passed（12 + 6）

- [ ] **Step 5: Commit**

```bash
git add alpha_trading_bot/ai/jev/ alpha_trading_bot/ai/__init__.py tests/unit/test_jev_fast_lane.py
git commit -m "feat(jev): JevFastLane 决策矩阵（置信度门控+shadow+风险旗标）"
```

---
### Task 7: prompt_builder 注入 Jev 初读

**Files:**
- Modify: `alpha_trading_bot/ai/prompt_builder.py`（`PromptBuilder.build` 与 `build_prompt` 增加 `jev_context` 可选参数）
- Test: `tests/unit/test_prompt_builder_jev_context.py`

**Interfaces:**
- Consumes: 现有 `PromptBuilder.build(market_data, provider)`（保持向后兼容）
- Produces:
  - `PromptBuilder.build(market_data: Dict[str, Any], provider: str = "default", jev_context: Optional[str] = None) -> str`
  - `build_prompt(market_data: Dict[str, Any], provider: str = "default", jev_context: Optional[str] = None) -> str`
  - `jev_context` 非空时，prompt 尾部追加小节：
    `## 快速模型初读（仅供参考，请独立判断）\n{jev_context}\n`
  - `jev_context=None` 时输出与现状**完全一致**（现有测试零破坏）

- [ ] **Step 1: 写失败测试**

创建 `tests/unit/test_prompt_builder_jev_context.py`：

```python
"""
prompt_builder Jev 初读注入单元测试
"""

from alpha_trading_bot.ai.prompt_builder import PromptBuilder, build_prompt

MARKET_DATA = {
    "symbol": "BTC-USDT",
    "price": 118000.0,
    "technical": {
        "rsi": 55,
        "macd_hist": 1.0,
        "trend_direction": "up",
        "trend_strength": 0.2,
    },
}

JEV_CONTEXT = (
    "[Jev初读] 倾向=BUY (置信 0.62) 分布: buy=0.45 hold=0.35\n"
    "          反转风险=0.31 震荡无方向=0.60\n"
    "          快车道置信度不足未能直接决策，请基于完整市场数据独立判断，不必与初读一致。"
)


def test_none_context_prompt_unchanged() -> None:
    """jev_context=None：输出与旧行为一致（无初读小节）。"""
    base = PromptBuilder.build(MARKET_DATA, "default")
    with_none = PromptBuilder.build(MARKET_DATA, "default", jev_context=None)
    assert base == with_none
    assert "快速模型初读" not in base


def test_jev_context_appended_section() -> None:
    """jev_context 非空：prompt 尾部追加初读小节，原内容不变（前缀一致）。"""
    base = PromptBuilder.build(MARKET_DATA, "default")
    prompt = PromptBuilder.build(MARKET_DATA, "default", jev_context=JEV_CONTEXT)
    assert prompt.startswith(base)
    assert "## 快速模型初读（仅供参考，请独立判断）" in prompt
    assert "[Jev初读]" in prompt


def test_convenience_function_forwards_context() -> None:
    prompt = build_prompt(MARKET_DATA, provider="default", jev_context=JEV_CONTEXT)
    assert "[Jev初读]" in prompt
    plain = build_prompt(MARKET_DATA)
    assert "快速模型初读" not in plain
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_prompt_builder_jev_context.py -v`
Expected: FAIL — `TypeError: build() got an unexpected keyword argument 'jev_context'`

- [ ] **Step 3: 实现**

修改 `alpha_trading_bot/ai/prompt_builder.py`（3 处）：

1) `PromptBuilder.build` 签名（约 line 101）：

oldText:
```python
    def build(cls, market_data: Dict[str, Any], provider: str = "default") -> str:
        """构建完整的Prompt - 差异化系统

        Args:
            market_data: 市场数据
            provider: AI 提供商（kimi/deepseek/default）
        """
```

newText:
```python
    def build(
        cls,
        market_data: Dict[str, Any],
        provider: str = "default",
        jev_context: Optional[str] = None,
    ) -> str:
        """构建完整的Prompt - 差异化系统

        Args:
            market_data: 市场数据
            provider: AI 提供商（kimi/deepseek/default）
            jev_context: Jev 快车道初读摘要（可选；非空时追加到 prompt 尾部）
        """
```

2) 把方法末尾的 `return f"""..."""`（约 line 326，以 `置信度范围：BUY/SHORT 50%-90%, HOLD 25%-65%"""` 结尾）改为先赋值再追加。只改两处锚点：

oldText（f-string 起始行，仅改 `return f"""` → `prompt = f"""`，其余原样）:
```python
        return f"""你是一位拥有10年加密货币交易经验的资深交易员
```

newText:
```python
        prompt = f"""你是一位拥有10年加密货币交易经验的资深交易员
```

oldText（f-string 结尾行）:
```python
- 置信度范围：BUY/SHORT 50%-90%, HOLD 25%-65%"""
```

newText:
```python
- 置信度范围：BUY/SHORT 50%-90%, HOLD 25%-65%"""

        # Jev 快车道初读：仅升级路径注入；None 时保持旧输出逐字节一致
        if jev_context:
            prompt += (
                f"\n## 快速模型初读（仅供参考，请独立判断）\n"
                f"{jev_context}\n"
            )
        return prompt
```

3) `build_prompt` 便捷函数（文件末尾）：

oldText:
```python
def build_prompt(market_data: Dict[str, Any], provider: str = "default") -> str:
    """构建AI交易决策Prompt - 便捷函数

    Args:
        market_data: 市场数据
        provider: AI 提供商(kimi/deepseek/default)

    Returns:
        格式化后的 prompt
    """
    return PromptBuilder.build(market_data, provider)
```

newText:
```python
def build_prompt(
    market_data: Dict[str, Any],
    provider: str = "default",
    jev_context: Optional[str] = None,
) -> str:
    """构建AI交易决策Prompt - 便捷函数

    Args:
        market_data: 市场数据
        provider: AI 提供商(kimi/deepseek/default)
        jev_context: Jev 快车道初读摘要（可选；非空时追加到 prompt 尾部）

    Returns:
        格式化后的 prompt
    """
    return PromptBuilder.build(market_data, provider, jev_context=jev_context)
```

> 注意：`prompt_builder.py` 顶部 import 需包含 `Optional`（现有代码已用 `Optional["PromptConfig"]`，若 import 行没有 `Optional` 则补上）。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_prompt_builder_jev_context.py -v`
Expected: 3 passed

再确认旧 prompt 行为零破坏（回归）：

Run: `python -m pytest tests/unit/ -k "prompt" -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add alpha_trading_bot/ai/prompt_builder.py tests/unit/test_prompt_builder_jev_context.py
git commit -m "feat(jev): prompt_builder 注入 Jev 初读上下文"
```

---

### Task 8: AIClient 接线（快车道分支 + _get_llm_signal + metrics）

**Files:**
- Modify: `alpha_trading_bot/ai/client.py`
- Test: `tests/unit/test_ai_client_fast_lane.py`

**Interfaces:**
- Consumes: `JevFastLane`/`FastLaneResult`（Task 6）、`build_prompt(..., jev_context=...)`（Task 7）
- Produces:
  - `AIClient.__init__(..., enable_cache: bool = True, fast_lane: Optional[JevFastLane] = None)`
  - `AIClient._init_fast_lane() -> Optional[JevFastLane]`（env `AI_FAST_LANE` 非 off 时自建，否则 None）
  - `async AIClient._get_llm_signal(market_data, jev_context: Optional[str] = None) -> Tuple[str, float]`
  - `jev_context` 沿 `_get_single_signal` / `_get_fusion_signal` / `_fallback_fusion` / `_call_ai_with_retry` / `_call_ai` 透传到 `build_prompt`
  - `AIClient.get_metrics()` 额外含 `fast_lane_adopted`/`fast_lane_escalated`/`fast_lane_errors`/`fast_lane_circuit_open`

- [ ] **Step 1: 写失败测试**

创建 `tests/unit/test_ai_client_fast_lane.py`：

```python
"""
AIClient × Jev 快车道集成单元测试
"""

from typing import Any, Dict, List, Optional

import pytest

from alpha_trading_bot.ai.client import AIClient
from alpha_trading_bot.ai.jev.fast_lane import FastLaneResult
from alpha_trading_bot.config.models import AIConfig


class _FakeBreakerView:
    def get_stats(self) -> Dict[str, Any]:
        return {"circuit_state": "closed", "consecutive_failures": 0}


class _FakeFastLane:
    """Mock 快车道：可控 adopt/escalate，记录 decide 调用。"""

    def __init__(self, result: FastLaneResult) -> None:
        self._result = result
        self.decide_calls = 0
        self.breaker = _FakeBreakerView()

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
    assert signal in ("buy", "hold", "sell", "short")


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
async def test_cache_hit_skips_both_jev_and_llm(monkeypatch: pytest.MonkeyPatch) -> None:
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
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_ai_client_fast_lane.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'fast_lane'`

- [ ] **Step 3: 实现 AIClient 改动**

修改 `alpha_trading_bot/ai/client.py`（12 处，按序）：

**3.1) import 增加 `os` 与 `JevFastLane`**

oldText:
```python
import asyncio
import hashlib
import importlib
import logging
import re
import time
```

newText:
```python
import asyncio
import hashlib
import importlib
import logging
import os
import re
import time
```

oldText:
```python
from .integrator import AISignalIntegrator
from .integrator_config import IntegrationConfig
```

newText:
```python
from .integrator import AISignalIntegrator
from .integrator_config import IntegrationConfig
from .jev.fast_lane import JevFastLane
```

**3.2) `__init__` 增加 `fast_lane` 参数**

oldText:
```python
    def __init__(
        self,
        config: Optional["AIConfig"] = None,
        api_keys: Optional[Dict[str, str]] = None,
        integrator_mode: str = "standard",
        cache_ttl: int = DEFAULT_CACHE_TTL,
        enable_cache: bool = True,
    ):
```

newText:
```python
    def __init__(
        self,
        config: Optional["AIConfig"] = None,
        api_keys: Optional[Dict[str, str]] = None,
        integrator_mode: str = "standard",
        cache_ttl: int = DEFAULT_CACHE_TTL,
        enable_cache: bool = True,
        fast_lane: Optional[JevFastLane] = None,
    ):
```

**3.3) `__init__` 末尾初始化快车道**（oldText 锚点为 `__init__` 最后一行）

oldText:
```python
        # 序列化 get_signal，防止并发调用在置位/判定窗口之间串扰降级标志。
        self._signal_lock: Optional[asyncio.Lock] = None
```

newText:
```python
        # 序列化 get_signal，防止并发调用在置位/判定窗口之间串扰降级标志。
        self._signal_lock: Optional[asyncio.Lock] = None

        # Jev 快车道：显式注入优先；否则按 env 自建
        # （AI_FAST_LANE=off 时返回 None，保持现状行为）
        if fast_lane is not None:
            self._fast_lane = fast_lane
        else:
            self._fast_lane = self._init_fast_lane()
```

**3.4) 新增 `_init_fast_lane` 与 `_get_llm_signal`**（插在 `_get_normalized_fusion_weights` 之前）

oldText:
```python
    def _get_normalized_fusion_weights(self) -> Dict[str, float]:
        """返回融合提供商完整且归一化的权重。"""
```

newText:
```python
    def _init_fast_lane(self) -> Optional[JevFastLane]:
        """启用时从 env 构建 Jev 快车道；禁用时返回 None（保持现状行为）。"""
        mode = os.getenv("AI_FAST_LANE", "off").strip().lower()
        if mode == "off":
            return None
        fast_lane = JevFastLane.from_env()
        logger.info(
            "[Jev快车道] 已启用 mode=%s model=%s "
            "阈值=buy:%s/sell:%s/hold:%s risk_gate:%s",
            mode,
            fast_lane.config.model,
            fast_lane.config.conf_buy,
            fast_lane.config.conf_sell,
            fast_lane.config.conf_hold,
            fast_lane.config.risk_noul_gate,
        )
        return fast_lane

    async def _get_llm_signal(
        self, market_data: Dict[str, Any], jev_context: Optional[str] = None
    ) -> Tuple[str, float]:
        """获取 LLM 原始信号（single/fusion），可携带 Jev 快车道初读上下文。"""
        if self.config.mode == "single":
            return await self._get_single_signal(
                market_data, jev_context=jev_context
            )
        return await self._get_fusion_signal(
            market_data, jev_context=jev_context
        )

    def _get_normalized_fusion_weights(self) -> Dict[str, float]:
        """返回融合提供商完整且归一化的权重。"""
```

**3.5) `get_signal` 原始信号获取分支**

oldText:
```python
            # 获取原始信号
            if self.config.mode == "single":
                original_signal, original_confidence = await self._get_single_signal(
                    market_data
                )
            else:
                original_signal, original_confidence = await self._get_fusion_signal(
                    market_data
                )
```

newText:
```python
            # 获取原始信号（Jev 快车道优先；低置信/故障时升级 LLM）
            if self._fast_lane is not None:
                fast_result = await self._fast_lane.decide(market_data)
                if fast_result.adopted:
                    original_signal = fast_result.signal or "hold"
                    original_confidence = fast_result.confidence
                    await log_signal_distribution(original_signal, source="jev")
                    logger.info(
                        "[AI请求] Jev快车道采用: %s "
                        "(置信=%.2f, %dms, 跳过LLM)",
                        original_signal,
                        original_confidence,
                        fast_result.latency_ms,
                    )
                else:
                    original_signal, original_confidence = (
                        await self._get_llm_signal(
                            market_data, jev_context=fast_result.jev_context
                        )
                    )
            else:
                original_signal, original_confidence = await self._get_llm_signal(
                    market_data
                )
```

**3.6) `_get_single_signal` 签名与内部调用**

oldText:
```python
    async def _get_single_signal(self, market_data: Dict[str, Any]) -> tuple:
        """单AI模式，返回 (signal, confidence)"""
        provider = self.config.default_provider
        api_key = self.api_keys.get(provider, "")
        logger.info(f"[AI请求] 单AI模式, 提供商: {provider}")

        # 使用带重试的调用
        response = await self._call_ai_with_retry(provider, market_data, api_key)
```

newText:
```python
    async def _get_single_signal(
        self, market_data: Dict[str, Any], jev_context: Optional[str] = None
    ) -> tuple:
        """单AI模式，返回 (signal, confidence)"""
        provider = self.config.default_provider
        api_key = self.api_keys.get(provider, "")
        logger.info(f"[AI请求] 单AI模式, 提供商: {provider}")

        # 使用带重试的调用（jev_context 为快车道初读，升级时透传给 prompt）
        response = await self._call_ai_with_retry(
            provider, market_data, api_key, jev_context=jev_context
        )
```

**3.7) `_get_fusion_signal` 签名**

oldText:
```python
    async def _get_fusion_signal(self, market_data: Dict[str, Any]) -> tuple:
        """多AI融合模式 - 并行调用多个AI并融合结果"""
```

newText:
```python
    async def _get_fusion_signal(
        self, market_data: Dict[str, Any], jev_context: Optional[str] = None
    ) -> tuple:
        """多AI融合模式 - 并行调用多个AI并融合结果"""
```

**3.8) `_get_fusion_signal` 内 tasks 构造**

oldText:
```python
            tasks.append(self._call_ai_with_retry(provider, market_data, api_key))
```

newText:
```python
            tasks.append(
                self._call_ai_with_retry(
                    provider, market_data, api_key, jev_context=jev_context
                )
            )
```

**3.9) `_get_fusion_signal` 内 fallback 调用**

oldText:
```python
            return await self._fallback_fusion(market_data)
```

newText:
```python
            return await self._fallback_fusion(
                market_data, jev_context=jev_context
            )
```

**3.10) `_fallback_fusion` 签名与内部调用**

oldText:
```python
    async def _fallback_fusion(self, market_data: Dict[str, Any]) -> tuple:
        """备用融合方案 - 当主提供商失败时使用"""
```

newText:
```python
    async def _fallback_fusion(
        self, market_data: Dict[str, Any], jev_context: Optional[str] = None
    ) -> tuple:
        """备用融合方案 - 当主提供商失败时使用"""
```

oldText:
```python
                response = await self._call_ai_with_retry(
                    provider, market_data, api_key
                )
```

newText:
```python
                response = await self._call_ai_with_retry(
                    provider,
                    market_data,
                    api_key,
                    jev_context=jev_context,
                )
```

**3.11) `_call_ai_with_retry` 与 `_call_ai` 签名及透传**

oldText:
```python
    async def _call_ai_with_retry(
        self, provider: str, market_data: Dict[str, Any], api_key: str
    ) -> str:
        """带指数退避重试的AI调用"""
        last_error = None

        for attempt in range(self.MAX_RETRIES):
            try:
                return await self._call_ai(provider, market_data, api_key)
```

newText:
```python
    async def _call_ai_with_retry(
        self,
        provider: str,
        market_data: Dict[str, Any],
        api_key: str,
        jev_context: Optional[str] = None,
    ) -> str:
        """带指数退避重试的AI调用"""
        last_error = None

        for attempt in range(self.MAX_RETRIES):
            try:
                return await self._call_ai(
                    provider, market_data, api_key, jev_context=jev_context
                )
```

oldText:
```python
    async def _call_ai(
        self, provider: str, market_data: Dict[str, Any], api_key: str
    ) -> str:
        """调用单个AI - 差异化"""
```

newText:
```python
    async def _call_ai(
        self,
        provider: str,
        market_data: Dict[str, Any],
        api_key: str,
        jev_context: Optional[str] = None,
    ) -> str:
        """调用单个AI - 差异化"""
```

oldText:
```python
        # 根据 provider 生成差异化 prompt
        prompt = build_prompt(market_data, provider=provider)
```

newText:
```python
        # 根据 provider 生成差异化 prompt（jev_context 为快车道初读，升级时注入）
        prompt = build_prompt(
            market_data, provider=provider, jev_context=jev_context
        )
```

**3.12) `get_metrics` 增加快车道统计**

oldText:
```python
    def get_metrics(self) -> Dict[str, int]:
        """返回当前累计的监控指标快照（用于诊断和报告）。"""
        return dict(self._metrics)
```

newText:
```python
    def get_metrics(self) -> Dict[str, int]:
        """返回当前累计的监控指标快照（用于诊断和报告）。"""
        metrics = dict(self._metrics)
        if self._fast_lane is not None:
            metrics.update(self._fast_lane.get_stats())
            metrics["fast_lane_circuit_open"] = int(
                self._fast_lane.breaker.get_stats()["circuit_state"] != "closed"
            )
        return metrics
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_ai_client_fast_lane.py -v`
Expected: 5 passed

再跑快车道相关全部测试确认无回归：

Run: `python -m pytest tests/unit/test_jev_config.py tests/unit/test_jev_types.py tests/unit/test_jev_questions.py tests/unit/test_jev_client.py tests/unit/test_jev_circuit_breaker.py tests/unit/test_jev_fast_lane.py tests/unit/test_prompt_builder_jev_context.py tests/unit/test_ai_client_fast_lane.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add alpha_trading_bot/ai/client.py tests/unit/test_ai_client_fast_lane.py
git commit -m "feat(jev): AIClient 快车道接线与 metrics"
```

---

### Task 9: 全量验证 + README 文档 + graphify 更新

**Files:**
- Modify: `README.md`（AI 配置章节追加 Jev 快车道小节）
- Run: 全量测试 / mypy / black / flake8 / graphify

**Interfaces:**
- Consumes: Task 1-8 全部产出
- Produces: 可合入的完整功能（`AI_FAST_LANE=off` 默认零行为变化）

- [ ] **Step 1: 全量测试**

Run: `python -m pytest tests/ -x -q`
Expected: 全部 PASS（含新增 8 个测试文件 + 既有全量测试）

- [ ] **Step 2: 类型检查**

Run: `mypy alpha_trading_bot/`
Expected: 无新增错误（若项目既有 baseline 错误，确认数量不增加）

- [ ] **Step 3: 格式化与 lint**

Run: `black --check alpha_trading_bot/ai/jev/ alpha_trading_bot/ai/client.py alpha_trading_bot/ai/prompt_builder.py alpha_trading_bot/ai/__init__.py tests/unit/test_jev_config.py tests/unit/test_jev_types.py tests/unit/test_jev_questions.py tests/unit/test_jev_client.py tests/unit/test_jev_circuit_breaker.py tests/unit/test_jev_fast_lane.py tests/unit/test_prompt_builder_jev_context.py tests/unit/test_ai_client_fast_lane.py`

若有格式差异：

Run: `black alpha_trading_bot/ai/jev/ alpha_trading_bot/ai/client.py alpha_trading_bot/ai/prompt_builder.py alpha_trading_bot/ai/__init__.py tests/unit/test_jev_config.py tests/unit/test_jev_types.py tests/unit/test_jev_questions.py tests/unit/test_jev_client.py tests/unit/test_jev_circuit_breaker.py tests/unit/test_jev_fast_lane.py tests/unit/test_prompt_builder_jev_context.py tests/unit/test_ai_client_fast_lane.py`

然后重跑 Step 1 测试确认仍全绿。

Run: `flake8 alpha_trading_bot/ai/jev/ --max-line-length=88 --extend-ignore=E203,W503`
Expected: 无输出（无错误）

- [ ] **Step 4: README 追加 Jev 快车道小节**

修改 `README.md`，在 `### 🤖 AI配置` 章节最后一行 `- \`AI_MAX_RETRIES\`: AI最大重试次数（默认2次）` 之后插入：

oldText:
```markdown
- `AI_MAX_RETRIES`: AI最大重试次数（默认2次）
```

newText:
```markdown
- `AI_MAX_RETRIES`: AI最大重试次数（默认2次）

#### Jev 快车道（TypeSafe System One）

AI 信号支持 Jev（TypeSafe "System One" 模型）快车道：Jev 先做快速结构化决策
（70–500ms，返回类型化值 + 概率分布 + 置信度），高置信且无风险旗标时直接采用、
跳过 LLM；低置信/反转风险旗标/超时/账户故障时自动升级现有 LLM 路径（并把
Jev 初读注入 LLM prompt 作为上下文）。熔断器在账户欠费/封停时自动关闭快车道
（全部流量回落纯 LLM），故障恢复后自动探测恢复。

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `AI_FAST_LANE` | `off` | `off`/`shadow`/`on` 三档 |
| `TYPESAFE_API_KEY` | - | TypeSafe API Key（`AI_FAST_LANE != off` 时必填） |
| `TYPESAFE_MODEL` | `jev-1.13.0` | 建议 pin 固定版本 |
| `JEV_TIMEOUT` | `5.0` | 快车道超时（秒） |
| `JEV_CONF_BUY` / `JEV_CONF_SELL` / `JEV_CONF_HOLD` | `0.75`/`0.75`/`0.50` | 采用置信阈值（非对称） |
| `JEV_RISK_NOUL_GATE` | `0.70` | 反转风险超此值强制升级 LLM |
| `JEV_CB_FAILURES` / `JEV_CB_COOLDOWN` / `JEV_CB_AUTH_COOLDOWN` | `3`/`600`/`21600` | 熔断参数 |

建议上线节奏：`off`（默认）→ `shadow`（观察 Jev 与 LLM 一致率与延迟，
决策仍走 LLM）→ `on`（真快车道）。随时 `AI_FAST_LANE=off` 一键回退。
```

- [ ] **Step 5: 更新知识图谱（AGENTS.md 要求）**

Run: `graphify update .`
Expected: 图谱更新成功（AST-only，无 API 成本）

- [ ] **Step 6: 最终回归 + Commit**

Run: `python -m pytest tests/ -x -q`
Expected: 全部 PASS

```bash
git add README.md
git commit -m "docs(jev): README 快车道文档与全量验证"
```

---

## Rollout 验收清单（实现完成后由用户执行）

1. `AI_FAST_LANE=off` 跑一次完整交易循环：日志无 Jev 相关输出，行为与合入前一致。
2. 配置 `TYPESAFE_API_KEY` + `AI_FAST_LANE=shadow` 跑 N 天：
   - grep `[Jev快车道][shadow]` 统计 would_adopt 分布与延迟
   - 对比 `log_signal_distribution_summary` 中 `jev`（本应判）与 LLM source 的一致率
   - 观察 `[Jev熔断]` 是否触发（Key 无效会立即暴露）
3. 一致率与延迟达标后 `AI_FAST_LANE=on`，监控 `get_metrics()` 的
   `fast_lane_adopted/escalated/errors` 与 `fast_lane_circuit_open`。
4. 故障演练（可选）：临时把 `TYPESAFE_API_KEY` 改成无效值跑 shadow 模式，
   验证熔断 OPEN（欠费/鉴权，6h 冷却）与 LLM 路径不受影响。
