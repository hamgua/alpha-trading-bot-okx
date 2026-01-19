"""
风险管理器 - 多维度风险评估和控制
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from ...core.base import BaseComponent, BaseConfig
from ..models import RiskAssessmentResult
from .dynamic_position_sizing import DynamicPositionSizing

logger = logging.getLogger(__name__)


class RiskManagerConfig(BaseConfig):
    """风险管理器配置"""

    max_daily_loss: float = 100.0
    max_position_risk: float = 0.05
    max_consecutive_losses: int = 3
    emergency_stop_loss: float = 0.025
    enable_ai_risk_assessment: bool = True
    enable_market_risk_monitoring: bool = True


class RiskManager(BaseComponent):
    """风险管理器 - 多维度风险评估"""

    def __init__(
        self, config: Optional[RiskManagerConfig] = None, exchange_client=None
    ):
        # 如果没有提供配置，创建默认配置
        if config is None:
            config = RiskManagerConfig(name="RiskManager")
        super().__init__(config)
        self.exchange_client = exchange_client  # 交易所客户端
        self.daily_loss = 0.0
        self.consecutive_losses = 0
        self.last_loss_time = None
        self.market_risk_score = 0.0
        self.position_risk_score = 0.0
        self.trade_history: list = []
        self._current_balance = None  # 存储当前余额信息

        # 初始化动态仓位管理器
        self.position_sizer = DynamicPositionSizing()

    async def initialize(self) -> bool:
        """初始化风险管理器"""
        logger.info("正在初始化风险管理器...")

        # 加载今日交易历史（用于计算当日盈亏）
        await self._load_daily_trades()

        self._initialized = True
        return True

    async def cleanup(self) -> None:
        """清理资源"""
        pass

    async def assess_risk(
        self,
        signals: list,
        current_price: float = 0,
        balance: Any = None,
        market_data: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """评估交易风险（兼容策略管理器调用的接口）"""
        # 存储余额信息供后续使用
        self._current_balance = balance
        logger.info(
            f"[风险管理器] 收到余额信息 - total: {balance.total if balance else 'None'}, free: {balance.free if balance else 'None'}"
        )
        try:
            # 如果没有信号，返回默认允许交易
            if not signals:
                return {"can_trade": True, "reason": "无交易信号", "risk_score": 0.0}

            # 简化实现：基于信号数量和质量评估风险
            risk_score = 0.0
            reasons = []

            # 获取当前价格（如果没有提供）
            if current_price == 0:
                from ...config import load_config

                config = load_config()
                # 这里应该获取实时价格，简化实现使用默认值
                current_price = 85000  # 默认价格

            # 1. 信号数量风险
            if len(signals) > 3:
                risk_score += 0.1
                reasons.append("信号过多，可能过度交易")

            # 2. 信号一致性风险
            # 支持大小写不敏感的信号类型检查
            buy_signals = sum(
                1 for s in signals if str(s.get("signal", "")).upper() == "BUY"
            )
            sell_signals = sum(
                1 for s in signals if str(s.get("signal", "")).upper() == "SELL"
            )
            hold_signals = sum(
                1 for s in signals if str(s.get("signal", "")).upper() == "HOLD"
            )

            # 也检查'type'字段，因为信号可能使用'type'而不是'signal'
            if buy_signals == 0 and sell_signals == 0 and hold_signals == 0:
                buy_signals = sum(
                    1 for s in signals if str(s.get("type", "")).upper() == "BUY"
                )
                sell_signals = sum(
                    1 for s in signals if str(s.get("type", "")).upper() == "SELL"
                )
                hold_signals = sum(
                    1 for s in signals if str(s.get("type", "")).upper() == "HOLD"
                )

            total_signals = len(signals)

            # 添加调试日志 - 查看信号实际内容
            logger.debug(f"[风险评估调试] 信号详情: {signals}")
            logger.debug(
                f"[风险评估调试] 信号统计 - BUY: {buy_signals}, SELL: {sell_signals}, HOLD: {hold_signals}, 总计: {total_signals}"
            )

            if total_signals > 0:
                max_consensus = (
                    max(buy_signals, sell_signals, hold_signals) / total_signals
                )
                logger.debug(f"[风险评估调试] 最大一致性比例: {max_consensus}")

                # 调整阈值：对于100%一致的信号，不应视为"一致性不足"
                if max_consensus < 0.6:
                    risk_score += 0.2
                    reasons.append("信号一致性不足")
                    logger.debug(f"[风险评估调试] 触发信号一致性不足，风险分数增加0.2")
                elif max_consensus == 1.0 and hold_signals == total_signals:
                    # 全HOLD信号是正常的市场观望状态，不应惩罚
                    risk_score += 0.0  # 不增加风险分数
                    logger.debug(f"[风险评估调试] 全HOLD信号，不增加风险分数")

            # 新增：价格位置风险评估
            if market_data is not None:
                composite_position = self._get_composite_price_position(
                    signals, market_data
                )
            else:
                composite_position = None

            if composite_position is not None:
                # 获取价格位置级别
                from ...ai.price_position_scaler import PricePositionScaler

                scaler = PricePositionScaler()
                level = scaler.get_price_position_level(composite_position)

                # 根据价格位置调整风险评分
                if level in ["extreme_high", "high"]:
                    # 高位买入风险显著增加
                    risk_score += 0.3
                    reasons.append(f"价格位置风险：{level}({composite_position:.1f}%)")
                    logger.info(
                        f"🚨 价格位置风险：{composite_position:.1f}%处于{level}，风险分数+0.3"
                    )
                elif level == "moderate_high":
                    # 偏高位置适度增加风险
                    risk_score += 0.15
                    reasons.append(f"价格位置风险：偏高({composite_position:.1f}%)")
                    logger.info(
                        f"⚠️ 价格位置风险：{composite_position:.1f}%偏高，风险分数+0.15"
                    )
                elif level in ["extreme_low", "low"]:
                    # 低位买入风险适度降低
                    risk_score -= 0.1
                    reasons.append(f"价格位置优势：{level}({composite_position:.1f}%)")
                    logger.info(
                        f"📈 价格位置优势：{composite_position:.1f}%处于{level}，风险分数-0.1"
                    )

                # 记录详细分析
                recommendation = scaler.get_position_recommendation(composite_position)
                logger.info(f"📍 价格位置建议: {recommendation}")

            # 3. 当日亏损检查
            if self.daily_loss >= self.config.max_daily_loss:
                return {
                    "can_trade": False,
                    "reason": f"当日亏损已达上限: {self.daily_loss:.2f} USDT",
                    "risk_score": 1.0,
                }

            # 4. 连续亏损检查
            if self.consecutive_losses >= self.config.max_consecutive_losses:
                return {
                    "can_trade": False,
                    "reason": f"连续亏损次数过多: {self.consecutive_losses}",
                    "risk_score": 1.0,
                }

            # 综合评估
            can_trade = risk_score <= 0.5
            reason = "; ".join(reasons) if reasons else "风险评估通过"

            # 计算风险等级
            if risk_score <= 0.2:
                risk_level = "low"
            elif risk_score <= 0.4:
                risk_level = "moderate"
            elif risk_score <= 0.7:
                risk_level = "high"
            else:
                risk_level = "critical"

            # 将信号转换为交易请求
            trades = []
            if can_trade:
                for signal in signals:
                    # 获取信号类型
                    signal_type = signal.get(
                        "signal", signal.get("type", "HOLD")
                    ).upper()
                    if signal_type in ["BUY", "SELL"]:
                        # 验证交易数量，确保满足最小交易量要求
                        symbol = signal.get("symbol", "BTC/USDT:USDT")

                        # 如果有余额信息，根据余额和杠杆计算最优交易数量
                        if self._current_balance and signal_type == "BUY":  # 只允许做多
                            logger.info(
                                f"[风险管理器] 检测到买入信号和余额信息，开始动态计算交易数量"
                            )
                            try:
                                # 获取合约大小
                                contract_size = 0.01  # BTC/USDT:USDT默认合约大小
                                if symbol in ["BTC/USDT:USDT", "BTC-USDT-SWAP"]:
                                    contract_size = 0.01

                                # 从配置获取杠杆倍数
                                from ...config import load_config

                                config = load_config()
                                leverage = config.trading.leverage

                                # 使用全部可用余额（保留少量缓冲）
                                available_balance = self._current_balance.free
                                # 保留5%的余额作为缓冲，防止价格波动导致爆仓
                                usable_balance = available_balance * 0.95

                                # 提前计算最小交易所需的保证金
                                min_contracts = 0.01  # OKX最小0.01张（不是1张）
                                min_required_margin = (
                                    min_contracts * contract_size * current_price
                                ) / leverage

                                # 检查余额是否足够最小交易
                                if usable_balance < min_required_margin:
                                    logger.warning(f"可用余额不足最小交易要求")
                                    logger.warning(
                                        f"  当前可用余额: {usable_balance:.4f} USDT"
                                    )
                                    logger.warning(
                                        f"  最小交易需要: {min_required_margin:.4f} USDT"
                                    )
                                    logger.warning(
                                        f"  缺少: {min_required_margin - usable_balance:.4f} USDT"
                                    )
                                    logger.warning(
                                        f"  建议: 增加账户余额或减少杠杆倍数"
                                    )

                                # 使用动态仓位管理器计算最优仓位
                                try:
                                    # 获取市场数据和技术指标
                                    from ...utils.technical import TechnicalIndicators

                                    tech_indicators = TechnicalIndicators()

                                    # 获取ATR数据 - 使用正确的异步方法名
                                    recent_data = (
                                        await self.exchange_client.fetch_ohlcv(
                                            symbol, "15m", limit=20
                                        )
                                    )
                                    if recent_data and len(recent_data) >= 14:
                                        high_low_data = [
                                            (d[2], d[3]) for d in recent_data
                                        ]
                                        atr_14 = tech_indicators.calculate_atr(
                                            high_low_data, period=14
                                        )

                                        # 计算信号强度和置信度
                                        signal_strength = signal.get(
                                            "confidence", 0.5
                                        )  # 从信号中获取
                                        confidence = signal.get("confidence", 0.5)

                                        # 确定风险等级
                                        risk_level = self._determine_risk_level(signal)

                                        # 确定市场波动率
                                        market_volatility = (
                                            self._determine_market_volatility(
                                                recent_data
                                            )
                                        )

                                        # 使用动态仓位管理器计算仓位
                                        position_result = (
                                            self.position_sizer.calculate_position_size(
                                                account_balance=available_balance,
                                                current_price=current_price,
                                                atr_14=atr_14,
                                                signal_strength=signal_strength,
                                                confidence=confidence,
                                                market_volatility=market_volatility,
                                                risk_level=risk_level,
                                                symbol=symbol.replace("/USDT", ""),
                                                max_risk_per_trade=0.02,
                                            )
                                        )

                                        # 获取建议的合约数量
                                        amount = position_result["contracts"]
                                        logger.info(
                                            f"动态仓位管理器计算结果: {position_result}"
                                        )

                                    else:
                                        # 数据不足，使用基础计算
                                        raise ValueError("市场数据不足")

                                except Exception as e:
                                    logger.error(
                                        f"动态仓位计算失败: {e}，回退到基础计算"
                                    )

                                    # 回退到基础仓位计算
                                    # 计算可交易的最大张数
                                    max_contracts = (usable_balance * leverage) / (
                                        contract_size * current_price
                                    )

                                    if max_contracts < min_contracts:
                                        logger.warning(
                                            f"计算的交易数量小于最小交易量要求，使用最小值: {min_contracts}"
                                        )
                                        amount = min_contracts
                                    else:
                                        amount = round(max_contracts, 4)

                                    # 计算实际使用的保证金
                                    actual_margin = (
                                        amount * contract_size * current_price
                                    ) / leverage
                                    logger.info(
                                        f"基础仓位计算 - 可用余额: {available_balance:.4f} USDT, "
                                        f"杠杆: {leverage}x, 合约数量: {amount}, 保证金: {actual_margin:.4f} USDT"
                                    )

                            except Exception as e:
                                logger.error(
                                    f"根据余额计算交易数量失败: {e}，使用默认数量1张"
                                )
                                amount = 1.0

                            # 添加辅助方法
                            def _determine_risk_level(
                                self, signal: Dict[str, Any]
                            ) -> str:
                                """根据信号确定风险等级"""
                                confidence = signal.get("confidence", 0.5)

                                if confidence > 0.8:
                                    return "low"
                                elif confidence > 0.6:
                                    return "medium"
                                elif confidence > 0.4:
                                    return "high"
                                else:
                                    return "very_high"

                            def _determine_market_volatility(
                                self, ohlcv_data: list
                            ) -> str:
                                """根据历史数据确定市场波动率"""
                                if len(ohlcv_data) < 5:
                                    return "normal"

                                # 计算价格变化
                                price_changes = []
                                for i in range(1, len(ohlcv_data)):
                                    change = abs(
                                        (ohlcv_data[i][4] - ohlcv_data[i - 1][4])
                                        / ohlcv_data[i - 1][4]
                                    )
                                    price_changes.append(change)

                                avg_change = sum(price_changes) / len(price_changes)

                                # 根据平均变化判断波动率
                                if avg_change < 0.001:  # 0.1%
                                    return "very_low"
                                elif avg_change < 0.002:  # 0.2%
                                    return "low"
                                elif avg_change < 0.005:  # 0.5%
                                    return "normal"
                                elif avg_change < 0.01:  # 1%
                                    return "high"
                                else:
                                    return "very_high"
                        else:
                            # 没有余额信息或不是买入信号，使用默认数量
                            amount = signal.get("size", 1.0)  # 默认交易量1张

                            # 验证最小交易量要求
                            if symbol in ["BTC/USDT:USDT", "BTC-USDT-SWAP"]:
                                min_contracts = 0.01  # OKX最小0.01张
                                if amount < min_contracts:
                                    logger.warning(
                                        f"交易数量 {amount} 张小于最小要求 {min_contracts} 张，调整为 {min_contracts} 张"
                                    )
                                    amount = min_contracts

                        trade_request = {
                            "symbol": signal.get("symbol", "BTC/USDT:USDT"),
                            "side": "buy" if signal_type == "BUY" else "sell",
                            "amount": amount,
                            "type": "market",
                            "price": signal.get("price")
                            or current_price,  # 使用当前价格如果信号中没有价格
                            "current_price": current_price,
                            "reason": signal.get("reason", "AI信号"),
                            "confidence": signal.get("confidence", 0.5),
                            "signal_source": signal.get("source", "unknown"),
                        }
                        trades.append(trade_request)

            return {
                "can_trade": can_trade,
                "reason": reason,
                "risk_score": risk_score,
                "risk_level": risk_level,
                "daily_loss": self.daily_loss,
                "consecutive_losses": self.consecutive_losses,
                "trades": trades,  # 添加交易列表
            }

        except Exception as e:
            logger.error(f"风险评估失败: {e}")
            return {
                "can_trade": False,
                "reason": f"风险评估异常: {str(e)}",
                "risk_score": 1.0,
                "risk_level": "critical",
            }

    async def assess_trade_risk(
        self, trade_request: Dict[str, Any]
    ) -> RiskAssessmentResult:
        """评估交易风险"""
        try:
            symbol = trade_request["symbol"]
            amount = trade_request["amount"]
            side = trade_request["side"]
            current_price = trade_request.get("current_price", 0)

            risk_score = 0.0
            risk_reasons = []

            # 1. 检查当日亏损限制
            if self.daily_loss >= self.config.max_daily_loss:
                return RiskAssessmentResult(
                    can_execute=False,
                    reason=f"当日亏损已达上限: {self.daily_loss:.2f} USDT",
                )

            # 2. 检查连续亏损次数
            if self.consecutive_losses >= self.config.max_consecutive_losses:
                return RiskAssessmentResult(
                    can_execute=False,
                    reason=f"连续亏损次数过多: {self.consecutive_losses}",
                )

            # 3. 检查仓位风险
            position_risk = await self._assess_position_risk(
                symbol, amount, current_price
            )
            if position_risk > self.config.max_position_risk:
                risk_score += 0.3
                risk_reasons.append(f"仓位风险过高: {position_risk:.2%}")

            # 4. 检查市场风险
            if self.config.enable_market_risk_monitoring:
                market_risk = await self._assess_market_risk(symbol)
                if market_risk > 0.7:
                    risk_score += 0.2
                    risk_reasons.append(f"市场风险较高: {market_risk:.2f}")

            # 5. AI风险评估
            ai_confidence = 0.5
            if self.config.enable_ai_risk_assessment:
                ai_confidence = await self._assess_ai_risk(trade_request)
                if ai_confidence < 0.3:
                    risk_score += 0.2
                    risk_reasons.append(f"AI信心不足: {ai_confidence:.2f}")

            # 综合评估
            if risk_score > 0.5:
                return RiskAssessmentResult(
                    can_execute=False,
                    reason="; ".join(risk_reasons) if risk_reasons else "风险评分过高",
                    risk_score=risk_score,
                    daily_loss=self.daily_loss,
                    position_risk=position_risk,
                    market_risk=self.market_risk_score,
                    ai_confidence=ai_confidence,
                )

            # 通过风险评估
            return RiskAssessmentResult(
                can_execute=True,
                reason="风险评估通过",
                risk_score=risk_score,
                daily_loss=self.daily_loss,
                position_risk=position_risk,
                market_risk=self.market_risk_score,
                ai_confidence=ai_confidence,
            )

        except Exception as e:
            logger.error(f"风险评估异常: {e}")
            return RiskAssessmentResult(
                can_execute=False, reason=f"风险评估异常: {str(e)}"
            )

    async def _assess_position_risk(
        self, symbol: str, amount: float, current_price: float
    ) -> float:
        """评估仓位风险"""
        try:
            # 这里应该获取当前仓位信息
            # 简化实现：基于交易金额和账户余额计算风险
            from ...config import load_config

            config = load_config()

            max_position_size = config.trading.max_position_size
            position_risk = min(amount / max_position_size, 1.0)

            return position_risk

        except Exception as e:
            logger.error(f"评估仓位风险失败: {e}")
            return 0.0

    async def _assess_market_risk(self, symbol: str) -> float:
        """评估市场风险"""
        try:
            # 简化实现：基于波动率和交易量评估
            # 实际应该获取市场数据并计算
            self.market_risk_score = 0.3  # 默认低风险
            return self.market_risk_score

        except Exception as e:
            logger.error(f"评估市场风险失败: {e}")
            return 0.0

    async def _assess_ai_risk(self, trade_request: Dict[str, Any]) -> float:
        """AI风险评估"""
        try:
            # 这里应该调用AI模块进行风险评估
            # 简化实现：返回默认置信度
            return 0.7

        except Exception as e:
            logger.error(f"AI风险评估失败: {e}")
            return 0.5

    async def update_trade_result(self, trade_result: Dict[str, Any]) -> None:
        """更新交易结果（用于风险统计）"""
        try:
            pnl = trade_result.get("pnl", 0)
            timestamp = trade_result.get("timestamp", datetime.now())

            # 更新当日盈亏
            if self._is_today(timestamp):
                self.daily_loss += pnl

            # 更新连续亏损次数
            if pnl < 0:
                self.consecutive_losses += 1
                self.last_loss_time = timestamp
            elif pnl > 0:
                self.consecutive_losses = 0

            # 添加到交易历史
            self.trade_history.append(trade_result)

            # 限制历史记录长度
            if len(self.trade_history) > 1000:
                self.trade_history = self.trade_history[-500:]

        except Exception as e:
            logger.error(f"更新交易结果失败: {e}")

    def _is_today(self, timestamp: datetime) -> bool:
        """检查是否为今日"""
        today = datetime.now().date()
        return timestamp.date() == today

    async def _load_daily_trades(self) -> None:
        """加载当日交易"""
        # 这里应该从数据库或文件加载当日交易
        # 简化实现：重置当日数据
        self.daily_loss = 0.0

    def get_daily_loss(self) -> float:
        """获取当日亏损"""
        return self.daily_loss

    def get_consecutive_losses(self) -> int:
        """获取连续亏损次数"""
        return self.consecutive_losses

    def get_risk_metrics(self) -> Dict[str, Any]:
        """获取风险指标"""
        return {
            "daily_loss": self.daily_loss,
            "consecutive_losses": self.consecutive_losses,
            "market_risk_score": self.market_risk_score,
            "position_risk_score": self.position_risk_score,
            "total_trades": len(self.trade_history),
            "profitable_trades": len(
                [t for t in self.trade_history if t.get("pnl", 0) > 0]
            ),
            "loss_trades": len([t for t in self.trade_history if t.get("pnl", 0) < 0]),
        }

    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        base_status = super().get_status()
        base_status.update(
            {
                "daily_loss": self.daily_loss,
                "consecutive_losses": self.consecutive_losses,
                "market_risk_score": self.market_risk_score,
                "position_risk_score": self.position_risk_score,
                "risk_metrics": self.get_risk_metrics(),
            }
        )
        return base_status

    async def emergency_stop(self) -> None:
        """紧急停止"""
        logger.warning("触发紧急停止！")
        # 这里应该实现紧急停止逻辑，如平仓所有仓位、取消所有订单等
        self.config.enable_ai_risk_assessment = False
        self.config.enable_market_risk_monitoring = False

    def reset_daily_stats(self) -> None:
        """重置当日统计"""
        self.daily_loss = 0.0
        self.consecutive_losses = 0
        logger.info("当日风险统计已重置")

    def _get_composite_price_position(
        self, signals: List[Dict[str, Any]], market_data: Dict[str, Any]
    ) -> Optional[float]:
        """获取综合价格位置

        Args:
            signals: AI信号列表
            market_data: 市场数据

        Returns:
            综合价格位置百分比，如果没有数据则返回None
        """
        try:
            # 优先从market_data中获取综合价格位置
            composite_position = market_data.get("composite_price_position")
            if composite_position is not None:
                return float(composite_position)

            # 回退方案：从信号中提取价格位置信息
            for signal in signals:
                if "price_position_analysis" in signal:
                    analysis = signal["price_position_analysis"]
                    if "price_position" in analysis:
                        return float(analysis["price_position"])

            # 最后回退：计算当日价格位置
            price = float(market_data.get("price", 0))
            daily_high = float(market_data.get("high", price))
            daily_low = float(market_data.get("low", price))

            if daily_high > daily_low and price > 0:
                return ((price - daily_low) / (daily_high - daily_low)) * 100

            return None
        except Exception as e:
            logger.warning(f"获取综合价格位置失败: {e}")
            return None
