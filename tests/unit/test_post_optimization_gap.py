"""回归补强：为 6a441d0 commit 复盘新增 2 条用例 (test-plan §2.1 / §2.2)

不修改现有 4 个测试文件中的任何一条；本文件遵守 pytest 命名约定。
"""

import json
import logging
from unittest.mock import MagicMock

import pytest

from alpha_trading_bot.ai.integrator import AISignalIntegrator
from alpha_trading_bot.core.opportunity_audit import OpportunityAuditor


class TestOpportunityAuditNaNThroughGateMetadata:
    """缺口回归：decision.metadata 含 NaN 时 audit 仍能返回 0.0（防 H2 串场）"""

    def test_metadata_nan_passed_to_audit_returns_zero(self) -> None:
        auditor = OpportunityAuditor()
        decision = {
            "action": "skip",
            "reason": "gate blocked (NaN test)",
            "metadata": {
                "confidence_gate_blocked": True,
                "gate_side": "short",
                "final_confidence": float("nan"),
                "min_trade_confidence": 0.4,
                "rsi": 60,
                "trend_strength": 0.05,
            },
        }
        record = auditor.build_skip_record(
            ai_signal="SHORT",
            selected=MagicMock(
                signal="SHORT", confidence=0.5, strategy_type="mean_reversion"
            ),
            decision=decision,
            market_data={
                "price": 64000.0,
                "technical": {"rsi": 60, "trend_strength": 0.05},
            },
            has_position=False,
        )
        assert record["gate_context"]["final_confidence"] == 0.0
        # 数值字段：凡是 _float 走过的字段都应当把 NaN 兜底为 0.0
        assert record["gate_context"]["long_rr"] == 0.0
        assert record["gate_context"]["short_rr"] == 0.0
        # 即便 metadata.min_trade_confidence 是合法 0.4，_float 透传仍正确
        assert record["gate_context"]["min_trade_confidence"] == 0.4




class TestIntegratorConfHistoryMarker:
    """缺口回归：SHORT 走 integrator 时第 4 步必须是 'HighPrice(skip non-BUY)'"""

    def test_short_marker_distinct_from_buy_marker(self, caplog) -> None:
        integrator = AISignalIntegrator()
        market_data = {
            "price": 64000.0,
            "technical": {
                "trend_direction": "sideways",
                "trend_strength": 0.05,
                "rsi": 70,
                "atr_percent": 0.003,
                "price_position": 0.7,
            },
            "price_history": [64000.0] * 60,
            "hourly_changes": [0.0] * 24,
        }
        with caplog.at_level(logging.INFO, logger="alpha_trading_bot.ai.integrator"):
            integrator.process(
                market_data=market_data,
                original_signal="SHORT",
                original_confidence=0.50,
            )

        names = [r.getMessage() for r in caplog.records]
        assert any(
            "[4] HighPrice(skip non-BUY)" in n for n in names
        ), f"期待 SHORT 走 [4] HighPrice(skip non-BUY) marker，实际: {names[-10:]}"
