# Alpha Trading Bot OKX

基于模块化架构的OKX加密货币交易机器人，支持AI驱动的自动化交易策略。

## 特性

- 🚀 **模块化架构** - 清晰的子包结构，易于维护和扩展
- 🤖 **AI信号增强** - 支持多种AI提供商（Kimi、DeepSeek、Qwen、OpenAI）
- 📊 **多策略支持** - 保守型、中等型、激进型投资策略
- 🛡️ **完善风控** - 三级风险控制，暴跌保护机制
- 📈 **实时监控** - 可选的Web界面实时监控
- 🧪 **回测功能** - 策略回测和优化
- 📝 **简洁API** - 提供简洁的顶层接口

## 快速开始

### 安装

```bash
# 克隆项目
git clone https://github.com/alphatrading/alpha-trading-bot-okx.git
cd alpha-trading-bot-okx

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate  # Windows

# 安装依赖
pip install -e .

# 安装AI支持（可选）
pip install -e ".[ai]"

# 安装Web界面（可选）
pip install -e ".[web]"
```

### 配置

1. 复制环境变量文件：
```bash
cp .env.example .env
```

2. 编辑 `.env` 文件，填入你的API密钥：
```
OKX_API_KEY=your_api_key
OKX_SECRET=your_secret
OKX_PASSWORD=your_password
```

### 使用

#### 命令行方式

```bash
# 启动测试模式机器人
alpha-bot run --bot-id my-bot

# 启动真实交易（谨慎使用！）
alpha-bot run --bot-id live-bot --real-trading

# 查看帮助
alpha-bot --help
```

#### Python API方式

```python
import asyncio
from alpha_trading_bot import create_bot, start_bot, stop_bot

async def main():
    # 创建机器人
    bot = await create_bot(
        bot_id="my-bot",
        name="My Trading Bot",
        config={
            "max_position_size": 0.01,
            "leverage": 10,
            "test_mode": True
        }
    )

    # 启动机器人
    await start_bot("my-bot")

    # 运行一段时间后停止
    await asyncio.sleep(3600)  # 运行1小时

    # 停止机器人
    await stop_bot("my-bot")

if __name__ == "__main__":
    asyncio.run(main())
```

## 项目结构

```
alpha_trading_bot/
├── __init__.py          # 简化API导出
├── core/                # 核心基础模块
│   ├── base.py         # 基础数据结构和组件
│   ├── bot.py          # 交易机器人主类
│   └── exceptions.py   # 自定义异常
├── config/              # 配置管理
│   ├── manager.py      # 配置管理器
│   └── models.py       # 配置数据模型
├── exchange/            # 交易所交互
│   ├── engine.py       # 交易引擎
│   ├── client.py       # 交易所客户端
│   ├── models.py       # 订单、仓位等模型
│   └── trading/        # 交易管理子模块
├── strategies/          # 交易策略
│   ├── manager.py      # 策略管理器
│   ├── base.py         # 基础策略类
│   ├── analyzer.py     # 市场分析器
│   └── optimization/   # 策略优化
├── ai/                  # AI信号生成
│   ├── manager.py      # AI管理器
│   ├── client.py       # AI客户端
│   ├── fusion.py       # AI融合决策
│   └── providers/      # AI提供商实现
├── utils/               # 工具模块
│   ├── logging.py      # 日志工具
│   ├── cache.py        # 缓存管理
│   └── monitoring.py   # 系统监控
├── api/                 # 对外API
│   └── bot_api.py      # 机器人管理API
└── cli/                 # 命令行接口
    └── main.py         # CLI主程序
```

## 配置说明

### 基础配置
- `TEST_MODE`: 测试模式（默认：true）
- `MAX_POSITION_SIZE`: 最大仓位大小
- `LEVERAGE`: 杠杆倍数
- `CYCLE_MINUTES`: 交易周期（分钟）

### 风险控制
- `MAX_DAILY_LOSS`: 最大日亏损（USDT）
- `MAX_POSITION_RISK`: 最大仓位风险比例

### AI配置
- `AI_PROVIDER`: AI提供商（kimi/deepseek/qwen/openai）
- `AI_MIN_CONFIDENCE`: 最小置信度阈值
- `USE_MULTI_AI`: 是否使用多AI融合

### Web界面
- `WEB_ENABLED`: 是否启用Web界面
- `WEB_PORT`: Web服务端口

## 开发

### 运行测试
```bash
pip install -e ".[dev]"
pytest
```

### 代码格式化
```bash
black alpha_trading_bot/
```

### 类型检查
```bash
mypy alpha_trading_bot/
```

## 注意事项

⚠️ **风险提示**：
- 加密货币交易存在高风险，可能导致资金损失
- 首次使用请务必在测试模式下运行
- 建议先进行充分的回测和模拟交易
- 合理设置风险控制参数
- 不要投入超过承受能力的资金

## 贡献

欢迎提交Issue和Pull Request！

## 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 更新日志

### v3.0.0
- 🎉 全新模块化架构重构
- 📦 按PEP 8推荐的子包收纳方式组织
- 🚀 提供简洁的顶层API接口
- 🛠️ 完善的项目配置和构建脚本
- 📚 详细的文档和示例代码

### 旧版本
- v2.x: 重构版，功能完整版
- v1.x: 原始版本，单文件实现

---

**免责声明**：本项目仅供学习和研究使用，不构成投资建议。使用本软件进行交易产生的任何损失，作者和贡献者不承担任何责任。请理性投资，注意风险。"}