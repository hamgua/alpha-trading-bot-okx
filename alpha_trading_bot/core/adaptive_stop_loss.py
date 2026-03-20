"""自适应止损管理模块

从 AdaptiveTradingBot 中提取的止损单创建逻辑（支持多空方向）
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class AdaptiveStopLossManager:
    """自适应止损管理器"""

    def __init__(self, exchange: Any):
        self._exchange = exchange

    async def create_stop_loss_with_retry(
        self,
        amount: float,
        stop_price: float,
        current_price: float,
        max_retries: int = 3,
        position_side: str = "long",
    ) -> Optional[str]:
        """创建止损单（带重试机制）"""
        for attempt in range(max_retries + 1):
            try:
                stop_side = "sell" if position_side == "long" else "buy"
                stop_order_id = await self._exchange.create_stop_loss(
                    symbol=self._exchange.symbol,
                    side=stop_side,
                    amount=amount,
                    stop_price=stop_price,
                )
                if stop_order_id:
                    return stop_order_id
                if attempt < max_retries:
                    stop_price = stop_price * 0.995
                    logger.warning(
                        f"[止损重试] 第{attempt + 1}次失败，降低止损价至 {stop_price:.1f}"
                    )
            except Exception as e:
                if "SL trigger price" in str(e) and attempt < max_retries:
                    stop_price = stop_price * 0.995
                    logger.warning(f"[止损重试] 止损价过高，降低至 {stop_price:.1f}")
                    continue
                logger.error(f"[止损重试] 创建止损单失败: {e}")
                break

        return None
