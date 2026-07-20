"""持仓消失平仓审计测试。"""

import logging
from typing import Any, Dict, List

import pytest

from alpha_trading_bot.core.position_close_audit import (
    PositionCloseAuditContext,
    PositionCloseAuditor,
)


def test_audit_ignores_static_algo_config_without_trigger_evidence() -> None:
    """只有静态触发价配置时，不能推断算法单已经触发。"""
    context = PositionCloseAuditContext(stop_order_id="sl-1")
    auditor = PositionCloseAuditor(context)
    history = [
        {
            "id": "sl-1",
            "info": {
                "algoId": "sl-1",
                "slTriggerPx": "99950",
            },
        }
    ]

    assert auditor.find_close_algo_history(history) is None


def test_audit_accepts_algo_history_with_trigger_evidence() -> None:
    """带实际触发/成交证据的算法单历史仍应被记录。"""
    context = PositionCloseAuditContext(stop_order_id="sl-1")
    auditor = PositionCloseAuditor(context)
    triggered = {
        "id": "sl-1",
        "info": {
            "algoId": "sl-1",
            "slTriggerPx": "99950",
            "actualPx": "99940",
        },
    }

    assert auditor.find_close_algo_history([triggered]) == triggered


@pytest.mark.asyncio
async def test_active_close_skips_disappeared_position_algo_audit(
    caplog: Any,
) -> None:
    """主动平仓已确认时，不查询旧算法单历史以免重复记录止损/止盈。"""
    context = PositionCloseAuditContext(
        side="long",
        entry_price=100.0,
        amount=0.01,
        stop_order_id="sl-1",
    )
    context.mark_active_close("close-1")
    auditor = PositionCloseAuditor(context)

    class _Exchange:
        async def get_algo_order_history(
            self, symbol: str, algo_id: str, limit: int = 20
        ) -> List[Dict[str, Any]]:
            raise AssertionError("active close should not query algo history")

    with caplog.at_level(logging.INFO):
        await auditor.log_disappeared_position_close_event(
            _Exchange(), "BTC/USDT:USDT"
        )

    assert "主动平仓已确认" in caplog.text
