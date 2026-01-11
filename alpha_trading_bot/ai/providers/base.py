"""
AI提供商基类
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from ...utils.price_calculator import PriceCalculator


class BaseAIProvider(ABC):
    """AI提供商基类"""

    def __init__(self, api_key: str, model: str = "default"):
        self.api_key = api_key
        self.model = model
        self.timeout = 30
        self.max_retries = 3

    @abstractmethod
    async def generate_signal(
        self, prompt: str, market_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
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
        """构建增强的基础提示词 - 与主prompt保持一致性"""

        # 基础市场数据
        price = float(market_data.get("price", 0))
        daily_high = float(market_data.get("high", price))
        daily_low = float(market_data.get("low", price))
        volume = float(market_data.get("volume", 0))

        # 24小时价格区间数据
        high_24h = daily_high
        low_24h = daily_low
        range_24h = high_24h - low_24h
        amplitude_24h = (range_24h / price * 100) if price > 0 else 0

        # 使用统一的价格位置计算器
        price_position_result = PriceCalculator.calculate_price_position(
            current_price=price,
            daily_high=daily_high,
            daily_low=daily_low,
            high_24h=high_24h,
            low_24h=low_24h,
        )

        # 向后兼容：保持原有变量名
        price_position = price_position_result.daily_position
        price_position_24h = price_position_result.position_24h

        # 获取技术指标
        technical_data = market_data.get("technical_data", {})
        rsi = float(technical_data.get("rsi", 50))
        atr_pct = float(technical_data.get("atr_pct", 0))

        # 构建基础分析
        rsi_status = "超卖" if rsi < 35 else "超买" if rsi > 70 else "正常"

        return f"""你是专业的加密货币交易员。请基于以下数据给出交易建议：

【市场数据】
当前价格: ${price:,.2f}
当日价格区间: ${daily_low:,.2f} - ${daily_high:,.2f}
当日价格位置: {price_position:.1f}% (相对当日区间)
24小时最高价: ${high_24h:,.2f}
24小时最低价: ${low_24h:,.2f}
24小时价格位置: {price_position_24h:.1f}% (相对24小时区间)
24小时振幅: {amplitude_24h:.2f}%
成交量: {volume:,.0f}
ATR波动率: {atr_pct:.2f}%

【技术指标】
RSI: {rsi:.1f} ({rsi_status})

【分析要求】
1. 结合价格位置和技术指标
2. 考虑24小时价格区间和振幅
3. 提供明确交易信号

请以JSON格式回复：
{{
    "signal": "BUY/SELL/HOLD",
    "confidence": 0.8,
    "reason": "分析理由",
    "holding_time": "持仓时间",
    "risk": "风险提示"
}}"""
