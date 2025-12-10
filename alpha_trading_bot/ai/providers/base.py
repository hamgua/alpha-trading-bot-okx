"""
AI提供商基类
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class BaseAIProvider(ABC):
    """AI提供商基类"""

    def __init__(self, api_key: str, model: str = "default"):
        self.api_key = api_key
        self.model = model
        self.timeout = 30
        self.max_retries = 3

    @abstractmethod
    async def generate_signal(self, prompt: str, market_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """生成交易信号"""
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        """获取提供商名称"""
        pass

    def validate_config(self) -> bool:
        """验证配置"""
        return bool(self.api_key and self.api_key.strip())

    def build_prompt(self, market_data: Dict[str, Any]) -> str:
        """构建提示词"""
        price = market_data.get('price', 0)
        high = market_data.get('high', price)
        low = market_data.get('low', price)
        volume = market_data.get('volume', 0)

        return f"""基于以下市场数据提供交易建议：

当前价格: {price}
当日最高: {high}
当日最低: {low}
成交量: {volume}

请分析并提供：
1. 交易信号 (BUY/SELL/HOLD)
2. 信心度 (0-1)
3. 分析理由

请以JSON格式回复。"""