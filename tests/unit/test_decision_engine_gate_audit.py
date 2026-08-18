"""_confidence_gate skip 时携带诊断 metadata 回归测试 (task-card R3)

覆盖：
1. SHORT 35% < 40% 时 gate 阻断并附带 metadata
2. LONG 高位+低置信时 gate 阻断并附带 metadata
3. opportunity_audit 的 gate_context 子字段透传 metadata
"""

from dataclasses import dataclass, field
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from alpha_trading_bot.core.decision_engine import DecisionEngine
from alpha_trading_bot.core.opportunity_audit import OpportunityAuditor


def _config() -> MagicMock:
    config = MagicMock()
    config.trading.allow_short_selling = True
    config.ai.fusion_threshold = 0.5
    return config


@dataclass
class _SelectedStub:
    signal: str = "SHORT"
    confidence: float = 0.55
    strategy_type: str = "mean_reversion"
    reasons: list = field(default_factory=list)


class TestConfidenceGateMetadata:
    def test_short_low_confidence_gate_blocked_carries_metadata(self) -> None:
        """SHORT final_confidence < min_trade_confidence 时 gate 返回带 metadata 的 skip"""
        engine = DecisionEngine(_config())
        market_data = {
            "technical": {"atr_percent": 0.30, "rsi": 60, "trend_strength": 0.05},
            "has_position": False,
            "short_risk_reward_ratio": 2.0,
            "risk_reward_ratio": 1.0,
            "min_trade_confidence": 0.40,
            "ai_final_confidence": 0.35,  # 触发低于阈值
            "final_confidence": 0.35,
        }

        result = engine.make_decision("SHORT", _SelectedStub(), market_data)

        # 决策被 gate 拦截
        assert result["action"] == "skip"
        assert "置信度35%低于阈值40%" in result["reason"]

        # 必须包含 metadata (task-card R3)
        metadata = result.get("metadata")
        assert metadata is not None, "metadata 字段必须存在"
        assert metadata["confidence_gate_blocked"] is True
        assert metadata["gate_side"] == "short"
        assert metadata["final_confidence"] == pytest.approx(0.35)
        assert metadata["min_trade_confidence"] == pytest.approx(0.40)
        assert metadata["short_rr"] == pytest.approx(2.0)
        assert metadata["rsi"] == 60
        assert metadata["trend_strength"] == pytest.approx(0.05)
        # market_structure 没传时为 None 或 ""，行为一致即可
        assert metadata["market_structure"] in (None, "")
        assert metadata["market_structure_direction"] in (None, "")

    def test_long_high_risk_gate_blocked_carries_metadata(self) -> None:
        """LONG 高位+低置信时 gate 阻断并附带 metadata"""
        engine = DecisionEngine(_config())
        market_data = {
            "technical": {"atr_percent": 0.30, "rsi": 60, "trend_strength": 0.05},
            "has_position": False,
            "short_risk_reward_ratio": 0,
            "risk_reward_ratio": 1.0,
            "min_trade_confidence": 0.45,
            "ai_final_confidence": 0.40,
            "final_confidence": 0.40,
            "is_high_risk": True,
        }

        selected = _SelectedStub(signal="BUY", strategy_type="trend_following")
        result = engine.make_decision("BUY", selected, market_data)

        # gate 阻断（LONG + high_risk + conf < 0.55）
        assert result["action"] == "skip"
        assert "BTC高位风险" in result["reason"]

        metadata = result.get("metadata")
        assert metadata is not None
        assert metadata["confidence_gate_blocked"] is True
        assert metadata["gate_side"] == "long"
        assert metadata["short_rr"] is None  # LONG 时 short_rr 应为 None

    def test_gate_passes_does_not_emit_metadata(self) -> None:
        """gate 通过时不应有 confidence_gate_blocked metadata，避免污染"""
        engine = DecisionEngine(_config())
        selected = _SelectedStub(signal="BUY", strategy_type="trend_following")
        market_data = {
            "technical": {"atr_percent": 0.30, "rsi": 60, "trend_strength": 0.05},
            "has_position": False,
            "short_risk_reward_ratio": 0,
            "risk_reward_ratio": 1.5,  # 满足 RR≥1.0 moderate
            "min_trade_confidence": 0.40,
            "ai_final_confidence": 0.65,
            "final_confidence": 0.65,
            "market_structure": "sideways",
        }

        # BUY + 非 high_risk + conf 0.65 > 0.40 → 通过 gate
        result = engine.make_decision("BUY", selected, market_data)

        assert result["action"] in ("open", "skip")  # 取决于后续 R/R
        metadata = result.get("metadata", {})
        # 如果有 metadata，不应有 confidence_gate_blocked=True
        assert not metadata.get("confidence_gate_blocked")


