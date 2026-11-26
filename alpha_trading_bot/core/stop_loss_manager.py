"""
止损管理器 - 封装止损相关操作

从 TradingBot 中提取的止损逻辑：
- 查询现有止损单
- 更新止损订单（带容错判断）
- 创建止损单（带重试机制）
"""

import logging
from typing import Any, Optional

from .adaptive_stop_loss import AdaptiveStopLossManager

logger = logging.getLogger(__name__)


class StopLossManager:
    """止损管理器"""

    def __init__(
        self,
        exchange: Any,
        config: Any,
        position_manager: Any,
    ):
        self._exchange = exchange
        self._config = config
        self._position_manager = position_manager

    async def get_existing_stop_order_id(self) -> Optional[str]:
        """查询交易所中现有的止损单ID"""
        symbol = self._config.exchange.symbol
        try:
            algo_orders = await self._exchange.get_algo_orders(symbol)
            for order in algo_orders:
                info = order.get("info", {})
                algo_id = info.get("algoId")
                if algo_id:
                    stop_price = info.get("slTriggerPx") or info.get("stopLossPrice")
                    if stop_price:
                        logger.info(
                            f"[止损查询] 找到现有止损单(algo): {algo_id}, 止损价={stop_price}"
                        )
                        return str(algo_id)
        except Exception as e:
            logger.warning(f"[止损查询] 查询算法订单失败: {e}")

        try:
            open_orders = await self._exchange.get_open_orders(symbol)
            for order in open_orders:
                order_type = (order.get("type") or "").lower()
                info = order.get("info", {})
                has_algo_id = bool(info.get("algoId"))
                has_stop_price = bool(
                    info.get("slTriggerPx") or info.get("stopLossPrice")
                )
                is_stop_order = (
                    order_type in ["stop_loss", "stop-loss", "trigger", "stop"]
                    or has_algo_id
                    or has_stop_price
                )
                if is_stop_order:
                    stop_order_id = info.get("algoId") or order.get("id")
                    if stop_order_id:
                        logger.info(
                            f"[止损查询] 找到现有止损单: {stop_order_id} (type={order_type})"
                        )
                        return str(stop_order_id)
        except Exception as e:
            logger.warning(f"[止损查询] 查询普通订单失败: {e}")

        logger.debug("[止损查询] 未找到现有止损单")
        return None

    async def update_stop_loss(
        self, current_price: float, atr_percent: float = 0.0
    ) -> None:
        """更新止损订单（带容错判断，避免频繁更新，支持做多/做空）

        智能止损模式下，新增"当前价与建仓价容错"判断：
        当做多持仓时，如果当前价与建仓价差值 < 0.1%，则不更新止损订单。

        2026-11-25 追踪止损 (模块 1): 计算候选后与统一止损取更紧者;
        trailing 生效时强制更新 (不进容错比较) —— 保本/上移若被容错吞掉,
        仓位利润会回吐到 0R 附近。atr_percent 为 0~1 比率 (0 → 追踪段关闭,
        保本段仍可用); 旧调用不传该参数零回归。
        """
        if not self._position_manager.has_position():
            return

        position = self._position_manager.position
        if position is None:
            logger.error("[止损更新] 数据不一致: has_position=True 但 position 为 None")
            return

        # 价格追踪 (最高/最低价) —— 追踪止损的极值来源; 幂等 (max/min),
        # 与 adaptive_bot 的直接调用同语义, 补上 standard bot 从不更新极值的缺口
        self._position_manager.update_price_tracking(current_price, position.side)

        local_stop_order_id = self._position_manager.stop_order_id
        exchange_stop_order_id = await self.get_existing_stop_order_id()

        if not local_stop_order_id and exchange_stop_order_id:
            logger.info(f"[止损更新] 发现交易所现有止损单: {exchange_stop_order_id}")
            self._position_manager.set_stop_order(exchange_stop_order_id)
            local_stop_order_id = exchange_stop_order_id

        has_existing_stop_order = local_stop_order_id is not None

        # 智能止损模式：检查当前价与建仓价的容错
        if (
            self._config.stop_loss.stop_loss_entry_based
            and position.side == "long"
            and has_existing_stop_order
        ):
            entry_price = self._position_manager.entry_price
            price_vs_entry_tolerance = (
                self._config.stop_loss.price_vs_entry_tolerance_percent
            )
            if entry_price > 0:
                price_vs_entry_percent = (current_price - entry_price) / entry_price
                # 当前价与建仓价差值的绝对值 < 容错值(0.1%)，不更新止损
                if abs(price_vs_entry_percent) < price_vs_entry_tolerance:
                    logger.info(
                        f"[止损更新-智能] 当前价与建仓价差值"
                        f"({price_vs_entry_percent * 100:.4f}%) < "
                        f"容错({price_vs_entry_tolerance * 100}%)，跳过止损更新"
                    )
                    return

        # 使用统一止损计算入口，自动判断做多/做空（M2修复：统一参数来源）
        #
        # 2026-11-26 P0-1 棘轮口径 (11-25 22:05/22:44/00:00 三笔趋势空单复盘):
        # 开仓已锁定初始止损价 (structural stop, 24h 摆动/2.5% 上限) 时,
        # 旧逻辑每周期用"当前价 × (1±STOP_LOSS_PERCENT=0.5%)"重算止损,
        # 第一个 HOLD 周期就把 2.5% 结构止损改写为"当前价+0.5%"——
        # 止损被压进 15m 噪声带 (00:14 一根 0.5% 上影直接扫损)。
        # 关键: 对空仓, 止损下移 = 收紧 (方向安全钳位视角), 单纯
        # "只收紧" 棘轮仍会接受 59754→58673 的有害下移。因此:
        # - 空仓: 保留既有止损, 完全不用当前价口径重锚; 下移收紧只由
        #   trailing 候选 (1R 保本 / 2R 起 3×ATR 极值) 驱动。
        # - 多仓: 保留 entry-based 追踪 (highest×99.98%) 但只允许上移,
        #   下移 (放松) 一律忽略。
        # 旧状态 (无 initial_stop) 保持旧行为, 零回归。
        initial_stop = self._position_manager.initial_stop_price
        if initial_stop > 0:
            base_stop = (
                self._position_manager.last_stop_price
                if self._position_manager.last_stop_price > 0
                else initial_stop
            )
            if position.side == "long":
                unified_stop = self._position_manager.calculate_stop_price_unified(
                    current_price
                )
                if unified_stop > base_stop:
                    logger.info(
                        f"[止损更新-棘轮] 初始止损已锁定, entry-based 追踪上移 "
                        f"{base_stop:.2f} → {unified_stop:.2f} (只收紧不放松)"
                    )
                    new_stop = unified_stop
                else:
                    logger.debug(
                        "[止损更新-棘轮] 初始止损已锁定, 多仓保留现有止损 %.2f "
                        "(候选 %.2f 未高于它, 下移放松被拒绝)",
                        base_stop,
                        unified_stop,
                    )
                    new_stop = base_stop
            else:
                logger.debug(
                    "[止损更新-棘轮] 初始止损已锁定, 空仓跳过当前价口径重算 "
                    "(保留止损 %.2f; 下移收紧仅由 trailing 候选驱动)",
                    base_stop,
                )
                new_stop = base_stop
        else:
            new_stop = self._position_manager.calculate_stop_price_unified(
                current_price
            )
        self._position_manager.log_stop_loss_info(current_price, new_stop)

        # ---- 2026-11-25 追踪止损合并 (模块 1): 只收紧不放松 ----
        # trailing 候选由 PositionManager 按"比当前止损更紧才返回"过滤;
        # 非 None 时取两者更紧者 (多=max, 空=min) 并强制更新 (绕过容错窗口)。
        trailing_stop = self._position_manager.calculate_trailing_stop(
            current_price, atr_percent
        )
        trailing_active = trailing_stop is not None
        if trailing_stop is not None and new_stop > 0:
            if position.side == "long":
                merged_stop = max(new_stop, trailing_stop)
            else:
                merged_stop = min(new_stop, trailing_stop)
            if merged_stop != new_stop:
                logger.info(
                    f"[追踪止损] 追踪候选={trailing_stop:.2f} 比统一止损 {new_stop:.2f} "
                    f"更紧 → 采用追踪价 (方向={position.side})"
                )
            new_stop = merged_stop

        # ---- 方向安全钳位 (OKX 51280/51278 防护, 复用 AdaptiveStopLossManager) ----
        # 做多止损必须 < 当前价, 做空止损必须 > 当前价 (追踪候选用 2R 后极值,
        # 极值更新滞后/ATR=0 边界时可能落在错误一侧)
        safe_stop = AdaptiveStopLossManager._calc_safe_stop_price(
            current_price, position.side
        )
        if safe_stop is not None and new_stop > 0:
            if position.side == "long" and new_stop >= current_price:
                logger.warning(
                    f"[追踪止损] 做多止损 {new_stop:.2f} ≥ 当前价 {current_price:.2f} "
                    f"(方向错误侧) → 钳位到 {safe_stop:.2f}"
                )
                new_stop = safe_stop
            elif position.side == "short" and new_stop <= current_price:
                logger.warning(
                    f"[追踪止损] 做空止损 {new_stop:.2f} ≤ 当前价 {current_price:.2f} "
                    f"(方向错误侧) → 钳位到 {safe_stop:.2f}"
                )
                new_stop = safe_stop

        # 根据持仓方向动态决定止损方向（M4修复：做多→sell，做空→buy）
        stop_side = "sell" if position.side == "long" else "buy"

        if not has_existing_stop_order:
            logger.info("[止损更新] 当前无止损单，直接创建")
            logger.info(f"[止损更新] 创建新止损单: 止损价={new_stop}, 方向={stop_side}")
            stop_order_id = await self.create_stop_loss_with_retry(
                position.amount, new_stop, current_price, stop_side=stop_side
            )
            if stop_order_id:
                self._position_manager.set_stop_order(stop_order_id, new_stop)
                logger.info(f"[止损更新] 止损单设置完成: {stop_order_id}")
            else:
                logger.error("[止损更新] 止损单创建失败，已达最大重试次数")
            return

        tolerance = self._config.stop_loss.stop_loss_tolerance_percent
        old_stop = self._position_manager.last_stop_price

        if old_stop <= 0:
            logger.info("[止损更新] 无历史止损价记录，强制创建止损单")
            old_stop = new_stop
            force_update = True
        else:
            force_update = False
        # 追踪止损生效 → 强制更新 (保本/上移不得被容错窗口吞掉)
        force_update = force_update or trailing_active

        price_diff_percent = abs(new_stop - old_stop) / old_stop if old_stop > 0 else 1

        if price_diff_percent < tolerance and not force_update:
            logger.info(
                f"[止损更新] 变化率:{price_diff_percent * 100:.4f}% < 容错:{tolerance * 100}%({tolerance * current_price:.1f}美元), 跳过更新"
            )
            return

        old_stop_order_id = self._position_manager.stop_order_id
        current_existing_id = await self.get_existing_stop_order_id()

        if current_existing_id:
            logger.info(f"[止损更新] 交易所现有止损单: {current_existing_id}")
            logger.info(f"[止损更新] 取消交易所现有止损单: {current_existing_id}")
            cancel_result = await self._exchange.cancel_algo_order(
                str(current_existing_id), self._config.exchange.symbol
            )
            cancel_success, cancel_reason = cancel_result
            if cancel_success:
                logger.info(f"[止损更新] 止损单取消成功: {current_existing_id}")
            elif cancel_reason == "already_gone":
                logger.info(
                    f"[止损更新] 止损单已不存在(可能已触发): {current_existing_id}"
                )
            else:
                logger.warning(f"[止损更新] 取消止损单失败: {current_existing_id}")
        else:
            logger.info("[止损更新] 交易所无现有止损单")
            if old_stop_order_id:
                logger.info(f"[止损更新] 本地记录 {old_stop_order_id} 已失效")

        logger.info(f"[止损更新] 创建新止损单: 止损价={new_stop}, 方向={stop_side}")
        stop_order_id = await self._exchange.create_stop_loss(
            symbol=self._config.exchange.symbol,
            side=stop_side,
            amount=position.amount,
            stop_price=new_stop,
        )

        self._position_manager.set_stop_order(stop_order_id, new_stop)
        logger.info(f"[止损更新] 止损单设置完成: {stop_order_id}")

    async def create_stop_loss_with_retry(
        self,
        amount: float,
        stop_price: float,
        current_price: float,
        max_retries: int = 2,
        stop_side: str = "sell",
    ) -> Optional[str]:
        """创建止损单（带重试机制，支持做多/做空方向）

        Args:
            amount: 持仓数量
            stop_price: 止损价
            current_price: 当前价格
            max_retries: 最大重试次数
            stop_side: 止损方向 (做多→sell, 做空→buy)
        """
        for attempt in range(max_retries + 1):
            try:
                stop_order_id = await self._exchange.create_stop_loss(
                    symbol=self._config.exchange.symbol,
                    side=stop_side,
                    amount=amount,
                    stop_price=stop_price,
                )
                if stop_order_id:
                    return stop_order_id

                if attempt < max_retries:
                    stop_price = stop_price * 0.998
                    logger.warning(
                        f"[止损重试] 第{attempt + 1}次失败，尝试降低止损价至 {stop_price:.1f}"
                    )
            except Exception as e:
                error_msg = str(e)
                if "SL trigger price must be less than the last price" in error_msg:
                    if attempt < max_retries:
                        stop_price = stop_price * 0.998
                        logger.warning(
                            f"[止损重试] 止损价过高，第{attempt + 1}次重试，"
                            f"降低至 {stop_price:.1f} (当前价={current_price:.1f})"
                        )
                        continue
                logger.error(f"[止损重试] 创建止损单失败: {e}")
                break

        return None
