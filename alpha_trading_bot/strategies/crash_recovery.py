#!/usr/bin/env python3
"""
暴跌后恢复策略
在暴跌后寻找合适的重新入场时机，采用分批建仓策略降低风险
"""

import logging
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import numpy as np

logger = logging.getLogger(__name__)


class RecoveryPhase(Enum):
    """恢复阶段"""
    WAITING = "waiting"           # 等待暴跌结束
    OBSERVING = "observing"       # 观察期，确认底部
    STAGE1 = "stage1"            # 第一批建仓
    STAGE2 = "stage2"            # 第二批建仓
    STAGE3 = "stage3"            # 第三批建仓
    RECOVERED = "recovered"      # 恢复完成


@dataclass
class RecoveryConfig:
    """恢复策略配置"""
    # 暴跌检测参数
    crash_drop_threshold: float = 0.03      # 3%跌幅阈值
    consecutive_periods: int = 4             # 连续下跌周期数
    min_rsi_oversold: float = 30.0           # RSI超卖阈值
    volume_spike_threshold: float = 2.0      # 成交量激增阈值

    # 重新入场条件
    min_stabilization_periods: int = 3       # 最小稳定期数
    max_volatility_after_crash: float = 0.02 # 暴跌后最大波动率
    min_volume_recovery: float = 0.8         # 成交量恢复比例
    trend_strength_recovery: float = 0.2     # 趋势强度恢复阈值

    # 分批建仓参数
    stage_interval_periods: int = 3          # 分批间隔周期数
    stage1_allocation: float = 0.3           # 第一批仓位占比
    stage2_allocation: float = 0.4           # 第二批仓位占比
    stage3_allocation: float = 0.3           # 第三批仓位占比

    # 风险控制
    max_recovery_position: float = 0.5       # 最大恢复仓位
    stage_stop_loss: float = 0.015           # 分批止损（1.5%）
    overall_stop_loss: float = 0.025         # 整体止损（2.5%）
    max_recovery_time: int = 7200            # 最大恢复时间（2小时）

    # 退出条件
    profit_target: float = 0.05              # 止盈目标（5%）
    rsi_overbought_exit: float = 70.0        # RSI超买退出


