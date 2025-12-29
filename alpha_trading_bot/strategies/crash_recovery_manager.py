#!/usr/bin/env python3
"""
暴跌恢复策略管理器
集成暴跌恢复策略到现有交易系统中
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import time

from .crash_recovery import CrashRecoveryStrategy, RecoveryConfig
from dataclasses import dataclass

@dataclass
class Signal:
    """简单的信号数据类"""
    provider: str
    signal: str
    confidence: float
    reason: str
    metadata: dict = None

logger = logging.getLogger(__name__)


class CrashRecoveryManager:
    """暴跌恢复策略管理器"""

    def __init__(self, enabled: bool = True, config: Optional[RecoveryConfig] = None):
        self.enabled = enabled
        self.recovery_strategy = CrashRecoveryStrategy(config) if enabled else None
        self.is_initialized = False
        self.current_position = None  # 当前持仓信息
        self.entry_signals = []       # 入场信号历史
        self.performance_stats = {
            'total_recoveries': 0,
            'successful_recoveries': 0,
            'failed_recoveries': 0,
            'total_profit': 0.0,
            'avg_recovery_time': 0,
            'max_drawdown': 0
        }

    def initialize(self, initial_position: Optional[Dict] = None):
        """初始化恢复策略管理器"""
        if not self.enabled:
            logger.info("暴跌恢复策略已禁用")
            return

        self.is_initialized = True
        self.current_position = initial_position

        if initial_position:
            logger.info(f"🚀 暴跌恢复策略已初始化，当前持仓：{initial_position}")
        else:
            logger.info("🚀 暴跌恢复策略已初始化，等待暴跌信号")

    def process_market_data(self, market_data: Dict) -> List[Signal]:
        """处理市场数据，生成恢复信号"""
        signals = []

        if not self.enabled or not self.is_initialized:
            return signals

        try:
            # 更新策略状态
            self.recovery_strategy.update_state(market_data)

            # 获取当前状态
            status = self.recovery_strategy.get_status()
            phase = status['phase']

            # 根据当前阶段生成相应信号
            if phase == 'waiting':
                # 检测暴跌
                if self.recovery_strategy.detect_crash(market_data):
                    signal = Signal(
                        provider='crash_recovery',
                        signal='HOLD',
                        confidence=0.8,
                        reason="检测到暴跌，暂停交易进入观察期",
                        metadata={'phase': 'crash_detected', 'crash_type': 'price_drop'}
                    )
                    signals.append(signal)

            elif phase == 'observing':
                # 观察期，检查入场条件
                can_enter, reason = self.recovery_strategy.check_entry_conditions(market_data)
                if can_enter:
                    signal = Signal(
                        provider='crash_recovery',
                        signal='BUY',
                        confidence=0.7,
                        reason=f"暴跌后恢复条件满足：{reason}",
                        metadata={'phase': 'ready_to_recover', 'stage': 1}
                    )
                    signals.append(signal)

            elif phase in ['stage1', 'stage2', 'stage3']:
                # 分批建仓阶段
                current_stage = status['current_stage']
                stage_num = int(phase.replace('stage', ''))

                # 检查是否应该进入下一批次
                should_enter, reason = self.recovery_strategy.should_enter_stage(stage_num, market_data)
                if should_enter:
                    allocation = self.recovery_strategy.config.__getattribute__(f'stage{stage_num}_allocation')
                    signal = Signal(
                        provider='crash_recovery',
                        signal='BUY',
                        confidence=0.6 + (stage_num * 0.1),  # 分批增加信心度
                        reason=f"暴跌恢复第{stage_num}批建仓：{reason}",
                        metadata={
                            'phase': 'recovery_stage',
                            'stage': stage_num,
                            'allocation': allocation,
                            'stage_type': 'pyramid_entry'
                        }
                    )
                    signals.append(signal)

            elif phase == 'recovered':
                # 恢复完成，检查退出条件
                current_pnl = self._calculate_current_pnl(market_data)
                should_exit, reason = self.recovery_strategy.should_exit(market_data, current_pnl)
                if should_exit:
                    signal = Signal(
                        provider='crash_recovery',
                        signal='SELL',
                        confidence=0.8,
                        reason=f"暴跌恢复完成，退出：{reason}",
                        metadata={'phase': 'recovery_complete', 'pnl': current_pnl}
                    )
                    signals.append(signal)
                    self._record_recovery_completion(current_pnl)

            # 检查是否需要紧急退出
            emergency_exit = self._check_emergency_exit(market_data)
            if emergency_exit:
                signals.append(emergency_exit)

        except Exception as e:
            logger.error(f"处理市场数据失败：{e}")

        return signals

    def _calculate_current_pnl(self, market_data: Dict) -> float:
        """计算当前持仓盈亏"""
        if not self.current_position or not self.current_position.get('entry_price'):
            return 0.0

        try:
            current_price = market_data.get('price', 0)
            entry_price = self.current_position['entry_price']
            position_size = self.current_position.get('size', 0)

            if entry_price > 0 and position_size > 0:
                pnl_pct = (current_price - entry_price) / entry_price
                return pnl_pct * 100  # 转换为百分比

        except Exception as e:
            logger.error(f"计算盈亏失败：{e}")

        return 0.0

    def _check_emergency_exit(self, market_data: Dict) -> Optional[Signal]:
        """检查是否需要紧急退出"""
        if not self.current_position:
            return None

        try:
            current_price = market_data.get('price', 0)
            entry_price = self.current_position.get('entry_price', 0)

            if entry_price > 0:
                # 检查是否触发紧急止损
                drawdown = (entry_price - current_price) / entry_price
                if drawdown > 0.03:  # 3%亏损
                    return Signal(
                        provider='crash_recovery',
                        signal='SELL',
                        confidence=0.9,
                        reason=f"触发紧急止损，当前回撤{drawdown*100:.1f}%",
                        metadata={'emergency': True, 'stop_loss_triggered': True}
                    )

                # 检查价格是否跌破暴跌低点
                status = self.recovery_strategy.get_status()
                crash_low = status.get('crash_low_price')
                if crash_low and current_price < crash_low * 0.98:  # 跌破最低点2%
                    return Signal(
                        provider='crash_recovery',
                        signal='SELL',
                        confidence=0.85,
                        reason=f"价格跌破暴跌最低点{crash_low:.2f}，可能再次暴跌",
                        metadata={'emergency': True, 'below_crash_low': True}
                    )

        except Exception as e:
            logger.error(f"紧急退出检查失败：{e}")

        return None

    def _record_recovery_completion(self, final_pnl: float):
        """记录恢复完成信息"""
        self.performance_stats['total_recoveries'] += 1

        if final_pnl > 0:
            self.performance_stats['successful_recoveries'] += 1
        else:
            self.performance_stats['failed_recoveries'] += 1

        self.performance_stats['total_profit'] += final_pnl
        self.performance_stats['avg_recovery_time'] = (
            (self.performance_stats['avg_recovery_time'] * (self.performance_stats['total_recoveries'] - 1) +
             self.recovery_strategy.get_status().get('recovery_duration', 0)) /
            self.performance_stats['total_recoveries']
        )

        # 重置策略
        self.recovery_strategy.reset()
        self.current_position = None

        logger.info(f"📊 暴跌恢复完成，盈亏：{final_pnl:.2f}%，成功率：{
            self.performance_stats['successful_recoveries'] / self.performance_stats['total_recoveries'] * 100:.1f}%")

    def update_position(self, position: Optional[Dict]):
        """更新当前持仓信息"""
        self.current_position = position
        if position:
            logger.debug(f"📈 更新持仓信息：{position}")

    def get_status(self) -> Dict:
        """获取策略状态"""
        if not self.enabled:
            return {'enabled': False}

        status = {
            'enabled': True,
            'initialized': self.is_initialized,
            'current_phase': self.recovery_strategy.get_status(),
            'performance_stats': self.performance_stats.copy(),
            'has_position': self.current_position is not None
        }

        if self.current_position:
            status['current_position'] = {
                'entry_price': self.current_position.get('entry_price'),
                'size': self.current_position.get('size'),
                'side': self.current_position.get('side', 'LONG')
            }

        return status

    def get_recommendations(self) -> List[str]:
        """获取策略建议"""
        if not self.enabled or not self.is_initialized:
            return []

        recommendations = []
        status = self.recovery_strategy.get_status()
        phase = status['phase']

        if phase == 'waiting':
            recommendations.append("✅ 暴跌恢复策略正常运行，等待暴跌信号")
            recommendations.append("📊 建议关注RSI是否低于30，价格是否连续下跌")

        elif phase == 'observing':
            recommendations.append("👀 当前处于暴跌观察期，等待入场时机")
            recommendations.append("⏰ 建议等待至少3个周期确认底部")
            recommendations.append("📈 关注MACD是否出现底背离")

        elif phase in ['stage1', 'stage2', 'stage3']:
            stage_num = int(phase.replace('stage', ''))
            recommendations.append(f"🚀 正在进行暴跌恢复，当前第{stage_num}批建仓")
            recommendations.append("💰 建议采用金字塔式建仓，价格越低仓位越大")
            recommendations.append(f"⚠️ 设置分批止损，止损价：{status['entry_prices'][-1] * 0.985 if status['entry_prices'] else 'N/A'}")

        elif phase == 'recovered':
            recommendations.append("✅ 暴跌恢复完成，考虑逐步退出")
            recommendations.append("💡 建议分批止盈，不要贪心")
            recommendations.append("📊 关注RSI是否超过70，趋势是否减弱")

        # 通用建议
        recommendations.append("🛡️ 始终设置止损，控制风险")
        recommendations.append("📊 建议结合AI信号和其他技术指标综合判断")

        return recommendations

    def reset(self):
        """重置策略"""
        if self.recovery_strategy:
            self.recovery_strategy.reset()
        self.current_position = None
        logger.info("🔄 暴跌恢复策略管理器已重置")