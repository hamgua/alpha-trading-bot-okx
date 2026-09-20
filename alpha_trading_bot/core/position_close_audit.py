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
    # 2026-09-20 loss-structure-fix / R5: 止盈单上下文。
    # 旧实现只查止损单 algo 历史 —— 止盈单触发平仓时止损单无成交记录，
    # 永远 algo_history_not_found，49% 平仓只能"推断"且按止损价估算 PnL
    # (止盈盈利被记成止损亏损)，学习闭环样本系统性失真。
    take_profit_order_id: str = ""
    take_profit_price: float = 0.0
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
        take_profit_order_id: str = "",
        take_profit_price: Any = 0.0,
    ) -> None:
        """保存最近持仓上下文。"""
        self.side = side
        self.entry_price = extract_float(entry_price)
        self.amount = extract_float(amount)
        self.unrealized_pnl = extract_float(unrealized_pnl)
        self.stop_order_id = stop_order_id or ""
        self.stop_price = extract_float(stop_price)
        self.take_profit_order_id = take_profit_order_id or ""
        self.take_profit_price = extract_float(take_profit_price)
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
    ) -> Dict[str, Any]:
        """查询算法单历史并记录平仓事件。

        Returns:
            解析结果 dict（dream C2 学习闭环补记）：
              - handled: 是否建议上层补记 close_trade
              - close_type: confirmed(算法单实际成交) / estimated(last_stop估算)
              - quality: confirmed_algo / estimated_last_stop
              - match_strategy: exact_algo_id / fuzzy_price / none
              - side / exit_price
              - pnl_percent: 百分比(仅供日志/审计，补记用 exit_price 重算)
              - reason: 未补记时的原因
        """
        if self.context.active_close_confirmed:
            logger.info(
                "[平仓审计] 主动平仓已确认，跳过算法单触发审计: "
                f"order_id={self.context.active_close_order_id or 'unknown'}, "
                f"side={self.context.side}, entry={self.context.entry_price}"
            )
            return {
                "handled": False,
                "reason": "active_close_confirmed",
                "match_strategy": "none",
            }

        if exchange is None:
            self.log_inferred_position_close_event("exchange_not_initialized")
            return {
                "handled": False,
                "reason": "exchange_not_initialized",
                "match_strategy": "none",
            }

        history = []
        ord_types_queried: list = []
        if self.context.stop_order_id and hasattr(exchange, "get_algo_order_history"):
            ord_types_queried = ["conditional", "trigger", "move_order_stop"]
            try:
                history = await exchange.get_algo_order_history(
                    symbol,
                    algo_id=self.context.stop_order_id,
                    limit=20,
                    ord_types=ord_types_queried,
                )
            except TypeError:
                # 兼容旧版签名（无 ord_types 参数）
                ord_types_queried = ["conditional"]
                try:
                    history = await exchange.get_algo_order_history(
                        symbol, algo_id=self.context.stop_order_id, limit=20
                    )
                except Exception as e:
                    logger.warning(f"[平仓审计] 查询算法单历史失败(legacy): {e}")
            except Exception as e:
                logger.warning(f"[平仓审计] 查询算法单历史失败: {e}")

        matched = self.find_close_algo_history(history)
        if not matched:
            # 2026-09-20 loss-structure-fix / R5: 止损单无成交记录时，
            # 再查止盈单 algo 历史 —— 止盈触发的平仓此前永远落入"推断"，
            # 且按止损价估算 PnL（止盈盈利被记成止损亏损）。
            tp_match = await self._query_take_profit_close(exchange)
            if tp_match is not None:
                return tp_match
            self.log_inferred_position_close_event(
                "algo_history_not_found",
                ord_types_queried=ord_types_queried,
            )
            # dream C2: 算法单历史暂不可用，但持仓确实消失（交易所侧止损/止盈已成交）。
            # 用最后锁定的止损价做估算补记，打质量标记 estimated_last_stop；
            # 止损价缺失时回退止盈价（追踪止损更新后 stop_price 可能过期/缺失，
            # 但止盈单不随追踪更新，仍是有效保护价）。
            est_price = (
                self.context.stop_price
                if self.context.stop_price > 0
                else self.context.take_profit_price
            )
            if est_price > 0:
                est_pnl = self.calculate_close_pnl_percent(est_price)
                return {
                    "handled": True,
                    "close_type": "estimated",
                    "quality": "estimated_last_stop",
                    "match_strategy": "none",
                    "side": self.context.side,
                    "exit_price": est_price,
                    "pnl_percent": est_pnl,
                }
            return {
                "handled": False,
                "reason": "no_exit_price",
                "match_strategy": "none",
            }

        info = matched.get("info", {})
        match_strategy = matched.get("_match_strategy", "exact_algo_id")
        close_type = (
            "止盈" if info.get("tpTriggerPx") or info.get("takeProfitPrice") else "止损"
        )
        trigger_price = extract_float(
            info.get("slTriggerPx")
            or info.get("tpTriggerPx")
            or info.get("stopLossPrice")
            or info.get("takeProfitPrice")
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
            f"match={match_strategy}, "
            f"entry={self.context.entry_price}, "
            f"{close_type}价={trigger_price}, exit={exit_price}, "
            f"amount={amount}, pnl={pnl_percent:.2f}%, "
            f"trigger_time={trigger_time or 'unknown'}"
        )
        # dream C2: 返回解析结果，供上层补记 performance_tracker.close_trade
        return {
            "handled": True,
            "close_type": "confirmed",
            "quality": "confirmed_algo",
            "match_strategy": match_strategy,
            "side": self.context.side,
            "exit_price": exit_price,
            "pnl_percent": pnl_percent,
        }

    def find_close_algo_history(self, history: Any) -> Optional[Dict[str, Any]]:
        """从算法单历史中找到最近一次止损/止盈触发记录。

        优先精确匹配 algo_id；若 algo_id 不匹配，按止损/止盈价格容差 ±0.5%
        与 context.stop_price 做粗糙匹配（标记 _match_strategy=fuzzy_price）。
        """
        return self._match_close_history(
            history,
            order_id=self.context.stop_order_id,
            ref_price=self.context.stop_price,
        )

    def _match_close_history(
        self,
        history: Any,
        order_id: str,
        ref_price: float,
    ) -> Optional[Dict[str, Any]]:
        """通用算法单历史匹配（精确 algo_id → 价格容差 ±0.5%）。"""
        if not isinstance(history, list):
            return None

        # Pass 1: exact algo_id match
        for order in history:
            if not isinstance(order, dict):
                continue
            info = order.get("info", {})
            algo_id = str(order.get("id") or info.get("algoId") or "")
            if order_id and algo_id != order_id:
                continue
            if self._has_close_trigger_field(info) and self._has_trigger_evidence(info):
                order["_match_strategy"] = "exact_algo_id"
                return order

        # Pass 2: fuzzy price match (仅当未通过 algo_id 找到时)
        if ref_price > 0:
            tolerance = 0.005  # ±0.5% 容差
            for order in history:
                if not isinstance(order, dict):
                    continue
                info = order.get("info", {})
                for price_key in (
                    "slTriggerPx",
                    "stopLossPrice",
                    "tpTriggerPx",
                    "takeProfitPrice",
                ):
                    raw = info.get(price_key)
                    if raw is None:
                        continue
                    try:
                        px = float(raw)
                    except (TypeError, ValueError):
                        continue
                    if abs(
                        px - ref_price
                    ) / ref_price <= tolerance and self._has_trigger_evidence(info):
                        order["_match_strategy"] = "fuzzy_price"
                        return order
        return None

    async def _query_take_profit_close(self, exchange: Any) -> Optional[Dict[str, Any]]:
        """查询止盈单 algo 历史并确认止盈触发平仓。

        2026-09-20 loss-structure-fix / R5: 止盈触发的持仓消失不再落入
        "推断平仓"，按止盈成交价确认 PnL（精确 algo_id 匹配才确认，
        价格模糊匹配只记录日志不补记，避免误记不相关历史单）。
        """
        tp_order_id = self.context.take_profit_order_id
        if not tp_order_id or exchange is None:
            return None
        if not hasattr(exchange, "get_algo_order_history"):
            return None
        try:
            history = await exchange.get_algo_order_history(
                self._symbol_hint(exchange),
                algo_id=tp_order_id,
                limit=20,
                ord_types=["conditional", "trigger", "move_order_stop"],
            )
        except TypeError:
            try:
                history = await exchange.get_algo_order_history(
                    self._symbol_hint(exchange),
                    algo_id=tp_order_id,
                    limit=20,
                )
            except Exception as e:
                logger.warning(f"[平仓审计] 查询止盈单历史失败(legacy): {e}")
                return None
        except Exception as e:
            logger.warning(f"[平仓审计] 查询止盈单历史失败: {e}")
            return None

        matched = self._match_close_history(
            history, order_id=tp_order_id, ref_price=self.context.take_profit_price
        )
        if matched is None:
            return None

        info = matched.get("info", {})
        match_strategy = matched.get("_match_strategy", "exact_algo_id")
        exit_price = extract_float(
            info.get("actualPx")
            or info.get("avgPx")
            or info.get("tpTriggerPx")
            or self.context.take_profit_price
        )
        if exit_price <= 0:
            return None
        if match_strategy != "exact_algo_id":
            # 模糊匹配不可作为补记依据，仅留日志
            logger.info(
                f"[平仓审计] 止盈单历史模糊匹配(不补记): "
                f"side={self.context.side}, tp_algoId={tp_order_id}, "
                f"match={match_strategy}, exit={exit_price}"
            )
            return None
        pnl_percent = self.calculate_close_pnl_percent(exit_price)
        logger.info(
            f"[平仓确认] 止盈单触发平仓: side={self.context.side}, "
            f"algoId={tp_order_id}, match=exact_algo_id, "
            f"entry={self.context.entry_price}, "
            f"止盈价={self.context.take_profit_price}, exit={exit_price}, "
            f"amount={self.context.amount}, pnl={pnl_percent:.2f}%"
        )
        return {
            "handled": True,
            "close_type": "confirmed",
            "quality": "confirmed_algo",
            "match_strategy": "exact_algo_id",
            "side": self.context.side,
            "exit_price": exit_price,
            "pnl_percent": pnl_percent,
        }

    @staticmethod
    def _symbol_hint(exchange: Any) -> str:
        """安全提取交易所符号，审计查询失败不抛异常。"""
        try:
            return str(getattr(exchange, "symbol", "") or "")
        except Exception:
            return ""

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

    def log_inferred_position_close_event(
        self, reason: str, ord_types_queried: Optional[list] = None
    ) -> None:
        """算法单历史暂不可用时，至少记录一条可追踪的推断平仓日志。"""
        ord_types_str = ",".join(ord_types_queried or []) or "none"
        logger.info(
            f"[平仓推断] 持仓消失，疑似止损/止盈触发: "
            f"side={self.context.side}, "
            f"last_stop_algoId={self.context.stop_order_id or 'unknown'}, "
            f"entry={self.context.entry_price}, "
            f"last_stop={self.context.stop_price}, "
            f"amount={self.context.amount}, "
            f"last_unrealized_pnl={self.context.unrealized_pnl}, "
            f"reason={reason}, "
            f"ord_types_queried={ord_types_str}"
        )

    def calculate_close_pnl_percent(self, exit_price: float) -> float:
        """根据最后持仓上下文估算平仓收益率。"""
        entry = self.context.entry_price
        if entry <= 0 or exit_price <= 0:
            return 0.0
        if self.context.side == "short":
            return (entry - exit_price) / entry * 100
        return (exit_price - entry) / entry * 100
