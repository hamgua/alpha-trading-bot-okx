"""
风险管理器 - 多维度风险评估和控制
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from ...core.base import BaseComponent, BaseConfig
from ..models import RiskAssessmentResult

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

    def __init__(self, config: Optional[RiskManagerConfig] = None):
        # 如果没有提供配置，创建默认配置
        if config is None:
            config = RiskManagerConfig(name="RiskManager")
        super().__init__(config)
        self.daily_loss = 0.0
        self.consecutive_losses = 0
        self.last_loss_time = None
        self.market_risk_score = 0.0
        self.position_risk_score = 0.0
        self.trade_history: list = []

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

    async def assess_risk(self, signals: list) -> Dict[str, Any]:
        """评估交易风险（兼容策略管理器调用的接口）"""
        try:
            # 如果没有信号，返回默认允许交易
            if not signals:
                return {
                    'can_trade': True,
                    'reason': '无交易信号',
                    'risk_score': 0.0
                }

            # 简化实现：基于信号数量和质量评估风险
            risk_score = 0.0
            reasons = []

            # 1. 信号数量风险
            if len(signals) > 3:
                risk_score += 0.1
                reasons.append("信号过多，可能过度交易")

            # 2. 信号一致性风险
            buy_signals = sum(1 for s in signals if s.get('signal') == 'BUY')
            sell_signals = sum(1 for s in signals if s.get('signal') == 'SELL')
            hold_signals = sum(1 for s in signals if s.get('signal') == 'HOLD')

            total_signals = len(signals)
            if total_signals > 0:
                max_consensus = max(buy_signals, sell_signals, hold_signals) / total_signals
                if max_consensus < 0.6:
                    risk_score += 0.2
                    reasons.append("信号一致性不足")

            # 3. 当日亏损检查
            if self.daily_loss >= self.config.max_daily_loss:
                return {
                    'can_trade': False,
                    'reason': f"当日亏损已达上限: {self.daily_loss:.2f} USDT",
                    'risk_score': 1.0
                }

            # 4. 连续亏损检查
            if self.consecutive_losses >= self.config.max_consecutive_losses:
                return {
                    'can_trade': False,
                    'reason': f"连续亏损次数过多: {self.consecutive_losses}",
                    'risk_score': 1.0
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

            return {
                'can_trade': can_trade,
                'reason': reason,
                'risk_score': risk_score,
                'risk_level': risk_level,
                'daily_loss': self.daily_loss,
                'consecutive_losses': self.consecutive_losses
            }

        except Exception as e:
            logger.error(f"风险评估失败: {e}")
            return {
                'can_trade': False,
                'reason': f"风险评估异常: {str(e)}",
                'risk_score': 1.0,
                'risk_level': 'critical'
            }

    async def assess_trade_risk(self, trade_request: Dict[str, Any]) -> RiskAssessmentResult:
        """评估交易风险"""
        try:
            symbol = trade_request['symbol']
            amount = trade_request['amount']
            side = trade_request['side']
            current_price = trade_request.get('current_price', 0)

            risk_score = 0.0
            risk_reasons = []

            # 1. 检查当日亏损限制
            if self.daily_loss >= self.config.max_daily_loss:
                return RiskAssessmentResult(
                    can_execute=False,
                    reason=f"当日亏损已达上限: {self.daily_loss:.2f} USDT"
                )

            # 2. 检查连续亏损次数
            if self.consecutive_losses >= self.config.max_consecutive_losses:
                return RiskAssessmentResult(
                    can_execute=False,
                    reason=f"连续亏损次数过多: {self.consecutive_losses}"
                )

            # 3. 检查仓位风险
            position_risk = await self._assess_position_risk(symbol, amount, current_price)
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
                    ai_confidence=ai_confidence
                )

            # 通过风险评估
            return RiskAssessmentResult(
                can_execute=True,
                reason="风险评估通过",
                risk_score=risk_score,
                daily_loss=self.daily_loss,
                position_risk=position_risk,
                market_risk=self.market_risk_score,
                ai_confidence=ai_confidence
            )

        except Exception as e:
            logger.error(f"风险评估异常: {e}")
            return RiskAssessmentResult(
                can_execute=False,
                reason=f"风险评估异常: {str(e)}"
            )

    async def _assess_position_risk(self, symbol: str, amount: float, current_price: float) -> float:
        """评估仓位风险"""
        try:
            # 这里应该获取当前仓位信息
            # 简化实现：基于交易金额和账户余额计算风险
            from ..config import load_config
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
            pnl = trade_result.get('pnl', 0)
            timestamp = trade_result.get('timestamp', datetime.now())

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
            'daily_loss': self.daily_loss,
            'consecutive_losses': self.consecutive_losses,
            'market_risk_score': self.market_risk_score,
            'position_risk_score': self.position_risk_score,
            'total_trades': len(self.trade_history),
            'profitable_trades': len([t for t in self.trade_history if t.get('pnl', 0) > 0]),
            'loss_trades': len([t for t in self.trade_history if t.get('pnl', 0) < 0])
        }

    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        base_status = super().get_status()
        base_status.update({
            'daily_loss': self.daily_loss,
            'consecutive_losses': self.consecutive_losses,
            'market_risk_score': self.market_risk_score,
            'position_risk_score': self.position_risk_score,
            'risk_metrics': self.get_risk_metrics()
        })
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