"""持仓状态恢复模块

从 AdaptiveTradingBot 中提取的持仓验证和恢复逻辑：
- 订单创建失败后验证持仓状态
- 平仓前取消止损单
"""

import logging
from typing import Any, Dict, Optional

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
                logger.info("[状态验证] 交易所无持仓")
                self._position_manager.update_from_exchange({})

        except Exception as e:
            logger.error(f"[状态验证] 获取持仓失败: {e}")

    async def cancel_stop_loss_before_close(self) -> None:
        """平仓前取消现有止损单"""
        try:
            existing_stop_id = await self._get_existing_stop_order_id()
            if existing_stop_id:
                logger.info(f"[平仓] 取消现有止损单: {existing_stop_id}")
                await self._exchange.cancel_algo_order(
                    str(existing_stop_id), self._exchange.symbol
                )
                logger.info("[平仓] 止损单已取消")
                self._position_manager.set_stop_order(None, 0)
            else:
                logger.debug("[平仓] 无现有止损单需要取消")
        except Exception as e:
            logger.warning(f"[平仓] 取消止损单失败: {e}")

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
