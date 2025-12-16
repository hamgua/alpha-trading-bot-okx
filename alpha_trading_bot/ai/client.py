"""
AI客户端 - 处理与多个AI提供商的通信
"""

import asyncio
import aiohttp
import json
import time
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from ..core.exceptions import AIProviderError, NetworkError, RateLimitError

logger = logging.getLogger(__name__)

class AIClient:
    """AI客户端 - 支持多个AI提供商"""

    def __init__(self):
        self.providers = {}
        self.timeout_config = {
            'deepseek': {
                'connection_timeout': 10.0,
                'response_timeout': 20.0,
                'total_timeout': 35.0,
                'retry_base_delay': 3.0,
                'max_retries': 3,
                'performance_score': 0.75
            },
            'kimi': {
                'connection_timeout': 6.0,
                'response_timeout': 10.0,
                'total_timeout': 18.0,
                'retry_base_delay': 2.5,
                'max_retries': 3,
                'performance_score': 0.80
            },
            'qwen': {
                'connection_timeout': 5.0,
                'response_timeout': 8.0,
                'total_timeout': 15.0,
                'retry_base_delay': 2.0,
                'max_retries': 3,
                'performance_score': 0.85
            },
            'openai': {
                'connection_timeout': 10.0,
                'response_timeout': 15.0,
                'total_timeout': 25.0,
                'retry_base_delay': 4.0,
                'max_retries': 2,
                'performance_score': 0.70
            }
        }
        self.session = None

    async def initialize(self) -> bool:
        """初始化AI客户端"""
        try:
            # 创建HTTP会话
            timeout = aiohttp.ClientTimeout(total=60)
            connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=30,
                ttl_dns_cache=300,
                use_dns_cache=True,
                keepalive_timeout=30
            )
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={'User-Agent': 'AlphaTradingBot/3.0'}
            )

            # 加载提供商配置
            from ..config import load_config
            config = load_config()
            self.providers = config.ai.models

            logger.info(f"AI客户端初始化成功，配置 {len(self.providers)} 个提供商")
            return True

        except Exception as e:
            logger.error(f"AI客户端初始化失败: {e}")
            return False

    async def cleanup(self) -> None:
        """清理资源"""
        if self.session:
            logger.info(f"正在关闭AI客户端会话...")
            await self.session.close()
            self.session = None
            logger.info(f"AI客户端会话已关闭")

    async def generate_signal(self, provider: str, market_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """生成AI信号"""
        try:
            if provider not in self.providers:
                raise AIProviderError(f"未知的AI提供商: {provider}")

            api_key = self.providers[provider]
            if not api_key:
                raise AIProviderError(f"提供商 {provider} 未配置API密钥")

            # 调试：检查market_data结构
            logger.debug(f"生成AI信号 - 提供商: {provider}")
            logger.debug(f"Market data类型检查 - price: {type(market_data.get('price'))}, "
                        f"high: {type(market_data.get('high'))}, "
                        f"low: {type(market_data.get('low'))}, "
                        f"volume: {type(market_data.get('volume'))}")

            # 构建提示词 - 根据提供商选择不同的prompt策略
            if provider in ['kimi', 'deepseek']:
                # 对于高级提供商，使用增强的prompt
                prompt = self._build_enhanced_prompt(provider, market_data)
            else:
                # 其他提供商使用标准prompt
                prompt = self._build_trading_prompt(market_data)

            # 根据提供商调用不同的API
            if provider == 'kimi':
                return await self._call_kimi(api_key, prompt, market_data)
            elif provider == 'deepseek':
                return await self._call_deepseek(api_key, prompt, market_data)
            elif provider == 'qwen':
                return await self._call_qwen(api_key, prompt, market_data)
            elif provider == 'openai':
                return await self._call_openai(api_key, prompt, market_data)
            else:
                raise AIProviderError(f"不支持的提供商: {provider}")

        except Exception as e:
            logger.error(f"生成AI信号失败 ({provider}): {e}")
            if isinstance(e, (NetworkError, RateLimitError)):
                raise
            raise AIProviderError(f"生成信号失败: {str(e)}")

    def _build_trading_prompt(self, market_data: Dict[str, Any]) -> str:
        """构建增强的交易提示词 - 参考alpha-pilot-bot的先进设计"""

        # 基础市场数据
        price = float(market_data.get('price', 0))

        # 使用当日最高最低价格（标量值）
        daily_high = float(market_data.get('high', price))
        daily_low = float(market_data.get('low', price))
        volume = float(market_data.get('volume', 0))

        # 计算价格位置（相对当日高低位置）
        price_position = 50  # 默认中位
        if daily_high > daily_low:
            price_position = ((price - daily_low) / (daily_high - daily_low)) * 100

        # 计算价格变化
        price_change_pct = float(market_data.get('price_change_pct', 0))

        # 获取技术指标数据（如果有）
        technical_data = market_data.get('technical_data', {})
        rsi = float(technical_data.get('rsi', 50))
        macd = technical_data.get('macd', 'N/A')
        ma_status = technical_data.get('ma_status', 'N/A')
        atr_pct = float(technical_data.get('atr_pct', 0))

        # 获取趋势分析
        trend_analysis = market_data.get('trend_analysis', {})
        overall_trend = trend_analysis.get('overall', '震荡')
        trend_strength = trend_analysis.get('strength', 'normal')

        # 构建技术指标状态
        rsi_status = "超卖" if rsi < 35 else "超买" if rsi > 70 else "正常"

        # 检测市场状态
        is_high_volatility = atr_pct > 3.0
        is_consolidation = (
            atr_pct < 1.5 and
            abs(price_change_pct) < 4 and
            price_position > 25 and
            price_position < 75
        )

        # 构建市场情绪
        if rsi < 30:
            sentiment = "📉 极度恐慌，可能反弹"
        elif rsi > 70:
            sentiment = "📈 极度贪婪，可能回调"
        elif is_consolidation:
            sentiment = "➡️ 震荡观望，等待方向"
        else:
            sentiment = "😐 相对平衡"

        # 构建风控提示
        if is_consolidation:
            risk_hint = "⚠️ 震荡市: 缩小止盈止损范围，降低仓位"
        elif is_high_volatility:
            risk_hint = "⚠️ 高波动: 扩大止损范围，谨慎操作"
        else:
            risk_hint = "✅ 正常波动: 标准止盈止损设置"

        # 构建增强的prompt
        prompt = f"""你是一个专业的加密货币交易员，擅长波段操作和趋势跟踪。请基于以下市场数据给出精准的交易建议：

【📊 核心市场数据】
当前价格: ${price:,.2f}
价格区间: ${daily_low:,.2f} - ${daily_high:,.2f}
价格位置: {price_position:.1f}% (相对当日区间)
价格变化: {price_change_pct:+.2f}%
成交量: {volume:,.0f}
ATR波动率: {atr_pct:.2f}%

【🔧 技术分析】
RSI: {rsi:.1f} ({rsi_status})
MACD: {macd}
均线状态: {ma_status}
整体趋势: {overall_trend} ({trend_strength})
市场情绪: {sentiment}

【⚡ 关键分析要求】
1. 结合价格位置和技术指标综合判断
2. 考虑波动率对策略的影响
3. 关注市场情绪和资金流向
4. 基于博弈思维寻找最优入场点
5. 在低波动率环境下（ATR<1.5%），积极寻找区间交易机会，避免过度保守

【⚠️ 风险控制】
{risk_hint}

【💡 决策框架】
- 如果价格处于相对低位且技术指标超卖，优先考虑做多
- 如果价格处于相对高位且技术指标超买，优先考虑做空
- 在震荡市中，采用区间交易策略，高抛低吸
- 在趋势明确时，顺势而为，避免逆势操作

请以JSON格式回复，包含以下字段：
{{
    "signal": "BUY/SELL/HOLD",
    "confidence": 0.8,
    "reason": "详细分析理由（不少于50字）",
    "holding_time": "建议持仓时间",
    "risk": "风险提示和止损建议"
}}"""

        return prompt

    def _build_enhanced_prompt(self, provider: str, market_data: Dict[str, Any]) -> str:
        """构建增强的AI提示词 - 参考alpha-pilot-bot的先进设计"""

        # 基础市场数据
        price = float(market_data.get('price', 0))
        daily_high = float(market_data.get('high', price))
        daily_low = float(market_data.get('low', price))
        volume = float(market_data.get('volume', 0))

        # 计算价格位置（相对当日高低位置）
        price_position = 50  # 默认中位
        if daily_high > daily_low:
            price_position = ((price - daily_low) / (daily_high - daily_low)) * 100

        # 计算价格变化
        price_change_pct = float(market_data.get('price_change_pct', 0))

        # 获取技术指标数据（如果有）
        technical_data = market_data.get('technical_data', {})
        rsi = float(technical_data.get('rsi', 50))
        macd = technical_data.get('macd', 'N/A')
        ma_status = technical_data.get('ma_status', 'N/A')
        atr_pct = float(technical_data.get('atr_pct', 0))

        # 获取趋势分析
        trend_analysis = market_data.get('trend_analysis', {})
        overall_trend = trend_analysis.get('overall', '震荡')
        trend_strength = trend_analysis.get('strength', 'normal')

        # 构建技术指标状态
        rsi_status = "超卖" if rsi < 35 else "超买" if rsi > 70 else "正常"

        # 检测市场状态
        is_high_volatility = atr_pct > 3.0
        is_consolidation = (
            atr_pct < 1.5 and
            abs(price_change_pct) < 4 and
            price_position > 25 and
            price_position < 75
        )

        # 构建市场情绪
        if rsi < 30:
            sentiment = "📉 极度恐慌，可能反弹"
        elif rsi > 70:
            sentiment = "📈 极度贪婪，可能回调"
        elif is_consolidation:
            sentiment = "➡️ 震荡观望，等待方向"
        else:
            sentiment = "😐 相对平衡"

        # 构建风控提示
        if is_consolidation:
            risk_hint = "⚠️ 震荡市: 缩小止盈止损范围，降低仓位"
        elif is_high_volatility:
            risk_hint = "⚠️ 高波动: 扩大止损范围，谨慎操作"
        else:
            risk_hint = "✅ 正常波动: 标准止盈止损设置"

        # 提供商特定分析框架
        provider_frameworks = {
            'deepseek': f"""
【🎯 DEEPSEEK 核心分析框架】
1. 价格位置分析: 当前处于{price_position:.1f}%位置
2. 技术形态识别: 寻找突破/反转信号
3. 博弈策略: 考虑对手盘行为
4. 趋势跟踪: {overall_trend}趋势中的机会

交易风格: 波段操作，精准入场
""",
            'kimi': f"""
【📈 KIMI 短线分析框架】
1. 15分钟周期分析
2. RSI指标: {rsi:.1f} ({rsi_status})
3. 价格动能: {price_change_pct:+.2f}%
4. 支撑阻力: 基于价格位置判断

交易风格: 短线快进快出，严格止损
"""
        }

        # 获取提供商特定框架
        framework = provider_frameworks.get(provider, "")

        # 构建增强的prompt
        prompt = f"""你是{provider.upper()} AI交易助手，{provider}以精准的市场分析和独特的交易视角著称。请基于以下市场数据给出专业的交易建议：

【📊 核心市场数据】
当前价格: ${price:,.2f}
价格区间: ${daily_low:,.2f} - ${daily_high:,.2f}
价格位置: {price_position:.1f}% (相对当日区间)
价格变化: {price_change_pct:+.2f}%
成交量: {volume:,.0f}
ATR波动率: {atr_pct:.2f}%

【🔧 技术分析】
RSI: {rsi:.1f} ({rsi_status})
MACD: {macd}
均线状态: {ma_status}
整体趋势: {overall_trend} ({trend_strength})
市场情绪: {sentiment}

{framework}

【⚡ 关键分析要求】
1. 结合价格位置和技术指标综合判断
2. 考虑波动率对策略的影响
3. 关注市场情绪和资金流向
4. 基于博弈思维寻找最优入场点
5. 在低波动率环境下（ATR<1.5%），积极寻找区间交易机会，避免过度保守

【⚠️ 风险控制】
{risk_hint}

【💡 决策要点】
- 价格相对位置: {price_position:.1f}% (0%=底部, 100%=顶部)
- 技术指标状态: RSI {rsi_status}
- 波动率水平: {'高' if is_high_volatility else '低' if is_consolidation else '正常'}
- 建议操作: 基于以上分析给出明确信号

请以JSON格式回复，包含以下字段：
{{
    "signal": "BUY/SELL/HOLD",
    "confidence": 0.8,
    "reason": "详细分析理由（不少于50字）",
    "holding_time": "建议持仓时间",
    "risk": "风险提示和止损建议"
}}"""

        return prompt

    async def _call_kimi(self, api_key: str, prompt: str, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """调用Kimi API"""
        timeout_config = self.timeout_config['kimi']

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        data = {
            'model': 'moonshot-v1-32k',
            'messages': [
                {'role': 'user', 'content': prompt}
            ],
            'temperature': 0.2,  # 降低随机性，提高交易决策的一致性
            'max_tokens': 800  # 增加输出空间，支持更详细的市场分析
        }

        try:
            async with self.session.post(
                'https://api.moonshot.cn/v1/chat/completions',
                headers=headers,
                json=data,
                timeout=aiohttp.ClientTimeout(total=timeout_config['total_timeout'])
            ) as response:
                if response.status == 429:
                    raise RateLimitError("Kimi API速率限制")
                elif response.status != 200:
                    raise NetworkError(f"Kimi API错误: {response.status}")

                result = await response.json()
                content = result['choices'][0]['message']['content']

                # 解析JSON响应
                return self._parse_ai_response(content, 'kimi')

        except asyncio.TimeoutError:
            raise NetworkError("Kimi API请求超时")
        except Exception as e:
            raise NetworkError(f"Kimi API调用失败: {e}")

    async def _call_deepseek(self, api_key: str, prompt: str, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """调用DeepSeek API"""
        timeout_config = self.timeout_config['deepseek']

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        data = {
            'model': 'deepseek-chat',
            'messages': [
                {'role': 'user', 'content': prompt}
            ],
            'temperature': 0.2,  # 降低随机性，保持一致性
            'max_tokens': 600,   # 适度增加，支持更详细分析
            'top_p': 0.95,       # 限制采样范围
            'frequency_penalty': 0.1,  # 减少重复
            'presence_penalty': 0.1    # 鼓励新观点
        }

        try:
            async with self.session.post(
                'https://api.deepseek.com/v1/chat/completions',
                headers=headers,
                json=data,
                timeout=aiohttp.ClientTimeout(total=timeout_config['total_timeout'])
            ) as response:
                if response.status == 429:
                    raise RateLimitError("DeepSeek API速率限制")
                elif response.status != 200:
                    raise NetworkError(f"DeepSeek API错误: {response.status}")

                result = await response.json()
                content = result['choices'][0]['message']['content']

                return self._parse_ai_response(content, 'deepseek')

        except asyncio.TimeoutError:
            raise NetworkError("DeepSeek API请求超时")
        except Exception as e:
            raise NetworkError(f"DeepSeek API调用失败: {e}")

    async def _call_qwen(self, api_key: str, prompt: str, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """调用Qwen API"""
        timeout_config = self.timeout_config['qwen']

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        data = {
            'model': 'qwen-turbo',
            'input': {
                'messages': [
                    {'role': 'user', 'content': prompt}
                ]
            },
            'parameters': {
                'temperature': 0.3,
                'max_tokens': 500
            }
        }

        try:
            async with self.session.post(
                'https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation',
                headers=headers,
                json=data,
                timeout=aiohttp.ClientTimeout(total=timeout_config['total_timeout'])
            ) as response:
                if response.status == 429:
                    raise RateLimitError("Qwen API速率限制")
                elif response.status != 200:
                    raise NetworkError(f"Qwen API错误: {response.status}")

                result = await response.json()
                content = result['output']['choices'][0]['message']['content']

                return self._parse_ai_response(content, 'qwen')

        except asyncio.TimeoutError:
            raise NetworkError("Qwen API请求超时")
        except Exception as e:
            raise NetworkError(f"Qwen API调用失败: {e}")

    async def _call_openai(self, api_key: str, prompt: str, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """调用OpenAI API"""
        timeout_config = self.timeout_config['openai']

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        data = {
            'model': 'gpt-3.5-turbo',
            'messages': [
                {'role': 'user', 'content': prompt}
            ],
            'temperature': 0.3,
            'max_tokens': 500
        }

        try:
            async with self.session.post(
                'https://api.openai.com/v1/chat/completions',
                headers=headers,
                json=data,
                timeout=aiohttp.ClientTimeout(total=timeout_config['total_timeout'])
            ) as response:
                if response.status == 429:
                    raise RateLimitError("OpenAI API速率限制")
                elif response.status != 200:
                    raise NetworkError(f"OpenAI API错误: {response.status}")

                result = await response.json()
                content = result['choices'][0]['message']['content']

                return self._parse_ai_response(content, 'openai')

        except asyncio.TimeoutError:
            raise NetworkError("OpenAI API请求超时")
        except Exception as e:
            raise NetworkError(f"OpenAI API调用失败: {e}")

    def _parse_ai_response(self, content: str, provider: str) -> Dict[str, Any]:
        """解析AI响应"""
        try:
            # 尝试提取JSON
            import json
            import re

            # 查找JSON内容
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                ai_data = json.loads(json_str)

                # 验证必需字段
                signal = ai_data.get('signal', 'HOLD').upper()
                confidence = float(ai_data.get('confidence', 0.5))
                reason = ai_data.get('reason', f'{provider} AI分析')
                holding_time = ai_data.get('holding_time', '15分钟')

                # 验证信号有效性
                if signal not in ['BUY', 'SELL', 'HOLD']:
                    signal = 'HOLD'

                # 验证置信度范围
                confidence = max(0.0, min(1.0, confidence))

                return {
                    'signal': signal,
                    'confidence': confidence,
                    'reason': reason,
                    'holding_time': holding_time,
                    'timestamp': datetime.now().isoformat(),
                    'provider': provider,
                    'raw_response': content
                }
            else:
                # 如果没有JSON，尝试解析文本
                content_lower = content.lower()
                if 'buy' in content_lower:
                    signal = 'BUY'
                    confidence = 0.7
                elif 'sell' in content_lower:
                    signal = 'SELL'
                    confidence = 0.7
                else:
                    signal = 'HOLD'
                    confidence = 0.5

                return {
                    'signal': signal,
                    'confidence': confidence,
                    'reason': f'{provider} AI建议: {content[:100]}...',
                    'holding_time': '15分钟',
                    'timestamp': datetime.now().isoformat(),
                    'provider': provider,
                    'raw_response': content
                }

        except Exception as e:
            logger.error(f"解析AI响应失败: {e}")
            return {
                'signal': 'HOLD',
                'confidence': 0.3,
                'reason': f'解析AI响应失败: {str(e)}',
                'holding_time': '15分钟',
                'timestamp': datetime.now().isoformat(),
                'provider': provider,
                'raw_response': content
            }