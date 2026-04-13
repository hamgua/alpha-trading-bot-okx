"""
Trading Bot 异常层次

按照 AGENTS.md 规范定义的异常类体系。所有自定义异常应继承自 TradingBotException。

异常处理规范：
- 所有 except 必须指定具体异常类型（禁止 bare except）
- 异常必须记录日志
- 异常必须传播或转换为业务异常
"""


class TradingBotException(Exception):
    """交易机器人基类异常

    所有自定义异常的基类。捕获后可获取通用错误信息。
    """

    pass


class ConfigurationError(TradingBotException):
    """配置相关错误

    当配置缺失、无效或无法加载时抛出。
    包括：API Key 缺失、参数超范围、配置文件错误等。
    """

    pass


class ExchangeError(TradingBotException):
    """交易所相关错误

    当与交易所交互失败时抛出。
    包括：API 调用失败、订单执行失败、余额不足等。
    """

    pass


class StrategyError(TradingBotException):
    """策略相关错误

    当策略执行或选择失败时抛出。
    包括：策略不存在、策略参数错误、信号生成失败等。
    """

    pass


class RiskControlError(TradingBotException):
    """风控相关错误

    当风控规则触发或风控检查失败时抛出。
    包括：止损触发、仓位超限、熔断激活等。
    """

    pass


class AIProviderError(TradingBotException):
    """AI 提供商相关错误

    当 AI 服务调用失败时抛出。
    包括：API 错误、超时、响应解析失败等。
    """

    pass


class NetworkError(TradingBotException):
    """网络相关错误

    当网络连接或通信失败时抛出。
    包括：DNS 解析失败、连接超时、SSL 错误等。
    """

    pass


class RateLimitError(TradingBotException):
    """速率限制错误

    当触发 API 速率限制时抛出。
    包括：请求频率超限、并发限制等。
    """

    pass
