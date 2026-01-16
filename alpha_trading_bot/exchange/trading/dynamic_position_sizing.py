"""
动态仓位管理系统 - 基于多重风险因子的智能仓位管理
"""

import logging
import numpy as np
from typing import Dict, Any, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


class DynamicPositionSizing:
    """动态仓位管理器"""

    # 风险等级对应的仓位上限
    RISK_POSITION_LIMITS = {
        "very_low": 0.05,  # 5% - 极低风险
        "low": 0.10,  # 10% - 低风险
        "medium": 0.20,  # 20% - 中等风险
        "high": 0.30,  # 30% - 高风险
        "very_high": 0.50,  # 50% - 极高风险（慎用）
    }

    # 波动率对应的仓位调整系数
    VOLATILITY_MULTIPLIERS = {
        "very_low": 1.5,  # 低波动可以加大仓位
        "low": 1.2,
        "normal": 1.0,
        "high": 0.7,
        "very_high": 0.4,  # 高波动减小仓位
    }

    # 凯利公式参数
    KELLY_FRACTION = 0.25  # 使用1/4凯利公式，降低风险
    MIN_KELLY_FRACTION = 0.1  # 最小凯利比例

    def __init__(self):
        self.position_history = []
        self.performance_metrics = {
            "win_rate": 0.5,
            "avg_win": 0.02,
            "avg_loss": 0.015,
            "sharpe_ratio": 1.0,
            "max_drawdown": 0.05,
        }

    def calculate_position_size(
        self,
        account_balance: float,
        current_price: float,
        atr_14: float,
        signal_strength: float = 0.5,
        confidence: float = 0.5,
        market_volatility: str = "normal",
        risk_level: str = "medium",
        win_rate: float = None,
        avg_win: float = None,
        avg_loss: float = None,
        symbol: str = "BTC",
        position_side: str = "long",
        max_risk_per_trade: float = 0.02,  # 每笔交易最大风险2%
    ) -> Dict[str, Any]:
        """
        计算动态仓位大小

        Args:
            account_balance: 账户余额
            current_price: 当前价格
            atr_14: 14日ATR
            signal_strength: 信号强度 (0-1)
            confidence: 置信度 (0-1)
            market_volatility: 市场波动率等级
            risk_level: 风险等级
            win_rate: 胜率（如不提供使用历史数据）
            avg_win: 平均盈利（如不提供使用历史数据）
            avg_loss: 平均亏损（如不提供使用历史数据）
            symbol: 交易币种
            position_side: 持仓方向
            max_risk_per_trade: 每笔交易最大风险比例

        Returns:
            包含仓位大小和详细信息的字典
        """
        try:
            # 1. 基础仓位计算（基于风险等级）
            base_position = self._calculate_base_position(
                account_balance, risk_level, max_risk_per_trade
            )

            # 2. 凯利公式优化（基于历史表现）
            kelly_position = self._calculate_kelly_position(
                win_rate or self.performance_metrics["win_rate"],
                avg_win or self.performance_metrics["avg_win"],
                avg_loss or self.performance_metrics["avg_loss"],
                account_balance,
            )

            # 3. 波动率调整
            volatility_adjusted = self._adjust_for_volatility(
                base_position, market_volatility, atr_14, current_price
            )

            # 4. 信号质量调整
            signal_adjusted = self._adjust_for_signal_quality(
                volatility_adjusted, signal_strength, confidence
            )

            # 5. 风险因子综合调整
            final_position = self._apply_risk_factors(
                signal_adjusted,
                market_volatility,
                risk_level,
                current_price,
                atr_14,
                account_balance,
            )

            # 6. 计算实际交易数量
            position_size_info = self._calculate_contract_size(
                final_position, current_price, symbol, account_balance
            )

            # 7. 生成详细报告
            position_report = self._generate_position_report(
                account_balance,
                base_position,
                kelly_position,
                volatility_adjusted,
                signal_adjusted,
                final_position,
                position_size_info,
                symbol,
                position_side,
            )

            return position_report

        except Exception as e:
            logger.error(f"计算动态仓位失败: {e}")
            # 失败时使用保守的默认仓位
            default_size = account_balance * 0.01 / current_price  # 1%风险
            return {
                "position_size": default_size,
                "position_value": default_size * current_price,
                "risk_percentage": 0.01,
                "error": str(e),
                "fallback": True,
            }

    def _calculate_base_position(
        self, account_balance: float, risk_level: str, max_risk_per_trade: float
    ) -> float:
        """基于风险等级计算基础仓位"""
        # 获取风险等级对应的仓位上限
        risk_limit = self.RISK_POSITION_LIMITS.get(risk_level, 0.20)

        # 基础仓位 = 账户余额 * 风险限制 * 风险系数
        # 使用最大风险的1/2作为基础，给后续调整留空间
        base_risk = min(max_risk_per_trade * 0.5, risk_limit)

        base_position_value = account_balance * base_risk

        logger.info(
            f"基础仓位计算 - 风险等级: {risk_level}, 上限: {risk_limit:.1%}, "
            f"基础风险: {base_risk:.1%}, 仓位价值: ${base_position_value:.2f}"
        )

        return base_position_value

    def _calculate_kelly_position(
        self, win_rate: float, avg_win: float, avg_loss: float, account_balance: float
    ) -> float:
        """使用凯利公式计算最优仓位"""
        try:
            # 凯利公式：f = (p*b - q*a) / (b*a)
            # p = 胜率, q = 败率, b = 平均盈利, a = 平均亏损
            p = win_rate
            q = 1 - p
            b = avg_win
            a = avg_loss

            # 计算凯利比例
            if a == 0:
                kelly_fraction = 0
            else:
                kelly_fraction = (p * b - q * a) / (b * a)

            # 应用凯利分数限制（使用1/4凯利降低风险）
            kelly_fraction = max(0, min(kelly_fraction, 1.0))  # 确保在0-1之间
            adjusted_kelly = kelly_fraction * self.KELLY_FRACTION

            # 确保不低于最小凯利比例
            adjusted_kelly = max(adjusted_kelly, self.MIN_KELLY_FRACTION)

            # 计算凯利仓位价值
            kelly_position = account_balance * adjusted_kelly

            logger.info(
                f"凯利公式计算 - 胜率: {win_rate:.1%}, 平均盈利: {avg_win:.2%}, "
                f"平均亏损: {avg_loss:.2%}, 凯利比例: {kelly_fraction:.2%}, "
                f"调整后: {adjusted_kelly:.2%}, 仓位价值: ${kelly_position:.2f}"
            )

            return kelly_position

        except Exception as e:
            logger.error(f"凯利公式计算失败: {e}")
            return account_balance * 0.02  # 默认2%仓位

    def _adjust_for_volatility(
        self,
        base_position: float,
        market_volatility: str,
        atr_14: float,
        current_price: float,
    ) -> float:
        """基于波动率调整仓位"""
        # 获取波动率调整系数
        vol_multiplier = self.VOLATILITY_MULTIPLIERS.get(market_volatility, 1.0)

        # 计算ATR百分比
        atr_percent = atr_14 / current_price if current_price > 0 else 0.02

        # ATR额外调整
        if atr_percent < 0.01:  # ATR < 1%
            atr_adjustment = 1.2
        elif atr_percent < 0.02:  # ATR 1-2%
            atr_adjustment = 1.0
        elif atr_percent < 0.03:  # ATR 2-3%
            atr_adjustment = 0.8
        else:  # ATR > 3%
            atr_adjustment = 0.6

        # 综合调整
        volatility_adjusted = base_position * vol_multiplier * atr_adjustment

        logger.info(
            f"波动率调整 - 市场波动率: {market_volatility}, 调整系数: {vol_multiplier:.2f}, "
            f"ATR百分比: {atr_percent:.2%}, ATR调整: {atr_adjustment:.2f}, "
            f"调整后仓位: ${volatility_adjusted:.2f}"
        )

        return volatility_adjusted

    def _adjust_for_signal_quality(
        self, position_value: float, signal_strength: float, confidence: float
    ) -> float:
        """基于信号质量调整仓位"""
        # 信号质量综合评分
        signal_score = signal_strength * 0.6 + confidence * 0.4

        # 信号质量调整系数
        # 信号越好，仓位越大；信号越差，仓位越小
        if signal_score > 0.8:  # 强信号
            signal_multiplier = 1.2
        elif signal_score > 0.6:  # 中等信号
            signal_multiplier = 1.0
        elif signal_score > 0.4:  # 弱信号
            signal_multiplier = 0.7
        else:  # 极弱信号
            signal_multiplier = 0.4

        signal_adjusted = position_value * signal_multiplier

        logger.info(
            f"信号质量调整 - 信号强度: {signal_strength:.2f}, 置信度: {confidence:.2f}, "
            f"综合评分: {signal_score:.2f}, 调整系数: {signal_multiplier:.2f}, "
            f"调整后仓位: ${signal_adjusted:.2f}"
        )

        return signal_adjusted

    def _apply_risk_factors(
        self,
        position_value: float,
        market_volatility: str,
        risk_level: str,
        current_price: float,
        atr_14: float,
        account_balance: float,
    ) -> float:
        """应用综合风险因子"""
        risk_factors = []

        # 1. 价格水平风险（高价资产风险更大）
        if current_price > 50000:  # BTC > 50k
            risk_factors.append(0.9)  # 降低10%
        elif current_price > 30000:
            risk_factors.append(1.0)  # 无调整
        else:
            risk_factors.append(1.1)  # 增加10%

        # 2. 波动率风险
        if market_volatility == "very_high":
            risk_factors.append(0.7)
        elif market_volatility == "high":
            risk_factors.append(0.85)
        elif market_volatility == "low":
            risk_factors.append(1.1)
        else:
            risk_factors.append(1.0)

        # 3. ATR异常风险
        atr_percent = atr_14 / current_price if current_price > 0 else 0.02
        if atr_percent > 0.05:  # ATR > 5%
            risk_factors.append(0.7)
        elif atr_percent > 0.03:  # ATR > 3%
            risk_factors.append(0.85)

        # 4. 风险等级限制
        risk_limit = self.RISK_POSITION_LIMITS.get(risk_level, 0.20)
        max_position_value = account_balance * risk_limit
        if position_value > max_position_value:
            position_value = max_position_value
            risk_factors.append(max_position_value / position_value)

        # 综合风险因子
        if risk_factors:
            final_risk_factor = sum(risk_factors) / len(risk_factors)
            final_position = position_value * final_risk_factor
            logger.info(
                f"综合风险因子调整 - 风险因子: {risk_factors}, 平均: {final_risk_factor:.2f}"
            )
        else:
            final_position = position_value

        return final_position

    def _calculate_contract_size(
        self,
        position_value_usd: float,
        current_price: float,
        symbol: str,
        account_balance: float,
    ) -> Dict[str, Any]:
        """计算合约数量"""
        try:
            # 基础合约价值计算
            if symbol == "BTC":
                contract_size = 0.01  # BTC合约通常是0.01张
            else:
                contract_size = 0.1  # 其他币种可能是0.1张

            # 计算合约数量
            contracts = position_value_usd / (current_price * contract_size)

            # 确保最小交易量
            min_contracts = 0.01
            if contracts < min_contracts:
                contracts = min_contracts
                logger.warning(f"仓位小于最小交易量，调整为最小值: {contracts}")

            # 确保最大交易量限制（防止过度交易）
            max_contracts = 10.0  # 最大10张
            if contracts > max_contracts:
                contracts = max_contracts
                logger.warning(f"仓位超过最大限制，调整为最大值: {contracts}")

            actual_position_value = contracts * contract_size * current_price

            return {
                "contracts": round(contracts, 4),
                "contract_size": contract_size,
                "position_value_usd": actual_position_value,
                "contracts_risk_pct": actual_position_value / account_balance,
            }

        except Exception as e:
            logger.error(f"合约数量计算失败: {e}")
            return {
                "contracts": 0.01,  # 最小合约数
                "contract_size": 0.01,
                "position_value_usd": 0.01 * current_price,
                "contracts_risk_pct": 0.001,
            }

    def _generate_position_report(
        self,
        account_balance: float,
        base_position: float,
        kelly_position: float,
        volatility_adjusted: float,
        signal_adjusted: float,
        final_position: float,
        contract_info: Dict[str, Any],
        symbol: str,
        position_side: str,
    ) -> Dict[str, Any]:
        """生成仓位详细报告"""
        report = {
            "timestamp": datetime.now(),
            "symbol": symbol,
            "position_side": position_side,
            "account_balance": account_balance,
            # 仓位计算过程
            "base_position_value": base_position,
            "kelly_position_value": kelly_position,
            "volatility_adjusted_value": volatility_adjusted,
            "signal_adjusted_value": signal_adjusted,
            "final_position_value": final_position,
            # 合约信息
            "contracts": contract_info["contracts"],
            "contract_size": contract_info["contract_size"],
            "position_value_usd": contract_info["position_value_usd"],
            "risk_percentage": contract_info["contracts_risk_pct"],
            # 风险指标
            "position_leverage": contract_info["position_value_usd"] / account_balance,
            "risk_efficiency": final_position / max(base_position, 1),
            # 建议
            "recommendation": self._get_position_recommendation(
                contract_info["contracts_risk_pct"]
            ),
        }

        logger.info(f"仓位管理报告生成完成 - 建议: {report['recommendation']}")
        return report

    def _get_position_recommendation(self, risk_pct: float) -> str:
        """根据风险百分比给出建议"""
        if risk_pct < 0.005:
            return "仓位过小，可能影响收益"
        elif risk_pct < 0.01:
            return "仓位偏小，可考虑适当增加"
        elif risk_pct < 0.03:
            return "仓位适中，风险可控"
        elif risk_pct < 0.05:
            return "仓位较大，注意风险控制"
        else:
            return "仓位过大，建议减仓"

    def update_performance_metrics(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        sharpe_ratio: float = None,
        max_drawdown: float = None,
    ):
        """更新绩效指标（用于优化凯利公式）"""
        self.performance_metrics.update(
            {
                "win_rate": win_rate,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "sharpe_ratio": sharpe_ratio
                or self.performance_metrics["sharpe_ratio"],
                "max_drawdown": max_drawdown
                or self.performance_metrics["max_drawdown"],
            }
        )

        logger.info(
            f"绩效指标已更新 - 胜率: {win_rate:.1%}, 平均盈利: {avg_win:.2%}, "
            f"平均亏损: {avg_loss:.2%}"
        )

    def calculate_position_size_for_recovery(
        self,
        current_drawdown: float,
        account_balance: float,
        target_recovery_pct: float = 0.5,
    ) -> float:
        """计算恢复性仓位（用于处理回撤后的仓位调整）"""
        try:
            # 计算需要恢复的金额
            peak_balance = account_balance / (1 - current_drawdown)
            loss_amount = peak_balance - account_balance
            target_recovery_amount = loss_amount * target_recovery_pct

            # 基于历史胜率计算成功概率
            success_prob = self.performance_metrics["win_rate"]

            # 计算所需仓位
            avg_return = self.performance_metrics[
                "avg_win"
            ] * success_prob - self.performance_metrics["avg_loss"] * (1 - success_prob)

            if avg_return <= 0:
                return account_balance * 0.01  # 保守仓位

            required_position = target_recovery_amount / (avg_return * success_prob)

            # 限制最大仓位（不超过账户余额的30%）
            max_position = account_balance * 0.30
            final_position = min(required_position, max_position)

            logger.info(
                f"恢复性仓位计算 - 当前回撤: {current_drawdown:.1%}, "
                f"目标恢复: {target_recovery_pct:.1%}, 所需仓位: ${final_position:.2f}"
            )

            return final_position

        except Exception as e:
            logger.error(f"恢复性仓位计算失败: {e}")
            return account_balance * 0.02  # 默认2%仓位
