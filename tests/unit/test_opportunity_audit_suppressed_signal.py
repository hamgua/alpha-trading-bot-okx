"""opportunity_audit 新增 suppressed_signal 观测字段测试。"""

from typing import Any

from alpha_trading_bot.core.opportunity_audit import OpportunityAuditor


def _build_market_data() -> dict:
    return {
        "technical": {"rsi": 35.0, "atr_percent": 0.005, "trend_strength": 0.2},
        "price": 63000.0,
        "market_structure": "bearish",
        "market_structure_direction": "short",
        "risk_reward_ratio": 0.5,
        "short_risk_reward_ratio": 2.5,
        "final_confidence": 0.55,
        "min_trade_confidence": 0.48,
    }


class _Selected:
    def __init__(self, signal: str, strategy_type: str = "mean_reversion", confidence: float = 0.65):
        self.signal = signal
        self.strategy_type = strategy_type
        self.confidence = confidence


def test_suppressed_when_ai_hold_and_strategy_sell() -> None:
    auditor = OpportunityAuditor()
    rec = auditor.build_skip_record(
        ai_signal="HOLD",
        selected=_Selected("SELL"),
        decision={"reason": "AI-HOLD覆盖策略(sell)"},
        market_data=_build_market_data(),
        has_position=False,
    )
    suppressed = rec["suppressed_signal"]
    assert suppressed["suppressed"] is True
    assert suppressed["direction"] == "short"
    assert suppressed["strategy_type"] == "mean_reversion"
    assert "open_short_at_63000.0" in suppressed["hypothetical_action"]


def test_suppressed_when_ai_hold_and_strategy_buy() -> None:
    auditor = OpportunityAuditor()
    rec = auditor.build_skip_record(
        ai_signal="HOLD",
        selected=_Selected("BUY"),
        decision={"reason": "AI-HOLD覆盖策略(buy)"},
        market_data=_build_market_data(),
        has_position=False,
    )
    suppressed = rec["suppressed_signal"]
    assert suppressed["suppressed"] is True
    assert suppressed["direction"] == "long"


def test_not_suppressed_when_ai_buy() -> None:
    auditor = OpportunityAuditor()
    rec = auditor.build_skip_record(
        ai_signal="BUY",
        selected=_Selected("BUY"),
        decision={"reason": "置信度不足"},
        market_data=_build_market_data(),
        has_position=False,
    )
    assert rec["suppressed_signal"] == {"suppressed": False}


def test_not_suppressed_when_strategy_hold() -> None:
    auditor = OpportunityAuditor()
    rec = auditor.build_skip_record(
        ai_signal="HOLD",
        selected=_Selected("HOLD"),
        decision={"reason": "AI和策略都是HOLD"},
        market_data=_build_market_data(),
        has_position=False,
    )
    assert rec["suppressed_signal"] == {"suppressed": False}


def test_hypothetical_action_format() -> None:
    auditor = OpportunityAuditor()
    rec = auditor.build_skip_record(
        ai_signal="HOLD",
        selected=_Selected("SELL"),
        decision={"reason": "AI-HOLD覆盖策略(sell)"},
        market_data=_build_market_data(),
        has_position=False,
    )
    action = rec["suppressed_signal"]["hypothetical_action"]
    assert action.startswith("open_short_at_")
    assert "_with_rr_" in action
