#!/bin/bash
# Alpha Trading Bot 启动脚本

# 激活虚拟环境
source venv/bin/activate

# 启动交易机器人
python main.py "$@"
