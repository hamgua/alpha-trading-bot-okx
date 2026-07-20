"""止盈价计算模块"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TakeProfitCalculator:
    """止盈价计算器

    止盈价统一基于入场价计算（与 PositionManager 保持一致）：
    - 做多: entry_price × (1 + percent)
    - 做空: entry_price × (1 - percent)
    """

    def __init__(self, config: Any = None):
        self._config = config
        self._take_profit_percent = 0.008
        self._take_profit_mode = "adaptive"
        self._atr_multiplier = 1.5
        self._min_percent = 0.004
        self._max_percent = 0.02
        self._structure_buffer_percent = 0.001
        if config and hasattr(config, "stop_loss"):
            stop_loss = config.stop_loss
            self._take_profit_percent = stop_loss.take_profit_percent
            self._take_profit_mode = getattr(stop_loss, "take_profit_mode", "adaptive")
            self._atr_multiplier = getattr(
                stop_loss, "take_profit_atr_multiplier", 1.5
            )
            self._min_percent = getattr(stop_loss, "take_profit_min_percent", 0.004)
            self._max_percent = getattr(stop_loss, "take_profit_max_percent", 0.02)
            self._structure_buffer_percent = getattr(
                stop_loss, "take_profit_structure_buffer_percent", 0.001
            )

    def calculate(
        self,
        entry_price: float,
        position_side: str,
        market_data: Optional[Dict[str, Any]] = None,
    ) -> float:
        """计算止盈价（基于入场价）

        Args:
            entry_price: 入场价
            position_side: 持仓方向 (long/short)
            market_data: 本周期市场数据，包含 ATR、支撑位、阻力位
        """
        if entry_price <= 0:
            return 0.0

        if self._take_profit_mode == "adaptive" and market_data:
            adaptive_price = self._calculate_adaptive(
                entry_price, position_side, market_data
            )
            if adaptive_price > 0:
                return adaptive_price

        return self._calculate_fixed(entry_price, position_side)

    def _calculate_fixed(self, entry_price: float, position_side: str) -> float:
        """按固定百分比计算止盈价。"""
        percent = self._take_profit_percent
        if position_side == "short":
            take_profit_price = entry_price * (1 - percent)
            logger.info(
                f"[止盈计算-做空] 入场价={entry_price:.1f}, 止盈价={take_profit_price:.1f} "
                f"(价格下跌{percent * 100}%触发)"
            )
        else:
            take_profit_price = entry_price * (1 + percent)
            logger.info(
                f"[止盈计算-做多] 入场价={entry_price:.1f}, 止盈价={take_profit_price:.1f} "
                f"(价格上涨{percent * 100}%触发)"
            )
        return take_profit_price

    def _calculate_adaptive(
        self,
        entry_price: float,
        position_side: str,
        market_data: Dict[str, Any],
    ) -> float:
        """按 ATR 和支撑/阻力计算自适应止盈价。"""
        candidates = self._build_adaptive_candidates(
            entry_price, position_side, market_data
        )
        if not candidates:
            return 0.0

        if position_side == "short":
            take_profit_price = max(candidates)
            take_profit_price = self._clamp_short_target(entry_price, take_profit_price)
            logger.info(
                f"[止盈计算-做空-自适应] 入场价={entry_price:.1f}, "
                f"止盈价={take_profit_price:.1f}, 候选={candidates}"
            )
            return take_profit_price

        take_profit_price = min(candidates)
        take_profit_price = self._clamp_long_target(entry_price, take_profit_price)
        logger.info(
            f"[止盈计算-做多-自适应] 入场价={entry_price:.1f}, "
            f"止盈价={take_profit_price:.1f}, 候选={candidates}"
        )
        return take_profit_price

    def _build_adaptive_candidates(
        self,
        entry_price: float,
        position_side: str,
        market_data: Dict[str, Any],
    ) -> List[float]:
        """生成 ATR 和结构止盈候选价格。"""
        candidates: List[float] = []
        technical = market_data.get("technical", {})
        atr_percent = self._extract_float(technical.get("atr_percent"))
        if atr_percent > 0:
            atr_distance_percent = atr_percent * self._atr_multiplier
            if position_side == "short":
                candidates.append(entry_price * (1 - atr_distance_percent))
            else:
                candidates.append(entry_price * (1 + atr_distance_percent))

        if position_side == "short":
            support = self._extract_float(market_data.get("nearest_support"))
            structure_price = support * (1 + self._structure_buffer_percent)
            if support > 0 and structure_price < entry_price:
                candidates.append(structure_price)
        else:
            resistance = self._extract_float(market_data.get("nearest_resistance"))
            structure_price = resistance * (1 - self._structure_buffer_percent)
            if resistance > 0 and structure_price > entry_price:
                candidates.append(structure_price)

        return candidates

    def _clamp_long_target(self, entry_price: float, target_price: float) -> float:
        """限制做多止盈价距离，避免目标过近或过远。"""
        min_target = entry_price * (1 + self._min_percent)
        max_target = entry_price * (1 + self._max_percent)
        return min(max(target_price, min_target), max_target)

    def _clamp_short_target(self, entry_price: float, target_price: float) -> float:
        """限制做空止盈价距离，避免目标过近或过远。"""
        min_target = entry_price * (1 - self._max_percent)
        max_target = entry_price * (1 - self._min_percent)
        return min(max(target_price, min_target), max_target)

    @staticmethod
    def _extract_float(value: Any) -> float:
        """安全提取 float。"""
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
