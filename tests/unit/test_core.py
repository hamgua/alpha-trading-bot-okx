"""
核心模块单元测试
"""

import pytest
from datetime import datetime
from alpha_trading_bot.core import (
    BaseConfig, BaseComponent, SignalData, MarketData, TradingResult,
    TradingBot, BotConfig
)

class TestBaseConfig:
    """测试基础配置类"""

    def test_default_values(self):
        """测试默认值"""
        config = BaseConfig(name="test")
        assert config.name == "test"
        assert config.enabled is True
        assert config.timeout == 30
        assert config.max_retries == 3
        assert config.retry_delay == 1

    def test_to_dict(self):
        """测试转换为字典"""
        config = BaseConfig(name="test", enabled=False, timeout=60)
        result = config.to_dict()
        assert result['name'] == "test"
        assert result['enabled'] is False
        assert result['timeout'] == 60

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            'name': 'test',
            'enabled': False,
            'timeout': 60,
            'max_retries': 5,
            'retry_delay': 2
        }
        config = BaseConfig.from_dict(data)
        assert config.name == "test"
        assert config.enabled is False
        assert config.timeout == 60
        assert config.max_retries == 5
        assert config.retry_delay == 2

class TestSignalData:
    """测试信号数据类"""

    def test_creation(self):
        """测试创建"""
        timestamp = datetime.now()
        signal = SignalData(
            signal="BUY",
            confidence=0.8,
            reason="Test signal",
            timestamp=timestamp,
            provider="TestProvider",
            metadata={"key": "value"}
        )
        assert signal.signal == "BUY"
        assert signal.confidence == 0.8
        assert signal.reason == "Test signal"
        assert signal.timestamp == timestamp
        assert signal.provider == "TestProvider"
        assert signal.metadata == {"key": "value"}

    def test_to_dict(self):
        """测试转换为字典"""
        timestamp = datetime.now()
        signal = SignalData(
            signal="SELL",
            confidence=0.9,
            reason="Test sell",
            timestamp=timestamp
        )
        result = signal.to_dict()
        assert result['signal'] == "SELL"
        assert result['confidence'] == 0.9
        assert result['reason'] == "Test sell"
        assert result['timestamp'] == timestamp.isoformat()

class TestMarketData:
    """测试市场数据类"""

    def test_creation(self):
        """测试创建"""
        timestamp = datetime.now()
        market_data = MarketData(
            price=50000.0,
            timestamp=timestamp,
            volume=1000.0,
            high=51000.0,
            low=49000.0,
            open=49500.0
        )
        assert market_data.price == 50000.0
        assert market_data.timestamp == timestamp
        assert market_data.volume == 1000.0
        assert market_data.high == 51000.0
        assert market_data.low == 49000.0
        assert market_data.open == 49500.0

    def test_to_dict(self):
        """测试转换为字典"""
        timestamp = datetime.now()
        market_data = MarketData(
            price=50000.0,
            timestamp=timestamp
        )
        result = market_data.to_dict()
        assert result['price'] == 50000.0
        assert result['timestamp'] == timestamp.isoformat()

class TestTradingResult:
    """测试交易结果类"""

    def test_success_creation(self):
        """测试成功交易创建"""
        result = TradingResult(
            success=True,
            order_id="12345",
            filled_amount=0.01,
            average_price=50000.0
        )
        assert result.success is True
        assert result.order_id == "12345"
        assert result.error_message is None
        assert result.filled_amount == 0.01
        assert result.average_price == 50000.0
        assert result.timestamp is not None

    def test_failure_creation(self):
        """测试失败交易创建"""
        result = TradingResult(
            success=False,
            error_message="Insufficient balance"
        )
        assert result.success is False
        assert result.order_id is None
        assert result.error_message == "Insufficient balance"
        assert result.filled_amount == 0.0
        assert result.average_price == 0.0

    def test_to_dict(self):
        """测试转换为字典"""
        result = TradingResult(
            success=True,
            order_id="12345",
            filled_amount=0.01,
            average_price=50000.0
        )
        result_dict = result.to_dict()
        assert result_dict['success'] is True
        assert result_dict['order_id'] == "12345"
        assert result_dict['error_message'] is None
        assert result_dict['filled_amount'] == 0.01
        assert result_dict['average_price'] == 50000.0

class TestBotConfig:
    """测试机器人配置类"""

    def test_default_values(self):
        """测试默认值"""
        config = BotConfig(name="test-bot")
        assert config.name == "test-bot"
        assert config.trading_enabled is True
        assert config.max_position_size == 0.01
        assert config.leverage == 10
        assert config.test_mode is True
        assert config.cycle_interval == 15

    def test_custom_values(self):
        """测试自定义值"""
        config = BotConfig(
            name="custom-bot",
            trading_enabled=False,
            max_position_size=0.02,
            leverage=20,
            test_mode=False,
            cycle_interval=30
        )
        assert config.name == "custom-bot"
        assert config.trading_enabled is False
        assert config.max_position_size == 0.02
        assert config.leverage == 20
        assert config.test_mode is False
        assert config.cycle_interval == 30

@pytest.mark.asyncio
class TestTradingBot:
    """测试交易机器人类"""

    async def test_creation(self):
        """测试创建"""
        config = BotConfig(name="test-bot")
        bot = TradingBot(config)
        assert bot.config == config
        assert bot._initialized is False
        assert bot._running is False

    async def test_get_status_not_initialized(self):
        """测试未初始化时的状态"""
        bot = TradingBot()
        status = bot.get_status()
        assert status['name'] == "TradingBot"
        assert status['initialized'] is False
        assert status['running'] is False
        assert status['uptime'] >= 0

    async def test_get_status_initialized(self):
        """测试初始化后的状态"""
        bot = TradingBot()
        # 模拟初始化
        bot._initialized = True
        bot._running = True
        bot.trade_count = 5
        bot.total_pnl = 100.5

        status = bot.get_status()
        assert status['initialized'] is True
        assert status['running'] is True
        assert status['trades_executed'] == 5
        assert status['profit_loss'] == 100.5