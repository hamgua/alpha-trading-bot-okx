# Alpha Trading Bot 启动指南

## 问题描述
启动时报错：`No module named 'dotenv'`，这是因为缺少 `python-dotenv` 依赖包。

## 解决方案

### 方案1：使用启动脚本（推荐）

1. **运行安装脚本**（自动处理虚拟环境和依赖）：
   ```bash
   ./setup.sh
   ```

2. **使用启动脚本运行**：
   ```bash
   ./run.sh --help          # 查看帮助
   ./run.sh -d              # 调试模式运行
   ./run.sh -c config.json  # 使用配置文件
   ```

### 方案2：手动设置虚拟环境

1. **创建虚拟环境**：
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

2. **安装依赖**：
   ```bash
   pip install --upgrade pip
   pip install python-dotenv
   pip install -r requirements.txt
   ```

3. **运行程序**：
   ```bash
   python main.py --help
   ```

### 方案3：使用 Docker（推荐生产环境）

1. **使用本地开发 Docker 配置**：
   ```bash
   # 构建镜像
   docker-compose -f docker-compose.local.yml build

   # 运行容器
   docker-compose -f docker-compose.local.yml up

   # 查看日志
   docker-compose -f docker-compose.local.yml logs -f
   ```

2. **使用生产环境 Docker 配置**：
   ```bash
   docker-compose up -d
   ```

## 文件说明

### 新创建的文件

1. **start_bot.sh** - 简单的启动脚本（已废弃，使用 run.sh 替代）
2. **setup.sh** - 完整的安装和设置脚本
3. **run.sh** - 项目启动脚本（由 setup.sh 生成）
4. **Dockerfile.local** - 本地开发用的 Dockerfile
5. **docker-compose.local.yml** - 本地开发用的 Docker Compose 配置

### 关键配置

1. **虚拟环境**：项目使用 Python 虚拟环境隔离依赖
2. **依赖管理**：通过 requirements.txt 管理所有依赖
3. **配置文件**：使用 .env 文件配置交易参数

## 常见问题

### 1. pip 安装失败
如果遇到 pip 安装失败，可以尝试：
```bash
# 使用国内镜像
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple python-dotenv

# 或者使用 --break-system-packages（不推荐）
pip install --break-system-packages python-dotenv
```

### 2. 网络超时
如果安装依赖时网络超时：
```bash
# 更换 pip 源
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

### 3. 权限问题
如果遇到权限问题：
```bash
chmod +x setup.sh
chmod +x run.sh
```

## 验证安装

运行以下命令验证安装是否成功：
```bash
# 应该显示帮助信息
./run.sh --help

# 或者
python main.py --version
```

## 下一步

1. 编辑 `.env` 文件配置交易参数
2. 设置交易所 API 密钥
3. 配置投资策略类型
4. 启动交易机器人

## 技术支持

如果仍然遇到问题，请检查：
1. Python 版本是否 ≥ 3.8
2. 虚拟环境是否正确激活
3. 所有依赖是否成功安装
4. .env 文件是否存在且配置正确