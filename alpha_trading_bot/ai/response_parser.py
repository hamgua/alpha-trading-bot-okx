"""
响应解析器 - 解析AI返回的交易信号
"""

import re
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


class ResponseParser:
    """解析AI响应，提取信号和置信度"""

    # 有效信号列表
    VALID_SIGNALS = ["buy", "hold", "sell", "short"]

    @classmethod
    def parse(cls, response: str) -> Tuple[str, Optional[int]]:
        """
        解析AI响应

        Args:
            response: AI返回的原始文本

        Returns:
            Tuple[信号, 置信度]
            信号: buy/hold/sell/short
            置信度: 0-100，None表示无法解析
        """
        response = response.lower().strip()

        # 去除思考标签内容（如 MiniMax 等模型的内部推理）
        response = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()

        # 尝试提取信号和置信度
        match = re.search(
            r"^(buy|hold|sell|short)\s*\|?\s*confidence:\s*(\d+)%?",
            response,
            re.MULTILINE,
        )

        if match:
            signal = match.group(1)
            confidence = int(match.group(2))
            logger.debug(f"解析结果: signal={signal}, confidence={confidence}%")
            return signal, confidence

        # 尝试在多行中查找 answer line（如 MiniMax 返回多行时）
        match = re.search(
            r"^(buy|hold|sell|short)\s*\|?\s*confidence:\s*(\d+)%?",
            response,
            re.MULTILINE | re.IGNORECASE,
        )
        if match:
            signal = match.group(1).lower()
            confidence = int(match.group(2))
            logger.debug(
                f"解析结果(MultiLine): signal={signal}, confidence={confidence}%"
            )
            return signal, confidence

        # 回退到原有解析逻辑
        signal = cls._simple_parse(response)
        return signal, None

    @classmethod
    def _simple_parse(cls, response: str) -> str:
        """简单解析 - 只提取信号"""
        # 优先检查 short（避免与 buy 冲突）
        if "short" in response and "buy" not in response:
            return "short"
        elif "buy" in response and "sell" not in response and "hold" not in response:
            return "buy"
        elif "sell" in response and "hold" not in response:
            return "sell"
        elif "hold" in response:
            return "hold"
        else:
            logger.warning(f"无法解析响应: {response}，默认hold")
            return "hold"

    @classmethod
    def validate(cls, signal: str) -> bool:
        """验证信号是否有效"""
        return signal in cls.VALID_SIGNALS


def parse_response(response: str) -> Tuple[str, Optional[int]]:
    """便捷函数"""
    return ResponseParser.parse(response)


def extract_signal(response: str) -> str:
    """提取信号（忽略置信度）"""
    signal, _ = ResponseParser.parse(response)
    return signal
