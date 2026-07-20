"""持仓消失后的平仓审计日志。"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def extract_float(value: Any, default: float = 0.0) -> float:
    """安全提取 float。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class PositionCloseAuditContext:
    """最近持仓上下文，用于下一轮持仓消失审计。"""

    side: str = ""
    entry_price: float = 0.0
    amount: float = 0.0
    unrealized_pnl: float = 0.0
    stop_order_id: str = ""
    stop_price: float = 0.0
    active_close_confirmed: bool = False
    active_close_order_id: str = ""

    def remember(
        self,
        side: str,
        entry_price: Any,
        amount: Any,
        unrealized_pnl: Any = 0.0,
        stop_order_id: str = "",
        stop_price: Any = 0.0,
    ) -> None:
        """保存最近持仓上下文。"""
        self.side = side
        self.entry_price = extract_float(entry_price)
        self.amount = extract_float(amount)
        self.unrealized_pnl = extract_float(unrealized_pnl)
        self.stop_order_id = stop_order_id or ""
        self.stop_price = extract_float(stop_price)
        self.active_close_confirmed = False
        self.active_close_order_id = ""

    def mark_active_close(self, order_id: str = "") -> None:
        """标记最近持仓已由本系统主动平仓。"""
        self.active_close_confirmed = True
        self.active_close_order_id = order_id or ""


class PositionCloseAuditor:
    """查询算法单历史并记录止损/止盈触发平仓事件。"""

    def __init__(self, context: PositionCloseAuditContext):
        self.context = context

    async def log_disappeared_position_close_event(
        self,
        exchange: Any,
        symbol: str,
    ) -> None:
        """查询算法单历史并记录平仓事件。"""
        if self.context.active_close_confirmed:
            logger.info(
                "[平仓审计] 主动平仓已确认，跳过算法单触发审计: "
                f"order_id={self.context.active_close_order_id or 'unknown'}, "
                f"side={self.context.side}, entry={self.context.entry_price}"
            )
            return

        if exchange is None:
            self.log_inferred_position_close_event("exchange_not_initialized")
            return

        history = []
        if self.context.stop_order_id and hasattr(exchange, "get_algo_order_history"):
            try:
                history = await exchange.get_algo_order_history(
                    symbol, algo_id=self.context.stop_order_id, limit=20
                )
            except Exception as e:
                logger.warning(f"[平仓审计] 查询算法单历史失败: {e}")

        matched = self.find_close_algo_history(history)
        if not matched:
            self.log_inferred_position_close_event("algo_history_not_found")
            return

        info = matched.get("info", {})
        close_type = "止盈" if info.get("tpTriggerPx") else "止损"
        trigger_price = extract_float(
            info.get("slTriggerPx")
            or info.get("tpTriggerPx")
            or self.context.stop_price
        )
        exit_price = extract_float(
            info.get("actualPx")
            or info.get("avgPx")
            or info.get("triggerPx")
            or trigger_price
        )
        amount = extract_float(info.get("sz"), self.context.amount)
        pnl_percent = self.calculate_close_pnl_percent(exit_price)
        trigger_time = info.get("triggerTime") or info.get("uTime") or info.get("cTime")

        logger.info(
            f"[平仓确认] {close_type}单触发平仓: "
            f"side={self.context.side}, "
            f"algoId={matched.get('id') or self.context.stop_order_id}, "
            f"entry={self.context.entry_price}, "
            f"{close_type}价={trigger_price}, exit={exit_price}, "
            f"amount={amount}, pnl={pnl_percent:.2f}%, "
            f"trigger_time={trigger_time or 'unknown'}"
        )

    def find_close_algo_history(self, history: Any) -> Optional[Dict[str, Any]]:
        """从算法单历史中找到最近一次止损/止盈触发记录。"""
        if not isinstance(history, list):
            return None
        for order in history:
            if not isinstance(order, dict):
                continue
            info = order.get("info", {})
            algo_id = str(order.get("id") or info.get("algoId") or "")
            if self.context.stop_order_id and algo_id != self.context.stop_order_id:
                continue
            if self._has_close_trigger_field(info) and self._has_trigger_evidence(
                info
            ):
                return order
        return None

    @staticmethod
    def _has_close_trigger_field(info: Dict[str, Any]) -> bool:
        """判断算法单历史是否属于止损/止盈单。"""
        return bool(
            info.get("slTriggerPx")
            or info.get("stopLossPrice")
            or info.get("tpTriggerPx")
            or info.get("takeProfitPrice")
        )

    @staticmethod
    def _has_trigger_evidence(info: Dict[str, Any]) -> bool:
        """判断算法单历史是否包含实际触发或成交证据。"""
        return bool(
            info.get("actualPx")
            or info.get("avgPx")
            or info.get("triggerTime")
            or info.get("ordId")
        )

    def log_inferred_position_close_event(self, reason: str) -> None:
        """算法单历史暂不可用时，至少记录一条可追踪的推断平仓日志。"""
        logger.info(
            f"[平仓推断] 持仓消失，疑似止损/止盈触发: "
            f"side={self.context.side}, "
            f"last_stop_algoId={self.context.stop_order_id or 'unknown'}, "
            f"entry={self.context.entry_price}, "
            f"last_stop={self.context.stop_price}, "
            f"amount={self.context.amount}, "
            f"last_unrealized_pnl={self.context.unrealized_pnl}, "
            f"reason={reason}"
        )

    def calculate_close_pnl_percent(self, exit_price: float) -> float:
        """根据最后持仓上下文估算平仓收益率。"""
        entry = self.context.entry_price
        if entry <= 0 or exit_price <= 0:
            return 0.0
        if self.context.side == "short":
            return (entry - exit_price) / entry * 100
        return (exit_price - entry) / entry * 100
