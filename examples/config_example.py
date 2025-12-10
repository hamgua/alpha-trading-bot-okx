#!/usr/bin/env python3
"""
配置管理示例 - 展示如何使用配置系统
"""

import os
from pathlib import Path
from alpha_trading_bot.config import load_config, ConfigManager
from alpha_trading_bot.utils import setup_logging

def config_example():
    """配置管理示例"""
    # 设置日志
    setup_logging(level='INFO')

    print("配置管理示例")
    print("=" * 50)

    # 1. 加载配置
    print("\n1. 加载配置...")
    config = load_config()
    print("✓ 配置加载成功")

    # 2. 查看各模块配置
    print("\n2. 查看各模块配置:")

    # 交易所配置
    print(f"\n📈 交易所配置:")
    print(f"   交易所: {config.exchange.exchange}")
    print(f"   交易对: {config.exchange.symbol}")
    print(f"   时间框架: {config.exchange.timeframe}")
    print(f"   沙盒模式: {config.exchange.sandbox}")

    # 交易配置
    print(f"\n💰 交易配置:")
    print(f"   测试模式: {config.trading.test_mode}")
    print(f"   最大仓位: {config.trading.max_position_size}")
    print(f"   杠杆倍数: {config.trading.leverage}")
    print(f"   交易周期: {config.trading.cycle_minutes} 分钟")

    # 风险控制配置
    print(f"\n🛡️ 风险控制配置:")
    print(f"   最大日亏损: {config.risk.max_daily_loss} USDT")
    print(f"   最大仓位风险: {config.risk.max_position_risk * 100:.1f}%")
    print(f"   止损启用: {config.risk.stop_loss_enabled}")
    print(f"   止盈启用: {config.risk.take_profit_enabled}")

    # AI配置
    print(f"\n🤖 AI配置:")
    print(f"   AI提供商: {config.ai.ai_provider}")
    print(f"   多AI融合: {config.ai.use_multi_ai}")
    print(f"   最小置信度: {config.ai.min_confidence_threshold}")
    print(f"   回退启用: {config.ai.fallback_enabled}")

    # 系统配置
    print(f"\n⚙️ 系统配置:")
    print(f"   日志级别: {config.system.log_level}")
    print(f"   监控启用: {config.system.monitoring_enabled}")
    print(f"   Web界面: {config.system.web_interface_enabled}")
    print(f"   Web端口: {config.system.web_port}")

    # 3. 获取所有配置
    print(f"\n3. 获取所有配置...")
    all_config = config.get_all()
    print(f"配置键: {list(all_config.keys())}")

    # 4. 环境变量检查
    print(f"\n4. 环境变量检查:")
    env_vars = [
        'OKX_API_KEY',
        'OKX_SECRET',
        'OKX_PASSWORD',
        'KIMI_API_KEY',
        'DEEPSEEK_API_KEY'
    ]

    for var in env_vars:
        value = os.getenv(var)
        if value:
            masked_value = value[:4] + '*' * (len(value) - 8) + value[-4:] if len(value) > 8 else '已设置'
            print(f"   {var}: {masked_value}")
        else:
            print(f"   {var}: 未设置")

    # 5. 配置验证
    print(f"\n5. 配置验证...")
    validation_result = config._validate_config()

    if validation_result.is_valid:
        print("✓ 配置验证通过")
    else:
        print("❌ 配置验证失败:")
        for error in validation_result.errors:
            print(f"   - {error}")

    if validation_result.warnings:
        print("⚠️ 配置警告:")
        for warning in validation_result.warnings:
            print(f"   - {warning}")

    print("\n配置示例完成！")

if __name__ == "__main__":
    config_example()