"""自适应止损管理模块

从 AdaptiveTradingBot 中提取的止损单创建逻辑（支持多空方向）

注意：OKX 止损单价格限制规则：
  - 做多(LONG)止损 = sell 单：触发价必须 < 当前价 (code 51280)
  - 做空(SHORT)止损 = buy 单：触发价必须 > 当前价 (code 51278)
  重试时必须根据方向调整止损价方向

重试算法升级（2026-06-17 fix-sl-trigger-price）：
  - 重试时优先基于 current_price 重算安全止损价（不再用绝对价格递减）
  - 安全裕度 = max(current_price * 0.001, 1.0 USDT)
  - 兜底：current_price 无效时回退到原百分比调整逻辑
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 安全裕度常量：避免价格波动瞬间触发
_SAFETY_MARGIN_PCT = 0.001  # 0.1% 比例
_SAFETY_MARGIN_ABS = 1.0    # 1 USDT 绝对值


class AdaptiveStopLossManager:
    """自适应止损管理器"""

    def __init__(self, exchange: Any):
        self._exchange = exchange

    @staticmethod
    def _calc_safe_stop_price(
        current_price: float, position_side: str
    ) -> Optional[float]:
        """基于当前价计算安全止损价（避免 OKX 51280/51278 错误）

        Args:
            current_price: 当前市价
            position_side: 持仓方向 (long/short)

        Returns:
            安全止损价（做多 < current_price，做空 > current_price）；
            current_price 无效时返回 None
        """
        if current_price <= 0:
            return None
        margin = max(current_price * _SAFETY_MARGIN_PCT, _SAFETY_MARGIN_ABS)
        if position_side == "short":
            return current_price + margin
        return current_price - margin

    async def create_stop_loss_with_retry(
        self,
        amount: float,
        stop_price: float,
        current_price: float,
        max_retries: int = 3,
        position_side: str = "long",
    ) -> Optional[str]:
        """创建止损单（带重试机制）

        重试策略：
        - 首次：使用传入的 stop_price（基于建仓价或 ATR 算法）
        - 重试：当 OKX 返回 51280/51278 错误时，优先基于 current_price
          重算安全止损价（而不是简单的百分比递减），确保严格满足
          OKX 的触发价约束。
        - 兜底：当 current_price 无效时，回退到原百分比调整逻辑。

        Args:
            amount: 数量
            stop_price: 止损触发价
            current_price: 当前市价（用于重试时参考）
            max_retries: 最大重试次数
            position_side: 持仓方向 (long/short)
        """
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
                    return str(stop_order_id)
                if attempt < max_retries:
                    # 返回值为空：基于 current_price 计算安全止损价
                    safe_price = self._calc_safe_stop_price(
                        current_price, position_side
                    )
                    if safe_price is not None:
                        stop_price = safe_price
                        logger.warning(
                            f"[止损重试] 第{attempt + 1}次失败，"
                            f"基于当前价({current_price:.1f})"
                            f"重算止损价至 {stop_price:.1f}"
                        )
                    else:
                        # 兜底：current_price 无效，按方向调整
                        if position_side == "short":
                            stop_price = stop_price * 1.005
                        else:
                            stop_price = stop_price * 0.995
                        logger.warning(
                            f"[止损重试] 第{attempt + 1}次失败，"
                            f"current_price无效，按方向调整至 {stop_price:.1f}"
                        )
            except Exception as e:
                error_msg = str(e)
                if "SL trigger price" in error_msg and attempt < max_retries:
                    safe_price = self._calc_safe_stop_price(
                        current_price, position_side
                    )
                    if safe_price is not None:
                        stop_price = safe_price
                        logger.warning(
                            f"[止损重试] 止损价与当前价不符，"
                            f"基于当前价({current_price:.1f})"
                            f"重算止损价至 {stop_price:.1f}"
                        )
                        continue
                    # 兜底：current_price 无效，按方向调整
                    if position_side == "short":
                        stop_price = stop_price * 1.005
                        logger.warning(
                            f"[止损重试] 止损价过低，提高至 {stop_price:.1f}"
                        )
                    else:
                        stop_price = stop_price * 0.995
                        logger.warning(
                            f"[止损重试] 止损价过高，降低至 {stop_price:.1f}"
                        )
                    continue
                logger.error(f"[止损重试] 创建止损单失败: {e}")
                break

        return None
