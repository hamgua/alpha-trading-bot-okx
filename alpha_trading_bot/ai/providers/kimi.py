"""
Kimi AI提供商实现
"""

import aiohttp
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from .base import BaseAIProvider
from ...core.exceptions import NetworkError, RateLimitError

logger = logging.getLogger(__name__)

class KimiProvider(BaseAIProvider):
    """Kimi AI提供商"""

    def __init__(self, api_key: str, model: str = "moonshot-v1-8k"):
        super().__init__(api_key, model)
        self.base_url = "https://api.moonshot.cn/v1"
        self.timeout = 18.0

    async def generate_signal(self, prompt: str, market_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """生成交易信号"""
        try:
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }

            data = {
                'model': self.model,
                'messages': [
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': 0.3,
                'max_tokens': 500
            }

            # 使用AI客户端的共享会话
            session = self.client.session
            if not session:
                raise NetworkError("AI客户端会话未初始化")

            async with session.post(
                f'{self.base_url}/chat/completions',
                headers=headers,
                json=data,
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as response:
                if response.status == 429:
                    raise RateLimitError("Kimi API速率限制")
                elif response.status != 200:
                    raise NetworkError(f"Kimi API错误: {response.status}")

                result = await response.json()
                content = result['choices'][0]['message']['content']

                return self._parse_response(content)

        except Exception as e:
            logger.error(f"Kimi信号生成失败: {e}")
            return None

    def _parse_response(self, content: str) -> Optional[Dict[str, Any]]:
        """解析响应内容"""
        try:
            import re

            # 查找JSON内容
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                ai_data = json.loads(json_str)

                # 验证必需字段
                signal = ai_data.get('signal', 'HOLD').upper()
                confidence = float(ai_data.get('confidence', 0.5))
                reason = ai_data.get('reason', 'Kimi AI分析')

                # 验证信号有效性
                if signal not in ['BUY', 'SELL', 'HOLD']:
                    signal = 'HOLD'

                # 验证置信度范围
                confidence = max(0.0, min(1.0, confidence))

                return {
                    'signal': signal,
                    'confidence': confidence,
                    'reason': reason,
                    'timestamp': datetime.now().isoformat(),
                    'provider': 'kimi',
                    'raw_response': content
                }

            return None

        except Exception as e:
            logger.error(f"解析Kimi响应失败: {e}")
            return None

    def get_provider_name(self) -> str:
        """获取提供商名称"""
        return "kimi"