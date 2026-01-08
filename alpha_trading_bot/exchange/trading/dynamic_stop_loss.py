"""
动态止损系统 - 基于ATR和市场波动率的智能止损
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class DynamicStopLoss:
    """动态止损管理器"""

    # ATR倍数配置（基于市场波动性）
    ATR_MULTIPLIERS = {
        "conservative": 2.0,  # 低波动市场
        "normal": 2.5,  # 正常波动市场
        "volatile": 3.0,  # 高波动市场
        "extreme": 4.0,  # 极端波动市场
    }

    # 最小止损百分比（防止过度收紧）
    MIN_STOP_LOSS_PCT = {
        "BTC": 0.008,  # BTC最小0.8%
        "ETH": 0.012,  # ETH最小1.2%
        "default": 0.015,  # 其他币种默认1.5%
    }

    # 最大止损百分比（防止过度宽松）
    MAX_STOP_LOSS_PCT = {
        "BTC": 0.08,  # BTC最大8%
        "ETH": 0.10,  # ETH最大10%
        "default": 0.12,  # 其他币种最大12%
    }

    def __init__(self):
        self.atr_cache = {}
        self.volatility_regime = "normal"

    def calculate_stop_loss(
        self,
        entry_price: float,
        current_price: float,
        atr_14: float,
        symbol: str = "BTC",
        position_side: str = "long",
        market_volatility: str = "normal",
        account_risk_pct: float = 0.02,  # 账户风险2%
    ) -> Dict[str, Any]:
        """
        计算动态止损价格

        Args:
            entry_price: 入场价格
            current_price: 当前价格
            atr_14: 14日ATR值
            symbol: 交易币种
            position_side: 持仓方向 ('long' 或 'short')
            market_volatility: 市场波动率等级
            account_risk_pct: 账户风险百分比

        Returns:
            包含止损价格和信息的字典
        """
        try:
            # 1. 基于ATR计算基础止损距离
            atr_based_stop = self._calculate_atr_stop_loss(
                entry_price, atr_14, symbol, market_volatility
            )

            # 2. 基于账户风险调整止损距离
            risk_adjusted_stop = self._adjust_for_account_risk(
                entry_price, account_risk_pct, symbol
            )

            # 3. 基于价格位置优化止损
            price_position_stop = self._adjust_for_price_position(
                entry_price, current_price, symbol
            )

            # 4. 综合计算最终止损价格
            final_stop_loss = self._calculate_final_stop_loss(
                entry_price,
                current_price,
                atr_based_stop,
                risk_adjusted_stop,
                price_position_stop,
                position_side,
                symbol,
            )

            # 5. 计算追踪止损参数
            trailing_params = self._calculate_trailing_params(
                entry_price, current_price, symbol, market_volatility
            )

            return {
                "stop_loss_price": final_stop_loss,
                "stop_loss_pct": price_position_stop,  # 现在直接使用位置止损百分比
                "atr_based_pct": atr_based_stop,
                "risk_adjusted_pct": risk_adjusted_stop,
                "price_position_pct": price_position_stop,  # 位置止损就是最终使用的百分比
                "trailing_enabled": trailing_params["enabled"],
                "trailing_distance_pct": trailing_params["distance_pct"],
                "trailing_step_pct": trailing_params["step_pct"],
                "volatility_regime": market_volatility,
                "symbol": symbol,
                "position_side": position_side,
                "updated_at": datetime.now(),
            }

        except Exception as e:
            logger.error(f"计算动态止损失败: {e}")
            # 失败时使用保守的默认止损
            default_stop = entry_price * (0.98 if position_side == "long" else 1.02)
            return {
                "stop_loss_price": default_stop,
                "stop_loss_pct": 0.02,
                "error": str(e),
                "fallback": True,
            }

    def _calculate_atr_stop_loss(
        self, entry_price: float, atr_14: float, symbol: str, market_volatility: str
    ) -> float:
        """基于ATR计算止损百分比"""
        # 获取当前波动率对应的ATR倍数
        atr_multiplier = self.ATR_MULTIPLIERS.get(market_volatility, 2.5)

        # 计算ATR止损距离
        atr_stop_distance = (atr_14 / entry_price) * atr_multiplier

        # 获取币种特定的最小/最大止损限制
        min_stop = self.MIN_STOP_LOSS_PCT.get(symbol, self.MIN_STOP_LOSS_PCT["default"])
        max_stop = self.MAX_STOP_LOSS_PCT.get(symbol, self.MAX_STOP_LOSS_PCT["default"])

        # 确保止损在合理范围内
        atr_stop_distance = max(min_stop, min(max_stop, atr_stop_distance))

        logger.info(
            f"ATR止损计算: 倍数={atr_multiplier}, 距离={atr_stop_distance:.2%}, "
            f"ATR={atr_14:.2f}, 入场价={entry_price:.2f}"
        )

        return atr_stop_distance

    def _adjust_for_account_risk(
        self, entry_price: float, account_risk_pct: float, symbol: str
    ) -> float:
        """基于账户风险调整止损"""
        # 基础风险调整
        risk_multiplier = account_risk_pct / 0.02  # 以2%为标准风险

        # 计算风险调整后的止损
        risk_adjusted_stop = 0.02 * risk_multiplier  # 基础2% * 风险倍数

        # 确保不低于最小止损
        min_stop = self.MIN_STOP_LOSS_PCT.get(symbol, self.MIN_STOP_LOSS_PCT["default"])
        risk_adjusted_stop = max(min_stop, risk_adjusted_stop)

        logger.info(
            f"风险调整止损: 账户风险={account_risk_pct:.1%}, "
            f"调整后={risk_adjusted_stop:.2%}"
        )

        return risk_adjusted_stop

    def _adjust_for_price_position(
        self, entry_price: float, current_price: float, symbol: str
    ) -> float:
        """基于价格位置设置止损百分比"""
        # 计算价格变化百分比
        price_change_pct = (current_price - entry_price) / entry_price

        # 根据价格位置直接设置止损百分比
        if price_change_pct >= 0:
            # 持仓高于入仓价格：止损0.2%
            stop_loss_pct = 0.002  # 0.2%
            logger.info(
                f"价格位置: 盈利{price_change_pct:.2%}, 设置止损为{stop_loss_pct:.2%}"
            )
        else:
            # 持仓低于入仓价格：止损0.5%
            stop_loss_pct = 0.005  # 0.5%
            logger.info(
                f"价格位置: 亏损{price_change_pct:.2%}, 设置止损为{stop_loss_pct:.2%}"
            )

        return stop_loss_pct

    def _calculate_final_stop_loss(
        self,
        entry_price: float,
        current_price: float,
        atr_based_stop: float,
        risk_adjusted_stop: float,
        price_position_stop: float,
        position_side: str,
        symbol: str,
    ) -> float:
        """计算最终止损价格"""
        # 现在price_position_stop直接是基于价格位置的止损百分比
        # 使用这个百分比作为最终止损
        if position_side == "long":
            stop_loss_price = entry_price * (1 - price_position_stop)

            # 确保止损价格不超过当前价格（防止立即触发）
            if stop_loss_price >= current_price:
                # 调整止损到当前价格下方
                stop_loss_price = current_price * 0.995  # 当前价下方0.5%
                logger.warning(f"止损价格调整: 原止损价过高，调整到当前价下方0.5%")

        else:  # 空头
            stop_loss_price = entry_price * (1 + price_position_stop)

            # 确保止损价格不低于当前价格
            if stop_loss_price <= current_price:
                stop_loss_price = current_price * 1.005  # 当前价上方0.5%

        logger.info(
            f"最终止损计算: 入场价={entry_price:.2f}, "
            f"位置止损={price_position_stop:.2%}"
        )

        return round(stop_loss_price, 2)

    def _calculate_trailing_params(
        self,
        entry_price: float,
        current_price: float,
        symbol: str,
        market_volatility: str,
    ) -> Dict[str, Any]:
        """计算追踪止损参数"""
        # 盈利超过1%时启用追踪止损
        profit_pct = (current_price - entry_price) / entry_price

        if profit_pct > 0.01:  # 盈利超过1%
            # 根据波动率设置追踪距离
            if market_volatility == "low":
                trailing_distance = 0.008  # 0.8%
                trailing_step = 0.004  # 0.4%
            elif market_volatility == "normal":
                trailing_distance = 0.012  # 1.2%
                trailing_step = 0.006  # 0.6%
            else:  # high/extreme
                trailing_distance = 0.02  # 2%
                trailing_step = 0.01  # 1%

            return {
                "enabled": True,
                "distance_pct": trailing_distance,
                "step_pct": trailing_step,
            }

        return {"enabled": False, "distance_pct": 0, "step_pct": 0}

    def update_trailing_stop(
        self,
        entry_price: float,
        current_price: float,
        current_stop: float,
        trailing_distance_pct: float,
        position_side: str = "long",
    ) -> Dict[str, Any]:
        """更新追踪止损价格"""
        try:
            if position_side == "long":
                # 计算新的追踪止损价格
                new_trailing_stop = current_price * (1 - trailing_distance_pct)

                # 只在止损价格可以提高时更新（追踪止损只上移）
                if new_trailing_stop > current_stop:
                    logger.info(
                        f"追踪止损更新: {current_stop:.2f} → {new_trailing_stop:.2f} "
                        f"(当前价={current_price:.2f}, 距离={trailing_distance_pct:.1%})"
                    )
                    return {
                        "updated": True,
                        "new_stop_loss": new_trailing_stop,
                        "update_reason": "trailing_stop_updated",
                    }

            return {
                "updated": False,
                "new_stop_loss": current_stop,
                "update_reason": "no_update_needed",
            }

        except Exception as e:
            logger.error(f"更新追踪止损失败: {e}")
            return {"updated": False, "new_stop_loss": current_stop, "error": str(e)}

    def get_volatility_regime(
        self, atr_percent: float, price_volatility_24h: float
    ) -> str:
        """确定当前波动率制度"""
        # ATR百分比判断
        if atr_percent < 0.2:
            regime = "low"
        elif atr_percent < 0.5:
            regime = "normal"
        elif atr_percent < 1.0:
            regime = "volatile"
        else:
            regime = "extreme"

        # 24小时价格波动率调整
        if price_volatility_24h > 0.15:  # 24小时波动超过15%
            regime = "extreme"
        elif price_volatility_24h > 0.08:  # 24小时波动超过8%
            if regime != "extreme":
                regime = "volatile"

        self.volatility_regime = regime
        return regime
