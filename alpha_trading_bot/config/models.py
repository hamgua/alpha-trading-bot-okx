"""
配置数据模型
"""

from enum import Enum
from dataclasses import dataclass
from typing import Dict, Any, Optional, List

class ConfigSection(Enum):
    """配置段枚举"""
    EXCHANGE = "exchange"
    TRADING = "trading"
    STRATEGIES = "strategies"
    RISK = "risk"
    AI = "ai"
    SYSTEM = "system"

@dataclass
class ConfigValidationResult:
    """配置验证结果"""
    is_valid: bool
    errors: list[str]
    warnings: list[str]

@dataclass
class ExchangeConfig:
    """交易所配置"""
    exchange: str = 'okx'
    api_key: str = ''
    secret: str = ''
    password: str = ''
    sandbox: bool = False
    symbol: str = 'BTC/USDT:USDT'
    timeframe: str = '5m'
    contract_size: float = 0.01

@dataclass
class TradingConfig:
    """交易配置"""
    test_mode: bool = True
    max_position_size: float = 0.01
    min_trade_amount: float = 0.0005
    leverage: int = 10
    cycle_minutes: int = 15
    margin_mode: str = 'cross'
    position_mode: str = 'one_way'
    allow_short_selling: bool = False

@dataclass
class StrategyConfig:
    """策略配置"""
    investment_type: str = 'conservative'  # 投资策略类型: conservative/moderate/aggressive
    profit_lock_enabled: bool = True
    sell_signal_enabled: bool = True
    buy_signal_enabled: bool = True
    consolidation_protection_enabled: bool = True
    smart_tp_sl_enabled: bool = True
    limit_order_enabled: bool = True
    price_crash_protection_enabled: bool = True

@dataclass
class RiskConfig:
    """风险控制配置"""
    max_daily_loss: float = 100.0
    max_position_risk: float = 0.05
    stop_loss_enabled: bool = True
    take_profit_enabled: bool = True
    trailing_stop_enabled: bool = True
    trailing_distance: float = 0.015

@dataclass
class AIConfig:
    """AI配置"""
    use_multi_ai: bool = False
    cache_duration: int = 900
    timeout: int = 30
    max_retries: int = 2
    min_confidence_threshold: float = 0.3
    ai_provider: str = 'kimi'
    fallback_enabled: bool = True

@dataclass
class SystemConfig:
    """系统配置"""
    max_history_length: int = 100
    log_level: str = 'INFO'
    monitoring_enabled: bool = True
    web_interface_enabled: bool = False
    web_port: int = 8501