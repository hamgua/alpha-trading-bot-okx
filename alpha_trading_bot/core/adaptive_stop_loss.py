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

重试距离保持（2026-09-20 loss-structure-fix / R6）：
  - 原止损价仍在当前价正确一侧时直接复用（保留入场时锁定的 0.5%~1.5% 风险距离）
  - 仅当价格已越过原止损价（正确性被破坏）时才夹到 current_price ± 安全裕度
  - 旧实现重试一律塌缩到 current_price ± max(0.1%, 1 USDT) —— 对 BTC 约
    0.0013%~0.1%，比 15 分钟周期噪音还窄，日志中曾出现 +0.015% 的"止损"
    (2026-09-04 空单)，等同裸露仓位，是独立亏损源。
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 安全裕度常量：避免价格波动瞬间触发
_SAFETY_MARGIN_PCT = 0.001  # 0.1% 比例
_SAFETY_MARGIN_ABS = 1.0  # 1 USDT 绝对值


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

    @staticmethod
    def _rebase_stop_price_for_retry(
        original_stop: float,
        current_price: float,
        position_side: str,
    ) -> float:
        """重试重算止损价：优先保留原止损价（=保留入场风险距离）。

        2026-09-20 loss-structure-fix / R6:
        - 原止损价在当前价正确一侧 (做多 < current, 做空 > current) → 直接复用
        - 价格已越过原止损价 → 夹到 current_price ± 安全裕度
        """
        if original_stop <= 0 or current_price <= 0:
            return original_stop
        margin = max(current_price * _SAFETY_MARGIN_PCT, _SAFETY_MARGIN_ABS)
        if position_side == "short":
            # 空单止损 = buy 单, 触发价必须 > 当前价
            if original_stop > current_price:
                return original_stop
            return current_price + margin
        # 多单止损 = sell 单, 触发价必须 < 当前价
        if original_stop < current_price:
            return original_stop
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
                    # 返回值为空：优先保留原止损价，仅当价格已越界时夹到
                    # current_price 附近（避免 0.1% 塌缩止损，R6）
                    safe_price = self._rebase_stop_price_for_retry(
                        stop_price, current_price, position_side
                    )
                    if current_price > 0 and safe_price != stop_price:
                        stop_price = safe_price
                        logger.warning(
                            f"[止损重试] 第{attempt + 1}次失败，"
                            f"原止损价越界，重算至 {stop_price:.1f} "
                            f"(当前价 {current_price:.1f})"
                        )
                        continue
                    if current_price <= 0:
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
                    safe_price = self._rebase_stop_price_for_retry(
                        stop_price, current_price, position_side
                    )
                    if current_price > 0 and safe_price != stop_price:
                        stop_price = safe_price
                        logger.warning(
                            f"[止损重试] 止损价与当前价不符，"
                            f"原止损价越界，重算至 {stop_price:.1f} "
                            f"(当前价 {current_price:.1f})"
                        )
                        continue
                    if current_price > 0:
                        # 原止损价已在正确一侧但交易所仍拒绝：
                        # 按安全裕度再挪一档后重试（保留风险距离主体）
                        margin = max(
                            current_price * _SAFETY_MARGIN_PCT,
                            _SAFETY_MARGIN_ABS,
                        )
                        stop_price = (
                            stop_price + margin
                            if position_side == "short"
                            else stop_price - margin
                        )
                        logger.warning(
                            f"[止损重试] 原止损价越界校正失败，"
                            f"按裕度再调整至 {stop_price:.1f}"
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