class CrashRecoveryStrategy:
    """暴跌后恢复策略"""

    def __init__(self, config: Optional[RecoveryConfig] = None):
        self.config = config or RecoveryConfig()
        self.current_phase = RecoveryPhase.WAITING
        self.crash_detected_time = None
        self.entry_prices = []           # 各批次入场价格
        self.entry_volumes = []          # 各批次入场数量
        self.current_stage = 0           # 当前批次
        self.last_stage_time = None      # 上一批次时间
        self.total_position = 0          # 总仓位
        self.max_drawdown = 0            # 最大回撤

        # 状态跟踪
        self.is_active = False
        self.recovery_start_time = None
        self.crash_low_price = None      # 暴跌最低点价格
        self.stabilization_start_time = None

    def detect_crash(self, market_data: Dict) -> bool:
        """检测是否发生暴跌"""
        try:
            technical_data = market_data.get('technical_data', {})

            # 1. 价格跌幅检测
            price_change = market_data.get('price_change_pct', 0)
            if price_change < -self.config.crash_drop_threshold * 100:
                logger.warning(f"暴跌检测：价格跌幅{price_change:.2f}%超过阈值")
                return True

            # 2. 连续下跌检测
            close_prices = market_data.get('close_prices', [])
            if len(close_prices) >= self.config.consecutive_periods:
                recent_prices = close_prices[-self.config.consecutive_periods:]
                consecutive_down = 0
                for i in range(1, len(recent_prices)):
                    if recent_prices[i] < recent_prices[i-1]:
                        consecutive_down += 1
                    else:
                        break

                if consecutive_down >= self.config.consecutive_periods:
                    total_drop = (recent_prices[-1] - recent_prices[0]) / recent_prices[0]
                    if abs(total_drop) > 0.02:  # 总跌幅超过2%
                        logger.warning(f"暴跌检测：连续{consecutive_down}周期下跌，总跌幅{total_drop*100:.2f}%")
                        return True

            # 3. RSI超卖检测
            rsi = technical_data.get('rsi', 50)
            if rsi < self.config.min_rsi_oversold:
                logger.warning(f"暴跌检测：RSI{rsi:.1f}处于超卖状态")
                return True

            # 4. 成交量激增检测（恐慌性抛售）
            volume = market_data.get('volume', 0)
            avg_volume = market_data.get('avg_volume', volume)
            if avg_volume > 0 and volume > avg_volume * self.config.volume_spike_threshold:
                logger.warning(f"暴跌检测：成交量激增{volume/avg_volume:.1f}倍，可能存在恐慌性抛售")
                return True

            return False

        except Exception as e:
            logger.error(f"暴跌检测失败：{e}")
            return False

    def check_entry_conditions(self, market_data: Dict) -> Tuple[bool, str]:
        """检查重新入场条件"""
        try:
            technical_data = market_data.get('technical_data', {})
            current_price = market_data.get('price', 0)

            # 1. 稳定期检测
            if self.stabilization_start_time:
                stabilization_duration = time.time() - self.stabilization_start_time
                min_stabilization_time = self.config.min_stabilization_periods * 900  # 15分钟周期
                if stabilization_duration < min_stabilization_time:
                    return False, f"稳定期不足，需要{self.config.min_stabilization_periods}个周期"

            # 2. 价格波动率检测
            atr_pct = technical_data.get('atr_pct', 0)
            if atr_pct > self.config.max_volatility_after_crash * 100:
                return False, f"波动率过高{atr_pct:.2f}%，市场仍不稳定"

            # 3. 成交量检测
            volume = market_data.get('volume', 0)
            avg_volume = market_data.get('avg_volume', volume)
            if avg_volume > 0 and volume < avg_volume * self.config.min_volume_recovery:
                return False, f"成交量恢复不足{volume/avg_volume:.1f}倍"

            # 4. 趋势强度检测
            trend_strength = technical_data.get('trend_strength', 0)
            if trend_strength < self.config.trend_strength_recovery:
                return False, f"趋势强度恢复不足{trend_strength:.2f}"

            # 5. 价格位置检测（不能离最低点太远）
            if self.crash_low_price and current_price > self.crash_low_price * 1.02:
                return False, "价格已上涨过多，错过最佳入场时机"

            # 6. RSI检测（脱离超卖但不能过高）
            rsi = technical_data.get('rsi', 50)
            if rsi < 35 or rsi > 55:
                return False, f"RSI{rsi:.1f}不适合作入场"

            # 7. 技术指标反转检测
            macd_hist = technical_data.get('macd_histogram', 0)
            if macd_hist < 0:
                return False, "MACD仍为负值，下跌趋势未反转"

            return True, "满足所有入场条件"

        except Exception as e:
            logger.error(f"入场条件检查失败：{e}")
            return False, f"检查失败：{e}"

    def calculate_position_size(self, available_balance: float, current_price: float) -> List[float]:
        """计算各批次的仓位大小"""
        total_position_value = available_balance * self.config.max_recovery_position

        # 计算各批次价值
        stage1_value = total_position_value * self.config.stage1_allocation
        stage2_value = total_position_value * self.config.stage2_allocation
        stage3_value = total_position_value * self.config.stage3_allocation

        # 转换为数量
        stage1_quantity = stage1_value / current_price
        stage2_quantity = stage2_value / current_price
        stage3_quantity = stage3_value / current_price

        return [stage1_quantity, stage2_quantity, stage3_quantity]

    def should_enter_stage(self, stage: int, market_data: Dict) -> Tuple[bool, str]:
        """判断是否应该进入某一批次"""
        try:
            # 检查是否已经超时
            if self.recovery_start_time:
                recovery_duration = time.time() - self.recovery_start_time
                if recovery_duration > self.config.max_recovery_time:
                    return False, "恢复时间已超过最大限制"

            # 检查批次间隔
            if self.last_stage_time:
                min_interval = self.config.stage_interval_periods * 900  # 15分钟周期
                if time.time() - self.last_stage_time < min_interval:
                    return False, f"距离上一批次时间不足{self.config.stage_interval_periods}个周期"

            # 检查价格不能低于上一批次（金字塔建仓）
            if stage > 0 and self.entry_prices:
                current_price = market_data.get('price', 0)
                last_entry_price = self.entry_prices[-1]
                if current_price >= last_entry_price:
                    return False, f"当前价格{current_price:.2f}不低于上一批次价格{last_entry_price:.2f}"

            # 检查止损条件
            current_price = market_data.get('price', 0)
            if self.entry_prices:
                avg_entry_price = sum(self.entry_prices) / len(self.entry_prices)
                stop_loss_price = avg_entry_price * (1 - self.config.stage_stop_loss)
                if current_price <= stop_loss_price:
                    return False, f"触发分批止损，止损价{stop_loss_price:.2f}"

            return True, "满足进入条件"

        except Exception as e:
            logger.error(f"批次进入判断失败：{e}")
            return False, f"判断失败：{e}"

    def should_exit(self, market_data: Dict, current_position_pnl: float) -> Tuple[bool, str]:
        """判断是否应该退出"""
        try:
            technical_data = market_data.get('technical_data', {})
            current_price = market_data.get('price', 0)

            # 1. 止盈检查
            if current_position_pnl > self.config.profit_target * 100:
                return True, f"达到止盈目标，盈利{current_position_pnl:.2f}%"

            # 2. 整体止损检查
            if self.entry_prices:
                avg_entry_price = sum(self.entry_prices) / len(self.entry_prices)
                overall_stop_loss = avg_entry_price * (1 - self.config.overall_stop_loss)
                if current_price <= overall_stop_loss:
                    return True, f"触发整体止损，止损价{overall_stop_loss:.2f}"

            # 3. RSI超买检查
            rsi = technical_data.get('rsi', 50)
            if rsi > self.config.rsi_overbought_exit:
                return True, f"RSI{rsi:.1f}超买，考虑退出"

            # 4. 趋势反转检查
            trend_strength = technical_data.get('trend_strength', 0)
            if trend_strength < 0.1:
                return True, f"趋势强度{trend_strength:.2f}严重下降，考虑退出"

            # 5. 时间退出
            if self.recovery_start_time:
                recovery_duration = time.time() - self.recovery_start_time
                if recovery_duration > self.config.max_recovery_time:
                    return True, "达到最大恢复时间，强制退出"

            return False, "未达到退出条件"

        except Exception as e:
            logger.error(f"退出条件检查失败：{e}")
            return False, f"检查失败：{e}"

    def update_state(self, market_data: Dict):
        """更新策略状态"""
        try:
            current_price = market_data.get('price', 0)

            # 更新最大回撤
            if self.entry_prices:
                avg_entry_price = sum(self.entry_prices) / len(self.entry_prices)
                current_drawdown = (avg_entry_price - current_price) / avg_entry_price
                if current_drawdown > self.max_drawdown:
                    self.max_drawdown = current_drawdown

            # 更新最低点价格
            if self.crash_low_price is None or current_price < self.crash_low_price:
                self.crash_low_price = current_price

            # 状态机转换
            if self.current_phase == RecoveryPhase.WAITING:
                if self.detect_crash(market_data):
                    self.current_phase = RecoveryPhase.OBSERVING
                    self.crash_detected_time = time.time()
                    self.is_active = True
                    logger.info("🚨 暴跌检测完成，进入观察期")

            elif self.current_phase == RecoveryPhase.OBSERVING:
                # 检查是否可以进入恢复阶段
                can_enter, reason = self.check_entry_conditions(market_data)
                if can_enter:
                    self.current_phase = RecoveryPhase.STAGE1
                    self.recovery_start_time = time.time()
                    self.stabilization_start_time = None
                    logger.info(f"✅ 观察期结束，进入第一批建仓：{reason}")
                else:
                    # 如果还没开始稳定期，现在开始
                    if self.stabilization_start_time is None:
                        self.stabilization_start_time = time.time()
                        logger.info("📊 进入稳定观察期")

        except Exception as e:
            logger.error(f"状态更新失败：{e}")

    def get_status(self) -> Dict:
        """获取策略状态信息"""
        return {
            'phase': self.current_phase.value,
            'is_active': self.is_active,
            'current_stage': self.current_stage,
            'total_position': self.total_position,
            'entry_prices': self.entry_prices,
            'entry_volumes': self.entry_volumes,
            'max_drawdown': self.max_drawdown * 100,
            'crash_low_price': self.crash_low_price,
            'recovery_duration': time.time() - self.recovery_start_time if self.recovery_start_time else 0
        }

    def reset(self):
        """重置策略状态"""
        self.current_phase = RecoveryPhase.WAITING
        self.crash_detected_time = None
        self.entry_prices = []
        self.entry_volumes = []
        self.current_stage = 0
        self.last_stage_time = None
        self.total_position = 0
        self.max_drawdown = 0
        self.is_active = False
        self.recovery_start_time = None
        self.crash_low_price = None
        self.stabilization_start_time = None
        logger.info("🔄 暴跌恢复策略已重置")