#!/bin/bash
# Alpha Trading Bot 安装和设置脚本

set -e

echo "==================================="
echo "Alpha Trading Bot 安装脚本"
echo "==================================="

# 检查Python版本
check_python() {
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
        echo "检测到 Python 版本: $PYTHON_VERSION"
        if [[ "$PYTHON_VERSION" < "3.8" ]]; then
            echo "错误: 需要 Python 3.8 或更高版本"
            exit 1
        fi
    else
        echo "错误: 未检测到 Python3"
        exit 1
    fi
}

# 创建虚拟环境
create_venv() {
    if [ ! -d "venv" ]; then
        echo "创建虚拟环境..."
        python3 -m venv venv
    else
        echo "虚拟环境已存在"
    fi
}

# 安装依赖
install_dependencies() {
    echo "激活虚拟环境..."
    source venv/bin/activate

    echo "升级 pip..."
    pip install --upgrade pip

    echo "安装依赖包..."
    # 逐个安装关键依赖，避免网络问题
    pip install python-dotenv || echo "警告: python-dotenv 安装失败"
    pip install numpy || echo "警告: numpy 安装失败"
    pip install aiohttp || echo "警告: aiohttp 安装失败"

    # 尝试安装完整 requirements
    if [ -f "requirements.txt" ]; then
        echo "安装 requirements.txt 中的依赖..."
        pip install -r requirements.txt || echo "警告: 部分依赖安装失败"
    fi
}

# 创建必要的目录
create_directories() {
    echo "创建必要的目录..."
    mkdir -p logs data_json
}

# 检查配置文件
check_config() {
    if [ ! -f ".env" ]; then
        if [ -f ".env.example" ]; then
            echo "创建 .env 配置文件..."
            cp .env.example .env
            echo "请编辑 .env 文件以配置您的交易参数"
        else
            echo "警告: 未找到 .env.example 文件"
        fi
    else
        echo ".env 文件已存在"
    fi
}

# 创建启动脚本
create_start_script() {
    cat > run.sh << 'EOF'
#!/bin/bash
# Alpha Trading Bot 启动脚本

# 激活虚拟环境
source venv/bin/activate

# 启动交易机器人
python main.py "$@"
EOF
    chmod +x run.sh
}

# 主函数
main() {
    check_python
    create_venv
    install_dependencies
    create_directories
    check_config
    create_start_script

    echo ""
    echo "==================================="
    echo "安装完成！"
    echo "==================================="
    echo ""
    echo "使用方法:"
    echo "  ./run.sh --help         # 查看帮助"
    echo "  ./run.sh -d             # 调试模式运行"
    echo "  ./run.sh -c config.json # 使用配置文件"
    echo ""
    echo "或者使用 Docker:"
    echo "  docker-compose -f docker-compose.local.yml build"
    echo "  docker-compose -f docker-compose.local.yml up"
    echo ""
    echo "请确保编辑 .env 文件配置您的交易参数"
}

# 运行主函数
main