class TestOpportunityAuditGateContext:
    """验证：opportunity_audit 在 decision 带 metadata 时序列化 gate_context."""

    def _build_decision(self) -> Dict[str, Any]:
        return {
            "action": "skip",
            "reason": "最终置信度35%低于阈值40%",
            "confidence": 0.35,
            "strategy": "mean_reversion",
            "metadata": {
                "confidence_gate_blocked": True,
                "gate_side": "short",
                "final_confidence": 0.35,
                "min_trade_confidence": 0.40,
                "long_rr": 1.0,
                "short_rr": 2.5,
                "rsi": 60,
                "trend_strength": 0.05,
                "market_structure": "sideways",
                "market_structure_direction": "short",
            },
        }

    def test_gate_context_built_when_blocked(self) -> None:
        auditor = OpportunityAuditor()
        selected = MagicMock()
        selected.signal = "SHORT"
        selected.confidence = 0.5
        selected.strategy_type = "mean_reversion"

        record = auditor.build_skip_record(
            ai_signal="SHORT",
            selected=selected,
            decision=self._build_decision(),
            market_data={
                "price": 64000.0,
                "market_structure": "sideways",
                "market_structure_direction": "short",
                "risk_reward_ratio": 1.0,
                "short_risk_reward_ratio": 2.5,
                "final_confidence": 0.35,
                "min_trade_confidence": 0.40,
                "technical": {
                    "rsi": 60,
                    "atr_percent": 0.003,
                    "trend_strength": 0.05,
                },
            },
            has_position=False,
        )

        gate = record.get("gate_context", {})
        assert gate.get("gate_blocked") is True
        assert gate.get("final_confidence") == pytest.approx(0.35)
        assert gate.get("min_trade_confidence") == pytest.approx(0.40)
        assert gate.get("short_rr") == pytest.approx(2.5)
        assert gate.get("long_rr") == pytest.approx(1.0)
        assert gate.get("rsi") == 60
        assert gate.get("trend_strength") == pytest.approx(0.05)
        assert gate.get("market_structure") == "sideways"
        assert gate.get("market_structure_direction") == "short"

    def test_gate_context_empty_for_no_metadata(self) -> None:
        """向后兼容：旧 code path 不带 metadata 时，gate_context 必须为空 dict"""
        auditor = OpportunityAuditor()
        selected = MagicMock()
        selected.signal = "HOLD"
        selected.confidence = 0.6
        selected.strategy_type = "mean_reversion"

        # 不带 metadata 的旧 decision
        record = auditor.build_skip_record(
            ai_signal="HOLD",
            selected=selected,
            decision={"action": "skip", "reason": "AI和策略都是HOLD"},
            market_data={"price": 64000.0, "technical": {"rsi": 60}},
            has_position=False,
        )

        assert record.get("gate_context", {}) == {}

    def test_gate_context_safe_with_none_metadata(self) -> None:
        """防御性：metadata=None 时不抛异常"""
        auditor = OpportunityAuditor()
        selected = MagicMock()
        selected.signal = "HOLD"
        selected.confidence = 0.5
        selected.strategy_type = "mean_reversion"

        record = auditor.build_skip_record(
            ai_signal="HOLD",
            selected=selected,
            decision={"action": "skip", "reason": "test", "metadata": None},
            market_data={"price": 64000.0, "technical": {"rsi": 60}},
            has_position=False,
        )

        assert record.get("gate_context", {}) == {}
