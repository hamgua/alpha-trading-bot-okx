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
            await self.session.close()

    async def generate_signal(self, provider: str, market_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """生成AI信号"""
        try:
            if provider not in self.providers:
                raise AIProviderError(f"未知的AI提供商: {provider}")

            api_key = self.providers[provider]
            if not api_key:
                raise AIProviderError(f"提供商 {provider} 未配置API密钥")

            # 构建提示词
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
        """构建交易提示词"""
        price = market_data.get('price', 0)
        high = market_data.get('high', price)
        low = market_data.get('low', price)
        volume = market_data.get('volume', 0)

        prompt = f"""你是一个专业的加密货币交易员。请基于以下市场数据给出交易建议：

当前价格: {price}
当日最高: {high}
当日最低: {low}
成交量: {volume}

请提供：
1. 交易信号 (BUY/SELL/HOLD)
2. 信心度 (0-1)
3. 理由分析
4. 建议持仓时间

请以JSON格式回复，包含以下字段：
{{
    "signal": "BUY/SELL/HOLD",
    "confidence": 0.8,
    "reason": "分析理由",
    "holding_time": "建议持仓时间"
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
            'model': 'moonshot-v1-8k',
            'messages': [
                {'role': 'user', 'content': prompt}
            ],
            'temperature': 0.3,
            'max_tokens': 500
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
            'temperature': 0.3,
            'max_tokens': 500
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