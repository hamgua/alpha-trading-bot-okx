"""
自定义异常类
"""

class TradingBotException(Exception):
    """交易机器人基础异常"""
    pass

class ConfigurationError(TradingBotException):
    """配置错误"""
    pass

class ExchangeError(TradingBotException):
    """交易所相关错误"""
    pass

class StrategyError(TradingBotException):
    """策略相关错误"""
    pass

class RiskControlError(TradingBotException):
    """风险控制错误"""
    pass

class AIProviderError(TradingBotException):
    """AI服务提供商错误"""
    pass

class NetworkError(TradingBotException):
    """网络错误"""
    pass

class RateLimitError(TradingBotException):
    """速率限制错误"""
    pass