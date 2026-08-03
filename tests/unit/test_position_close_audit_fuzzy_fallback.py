"""平仓审计 fuzzy 匹配与多 ordType 增强的回归测试。"""

import logging
from typing import Any, Dict, List

import pytest

from alpha_trading_bot.core.position_close_audit import (
    PositionCloseAuditContext,
    PositionCloseAuditor,
)


def test_exact_match_still_preferred_over_fuzzy() -> None:
    """精确 algo_id 命中时，匹配策略标记为 exact_algo_id（不进 Pass 2）。"""
    context = PositionCloseAuditContext(
        stop_order_id="sl-1", stop_price=63050.0
    )
    auditor = PositionCloseAuditor(context)
    exact = {
        "id": "sl-1",
        "info": {
            "algoId": "sl-1",
            "slTriggerPx": "63050",
            "actualPx": "63040",
        },
    }
    matched = auditor.find_close_algo_history([exact])
    assert matched is exact
    assert matched["_match_strategy"] == "exact_algo_id"


def test_fuzzy_match_when_algo_id_not_found_but_price_matches() -> None:
    """algo_id 找不到时，按 stop_price ±0.5% 容差做模糊匹配。"""
    context = PositionCloseAuditContext(
        stop_order_id="sl-missing", stop_price=63000.0
    )
    auditor = PositionCloseAuditor(context)
    candidate = {
        "id": "unknown-id",
        "info": {
            "algoId": "unknown-id",
            "slTriggerPx": "63100",  # ~0.16% 偏差
            "actualPx": "63090",
        },
    }
    matched = auditor.find_close_algo_history([candidate])
    assert matched is candidate
    assert matched["_match_strategy"] == "fuzzy_price"


def test_no_fuzzy_match_when_price_outside_tolerance() -> None:
    """价格偏差超过 ±0.5% 不做模糊匹配。"""
    context = PositionCloseAuditContext(
        stop_order_id="sl-missing", stop_price=63000.0
    )
    auditor = PositionCloseAuditor(context)
    outside = {
        "id": "x",
        "info": {
            "algoId": "x",
            "slTriggerPx": "63500",  # ~0.79% 偏差
            "actualPx": "63490",
        },
    }
    assert auditor.find_close_algo_history([outside]) is None


def test_no_fuzzy_match_when_no_trigger_evidence() -> None:
    """即使价格命中容差，没有触发/成交证据也拒绝。"""
    context = PositionCloseAuditContext(
        stop_order_id="sl-missing", stop_price=63000.0
    )
    auditor = PositionCloseAuditor(context)
    no_evidence = {
        "id": "x",
        "info": {
            "algoId": "x",
            "slTriggerPx": "63010",
        },
    }
    assert auditor.find_close_algo_history([no_evidence]) is None


def test_no_fuzzy_match_when_stop_price_is_zero() -> None:
    """context.stop_price 为 0 时不进入 Pass 2，避免除零/无意义匹配。"""
    context = PositionCloseAuditContext(stop_order_id="sl-missing", stop_price=0.0)
    auditor = PositionCloseAuditor(context)
    history = [
        {
            "id": "x",
            "info": {
                "algoId": "x",
                "slTriggerPx": "63000",
                "actualPx": "63000",
            },
        }
    ]
    assert auditor.find_close_algo_history(history) is None


@pytest.mark.asyncio
async def test_log_inferred_includes_ord_types_queried(caplog: Any) -> None:
    """平仓推断日志中包含 ord_types_queried 字段，便于人工复检。"""
    context = PositionCloseAuditContext(
        side="long",
        entry_price=63000.0,
        amount=0.01,
        stop_order_id="sl-missing",
        stop_price=63000.0,
    )
    auditor = PositionCloseAuditor(context)

    class _Exchange:
        async def get_algo_order_history(
            self,
            symbol: str,
            algo_id: str = "",
            limit: int = 20,
            ord_types: Any = None,
        ) -> List[Dict[str, Any]]:
            return []

    with caplog.at_level(logging.INFO):
        await auditor.log_disappeared_position_close_event(
            _Exchange(), "BTC/USDT:USDT"
        )

    assert "ord_types_queried" in caplog.text
    assert "conditional" in caplog.text
