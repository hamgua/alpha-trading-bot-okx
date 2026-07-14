"""跳过交易机会审计测试。"""

import json
from unittest.mock import MagicMock

from alpha_trading_bot.core.opportunity_audit import OpportunityAuditor


def _selected(signal: str = "BUY", confidence: float = 0.72) -> MagicMock:
    selected = MagicMock()
    selected.signal = signal
    selected.confidence = confidence
    selected.strategy_type = "trend_following"
    selected.reasons = ["优先策略: trend_following"]
    return selected


def test_build_skip_record_contains_decision_context():
    """审计记录应包含跳过原因、信号、结构和 R/R。"""
    auditor = OpportunityAuditor()
    market_data = {
        "price": 62662.0,
        "market_structure": "bearish",
        "market_structure_direction": "none",
        "risk_reward_ratio": 0.8,
        "short_risk_reward_ratio": 1.4,
        "final_confidence": 0.72,
        "min_trade_confidence": 0.40,
        "technical": {
            "rsi": 48,
            "atr_percent": 0.03,
            "trend_strength": 0.08,
        },
    }
    decision = {"action": "skip", "reason": "AI-HOLD覆盖策略(BUY)"}

    record = auditor.build_skip_record(
        ai_signal="HOLD",
        selected=_selected(),
        decision=decision,
        market_data=market_data,
        has_position=False,
    )

    assert record["event"] == "skip_opportunity"
    assert record["decision_reason"] == "AI-HOLD覆盖策略(BUY)"
    assert record["ai_signal"] == "HOLD"
    assert record["strategy_signal"] == "BUY"
    assert record["market_structure"] == "bearish"
    assert record["short_risk_reward_ratio"] == 1.4
    assert record["technical"]["rsi"] == 48
    json.dumps(record, ensure_ascii=False)


def test_build_skip_record_marks_short_candidate():
    """bearish + 短 R/R 足够时应标记潜在做空机会。"""
    auditor = OpportunityAuditor()
    record = auditor.build_skip_record(
        ai_signal="HOLD",
        selected=_selected("HOLD", 0.72),
        decision={"action": "skip", "reason": "AI和策略都是HOLD"},
        market_data={
            "price": 62662.0,
            "market_structure": "bearish",
            "short_risk_reward_ratio": 1.25,
            "technical": {"rsi": 48, "atr_percent": 0.03, "trend_strength": 0.08},
        },
        has_position=False,
    )

    assert record["opportunity_flags"]["short_candidate"] is True
    assert record["opportunity_flags"]["long_candidate"] is False
