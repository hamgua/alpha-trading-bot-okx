"""
动态模型选择器 - 基于市场条件选择最优AI模型
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# 模型配置
MODEL_CONFIGS = {
    'deepseek': {
        'deepseek-chat': {  # 基础模型
            'input_cost': 0.28,  # $/百万tokens
            'output_cost': 0.42,
            'context_length': 128000,
            'strengths': ['成本控制', '快速响应', '基础分析'],
            'use_case': '日常分析'
        },
        'deepseek-reasoner': {  # 推理模型
            'input_cost': 2.0,
            'output_cost': 8.0,
            'context_length': 128000,
            'strengths': ['深度推理', '复杂分析', '逻辑严谨'],
            'use_case': '复杂决策'
        }
    },
    'kimi': {
        'moonshot-v1-8k': {  # 基础模型
            'input_cost': 0.2,
            'output_cost': 2.0,
            'context_length': 8000,
            'strengths': ['成本控制', '标准分析'],
            'use_case': '简单分析'
        },
        'moonshot-v1-32k': {  # 推荐升级
            'input_cost': 1.0,
            'output_cost': 3.0,
            'context_length': 32000,
            'strengths': ['多时间框架', '深度分析', '模式识别'],
            'use_case': '专业分析'
        },
        'moonshot-v1-128k': {  # 高级模型
            'input_cost': 2.0,
            'output_cost': 5.0,
            'context_length': 128000,
            'strengths': ['超大上下文', '历史分析', '复杂模式'],
            'use_case': '深度研究'
        }
    }
}

class ModelSelector:
    """动态模型选择器"""

    def __init__(self):
        self.current_models = {
            'deepseek': 'deepseek-chat',
            'kimi': 'moonshot-v1-32k'  # 已升级
        }
        self.selection_history = []

    def select_models(self, market_data: Dict[str, Any], volatility_level: str = 'normal') -> Dict[str, str]:
        """基于市场条件选择最优模型"""
        try:
            # 获取市场波动率
            volatility = self._calculate_volatility(market_data)

            # 根据波动率确定模型选择策略
            if volatility > 0.03:  # 高波动率 (>3%)
                selected_models = self._select_high_volatility_models()
            elif volatility < 0.01:  # 低波动率 (<1%)
                selected_models = self._select_low_volatility_models()
            else:  # 正常波动率
                selected_models = self._select_normal_volatility_models()

            # 记录选择历史
            self._record_selection(market_data, selected_models, volatility)

            return selected_models

        except Exception as e:
            logger.error(f"模型选择失败: {e}")
            # 返回默认配置
            return self.current_models.copy()

    def _calculate_volatility(self, market_data: Dict[str, Any]) -> float:
        """计算市场波动率"""
        try:
            # 使用ATR百分比作为波动率指标
            technical_data = market_data.get('technical_data', {})
            atr_pct = technical_data.get('atr_pct', 0)

            # 如果没有ATR数据，使用价格变化百分比
            if atr_pct == 0:
                price_change = abs(market_data.get('change_percent', 0))
                return price_change / 100

            return atr_pct / 100  # 转换为小数

        except Exception:
            return 0.015  # 默认正常波动率

    def _select_high_volatility_models(self) -> Dict[str, str]:
        """高波动率模型选择"""
        logger.info("检测到高波动率，选择增强分析模型")
        return {
            'deepseek': 'deepseek-chat',  # 保持成本效益
            'kimi': 'moonshot-v1-32k',    # 已升级，支持更复杂分析
            'reason': '高波动率需要更精确的分析和更大上下文'
        }

    def _select_low_volatility_models(self) -> Dict[str, str]:
        """低波动率模型选择"""
        logger.info("检测到低波动率，选择标准分析模型")
        return {
            'deepseek': 'deepseek-chat',  # 成本优先
            'kimi': 'moonshot-v1-32k',    # 保持32k用于区间分析
            'reason': '低波动率期间保持成本控制，但仍需充分上下文'
        }

    def _select_normal_volatility_models(self) -> Dict[str, str]:
        """正常波动率模型选择"""
        logger.info("🔄 正常波动率市场，使用标准配置")
        logger.info("  - DeepSeek: deepseek-chat (成本效益优先)")
        logger.info("  - Kimi: moonshot-v1-32k (已升级，支持复杂分析)")
        return {
            'deepseek': 'deepseek-chat',
            'kimi': 'moonshot-v1-32k',
            'reason': '标准市场条件下使用平衡配置'
        }

    def _record_selection(self, market_data: Dict[str, Any],
                         selected_models: Dict[str, str],
                         volatility: float):
        """记录模型选择历史"""
        record = {
            'timestamp': datetime.now(),
            'volatility': volatility,
            'price': market_data.get('price', 0),
            'selected_models': selected_models,
            'market_state': self._determine_market_state(volatility)
        }
        self.selection_history.append(record)

        # 保持最近100条记录
        if len(self.selection_history) > 100:
            self.selection_history = self.selection_history[-100:]

    def _determine_market_state(self, volatility: float) -> str:
        """确定市场状态"""
        if volatility > 0.03:
            return 'high_volatility'
        elif volatility < 0.01:
            return 'low_volatility'
        else:
            return 'normal_volatility'

    def get_cost_estimate(self, models: Dict[str, str],
                         estimated_tokens: int = 1000) -> float:
        """估算使用成本"""
        total_cost = 0

        for provider, model in models.items():
            if provider in MODEL_CONFIGS and model in MODEL_CONFIGS[provider]:
                config = MODEL_CONFIGS[provider][model]
                # 假设输入输出比例为 10:1
                input_tokens = estimated_tokens * 0.9
                output_tokens = estimated_tokens * 0.1

                cost = (input_tokens / 1000000 * config['input_cost'] +
                       output_tokens / 1000000 * config['output_cost'])
                total_cost += cost

        return total_cost

    def get_model_recommendations(self) -> List[Dict[str, Any]]:
        """获取模型推荐信息"""
        recommendations = []

        for provider, models in MODEL_CONFIGS.items():
            for model_name, config in models.items():
                recommendations.append({
                    'provider': provider,
                    'model': model_name,
                    'cost_per_1m_tokens': config['input_cost'] + config['output_cost'],
                    'context_length': config['context_length'],
                    'strengths': config['strengths'],
                    'use_case': config['use_case']
                })

        return sorted(recommendations, key=lambda x: x['cost_per_1m_tokens'])

    def get_selection_stats(self) -> Dict[str, Any]:
        """获取选择统计信息"""
        if not self.selection_history:
            return {'message': '暂无选择历史'}

        total_selections = len(self.selection_history)
        volatility_dist = {}
        model_usage = {}

        for record in self.selection_history:
            # 波动率分布
            vol_state = record['market_state']
            volatility_dist[vol_state] = volatility_dist.get(vol_state, 0) + 1

            # 模型使用统计
            models = record['selected_models']
            for provider, model in models.items():
                if provider != 'reason':  # 跳过原因字段
                    key = f"{provider}:{model}"
                    model_usage[key] = model_usage.get(key, 0) + 1

        return {
            'total_selections': total_selections,
            'volatility_distribution': volatility_dist,
            'model_usage': model_usage,
            'avg_volatility': sum(r['volatility'] for r in self.selection_history) / total_selections
        }

# 全局实例
model_selector = ModelSelector()