"""持仓状态恢复模块

从 AdaptiveTradingBot 中提取的持仓验证和恢复逻辑：
- 订单创建失败后验证持仓状态
- 平仓前取消止损单
"""

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class PositionRecoveryManager:
    """持仓状态恢复管理器"""

    def __init__(
        self,
        exchange: Any,
        position_manager: Any,
    ):
        self._exchange = exchange
        self._position_manager = position_manager

    async def verify_and_recover_position(self) -> None:
        """验证并恢复持仓状态"""
        try:
            logger.info("[状态验证] 重新获取持仓状态验证...")
            position_data = await self._exchange.get_position_with_retry(
                max_retries=3, retry_delay=1.0
            )

            if position_data and position_data.get("amount", 0) > 0:
                side = position_data.get("side", "")
                amount = position_data.get("amount", 0)
                entry_price = position_data.get("entry_price", 0)

                self._position_manager.update_from_exchange(position_data)

                if side == "short" or side == "short_to_close":
                    logger.error(
                        f"[状态验证] 检测到未平空单！数量={amount}, 入场价={entry_price}. "
                        f"请手动处理或等待下一个周期重试平仓"
                    )
                else:
                    logger.info(f"[状态验证] 持仓已更新: {side} {amount}@{entry_price}")
            else:
                query_failed = getattr(self._exchange, "last_query_failed", False)
                if query_failed:
                    logger.warning(
                        "[状态验证] API查询持仓失败，保留本地持仓状态不清理"
                    )
                else:
                    if self._position_manager.has_position():
                        local_pos = self._position_manager.position
                        logger.warning(
                            "[状态验证] API返回无持仓但本地有持仓状态，清理本地缓存。"
                            f"本地持仓: 方向={local_pos.side if local_pos else 'N/A'}, "
                            f"入场价={self._position_manager.entry_price}"
                        )
                    self._position_manager.update_from_exchange({})

        except Exception as e:
            logger.error(f"[状态验证] 获取持仓失败: {e}")

    async def cancel_stop_loss_before_close(self) -> None:
        """平仓前取消现有止损单"""
        await self.cancel_protection_orders_before_close()

    async def cancel_protection_orders_before_close(self) -> None:
        """平仓前取消现有止损/止盈保护单。"""
        try:
            protection_ids = await self._get_existing_protection_order_ids()
            if not protection_ids:
                logger.debug("[平仓] 无现有保护单需要取消")
                self._clear_local_protection_orders()
                return

            all_cleared = True
            for algo_id in protection_ids:
                logger.info(f"[平仓] 取消现有保护单: {algo_id}")
                result = await self._exchange.cancel_algo_order(
                    str(algo_id), self._exchange.symbol
                )
                cancel_success, cancel_reason = self._normalize_cancel_result(result)
                if cancel_success or cancel_reason == "already_gone":
                    logger.info(f"[平仓] 保护单已取消: {algo_id}")
                    continue
                all_cleared = False
                logger.warning(
                    f"[平仓] 取消保护单失败: {algo_id}, 原因={cancel_reason}"
                )

            if all_cleared:
                self._clear_local_protection_orders()
        except Exception as e:
            logger.warning(f"[平仓] 取消保护单失败: {e}")

    async def _get_existing_stop_order_id(self) -> Optional[str]:
        """查询交易所中现有的止损单ID"""
        try:
            algo_orders = await self._exchange.get_algo_orders(self._exchange.symbol)
            for order in algo_orders:
                info = order.get("info", {})
                algo_id = info.get("algoId")

                if algo_id:
                    stop_price = info.get("slTriggerPx") or info.get("stopLossPrice")
                    if stop_price:
                        logger.info(
                            f"[止损查询] 找到现有止损单: algoId={algo_id}, 止损价={stop_price}"
                        )
                        return str(algo_id)
            logger.debug("[止损查询] 无现有止损单")
        except Exception as e:
            logger.warning(f"[止损查询] 查询失败: {e}")
        return None

    async def _get_existing_protection_order_ids(self) -> List[str]:
        """查询本地和交易所中现有的止损/止盈保护单ID。"""
        protection_ids: List[str] = []
        seen: Set[str] = set()

        for algo_id in self._get_local_protection_order_ids():
            if algo_id not in seen:
                protection_ids.append(algo_id)
                seen.add(algo_id)

        try:
            algo_orders = await self._exchange.get_algo_orders(self._exchange.symbol)
            for order in algo_orders:
                info = order.get("info", {})
                algo_id = str(order.get("id") or info.get("algoId") or "")
                if not algo_id or algo_id in seen:
                    continue
                if self._has_protection_trigger(info):
                    protection_ids.append(algo_id)
                    seen.add(algo_id)
                    logger.info(f"[保护单查询] 找到现有保护单: algoId={algo_id}")
            if not protection_ids:
                logger.debug("[保护单查询] 无现有保护单")
        except Exception as e:
            logger.warning(f"[保护单查询] 查询失败: {e}")

        return protection_ids

    def _get_local_protection_order_ids(self) -> List[str]:
        """读取本地记录的止损/止盈单ID。"""
        order_ids: List[str] = []
        stop_order_id = getattr(self._position_manager, "stop_order_id", None)
        take_profit_order_id = getattr(
            self._position_manager, "take_profit_order_id", None
        )
        if stop_order_id:
            order_ids.append(str(stop_order_id))
        if take_profit_order_id:
            order_ids.append(str(take_profit_order_id))
        return order_ids

    @staticmethod
    def _has_protection_trigger(info: Dict[str, Any]) -> bool:
        """判断算法单是否包含止损或止盈触发字段。"""
        return bool(
            info.get("slTriggerPx")
            or info.get("stopLossPrice")
            or info.get("tpTriggerPx")
            or info.get("takeProfitPrice")
        )

    @staticmethod
    def _normalize_cancel_result(result: Any) -> Tuple[bool, str]:
        """兼容不同交易所取消接口返回格式。"""
        if isinstance(result, tuple) and len(result) >= 2:
            return bool(result[0]), str(result[1])
        return bool(result), "ok" if result else "unknown"

    def _clear_local_protection_orders(self) -> None:
        """清理本地保护单状态，兼容旧 PositionManager。"""
        clear_protection_orders = getattr(
            self._position_manager, "clear_protection_orders", None
        )
        if callable(clear_protection_orders):
            clear_protection_orders()
        else:
            self._position_manager.set_stop_order(None, 0)
