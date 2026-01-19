"""
交易成本分析系统 - 全面分析交易成本对策略的影响
"""

import logging
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict, deque

logger = logging.getLogger(__name__)


@dataclass
class TransactionCost:
    """单笔交易成本"""

    symbol: str
    side: str  # 'buy' or 'sell'
    quantity: float
    entry_price: float
    exit_price: float
    expected_price: float
    actual_price: float
    maker_fee: float = 0.0
    taker_fee: float = 0.0
    slippage: float = 0.0
    total_cost: float = 0.0
    cost_percentage: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ExecutionQuality:
    """订单执行质量"""

    order_id: str
    symbol: str
    order_type: str
    side: str
    quantity: float
    requested_price: float
    average_executed_price: float
    best_bid: float
    best_ask: float
    mid_price: float
    execution_time: float  # 执行时间（秒）
    fill_rate: float  # 成交率
    price_improvement: float  # 价格改善
    slippage_bps: float  # 滑点（基点）
    execution_quality_score: float  # 执行质量评分
    timestamp: datetime = field(default_factory=datetime.now)


class TransactionCostAnalyzer:
    """交易成本分析器"""

    # OKX交易所费率（需要根据实际账户等级调整）
    OKX_FEE_RATES = {
        "maker": {
            "regular": 0.0008,  # 0.08%
            "vip1": 0.0006,  # 0.06%
            "vip2": 0.0004,  # 0.04%
            "vip3": 0.0002,  # 0.02%
            "vip4": 0.0000,  # 0.00%
        },
        "taker": {
            "regular": 0.0010,  # 0.10%
            "vip1": 0.0008,  # 0.08%
            "vip2": 0.0006,  # 0.06%
            "vip3": 0.0004,  # 0.04%
            "vip4": 0.0002,  # 0.02%
        },
    }

    # 执行质量标准
    EXECUTION_QUALITY_BENCHMARKS = {
        "fill_rate": {
            "excellent": 0.95,  # 95%以上成交率
            "good": 0.85,  # 85%以上
            "acceptable": 0.75,  # 75%以上
            "poor": 0.50,  # 50%以下
        },
        "slippage_bps": {
            "excellent": 1,  # 1个基点以内
            "good": 3,  # 3个基点以内
            "acceptable": 5,  # 5个基点以内
            "poor": 10,  # 10个基点以上
        },
        "execution_time": {
            "excellent": 0.1,  # 0.1秒内
            "good": 0.5,  # 0.5秒内
            "acceptable": 1.0,  # 1秒内
            "poor": 3.0,  # 3秒以上
        },
    }

    def __init__(self, account_tier: str = "regular"):
        self.account_tier = account_tier
        self.fee_rates = self._get_fee_rates(account_tier)
        self.transaction_history: List[TransactionCost] = []
        self.execution_history: List[ExecutionQuality] = []
        self.daily_costs = defaultdict(list)
        self.weekly_costs = defaultdict(list)
        self.monthly_costs = defaultdict(list)

        # 滑点统计
        self.slippage_stats = {
            "buy": deque(maxlen=100),
            "sell": deque(maxlen=100),
            "market": deque(maxlen=100),
            "limit": deque(maxlen=100),
        }

        # 执行质量统计
        self.quality_stats = {
            "avg_fill_rate": 0.0,
            "avg_slippage_bps": 0.0,
            "avg_execution_time": 0.0,
            "total_orders": 0,
            "quality_score": 0.0,
        }

    def _get_fee_rates(self, account_tier: str) -> Dict[str, float]:
        """获取当前账户等级的费率"""
        maker_fee = self.OKX_FEE_RATES["maker"].get(
            account_tier, self.OKX_FEE_RATES["maker"]["regular"]
        )
        taker_fee = self.OKX_FEE_RATES["taker"].get(
            account_tier, self.OKX_FEE_RATES["taker"]["regular"]
        )

        return {"maker": maker_fee, "taker": taker_fee}

    def calculate_transaction_cost(
        self,
        symbol: str,
        side: str,
        quantity: float,
        expected_price: float,
        actual_price: float,
        order_type: str = "market",
        is_maker: bool = False,
    ) -> TransactionCost:
        """
        计算单笔交易成本

        Args:
            symbol: 交易对
            side: 交易方向 ('buy' or 'sell')
            quantity: 交易数量
            expected_price: 预期价格（下单时的价格）
            actual_price: 实际成交价格
            order_type: 订单类型 ('market', 'limit')
            is_maker: 是否为maker订单

        Returns:
            TransactionCost: 交易成本详情
        """
        try:
            # 处理None或0的价格
            if actual_price is None or actual_price == 0:
                actual_price = expected_price
            if expected_price is None or expected_price == 0:
                expected_price = actual_price

            # 再次检查，确保有有效价格
            if expected_price == 0 or actual_price == 0:
                logger.warning(
                    f"价格无效: expected_price={expected_price}, actual_price={actual_price}"
                )
                return TransactionCost(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    entry_price=0,
                    exit_price=0,
                    expected_price=0,
                    actual_price=0,
                    total_cost=0,
                    cost_percentage=0,
                )

            # 计算名义价值
            notional_value = quantity * actual_price

            # 计算手续费
            fee_rate = self.fee_rates["maker"] if is_maker else self.fee_rates["taker"]
            fee_amount = notional_value * fee_rate

            # 计算滑点
            if side == "buy":
                # 买入时，实际价格高于预期价格为负滑点
                slippage = (actual_price - expected_price) / expected_price
            else:  # sell
                # 卖出时，实际价格低于预期价格为负滑点
                slippage = (expected_price - actual_price) / expected_price

            # 滑点成本（以百分比表示）
            slippage_cost = abs(slippage) * notional_value

            # 总成本
            total_cost = fee_amount + slippage_cost

            # 成本占比
            cost_percentage = total_cost / notional_value

            # 记录滑点统计
            self.slippage_stats[side].append(slippage * 10000)  # 转换为基点
            self.slippage_stats[order_type].append(slippage * 10000)

            # 创建交易成本记录
            cost_record = TransactionCost(
                symbol=symbol,
                side=side,
                quantity=quantity,
                entry_price=expected_price,
                exit_price=actual_price,
                expected_price=expected_price,
                actual_price=actual_price,
                maker_fee=fee_amount if is_maker else 0,
                taker_fee=fee_amount if not is_maker else 0,
                slippage=slippage,
                total_cost=total_cost,
                cost_percentage=cost_percentage,
            )

            # 添加到历史记录
            self.transaction_history.append(cost_record)

            # 按日期分组
            today = datetime.now().date()
            self.daily_costs[today].append(cost_record)

            logger.info(
                f"交易成本计算 - 符号: {symbol}, 方向: {side}, 数量: {quantity}, "
                f"费率: {fee_rate:.2%}, 滑点: {slippage:.2%}, 总成本: ${total_cost:.2f}"
            )

            return cost_record

        except Exception as e:
            logger.error(f"交易成本计算失败: {e}")
            return TransactionCost(
                symbol=symbol,
                side=side,
                quantity=quantity,
                entry_price=0,
                exit_price=0,
                expected_price=0,
                actual_price=0,
                total_cost=0,
                cost_percentage=0,
            )

    def analyze_execution_quality(
        self,
        order_id: str,
        symbol: str,
        order_type: str,
        side: str,
        quantity: float,
        requested_price: float,
        executed_trades: List[Dict[str, Any]],
        orderbook_data: Optional[Dict[str, Any]] = None,
    ) -> ExecutionQuality:
        """
        分析订单执行质量

        Args:
            order_id: 订单ID
            symbol: 交易对
            order_type: 订单类型
            side: 交易方向
            quantity: 订单数量
            requested_price: 请求价格
            executed_trades: 成交明细
            orderbook_data: 订单簿数据

        Returns:
            ExecutionQuality: 执行质量分析
        """
        try:
            if not executed_trades:
                return ExecutionQuality(
                    order_id=order_id,
                    symbol=symbol,
                    order_type=order_type,
                    side=side,
                    quantity=quantity,
                    requested_price=requested_price,
                    average_executed_price=requested_price,
                    best_bid=requested_price * 0.999,  # 默认值
                    best_ask=requested_price * 1.001,  # 默认值
                    mid_price=requested_price,  # 默认值
                    execution_time=0.0,  # 默认值
                    fill_rate=0.0,
                    price_improvement=0.0,  # 默认值
                    slippage_bps=0.0,  # 默认值
                    execution_quality_score=0.0,
                )

            # 计算平均成交价格
            total_quantity = sum(trade.get("amount", 0) for trade in executed_trades)
            total_value = sum(
                trade.get("amount", 0) * trade.get("price", 0)
                for trade in executed_trades
            )
            average_executed_price = (
                total_value / total_quantity if total_quantity > 0 else requested_price
            )

            # 计算成交率
            fill_rate = total_quantity / quantity if quantity > 0 else 0

            # 获取订单簿数据
            if orderbook_data:
                best_bid = orderbook_data.get("bids", [[0, 0]])[0][0]
                best_ask = orderbook_data.get("asks", [[0, 0]])[0][0]
                mid_price = (
                    (best_bid + best_ask) / 2
                    if best_bid > 0 and best_ask > 0
                    else requested_price
                )
            else:
                best_bid = requested_price * 0.999
                best_ask = requested_price * 1.001
                mid_price = requested_price

            # 计算价格改善
            if side == "buy":
                price_improvement = (
                    requested_price - average_executed_price
                ) / requested_price
            else:  # sell
                price_improvement = (
                    average_executed_price - requested_price
                ) / requested_price

            # 计算滑点（基点）
            slippage_bps = (average_executed_price - mid_price) / mid_price * 10000
            if side == "buy":
                slippage_bps = max(0, slippage_bps)  # 买入滑点应为正
            else:
                slippage_bps = min(0, slippage_bps)  # 卖出滑点应为负

            # 计算执行时间
            if executed_trades:
                first_trade_time = datetime.fromisoformat(
                    executed_trades[0].get("timestamp", "")
                )
                last_trade_time = datetime.fromisoformat(
                    executed_trades[-1].get("timestamp", "")
                )
                execution_time = (last_trade_time - first_trade_time).total_seconds()
            else:
                execution_time = 0.0

            # 计算执行质量评分
            quality_score = self._calculate_execution_quality_score(
                fill_rate, abs(slippage_bps), execution_time
            )

            # 创建执行质量记录
            quality_record = ExecutionQuality(
                order_id=order_id,
                symbol=symbol,
                order_type=order_type,
                side=side,
                quantity=quantity,
                requested_price=requested_price,
                average_executed_price=average_executed_price,
                best_bid=best_bid,
                best_ask=best_ask,
                mid_price=mid_price,
                execution_time=execution_time,
                fill_rate=fill_rate,
                price_improvement=price_improvement,
                slippage_bps=slippage_bps,
                execution_quality_score=quality_score,
            )

            # 添加到历史记录
            self.execution_history.append(quality_record)

            # 更新执行质量统计
            self._update_quality_stats(quality_record)

            logger.info(
                f"执行质量分析 - 订单: {order_id}, 成交率: {fill_rate:.1%}, "
                f"滑点: {slippage_bps:.1f}bps, 质量评分: {quality_score:.1f}"
            )

            return quality_record

        except Exception as e:
            logger.error(f"执行质量分析失败: {e}")
            return ExecutionQuality(
                order_id=order_id,
                symbol=symbol,
                order_type=order_type,
                side=side,
                quantity=quantity,
                requested_price=requested_price,
                average_executed_price=requested_price,
                best_bid=requested_price * 0.999,  # 默认值
                best_ask=requested_price * 1.001,  # 默认值
                mid_price=requested_price,  # 默认值
                execution_time=0.0,  # 默认值
                fill_rate=0.0,
                price_improvement=0.0,  # 默认值
                slippage_bps=0.0,  # 默认值
                execution_quality_score=0.0,
            )

    def _calculate_execution_quality_score(
        self, fill_rate: float, slippage_bps: float, execution_time: float
    ) -> float:
        """计算执行质量评分"""
        try:
            # 成交率评分 (0-40分)
            if fill_rate >= self.EXECUTION_QUALITY_BENCHMARKS["fill_rate"]["excellent"]:
                fill_score = 40
            elif fill_rate >= self.EXECUTION_QUALITY_BENCHMARKS["fill_rate"]["good"]:
                fill_score = 30
            elif (
                fill_rate
                >= self.EXECUTION_QUALITY_BENCHMARKS["fill_rate"]["acceptable"]
            ):
                fill_score = 20
            else:
                fill_score = max(0, fill_rate * 40)

            # 滑点评分 (0-30分)
            if (
                slippage_bps
                <= self.EXECUTION_QUALITY_BENCHMARKS["slippage_bps"]["excellent"]
            ):
                slippage_score = 30
            elif (
                slippage_bps
                <= self.EXECUTION_QUALITY_BENCHMARKS["slippage_bps"]["good"]
            ):
                slippage_score = 20
            elif (
                slippage_bps
                <= self.EXECUTION_QUALITY_BENCHMARKS["slippage_bps"]["acceptable"]
            ):
                slippage_score = 10
            else:
                slippage_score = max(0, 30 - (slippage_bps - 5) * 2)

            # 执行时间评分 (0-30分)
            if (
                execution_time
                <= self.EXECUTION_QUALITY_BENCHMARKS["execution_time"]["excellent"]
            ):
                time_score = 30
            elif (
                execution_time
                <= self.EXECUTION_QUALITY_BENCHMARKS["execution_time"]["good"]
            ):
                time_score = 20
            elif (
                execution_time
                <= self.EXECUTION_QUALITY_BENCHMARKS["execution_time"]["acceptable"]
            ):
                time_score = 10
            else:
                time_score = max(0, 30 - (execution_time - 1) * 10)

            total_score = fill_score + slippage_score + time_score
            return min(100, max(0, total_score))

        except Exception as e:
            logger.error(f"执行质量评分计算失败: {e}")
            return 50  # 默认中等评分

    def _update_quality_stats(self, quality: ExecutionQuality):
        """更新执行质量统计"""
        try:
            self.quality_stats["total_orders"] += 1

            # 使用加权平均更新统计
            n = self.quality_stats["total_orders"]
            weight = 1 / n

            self.quality_stats["avg_fill_rate"] = (
                self.quality_stats["avg_fill_rate"] * (1 - weight)
                + quality.fill_rate * weight
            )

            self.quality_stats["avg_slippage_bps"] = (
                self.quality_stats["avg_slippage_bps"] * (1 - weight)
                + abs(quality.slippage_bps) * weight
            )

            self.quality_stats["avg_execution_time"] = (
                self.quality_stats["avg_execution_time"] * (1 - weight)
                + quality.execution_time * weight
            )

            self.quality_stats["quality_score"] = (
                self.quality_stats["quality_score"] * (1 - weight)
                + quality.execution_quality_score * weight
            )

        except Exception as e:
            logger.error(f"质量统计更新失败: {e}")

    def calculate_break_even_return(
        self, strategy_return: float, holding_period_days: int = 1
    ) -> float:
        """
        计算盈亏平衡所需回报率

        Args:
            strategy_return: 策略回报率（不含成本）
            holding_period_days: 持仓周期（天）

        Returns:
            盈亏平衡所需回报率
        """
        try:
            # 获取平均交易成本
            avg_cost_pct = self.get_average_cost_percentage()

            # 考虑时间价值的成本（资金占用成本）
            # 假设年化资金成本为5%
            annual_cost_rate = 0.05
            time_cost = annual_cost_rate * holding_period_days / 365

            # 总成本 = 交易成本 + 时间成本
            total_cost = float(avg_cost_pct) + time_cost

            # 盈亏平衡回报 = 总成本
            break_even_return = total_cost

            # 如果策略回报低于盈亏平衡点，需要额外回报
            if strategy_return < break_even_return:
                additional_return_needed = break_even_return - strategy_return
                logger.info(
                    f"策略回报 {strategy_return:.2%} 低于盈亏平衡点 {break_even_return:.2%}，"
                    f"需要额外 {additional_return_needed:.2%} 回报"
                )
                return additional_return_needed
            else:
                logger.info(
                    f"策略回报 {strategy_return:.2%} 已覆盖成本 {break_even_return:.2%}"
                )
                return 0.0

        except Exception as e:
            logger.error(f"盈亏平衡计算失败: {e}")
            return 0.01  # 默认1%

    def get_average_cost_percentage(self, days: int = 30) -> float:
        """获取平均成本百分比"""
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            recent_costs = [
                cost.cost_percentage
                for cost in self.transaction_history
                if cost.timestamp >= cutoff_date
            ]

            if not recent_costs:
                return 0.005  # 默认0.5%

            return float(np.mean(recent_costs))

        except Exception as e:
            logger.error(f"平均成本计算失败: {e}")
            return 0.005

    def get_cost_analysis_report(self, days: int = 30) -> Dict[str, Any]:
        """获取成本分析报告"""
        try:
            cutoff_date = datetime.now() - timedelta(days=days)

            # 筛选最近的交易
            recent_transactions = [
                cost
                for cost in self.transaction_history
                if cost.timestamp >= cutoff_date
            ]

            if not recent_transactions:
                return {
                    "period_days": days,
                    "total_trades": 0,
                    "message": "最近无交易记录",
                }

            # 成本分析
            total_fees = sum(
                cost.maker_fee + cost.taker_fee for cost in recent_transactions
            )
            total_slippage = sum(
                abs(cost.slippage) * cost.actual_price * cost.quantity
                for cost in recent_transactions
            )
            total_cost = sum(cost.total_cost for cost in recent_transactions)

            # 按方向统计
            buy_costs = [cost for cost in recent_transactions if cost.side == "buy"]
            sell_costs = [cost for cost in recent_transactions if cost.side == "sell"]

            # 按订单类型统计
            maker_costs = [cost for cost in recent_transactions if cost.maker_fee > 0]
            taker_costs = [cost for cost in recent_transactions if cost.taker_fee > 0]

            # 执行质量分析
            recent_executions = [
                exec for exec in self.execution_history if exec.timestamp >= cutoff_date
            ]

            report = {
                "period_days": days,
                "total_trades": len(recent_transactions),
                "total_volume": sum(
                    cost.actual_price * cost.quantity for cost in recent_transactions
                ),
                "total_fees": total_fees,
                "total_slippage": total_slippage,
                "total_cost": total_cost,
                "average_cost_percentage": np.mean(
                    [cost.cost_percentage for cost in recent_transactions]
                ),
                "median_cost_percentage": np.median(
                    [cost.cost_percentage for cost in recent_transactions]
                ),
                "cost_breakdown": {
                    "fees_percentage": (total_fees / (total_fees + total_slippage))
                    * 100
                    if total_fees + total_slippage > 0
                    else 0,
                    "slippage_percentage": (
                        total_slippage / (total_fees + total_slippage)
                    )
                    * 100
                    if total_fees + total_slippage > 0
                    else 0,
                },
                "by_side": {
                    "buy": {
                        "count": len(buy_costs),
                        "avg_cost": np.mean(
                            [cost.cost_percentage for cost in buy_costs]
                        )
                        if buy_costs
                        else 0,
                        "total_slippage_bps": np.mean(
                            [cost.slippage * 10000 for cost in buy_costs]
                        )
                        if buy_costs
                        else 0,
                    },
                    "sell": {
                        "count": len(sell_costs),
                        "avg_cost": np.mean(
                            [cost.cost_percentage for cost in sell_costs]
                        )
                        if sell_costs
                        else 0,
                        "total_slippage_bps": np.mean(
                            [cost.slippage * 10000 for cost in sell_costs]
                        )
                        if sell_costs
                        else 0,
                    },
                },
                "by_order_type": {
                    "maker": {
                        "count": len(maker_costs),
                        "avg_fee": np.mean([cost.maker_fee for cost in maker_costs])
                        if maker_costs
                        else 0,
                    },
                    "taker": {
                        "count": len(taker_costs),
                        "avg_fee": np.mean([cost.taker_fee for cost in taker_costs])
                        if taker_costs
                        else 0,
                    },
                },
                "execution_quality": {
                    "avg_fill_rate": self.quality_stats["avg_fill_rate"],
                    "avg_slippage_bps": self.quality_stats["avg_slippage_bps"],
                    "avg_execution_time": self.quality_stats["avg_execution_time"],
                    "quality_score": self.quality_stats["quality_score"],
                }
                if recent_executions
                else {},
                "recommendations": self._generate_cost_recommendations(
                    recent_transactions
                ),
            }

            return report

        except Exception as e:
            logger.error(f"成本分析报告生成失败: {e}")
            return {"period_days": days, "error": str(e), "message": "报告生成失败"}

    def _generate_cost_recommendations(
        self, transactions: List[TransactionCost]
    ) -> List[str]:
        """生成成本优化建议"""
        recommendations = []

        try:
            if not transactions:
                return recommendations

            # 分析成本构成
            avg_cost = np.mean([cost.cost_percentage for cost in transactions])
            avg_slippage = np.mean([abs(cost.slippage) for cost in transactions])

            # 成本过高建议
            if avg_cost > 0.01:  # >1%
                recommendations.append("交易成本过高(>1%)，建议优化执行策略")

            # 滑点过大建议
            if avg_slippage > 0.002:  # >0.2%
                recommendations.append("滑点较大，建议使用限价单而非市价单")

            # 手续费分析
            taker_ratio = sum(1 for cost in transactions if cost.taker_fee > 0) / len(
                transactions
            )
            if taker_ratio > 0.8:  # 80%以上都是taker
                recommendations.append(
                    "大部分订单为Taker，建议增加Maker订单比例以降低手续费"
                )

            # 执行时间分析
            recent_executions = [
                exec
                for exec in self.execution_history
                if exec.timestamp.date() == datetime.now().date()
            ]
            if recent_executions:
                slow_executions = sum(
                    1 for exec in recent_executions if exec.execution_time > 1.0
                )
                if slow_executions / len(recent_executions) > 0.3:  # 30%以上执行慢
                    recommendations.append("订单执行速度较慢，建议优化交易时段选择")

            return recommendations

        except Exception as e:
            logger.error(f"成本建议生成失败: {e}")
            return []

    def get_slippage_forecast(
        self,
        symbol: str,
        side: str,
        quantity: float,
        current_volatility: float,
        order_type: str = "market",
    ) -> float:
        """
        预测滑点

        Args:
            symbol: 交易对
            side: 交易方向
            quantity: 交易数量
            current_volatility: 当前波动率
            order_type: 订单类型

        Returns:
            预测的滑点百分比
        """
        try:
            # 基于历史滑点数据预测
            historical_slippage = list(self.slippage_stats.get(side, []))
            if historical_slippage:
                base_slippage = (
                    np.percentile(historical_slippage, 75) / 10000
                )  # 75分位数
            else:
                base_slippage = 0.001  # 默认0.1%

            # 波动率调整
            volatility_multiplier = 1 + (current_volatility - 0.02) * 10  # 基准波动率2%

            # 数量调整（大单滑点更大）
            size_multiplier = 1 + min(quantity / 100, 0.5)  # 每100张增加50%滑点

            # 订单类型调整
            if order_type == "limit":
                type_multiplier = 0.5  # 限价单滑点更小
            else:
                type_multiplier = 1.0

            predicted_slippage = (
                base_slippage
                * volatility_multiplier
                * size_multiplier
                * type_multiplier
            )

            return float(min(predicted_slippage, 0.01))  # 最大不超过1%

        except Exception as e:
            logger.error(f"滑点预测失败: {e}")
            return 0.001  # 默认0.1%

    def reset_statistics(self):
        """重置统计数据"""
        self.transaction_history.clear()
        self.execution_history.clear()
        self.daily_costs.clear()
        self.weekly_costs.clear()
        self.monthly_costs.clear()

        for key in self.slippage_stats:
            self.slippage_stats[key].clear()

        self.quality_stats = {
            "avg_fill_rate": 0.0,
            "avg_slippage_bps": 0.0,
            "avg_execution_time": 0.0,
            "total_orders": 0,
            "quality_score": 0.0,
        }

        logger.info("交易成本统计已重置")
