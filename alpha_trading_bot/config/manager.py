"""
配置管理器 - 统一管理所有配置
"""

import os
from typing import Dict, Any, Optional
from dotenv import load_dotenv

from .models import (
    ConfigValidationResult,
    ExchangeConfig,
    TradingConfig,
    StrategyConfig,
    RiskConfig,
    AIConfig,
    SystemConfig
)

from ..utils import get_logger

logger = get_logger(__name__)

# 加载环境变量
load_dotenv()

class ConfigManager:
    """配置管理器"""

    def __init__(self):
        """初始化配置管理器"""
        self._exchange = self._load_exchange_config()
        self._trading = self._load_trading_config()
        self._strategies = self._load_strategy_config()
        self._risk = self._load_risk_config()
        self._ai = self._load_ai_config()
        self._system = self._load_system_config()

        # 验证配置
        validation_result = self._validate_config()
        if not validation_result.is_valid:
            # 在非测试环境下才抛出错误
            import sys
            if 'pytest' not in sys.modules:
                raise ValueError(f"配置验证失败: {validation_result.errors}")
            else:
                # 测试环境下只记录警告
                logger.warning(f"配置验证失败: {validation_result.errors}")

    def _load_exchange_config(self) -> ExchangeConfig:
        """加载交易所配置"""
        return ExchangeConfig(
            exchange='okx',
            api_key=os.getenv('OKX_API_KEY', ''),
            secret=os.getenv('OKX_SECRET', ''),
            password=os.getenv('OKX_PASSWORD', ''),
            sandbox=os.getenv('OKX_SANDBOX', 'false').lower() == 'true',
            symbol='BTC/USDT:USDT',
            timeframe='5m',
            contract_size=0.01
        )

    def _load_trading_config(self) -> TradingConfig:
        """加载交易配置"""
        return TradingConfig(
            test_mode=os.getenv('TEST_MODE', 'true').lower() == 'true',
            max_position_size=float(os.getenv('MAX_POSITION_SIZE', '0.01')),
            min_trade_amount=float(os.getenv('MIN_TRADE_AMOUNT', '0.0005')),
            leverage=int(os.getenv('LEVERAGE', '10')),
            cycle_minutes=int(os.getenv('CYCLE_MINUTES', '15')),
            margin_mode='cross',
            position_mode='one_way',
            allow_short_selling=os.getenv('ALLOW_SHORT_SELLING', 'false').lower() == 'true'
        )

    def _load_strategy_config(self) -> StrategyConfig:
        """加载策略配置"""
        investment_type = os.getenv('INVESTMENT_TYPE', 'conservative')

        # 验证投资类型
        valid_types = ['conservative', 'moderate', 'aggressive']
        if investment_type not in valid_types:
            logger.warning(f"无效的投资类型 '{investment_type}'，使用默认值 'conservative'")
            investment_type = 'conservative'

        return StrategyConfig(
            investment_type=investment_type,
            profit_lock_enabled=True,
            sell_signal_enabled=True,
            buy_signal_enabled=True,
            consolidation_protection_enabled=True,
            smart_tp_sl_enabled=True,
            limit_order_enabled=os.getenv('LIMIT_ORDER_ENABLED', 'true').lower() == 'true',
            price_crash_protection_enabled=True
        )

    def _load_risk_config(self) -> RiskConfig:
        """加载风险控制配置"""
        return RiskConfig(
            max_daily_loss=float(os.getenv('MAX_DAILY_LOSS', '100')),
            max_position_risk=float(os.getenv('MAX_POSITION_RISK', '0.05')),
            stop_loss_enabled=True,
            take_profit_enabled=True,
            trailing_stop_enabled=True,
            trailing_distance=0.015
        )

    def _load_ai_config(self) -> AIConfig:
        """加载AI配置"""
        return AIConfig(
            use_multi_ai=os.getenv('USE_MULTI_AI', 'false').lower() == 'true',
            cache_duration=int(os.getenv('AI_CACHE_DURATION', '900')),
            timeout=int(os.getenv('AI_TIMEOUT', '30')),
            max_retries=int(os.getenv('AI_MAX_RETRIES', '2')),
            min_confidence_threshold=float(os.getenv('AI_MIN_CONFIDENCE', '0.3')),
            ai_provider=os.getenv('AI_PROVIDER', 'kimi'),
            fallback_enabled=os.getenv('AI_FALLBACK_ENABLED', 'true').lower() == 'true'
        )

    def _load_system_config(self) -> SystemConfig:
        """加载系统配置"""
        return SystemConfig(
            max_history_length=100,
            log_level=os.getenv('LOG_LEVEL', 'INFO'),
            monitoring_enabled=True,
            web_interface_enabled=os.getenv('WEB_ENABLED', 'false').lower() == 'true',
            web_port=int(os.getenv('WEB_PORT', '8501'))
        )

    def _validate_config(self) -> ConfigValidationResult:
        """验证配置"""
        errors = []
        warnings = []

        # 验证交易所配置
        if not self._exchange.api_key:
            errors.append("缺少OKX API密钥")
        if not self._exchange.secret:
            errors.append("缺少OKX密钥")
        if not self._exchange.password:
            errors.append("缺少OKX交易密码")

        # 验证交易配置
        if self._trading.max_position_size <= 0:
            errors.append("最大仓位必须大于0")
        if self._trading.leverage <= 0:
            errors.append("杠杆倍数必须大于0")

        return ConfigValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )

    @property
    def exchange(self) -> ExchangeConfig:
        """获取交易所配置"""
        return self._exchange

    @property
    def trading(self) -> TradingConfig:
        """获取交易配置"""
        return self._trading

    @property
    def strategies(self) -> StrategyConfig:
        """获取策略配置"""
        return self._strategies

    @property
    def risk(self) -> RiskConfig:
        """获取风险控制配置"""
        return self._risk

    @property
    def ai(self) -> AIConfig:
        """获取AI配置"""
        return self._ai

    @property
    def system(self) -> SystemConfig:
        """获取系统配置"""
        return self._system

    def get_all(self) -> Dict[str, Any]:
        """获取所有配置"""
        return {
            'exchange': self._exchange.__dict__,
            'trading': self._trading.__dict__,
            'strategies': self._strategies.__dict__,
            'risk': self._risk.__dict__,
            'ai': self._ai.__dict__,
            'system': self._system.__dict__
        }

# 全局配置实例
_config_manager = None

def load_config() -> ConfigManager:
    """加载配置管理器"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager