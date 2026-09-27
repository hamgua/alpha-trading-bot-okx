"""
Jev 快车道：熔断器 + 决策矩阵

- _CircuitBreaker: Jev 账户故障（欠费/封停）或瞬态网络故障 → 自动关闭快车道，
  全量流量回落现有 LLM 路径；故障恢复后自动探测恢复
- JevFastLane.decide(): 置信度门控级联决策（adopt / escalate）（Task 6 追加）
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from .config import JevFastLaneConfig
from .questions import JEV_QUESTIONS, build_state
from .typesafe_client import (
    ChoiceAnswer,
    JevClient,
    NoulAnswer,
    SystemOneResponse,
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
            "[Jev熔断] OPEN: %s，冷却 %ds，原因=%s",
            kind,
            cooldown,
            reason[:120],
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


# ---------- 快车道决策 ----------


@dataclass
class FastLaneResult:
    """快车道决策结果。

    adopted=True: AIClient 直接采用 signal（跳过 LLM）
    adopted=False: AIClient 调 LLM 做最终判断，jev_context 作为 prompt 上下文
    """

    adopted: bool
    signal: Optional[str] = None  # adopted 时为 buy/hold/sell/short
    confidence: float = 0.0  # 主问题 Choice 的 confidence
    probabilities: Dict[str, float] = field(default_factory=dict)
    jev_context: Optional[str] = None  # 升级 LLM 时的上下文文本
    reason: str = ""  # 审计：adopt/low_confidence/risk_gate/timeout/auth_error/
    # api_error/bad_response/circuit_open/shadow/disabled
    latency_ms: float = 0.0


class JevFastLane:
    """Jev 快车道门面：熔断检查 + Jev 调用 + 决策矩阵。

    决策矩阵（Review Focus #3 核心）:
    | Jev 结果 | 动作 |
    |---|---|
    | 熔断 OPEN | 跳过 Jev，升级 LLM，reason=circuit_open |
    | Timeout/APIError | 升级 LLM（记录失败进熔断），LLM 照常决策 |
    | AuthError | 升级 LLM + 熔断 OPEN（长冷却） |
    | 响应缺失主问题/类型错 | 升级 LLM（bad_response），不抛异常 |
    | 反转风险 Noul > 阈值 | 强制升级 LLM（安全旗标一票否决） |
    | Confidence ≥ 动作对应阈值 | 采用信号，跳过 LLM |
    | Confidence < 阈值 | 升级 LLM，携带 jev_context |
    """

    def __init__(
        self,
        config: JevFastLaneConfig,
        client: JevClient,
        now: Optional[Callable[[], float]] = None,
    ) -> None:
        self.config = config
        self.client = client
        self._breaker = _CircuitBreaker(config, now=now)
        self._key_warned = False
        self._adopted = 0
        self._escalated = 0
        self._errors = 0

    @property
    def breaker(self) -> _CircuitBreaker:
        """熔断器实例（供 AIClient.get_metrics 读 circuit_state）。"""
        return self._breaker

    @classmethod
    def from_env(cls) -> "JevFastLane":
        """从环境变量构建（对齐 providers 的 from_env 惯例）。"""
        config = JevFastLaneConfig.from_env()
        errors = config.validate()
        if errors:
            for error in errors:
                logger.warning("[Jev快车道] 配置错误: %s", error)
            # 配置无效 → 强制 off（快车道失效，主链路不受影响）
            config = JevFastLaneConfig(mode="off")
        return cls(config, client=JevClient(config))

    async def decide(self, market_data: Dict[str, Any]) -> FastLaneResult:
        """执行快车道决策（永不抛异常，失败路径都收敛为升级 LLM）。"""
        if not self._enabled():
            return FastLaneResult(
                adopted=False,
                signal="",
                confidence=0.0,
                probabilities={},
                reason="disabled",
            )
        if self._breaker.is_open():
            self._escalated += 1
            return FastLaneResult(
                adopted=False,
                signal="",
                confidence=0.0,
                probabilities={},
                reason="circuit_open",
            )

        state = build_state(market_data)
        start = time.monotonic()
        try:
            response = await self.client.system_one(state, JEV_QUESTIONS)
        except TypeSafeAuthError as e:
            self._record_error()
            self._breaker.record_failure(e)
            return FastLaneResult(
                adopted=False,
                signal="",
                confidence=0.0,
                probabilities={},
                reason="auth_error",
            )
        except TypeSafeTimeoutError as e:
            self._record_error()
            self._breaker.record_failure(e)
            return FastLaneResult(
                adopted=False,
                signal="",
                confidence=0.0,
                probabilities={},
                reason="timeout",
            )
        except Exception as e:  # noqa: B902 防御性兜底：快车道故障永不拖垮主链路
            self._record_error()
            self._breaker.record_failure(e)
            return FastLaneResult(
                adopted=False,
                signal="",
                confidence=0.0,
                probabilities={},
                reason="api_error",
            )
        latency_ms = (time.monotonic() - start) * 1000.0

        decision = response.answers.get("trade_decision")
        if not isinstance(decision, ChoiceAnswer):
            # 响应结构异常不视为网络失败：不驱动熔断，仅升级 LLM
            logger.warning("[Jev快车道] 响应缺少 trade_decision，升级 LLM")
            self._escalated += 1
            return FastLaneResult(
                adopted=False,
                signal="",
                confidence=0.0,
                probabilities={},
                reason="bad_response",
                latency_ms=latency_ms,
            )
        if decision.choice not in ("buy", "hold", "sell", "short"):
            # 词表外 choice（模型/API 漂移）：绝不采用，按 bad_response 升级 LLM
            logger.warning("[Jev快车道] 词表外 choice=%r，升级 LLM", decision.choice)
            self._escalated += 1
            return FastLaneResult(
                adopted=False,
                signal="",
                confidence=0.0,
                probabilities={},
                reason="bad_response",
                latency_ms=latency_ms,
            )

        # shadow 观察模式永不注入 jev_context（不污染 LLM prompt，
        # Phase 1 一致率观测必须基于未受污染的 LLM 决策）
        inject_context = self.config.mode == "on"

        self._breaker.record_success()
        # 安全旗标一票否决
        risk = response.answers.get("is_high_risk_reversal")
        risk_noul = risk.noul if isinstance(risk, NoulAnswer) else 0.0
        if risk_noul > self.config.risk_noul_gate:
            logger.info(
                "[Jev快车道] 反转风险旗标(%.2f > %.2f)，强制升级 LLM",
                risk_noul,
                self.config.risk_noul_gate,
            )
            self._escalated += 1
            return FastLaneResult(
                adopted=False,
                signal=decision.choice,
                confidence=decision.confidence,
                probabilities=decision.probabilities,
                jev_context=(
                    self._jev_context(decision, risk_noul, response)
                    if inject_context
                    else None
                ),
                reason="risk_gate",
                latency_ms=latency_ms,
            )

        threshold = self._threshold_for(decision.choice)
        if decision.confidence >= threshold:
            if self.config.mode == "shadow":
                # 观察模式：记录本应采用的结果，但不改变行为
                logger.info(
                    "[Jev快车道][shadow] 本可采用 %s (conf=%.2f, %.0fms)，" "仍走 LLM",
                    decision.choice,
                    decision.confidence,
                    latency_ms,
                )
                self._escalated += 1
                return FastLaneResult(
                    adopted=False,
                    signal=decision.choice,
                    confidence=decision.confidence,
                    probabilities=decision.probabilities,
                    jev_context=None,
                    reason="shadow",
                    latency_ms=latency_ms,
                )
            logger.info(
                "[Jev快车道] 采用 %s (conf=%.2f ≥ 阈值%.2f, %.0fms)",
                decision.choice,
                decision.confidence,
                threshold,
                latency_ms,
            )
            self._adopted += 1
            return FastLaneResult(
                adopted=True,
                signal=decision.choice,
                confidence=decision.confidence,
                probabilities=decision.probabilities,
                reason="adopt",
                latency_ms=latency_ms,
            )

        # 置信度不足：升级 LLM 并携带初读上下文（shadow 模式不注入）
        logger.info(
            "[Jev快车道] 置信度不足 (%.2f < %.2f)，升级 LLM",
            decision.confidence,
            threshold,
        )
        self._escalated += 1
        return FastLaneResult(
            adopted=False,
            signal=decision.choice,
            confidence=decision.confidence,
            probabilities=decision.probabilities,
            jev_context=(
                self._jev_context(decision, risk_noul, response)
                if inject_context
                else None
            ),
            reason="low_confidence",
            latency_ms=latency_ms,
        )

    def _enabled(self) -> bool:
        """mode 有效且 Key 已配置；Key 缺失时一次性 WARNING（Review Focus #3）。"""
        if self.config.mode == "off":
            return False
        if not self.config.api_key:
            if not self._key_warned:
                logger.warning(
                    "[Jev快车道] AI_FAST_LANE=%s 但 TYPESAFE_API_KEY 未设置，"
                    "快车道关闭（只走 LLM）。请配置 Key 或设 AI_FAST_LANE=off",
                    self.config.mode,
                )
                self._key_warned = True
            return False
        return True

    def _threshold_for(self, signal: str) -> float:
        """动作对应的非对称置信度阈值（BUY/SELL/SHORT 高，HOLD 低）。"""
        if signal == "buy":
            return self.config.conf_buy
        if signal in ("sell", "short"):
            return self.config.conf_sell
        return self.config.conf_hold

    def _jev_context(
        self,
        decision: ChoiceAnswer,
        risk_noul: float,
        response: SystemOneResponse,
    ) -> str:
        """组装升级 LLM 时的初读上下文（Jev 初读仅供参考，不产生交易指令）。"""
        probs = (
            ", ".join(
                f"{key}={value:.2f}" for key, value in decision.probabilities.items()
            )
            or "n/a"
        )
        choppy = response.answers.get("is_choppy_no_edge")
        choppy_noul = choppy.noul if isinstance(choppy, NoulAnswer) else 0.0
        return (
            "[Jev初读] "
            f"signal={decision.choice} conf={decision.confidence:.2f} "
            f"probabilities: {probs}; "
            f"反转风险Noul={risk_noul:.2f}; "
            f"震荡无方向Noul={choppy_noul:.2f}. "
            "以上为快速模型的初步判断，仅供参考，请以你的完整分析为准。"
        )

    def _record_error(self) -> None:
        self._errors += 1
        self._escalated += 1

    def get_stats(self) -> Dict[str, Any]:
        """统计信息（供 get_metrics() 暴露）。"""
        return {
            **self._breaker.get_stats(),
            "fast_lane_adopted": self._adopted,
            "fast_lane_escalated": self._escalated,
            "fast_lane_errors": self._errors,
            "fast_lane_circuit_open": self._breaker.is_open(),
        }
