"""
自学习参数优化器
基于历史回测数据自动调整最优参数
"""

import json
import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
import logging
from collections import deque
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class ParameterPerformance:
    """参数性能记录"""
    parameter_name: str
    parameter_value: float
    win_rate: float
    avg_return: float
    max_drawdown: float
    sharpe_ratio: float
    total_trades: int
    profitable_trades: int
    avg_holding_period: float

@dataclass
class MarketCondition:
    """市场条件"""
    trend_strength: float
    volatility: float
    volume_ratio: float
    price_position: float
    market_state: str  # bull, bear, sideways

class SelfLearningOptimizer:
    """自学习参数优化器"""

    def __init__(self, db_path: str = "data/parameter_optimization.db"):
        self.db_path = db_path
        self.performance_history = deque(maxlen=1000)  # 最近1000次交易
        self.parameter_space = self._initialize_parameter_space()
        self.learning_rate = 0.01
        self.exploration_rate = 0.1
        self.min_samples = 50  # 最少样本数才开始优化
        self.performance_cache = {}

        # 创建数据库
        self._create_database()

    def _initialize_parameter_space(self) -> Dict[str, Any]:
        """初始化参数空间"""
        return {
            'price_position_thresholds': {
                'extreme_high': {'min': 85, 'max': 99, 'step': 1},
                'high': {'min': 70, 'max': 90, 'step': 1},
                'extreme_low': {'min': 5, 'max': 25, 'step': 1}
            },
            'signal_attenuation': {
                'extreme_high': {'min': 0.3, 'max': 0.8, 'step': 0.05},
                'high': {'min': 0.5, 'max': 0.9, 'step': 0.05},
                'extreme_low': {'min': 1.2, 'max': 1.5, 'step': 0.05}
            },
            'breakout_threshold': {'min': 1.001, 'max': 1.005, 'step': 0.0005},
            'volume_confirmation': {'min': 1.0, 'max': 1.5, 'step': 0.1},
            'trend_strength_threshold': {'min': 0.3, 'max': 0.7, 'step': 0.05}
        }

    def _create_database(self):
        """创建数据库表"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 参数性能表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS parameter_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                parameter_name TEXT,
                parameter_value REAL,
                market_state TEXT,
                win_rate REAL,
                avg_return REAL,
                max_drawdown REAL,
                sharpe_ratio REAL,
                total_trades INTEGER,
                profitable_trades INTEGER,
                avg_holding_period REAL,
                trend_strength REAL,
                volatility REAL,
                volume_ratio REAL
            )
        ''')

        # 市场状态表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS market_conditions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                trend_strength REAL,
                volatility REAL,
                volume_ratio REAL,
                price_position REAL,
                market_state TEXT
            )
        ''')

        conn.commit()
        conn.close()

    def record_trade_performance(self, trade_data: Dict[str, Any]):
        """记录交易表现"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 提取交易数据
        entry_price = trade_data['entry_price']
        exit_price = trade_data['exit_price']
        holding_period = trade_data['holding_period_hours']
        market_conditions = trade_data['market_conditions']
        parameters_used = trade_data['parameters_used']

        # 计算收益
        return_pct = (exit_price - entry_price) / entry_price * 100

        # 记录到性能表
        for param_name, param_value in parameters_used.items():
            cursor.execute('''
                INSERT INTO parameter_performance (
                    timestamp, parameter_name, parameter_value, market_state,
                    win_rate, avg_return, max_drawdown, sharpe_ratio,
                    total_trades, profitable_trades, avg_holding_period,
                    trend_strength, volatility, volume_ratio
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().isoformat(),
                param_name,
                param_value,
                market_conditions['state'],
                1.0 if return_pct > 0 else 0.0,  # 简化版胜率
                return_pct,
                0.0,  # 最大回撤需要更复杂计算
                0.0,  # 夏普比率需要基准
                1,
                1 if return_pct > 0 else 0,
                holding_period,
                market_conditions['trend_strength'],
                market_conditions['volatility'],
                market_conditions['volume_ratio']
            ))

        conn.commit()
        conn.close()

    def analyze_parameter_performance(self, market_state: str = None) -> Dict[str, ParameterPerformance]:
        """分析参数表现"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 构建查询条件
        where_clause = ""
        params = []
        if market_state:
            where_clause = "WHERE market_state = ?"
            params = [market_state]

        # 查询参数表现
        cursor.execute(f'''
            SELECT parameter_name, parameter_value,
                   AVG(win_rate) as avg_win_rate,
                   AVG(avg_return) as avg_return,
                   AVG(max_drawdown) as avg_drawdown,
                   COUNT(*) as total_trades,
                   SUM(CASE WHEN profitable_trades = 1 THEN 1 ELSE 0 END) as profitable_trades,
                   AVG(avg_holding_period) as avg_holding_period
            FROM parameter_performance
            {where_clause}
            GROUP BY parameter_name, parameter_value
            HAVING COUNT(*) >= ?
            ORDER BY avg_win_rate DESC, avg_return DESC
        ''', params + [self.min_samples])

        results = {}
        for row in cursor.fetchall():
            param_perf = ParameterPerformance(
                parameter_name=row[0],
                parameter_value=row[1],
                win_rate=row[2],
                avg_return=row[3],
                max_drawdown=row[4],
                sharpe_ratio=0.0,  # 简化版
                total_trades=row[5],
                profitable_trades=row[6],
                avg_holding_period=row[7]
            )
            key = f"{row[0]}_{row[1]}"
            results[key] = param_perf

        conn.close()
        return results

    def get_optimal_parameters(self, current_market: MarketCondition) -> Dict[str, float]:
        """获取当前市场条件下的最优参数"""
        # 分析相似市场条件下的参数表现
        similar_conditions = self._find_similar_market_conditions(current_market)

        if not similar_conditions:
            logger.info("没有找到相似的市场条件，使用默认参数")
            return self._get_default_parameters()

        # 获取最优参数
        optimal_params = {}
        performance_data = self.analyze_parameter_performance(current_market.market_state)

        for param_name in self.parameter_space.keys():
            if isinstance(self.parameter_space[param_name], dict):
                # 复合参数
                for sub_param in self.parameter_space[param_name].keys():
                    best_value = self._find_best_parameter_value(
                        f"{param_name}.{sub_param}",
                        performance_data,
                        similar_conditions
                    )
                    if param_name not in optimal_params:
                        optimal_params[param_name] = {}
                    optimal_params[param_name][sub_param] = best_value
            else:
                # 简单参数
                best_value = self._find_best_parameter_value(
                    param_name,
                    performance_data,
                    similar_conditions
                )
                optimal_params[param_name] = best_value

        logger.info(f"自学习优化器 - 最优参数: {optimal_params}")
        return optimal_params

    def _find_similar_market_conditions(self, current_market: MarketCondition) -> List[Dict[str, Any]]:
        """找到相似的市场条件"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 查询相似的市场条件
        cursor.execute('''
            SELECT * FROM market_conditions
            WHERE ABS(trend_strength - ?) < 0.2
            AND ABS(volatility - ?) < 0.1
            AND ABS(volume_ratio - ?) < 0.3
            AND market_state = ?
            ORDER BY timestamp DESC
            LIMIT 100
        ''', (
            current_market.trend_strength,
            current_market.volatility,
            current_market.volume_ratio,
            current_market.market_state
        ))

        results = []
        for row in cursor.fetchall():
            results.append({
                'timestamp': row[1],
                'trend_strength': row[2],
                'volatility': row[3],
                'volume_ratio': row[4],
                'price_position': row[5],
                'market_state': row[6]
            })

        conn.close()
        return results

    def _find_best_parameter_value(self, param_name: str,
                                  performance_data: Dict[str, ParameterPerformance],
                                  similar_conditions: List[Dict[str, Any]]) -> float:
        """找到最优参数值"""
        # 筛选相关参数
        relevant_params = {
            k: v for k, v in performance_data.items()
            if k.startswith(param_name)
        }

        if not relevant_params:
            # 返回默认值
            return self._get_default_parameter_value(param_name)

        # 按胜率+收益率排序
        sorted_params = sorted(
            relevant_params.items(),
            key=lambda x: (x[1].win_rate, x[1].avg_return),
            reverse=True
        )

        # 返回最优值
        best_param_key = sorted_params[0][0]
        best_value = float(best_param_key.split('_')[-1])

        return best_value

    def _get_default_parameters(self) -> Dict[str, float]:
        """获取默认参数"""
        return {
            'price_position_thresholds': {
                'extreme_high': 95,
                'high': 80,
                'extreme_low': 15
            },
            'signal_attenuation': {
                'extreme_high': 0.5,
                'high': 0.7,
                'extreme_low': 1.3
            },
            'breakout_threshold': 1.002,
            'volume_confirmation': 1.2,
            'trend_strength_threshold': 0.4
        }

    def _get_default_parameter_value(self, param_name: str) -> float:
        """获取单个参数的默认值"""
        defaults = self._get_default_parameters()

        # 处理复合参数名
        if '.' in param_name:
            main_param, sub_param = param_name.split('.')
            return defaults.get(main_param, {}).get(sub_param, 0.5)
        else:
            return defaults.get(param_name, 0.5)

    def continuous_learning_update(self, recent_trades: List[Dict[str, Any]]):
        """持续学习更新"""
        if len(recent_trades) < self.min_samples:
            return

        # 分析最近交易表现
        total_return = sum(trade.get('return_pct', 0) for trade in recent_trades)
        win_rate = sum(1 for trade in recent_trades if trade.get('return_pct', 0) > 0) / len(recent_trades)

        logger.info(f"自学习更新 - 最近{len(recent_trades)}笔交易，胜率: {win_rate:.2f}，总收益: {total_return:.2f}%")

        # 如果表现良好，增加当前参数的信心度
        if win_rate > 0.6 and total_return > 0:
            self.learning_rate *= 0.95  # 降低学习率，更稳定
            logger.info(f"表现良好，降低学习率至: {self.learning_rate}")

        # 如果表现不佳，增加探索率
        elif win_rate < 0.4:
            self.exploration_rate = min(0.3, self.exploration_rate * 1.1)
            logger.info(f"表现不佳，增加探索率至: {self.exploration_rate}")

    def get_parameter_confidence(self, param_name: str, param_value: float) -> float:
        """获取参数信心度"""
        key = f"{param_name}_{param_value}"

        if key in self.performance_cache:
            perf = self.performance_cache[key]
            # 基于胜率和样本数量计算信心度
            confidence = perf.win_rate * (1 - 1 / max(perf.total_trades, 10))
            return max(0.1, min(0.99, confidence))

        return 0.5  # 默认信心度

    def export_optimization_report(self, filepath: str):
        """导出优化报告"""
        report = {
            'timestamp': datetime.now().isoformat(),
            'total_trades_analyzed': len(self.performance_history),
            'learning_rate': self.learning_rate,
            'exploration_rate': self.exploration_rate,
            'optimal_parameters': self._get_default_parameters(),  # 当前最优参数
            'parameter_space': self.parameter_space,
            'performance_summary': {
                'avg_win_rate': np.mean([p.win_rate for p in self.performance_history]) if self.performance_history else 0,
                'avg_return': np.mean([p.avg_return for p in self.performance_history]) if self.performance_history else 0,
                'total_profitable_trades': sum([p.profitable_trades for p in self.performance_history])
            }
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"优化报告已导出至: {filepath}")

# 全局实例
self_learning_optimizer = SelfLearningOptimizer()