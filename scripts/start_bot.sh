#!/bin/bash
# Alpha Trading Bot 启动脚本

echo "正在启动 Alpha Trading Bot..."

# 检查虚拟环境是否存在
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
source venv/bin/activate

# 检查是否已安装依赖
if ! python -c "import dotenv" 2>/dev/null; then
    echo "安装依赖包..."
    pip install python-dotenv
fi

# 启动交易机器人
echo "启动交易机器人..."
python main.py "$@"

# 停用虚拟环境
deactivate