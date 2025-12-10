"""
基础组件和配置类
提供统一的接口和基础功能
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime
import logging

@dataclass
class BaseConfig:
    """基础配置类"""
    name: str
    enabled: bool = True
    timeout: int = 30
    max_retries: int = 3
    retry_delay: int = 1

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'name': self.name,
            'enabled': self.enabled,
            'timeout': self.timeout,
            'max_retries': self.max_retries,
            'retry_delay': self.retry_delay
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BaseConfig':
        """从字典创建实例"""
        return cls(**data)

class BaseComponent(ABC):
    """基础组件类"""

    def __init__(self, config: Optional[BaseConfig] = None):
        """初始化基础组件"""
        self.config = config or BaseConfig(name=self.__class__.__name__)
        self.logger = logging.getLogger(self.__class__.__name__)
        self._initialized = False
        self._start_time = datetime.now()

    @abstractmethod
    async def initialize(self) -> bool:
        """初始化组件"""
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        """清理资源"""
        pass

    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self._initialized

    def get_uptime(self) -> float:
        """获取运行时间（秒）"""
        return (datetime.now() - self._start_time).total_seconds() if self._start_time else 0.0

    def get_status(self) -> Dict[str, Any]:
        """获取组件状态"""
        return {
            'name': self.config.name,
            'initialized': self._initialized,
            'uptime': self.get_uptime(),
            'enabled': self.config.enabled
        }

    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        return {
            'status': 'healthy' if self._initialized else 'unhealthy',
            'uptime': self.get_uptime(),
            'timestamp': datetime.now().isoformat()
        }

@dataclass
class SignalData:
    """信号数据结构"""
    signal: str
    confidence: float
    reason: str
    timestamp: datetime
    provider: str = ""
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'signal': self.signal,
            'confidence': self.confidence,
            'reason': self.reason,
            'timestamp': self.timestamp.isoformat(),
            'provider': self.provider,
            'metadata': self.metadata or {}
        }

@dataclass
class MarketData:
    """市场数据结构"""
    price: float
    timestamp: datetime
    volume: float = 0.0
    high: float = 0.0
    low: float = 0.0
    open: float = 0.0
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'price': self.price,
            'timestamp': self.timestamp.isoformat(),
            'volume': self.volume,
            'high': self.high,
            'low': self.low,
            'open': self.open,
            'metadata': self.metadata or {}
        }

@dataclass
class TradingResult:
    """交易结果数据结构"""
    success: bool
    order_id: Optional[str] = None
    error_message: Optional[str] = None
    filled_amount: float = 0.0
    average_price: float = 0.0
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'success': self.success,
            'order_id': self.order_id,
            'error_message': self.error_message,
            'filled_amount': self.filled_amount,
            'average_price': self.average_price,
            'timestamp': self.timestamp.isoformat()
        }