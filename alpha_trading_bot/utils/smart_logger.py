"""
智能日志管理器 - 自动按日期切换日志文件
"""

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import threading
import time


class SmartFileHandler(logging.Handler):
    """智能文件处理器 - 自动按日期切换文件"""

    def __init__(self, base_filename: str, encoding: str = 'utf-8', delay: bool = False):
        super().__init__()
        self.base_filename = base_filename
        self.encoding = encoding
        self.delay = delay
        self.current_date = None
        self.current_file = None
        self._lock = threading.Lock()

        # 初始化文件
        self._open_current_file()

        # 启动后台线程检查日期变化
        self._stop_flag = threading.Event()
        self._monitor_thread = threading.Thread(target=self._monitor_date_change, daemon=True)
        self._monitor_thread.start()

    def _open_current_file(self):
        """打开当前日期的日志文件"""
        with self._lock:
            # 获取当前日期
            today = datetime.now().strftime('%Y%m%d')

            # 如果日期没有变化，不需要切换
            if self.current_date == today and self.current_file is not None:
                return

            # 关闭旧文件
            if self.current_file is not None:
                self.current_file.close()

            # 生成新的文件名
            filename = f"{self.base_filename}-{today}.log"

            # 创建日志目录（如果不存在）
            log_path = Path(filename)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            # 打开新文件
            self.current_file = open(filename, 'a', encoding=self.encoding)
            self.current_date = today

            # 记录切换信息
            self.current_file.write(f"\n[日志文件切换] {datetime.now()} - 新日志文件: {filename}\n")
            self.current_file.flush()

    def _monitor_date_change(self):
        """后台线程监控日期变化"""
        while not self._stop_flag.is_set():
            try:
                # 每分钟检查一次日期
                time.sleep(60)

                # 获取当前日期
                today = datetime.now().strftime('%Y%m%d')

                # 如果日期变化，切换文件
                if today != self.current_date:
                    self._open_current_file()

            except Exception as e:
                # 如果出错，记录错误但继续运行
                print(f"日志监控线程错误: {e}")

    def emit(self, record):
        """写入日志记录"""
        try:
            # 确保使用正确的文件
            today = datetime.now().strftime('%Y%m%d')
            if today != self.current_date:
                self._open_current_file()

            # 格式化日志消息
            msg = self.format(record)

            # 写入文件
            with self._lock:
                if self.current_file and not self.current_file.closed:
                    self.current_file.write(msg + '\n')
                    self.current_file.flush()

        except Exception:
            self.handleError(record)

    def close(self):
        """关闭处理器"""
        # 停止监控线程
        self._stop_flag.set()
        if self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=1)

        # 关闭文件
        with self._lock:
            if self.current_file is not None:
                self.current_file.close()
                self.current_file = None

        super().close()


def setup_smart_logging(log_level=logging.INFO, log_dir: str = 'logs', base_filename: str = 'alpha-trading-bot-okx', logger_name: str = '__main__'):
    """设置智能日志系统"""
    # 创建日志目录
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)

    # 获取根logger并配置它
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # 清除根logger的现有处理器，避免重复
    root_logger.handlers.clear()

    # 创建格式化器
    formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s')

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 智能文件处理器
    base_path = str(log_path / base_filename)
    smart_handler = SmartFileHandler(base_path)
    smart_handler.setLevel(log_level)
    smart_handler.setFormatter(formatter)
    root_logger.addHandler(smart_handler)

    # 返回指定名称的logger（它将继承根logger的配置）
    return logging.getLogger(logger_name)