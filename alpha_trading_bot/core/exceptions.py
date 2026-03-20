"""
Trading Bot 异常层次

按照 AGENTS.md 规范定义的异常类体系
"""


class TradingBotException(Exception):
    """交易机器人基类异常"""

    pass


class ConfigurationError(TradingBotException):
    """配置相关错误"""

    pass


class ExchangeError(TradingBotException):
    """交易所相关错误"""

    pass


class StrategyError(TradingBotException):
    """策略相关错误"""

    pass


class RiskControlError(TradingBotException):
    """风控相关错误"""

    pass


class AIProviderError(TradingBotException):
    """AI 提供商相关错误"""

    pass


class NetworkError(TradingBotException):
    """网络相关错误"""

    pass


class RateLimitError(TradingBotException):
    """速率限制错误"""

    pass
