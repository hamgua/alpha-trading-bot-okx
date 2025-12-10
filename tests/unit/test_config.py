"""
配置模块单元测试
"""

import os
import pytest
from unittest.mock import patch
from alpha_trading_bot.config import (
    ConfigManager, load_config,
    ExchangeConfig, TradingConfig, StrategyConfig,
    RiskConfig, AIConfig, SystemConfig
)

class TestConfigModels:
    """测试配置模型"""

    def test_exchange_config_defaults(self):
        """测试交易所配置默认值"""
        config = ExchangeConfig()
        assert config.exchange == 'okx'
        assert config.symbol == 'BTC/USDT:USDT'
        assert config.timeframe == '5m'
        assert config.contract_size == 0.01
        assert config.sandbox is False

    def test_trading_config_defaults(self):
        """测试交易配置默认值"""
        config = TradingConfig()
        assert config.test_mode is True
        assert config.max_position_size == 0.01
        assert config.min_trade_amount == 0.0005
        assert config.leverage == 10
        assert config.cycle_minutes == 15
        assert config.margin_mode == 'cross'
        assert config.position_mode == 'one_way'
        assert config.allow_short_selling is False

    def test_strategy_config_defaults(self):
        """测试策略配置默认值"""
        config = StrategyConfig()
        assert config.profit_lock_enabled is True
        assert config.sell_signal_enabled is True
        assert config.buy_signal_enabled is True
        assert config.consolidation_protection_enabled is True
        assert config.smart_tp_sl_enabled is True
        assert config.limit_order_enabled is True
        assert config.price_crash_protection_enabled is True

    def test_risk_config_defaults(self):
        """测试风险控制配置默认值"""
        config = RiskConfig()
        assert config.max_daily_loss == 100.0
        assert config.max_position_risk == 0.05
        assert config.stop_loss_enabled is True
        assert config.take_profit_enabled is True
        assert config.trailing_stop_enabled is True
        assert config.trailing_distance == 0.015

    def test_ai_config_defaults(self):
        """测试AI配置默认值"""
        config = AIConfig()
        assert config.use_multi_ai is False
        assert config.cache_duration == 900
        assert config.timeout == 30
        assert config.max_retries == 2
        assert config.min_confidence_threshold == 0.3
        assert config.ai_provider == 'kimi'
        assert config.fallback_enabled is True

    def test_system_config_defaults(self):
        """测试系统配置默认值"""
        config = SystemConfig()
        assert config.max_history_length == 100
        assert config.log_level == 'INFO'
        assert config.monitoring_enabled is True
        assert config.web_interface_enabled is False
        assert config.web_port == 8501

class TestConfigManager:
    """测试配置管理器"""

    @patch.dict(os.environ, {
        'OKX_API_KEY': 'test_key',
        'OKX_SECRET': 'test_secret',
        'OKX_PASSWORD': 'test_password',
        'TEST_MODE': 'true',
        'MAX_POSITION_SIZE': '0.02',
        'LEVERAGE': '20'
    })
    def test_valid_config(self):
        """测试有效配置"""
        config = ConfigManager()
        assert config.exchange.api_key == 'test_key'
        assert config.exchange.secret == 'test_secret'
        assert config.exchange.password == 'test_password'
        assert config.trading.test_mode is True
        assert config.trading.max_position_size == 0.02
        assert config.trading.leverage == 20

    def test_missing_required_fields(self):
        """测试缺少必填字段"""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="配置验证失败"):
                ConfigManager()

    @patch.dict(os.environ, {
        'OKX_API_KEY': 'test_key',
        'OKX_SECRET': 'test_secret',
        'OKX_PASSWORD': 'test_password',
        'MAX_POSITION_SIZE': '0',
        'LEVERAGE': '0'
    })
    def test_invalid_values(self):
        """测试无效值"""
        with pytest.raises(ValueError, match="配置验证失败"):
            ConfigManager()

    @patch.dict(os.environ, {
        'OKX_API_KEY': 'test_key',
        'OKX_SECRET': 'test_secret',
        'OKX_PASSWORD': 'test_password',
        'TEST_MODE': 'false',
        'MAX_POSITION_SIZE': '0.01',
        'LEVERAGE': '10',
        'KIMI_API_KEY': 'kimi_key',
        'DEEPSEEK_API_KEY': 'deepseek_key'
    })
    def test_get_all_config(self):
        """测试获取所有配置"""
        config = ConfigManager()
        all_config = config.get_all()
        assert 'exchange' in all_config
        assert 'trading' in all_config
        assert 'strategies' in all_config
        assert 'risk' in all_config
        assert 'ai' in all_config
        assert 'system' in all_config

    @patch.dict(os.environ, {
        'OKX_API_KEY': 'test_key',
        'OKX_SECRET': 'test_secret',
        'OKX_PASSWORD': 'test_password',
        'WEB_ENABLED': 'true',
        'WEB_PORT': '8080'
    })
    def test_web_config(self):
        """测试Web配置"""
        config = ConfigManager()
        assert config.system.web_interface_enabled is True
        assert config.system.web_port == 8080

class TestLoadConfig:
    """测试加载配置函数"""

    @patch.dict(os.environ, {
        'OKX_API_KEY': 'test_key',
        'OKX_SECRET': 'test_secret',
        'OKX_PASSWORD': 'test_password'
    })
    def test_load_config_singleton(self):
        """测试配置单例"""
        config1 = load_config()
        config2 = load_config()
        assert config1 is config2

    @patch.dict(os.environ, {
        'OKX_API_KEY': 'test_key',
        'OKX_SECRET': 'test_secret',
        'OKX_PASSWORD': 'test_password'
    })
    def test_load_config_properties(self):
        """测试加载配置属性"""
        config = load_config()
        assert hasattr(config, 'exchange')
        assert hasattr(config, 'trading')
        assert hasattr(config, 'strategies')
        assert hasattr(config, 'risk')
        assert hasattr(config, 'ai')
        assert hasattr(config, 'system')