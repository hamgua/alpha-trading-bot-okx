#!/usr/bin/env python3
"""
[已废弃] 自适应交易机器人入口 v2.0

此文件已废弃，请使用项目根目录的 main.py 作为统一入口:

  python main.py                     # 默认 standard 模式
  python main.py --mode adaptive     # 自适应模式 (等价于原本此文件的功能)
  BOT_MODE=adaptive python main.py   # 通过环境变量切换
"""

import sys
import warnings

warnings.warn(
    "alpha_trading_bot/main.py 已废弃，请使用项目根目录的 main.py。"
    " 运行 `python main.py --mode adaptive` 获得等价功能。",
    DeprecationWarning,
    stacklevel=1,
)

# 向后兼容：直接转发到根 main.py 的 adaptive 模式
if __name__ == "__main__":
    import os
    os.environ.setdefault("BOT_MODE", "adaptive")

    # 导入并运行根入口
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    import asyncio
    # 动态导入根 main 的 main 函数
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "root_main", str(Path(__file__).parent.parent / "main.py")
    )
    root_main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(root_main)
