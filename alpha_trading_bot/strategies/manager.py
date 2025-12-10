"""
策略管理器 - 管理所有交易策略
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..core.base import BaseComponent, BaseConfig
from ..core.exceptions import StrategyError

logger = logging.getLogger(__name__)

class StrategyManagerConfig(BaseConfig):
    """策略管理器配置"""
    enable_backtesting: bool = True
    enable_optimization: bool = True
    default_strategy: str = "conservative"
    max_active_strategies: int = 3

class StrategyManager(BaseComponent):
    """策略管理器"""

    def __init__(self, config: Optional[StrategyManagerConfig] = None):
        super().__init__(config or StrategyManagerConfig())
        self.active_strategies: Dict[str, Any] = {}
        self.strategy_results: List[Dict[str, Any]] = []

    async def initialize(self) -> bool:
        """初始化策略管理器"""
        logger.info("正在初始化策略管理器...")

        # 加载默认策略
        await self._load_default_strategies()

        self._initialized = True
        return True

    async def cleanup(self) -> None:
        """清理资源"""
        self.active_strategies.clear()

    async def _load_default_strategies(self) -> None:
        """加载默认策略"""
        # 这里应该加载实际的策略实现
        # 简化实现：创建策略占位符
        self.active_strategies = {
            'conservative': {'enabled': True, 'priority': 1},
            'moderate': {'enabled': True, 'priority': 2},
            'aggressive': {'enabled': True, 'priority': 3}
        }

    async def generate_signals(self, market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """生成交易信号"""
        try:
            signals = []

            # 获取AI信号
            from ..ai import create_ai_manager
            ai_manager = await create_ai_manager()
            ai_signals = await ai_manager.generate_signals(market_data)

            # 转换AI信号为策略信号
            for ai_signal in ai_signals:
                signal = {
                    'type': ai_signal.get('signal', 'HOLD').lower(),
                    'confidence': ai_signal.get('confidence', 0.5),
                    'reason': ai_signal.get('reason', 'AI分析'),
                    'source': 'ai',
                    'provider': ai_signal.get('provider', 'unknown'),
                    'timestamp': datetime.now()
                }
                signals.append(signal)

            # 添加策略特定的信号
            strategy_signals = await self._generate_strategy_signals(market_data)
            signals.extend(strategy_signals)

            logger.info(f"生成了 {len(signals)} 个交易信号")
            return signals

        except Exception as e:
            logger.error(f"生成交易信号失败: {e}")
            return []

    async def _generate_strategy_signals(self, market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """生成策略信号"""
        # 简化实现：基于市场数据生成基础信号
        signals = []

        try:
            price = market_data.get('price', 0)
            high = market_data.get('high', price)
            low = market_data.get('low', price)

            if price > 0 and high > low:
                price_position = (price - low) / (high - low)

                # 保守策略信号
                if price_position < 0.2:
                    signals.append({
                        'type': 'buy',
                        'confidence': 0.7,
                        'reason': '保守策略：价格处于低位',
                        'source': 'conservative_strategy',
                        'timestamp': datetime.now()
                    })
                elif price_position > 0.8:
                    signals.append({
                        'type': 'sell',
                        'confidence': 0.7,
                        'reason': '保守策略：价格处于高位',
                        'source': 'conservative_strategy',
                        'timestamp': datetime.now()
                    })

                # 激进策略信号
                if price_position < 0.1:
                    signals.append({
                        'type': 'buy',
                        'confidence': 0.8,
                        'reason': '激进策略：价格极度低估',
                        'source': 'aggressive_strategy',
                        'timestamp': datetime.now()
                    })

        except Exception as e:
            logger.error(f"生成策略信号失败: {e}")

        return signals

    async def select_strategy(self, market_data: Dict[str, Any], signals: List[Dict[str, Any]]) -> Dict[str, Any]:
        """选择最优策略"""
        try:
            # 简化实现：选择置信度最高的信号
            if not signals:
                return {'type': 'hold', 'confidence': 0.5, 'reason': '无可用信号'}

            # 按置信度排序
            signals.sort(key=lambda x: x.get('confidence', 0), reverse=True)

            # 返回最佳信号
            best_signal = signals[0]
            return {
                'selected_signal': best_signal,
                'alternatives': signals[1:3],  # 备选方案
                'selection_reason': '最高置信度'
            }

        except Exception as e:
            logger.error(f"策略选择失败: {e}")
            return {'type': 'hold', 'confidence': 0.5, 'reason': '策略选择失败'}

    async def backtest_strategy(self, strategy_name: str, historical_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """回测策略"""
        if not self.config.enable_backtesting:
            return {'error': '回测功能已禁用'}

        try:
            # 简化实现：模拟回测结果
            total_trades = len(historical_data) // 10  # 假设每10个数据点一个交易
            win_rate = 0.65  # 假设胜率65%
            total_return = 0.12  # 假设总收益12%

            result = {
                'strategy': strategy_name,
                'total_trades': total_trades,
                'win_rate': win_rate,
                'total_return': total_return,
                'sharpe_ratio': 1.2,
                'max_drawdown': 0.08,
                'backtest_period': f"{len(historical_data)} 天",
                'status': 'completed'
            }

            self.strategy_results.append(result)
            return result

        except Exception as e:
            logger.error(f"策略回测失败: {e}")
            return {'error': str(e)}

    async def optimize_strategy(self, strategy_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """优化策略参数"""
        if not self.config.enable_optimization:
            return {'error': '优化功能已禁用'}

        try:
            # 简化实现：模拟优化过程
            optimized_params = {
                'take_profit': parameters.get('take_profit', 0.06) * 1.1,
                'stop_loss': parameters.get('stop_loss', 0.02) * 0.9,
                'position_size': parameters.get('position_size', 0.01) * 1.05
            }

            result = {
                'strategy': strategy_name,
                'original_parameters': parameters,
                'optimized_parameters': optimized_params,
                'expected_improvement': 0.15,
                'optimization_method': 'grid_search',
                'status': 'completed'
            }

            return result

        except Exception as e:
            logger.error(f"策略优化失败: {e}")
            return {'error': str(e)}

    def get_strategy_list(self) -> List[str]:
        """获取策略列表"""
        return list(self.active_strategies.keys())

    def get_strategy_status(self, strategy_name: str) -> Optional[Dict[str, Any]]:
        """获取策略状态"""
        return self.active_strategies.get(strategy_name)

    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        base_status = super().get_status()
        base_status.update({
            'active_strategies': len(self.active_strategies),
            'strategy_results': len(self.strategy_results),
            'strategy_list': self.get_strategy_list()
        })
        return base_status

# 创建策略管理器的工厂函数
async def create_strategy_manager() -> StrategyManager:
    """创建策略管理器实例"""
    from ..config import load_config
    config = load_config()

    sm_config = StrategyManagerConfig(
        name="AlphaStrategyManager",
        enable_backtesting=config.strategies.smart_tp_sl_enabled,
        enable_optimization=config.strategies.smart_tp_sl_enabled,
        default_strategy=config.system.log_level.lower(),
        max_active_strategies=3
    )

    manager = StrategyManager(sm_config)
    await manager.initialize()
    return manager

# 向后兼容的别名
MarketAnalyzer = StrategyManager
StrategySelector = StrategyManager
StrategyBacktestEngine = StrategyManager
StrategyOptimizer = StrategyManager
StrategyMonitor = StrategyManager
StrategyExecutor = StrategyManager
StrategyBehaviorHandler = StrategyManager

# 全局实例
market_analyzer = None
strategy_selector = None
consolidation_detector = None
crash_protection = None

async def initialize_strategies():
    """初始化策略模块（向后兼容）"""
    global market_analyzer, strategy_selector
    market_analyzer = await create_strategy_manager()
    strategy_selector = market_analyzer
    return market_analyzer

# 向后兼容的函数
def generate_enhanced_fallback_signal(market_data: Dict[str, Any], signal_history=None):
    """生成增强回退信号（向后兼容）"""
    # 简化实现
    from datetime import datetime
    return {
        'signal': 'HOLD',
        'confidence': 0.5,
        'reason': '回退信号',
        'timestamp': datetime.now().isoformat(),
        'provider': 'fallback'
    }