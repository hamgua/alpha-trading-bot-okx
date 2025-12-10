"""
日志工具模块
"""

import logging
import sys
from typing import Optional
from datetime import datetime

def setup_logging(
    level: str = 'INFO',
    log_file: Optional[str] = None,
    format_string: Optional[str] = None
) -> None:
    """
    设置日志配置

    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR)
        log_file: 日志文件路径，为None时不写文件
        format_string: 日志格式字符串
    """
    # 默认格式
    if format_string is None:
        format_string = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    # 创建logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, level.upper()))

    # 清除现有handler
    logger.handlers.clear()

    # 控制台handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, level.upper()))
    console_formatter = logging.Formatter(format_string)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # 文件handler
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(getattr(logging, level.upper()))
        file_formatter = logging.Formatter(format_string)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

def get_logger(name: str) -> logging.Logger:
    """
    获取logger实例

    Args:
        name: logger名称

    Returns:
        logging.Logger: logger实例
    """
    return logging.getLogger(name)

class LoggerMixin:
    """日志混入类"""

    @property
    def logger(self) -> logging.Logger:
        """获取logger"""
        return get_logger(self.__class__.__name__)