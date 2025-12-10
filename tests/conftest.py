"""
测试配置和共享fixture
"""

import pytest
import asyncio
import os
from unittest.mock import patch

@pytest.fixture
def mock_env_vars():
    """模拟环境变量"""
    env_vars = {
        'OKX_API_KEY': 'test_api_key',
        'OKX_SECRET': 'test_secret',
        'OKX_PASSWORD': 'test_password',
        'OKX_SANDBOX': 'true',
        'TEST_MODE': 'true',
        'MAX_POSITION_SIZE': '0.01',
        'LEVERAGE': '10',
        'CYCLE_MINUTES': '15',
        'MAX_DAILY_LOSS': '100',
        'MAX_POSITION_RISK': '0.05',
        'LOG_LEVEL': 'INFO',
        'WEB_ENABLED': 'false',
        'WEB_PORT': '8501',
        'LIMIT_ORDER_ENABLED': 'true',
        'AI_PROVIDER': 'kimi',
        'AI_MIN_CONFIDENCE': '0.3',
        'USE_MULTI_AI': 'false',
        'AI_FALLBACK_ENABLED': 'true'
    }

    with patch.dict(os.environ, env_vars):
        yield env_vars

@pytest.fixture
def mock_trading_bot_init():
    """模拟交易机器人初始化成功"""
    with patch('alpha_trading_bot.core.bot.TradingBot.initialize', return_value=True):
        yield

@pytest.fixture
def valid_config(mock_env_vars):
    """有效的配置"""
    from alpha_trading_bot.config import ConfigManager
    return ConfigManager()

@pytest.fixture
def event_loop():
    """创建事件循环用于异步测试"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()