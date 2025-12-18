# Alpha Trading Bot OKX

基于模块化架构的OKX加密货币交易机器人，支持AI驱动的自动化交易策略。

## 特性

### 🚀 核心架构
- **模块化架构** - 清晰的子包结构，易于维护和扩展
- **异步处理** - 所有网络请求异步执行，提升性能
- **插件化设计** - 策略、AI提供商可插拔扩展
- **配置灵活** - 丰富的配置选项，支持多种交易场景

### 🤖 AI信号增强
- **多AI提供商支持** - Kimi、DeepSeek、Qwen、OpenAI
- **AI信号融合** - 共识/多数表决/置信度优先/加权平均策略
- **智能缓存** - AI信号缓存15分钟，避免重复调用
- **回退机制** - AI服务失败时自动切换备用提供商
- **置信度评估** - 基于历史表现的AI可靠性评分

### 📊 智能交易策略
- **三级别投资策略** - 保守型(30%-70%)、中等型(25%-75%)、激进型(15%-85%)
- **多时间框架分析** - 15分钟、1小时、4小时周期
- **横盘检测保护** - 多维度识别横盘，自动暂停交易
- **动态参数调整** - 基于市场条件自动优化策略参数
- **信号优先级排序** - 多信号冲突时的智能排序

### 🛡️ 完善风控体系
- **三级风险控制** - 当日亏损、连续亏损、仓位风险
- **追踪止损** - 基于入场价的动态止损，价格反向波动时锁定利润
- **暴跌保护** - 多时间框架暴跌检测(1.5%-3.5%阈值)
- **仓位精确控制** - 基于余额的动态仓位计算，保留5%缓冲
- **紧急停止** - 一键清仓，取消所有订单

### 💡 高级交易功能
- **智能订单执行** - 市价/限价单，支持部分成交处理
- **动态余额使用** - 自动计算最优交易量，使用全部可用余额
- **做空控制** - 可禁用做空功能，只做多交易
- **加仓管理** - 支持金字塔式加仓策略
- **反向开仓** - 信号方向改变时自动反向开仓

### 📈 实时监控分析
- **仓位实时监控** - 未实现盈亏、爆仓价格监控
- **订单状态跟踪** - 活动订单实时状态更新
- **性能指标统计** - 胜率、盈亏比、最大回撤等
- **日志系统** - 按日期自动切分的智能日志管理

### 🧪 技术特性
- **完整技术指标库** - RSI、MACD、ADX、布林带、ATR等
- **币种特异性参数** - BTC、ETH、SHIB等不同阈值设置
- **精度智能处理** - OKX交易所0.01张精度要求适配
- **错误恢复机制** - 自动重试、降级策略、异常处理

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

### 📊 基础交易配置
- `TEST_MODE`: 测试模式（默认：true）
- `MAX_POSITION_SIZE`: 最大仓位大小（默认0.01张）
- `MIN_TRADE_AMOUNT`: 最小交易量（默认0.01张，符合OKX要求）
- `LEVERAGE`: 杠杆倍数（默认10倍）
- `CYCLE_MINUTES`: 交易周期（默认15分钟）
- `MARGIN_MODE`: 保证金模式（cross全仓/isolated逐仓）
- `POSITION_MODE`: 持仓模式（one_way单向/hedge双向）
- `ALLOW_SHORT_SELLING`: 是否允许做空（默认false，只做多）

### 🎯 策略配置
- `INVESTMENT_TYPE`: 投资策略（conservative稳健型/moderate中等型/aggressive激进型）
- `PROFIT_LOCK_ENABLED`: 利润锁定功能（默认开启）
- `SELL_SIGNAL_ENABLED`: 卖出信号开关（默认开启）
- `BUY_SIGNAL_ENABLED`: 买入信号开关（默认开启）
- `CONSOLIDATION_PROTECTION_ENABLED`: 横盘保护（默认开启）
- `SMART_TP_SL_ENABLED`: 智能止盈止损（默认开启）
- `LIMIT_ORDER_ENABLED`: 限价单功能（默认开启）
- `PRICE_CRASH_PROTECTION_ENABLED`: 暴跌保护（默认开启）
- `TAKE_PROFIT_PERCENT`: 止盈百分比（默认6%）
- `STOP_LOSS_PERCENT`: 止损百分比（默认2%）

### 🛡️ 风险控制配置
- `MAX_DAILY_LOSS`: 最大日亏损（默认100 USDT）
- `MAX_POSITION_RISK`: 最大仓位风险比例（默认5%）
- `STOP_LOSS_ENABLED`: 止损开关（默认开启）
- `TAKE_PROFIT_ENABLED`: 止盈开关（默认开启）
- `TRAILING_STOP_ENABLED`: 追踪止损开关（默认开启）
- `TRAILING_DISTANCE`: 追踪距离（默认1.5%）
- `TRAILING_STOP_LOSS_ENABLED`: 追踪止损功能（默认开启）
- `TRAILING_STOP_LOSS_MODE`: 追踪模式（entry_based基于入场价）
- `MAX_CONSECUTIVE_LOSSES`: 最大连续亏损次数（默认3次）

### 🤖 AI配置
- `AI_MODE`: AI决策模式（single单AI/fusion融合）
- `AI_DEFAULT_PROVIDER`: 默认AI提供商（kimi/deepseek/qwen/openai）
- `AI_MIN_CONFIDENCE`: 最小置信度阈值（默认30%）
- `AI_FUSION_PROVIDERS`: AI融合提供商列表
- `AI_FUSION_STRATEGY`: AI融合策略（consensus/weighted/majority/confidence）
- `AI_FUSION_THRESHOLD`: AI融合阈值（默认60%）
- `AI_CACHE_DURATION`: AI信号缓存时间（默认900秒）
- `AI_TIMEOUT`: AI请求超时时间（默认30秒）
- `AI_MAX_RETRIES`: AI最大重试次数（默认2次）
- `USE_MULTI_AI_FUSION`: 是否使用多AI融合（默认开启）
- `FALLBACK_ENABLED`: 回退机制开关（默认开启）

### 🌐 网络配置
- `PROXY_ENABLED`: 代理开关（默认关闭）
- `HTTP_PROXY`: HTTP代理地址
- `HTTPS_PROXY`: HTTPS代理地址
- `TIMEOUT`: 网络超时时间（默认30秒）
- `MAX_RETRIES`: 最大重试次数（默认3次）
- `RETRY_DELAY`: 重试延迟（默认1秒）

### 🔧 系统配置
- `MAX_HISTORY_LENGTH`: 最大历史记录长度（默认100条）
- `LOG_LEVEL`: 日志级别（INFO/DEBUG/WARNING/ERROR）
- `MONITORING_ENABLED`: 监控功能开关（默认开启）
- `WEB_INTERFACE_ENABLED`: Web界面开关（默认关闭）
- `WEB_PORT`: Web服务端口（默认8501）

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

### v3.5.9 (最新版本)
- 🎯 **追踪止损功能完善** - 实现基于入场价的四阶段追踪止损逻辑
- 💰 **智能余额管理** - 自动使用全部USDT余额，保留5%缓冲防止爆仓
- ⚙️ **精度智能适配** - 完美适配OKX交易所0.01张最小交易量要求
- 🔧 **做空控制优化** - 可配置禁用做空，专注做多策略
- 🛡️ **风险连续控制** - 新增连续亏损次数限制，防止情绪化交易

### v3.5.0-v3.5.8
- 📊 **AI信号融合增强** - 新增加权平均和置信度优先策略
- 🚀 **订单执行优化** - 改进部分成交处理，支持反向开仓
- 🛡️ **暴跌检测升级** - 多时间框架暴跌检测，分级预警机制
- 🔍 **横盘识别精确化** - 币种特异性参数，BTC/ETH/SHIB不同阈值
- 💡 **日志系统智能化** - 按日期自动切分，线程安全写入

### v3.0.0-v3.4.0
- 🏗️ **架构重构** - 全新模块化设计，子包收纳方式
- 🤖 **AI系统集成** - 多提供商支持，信号融合决策
- 📈 **技术指标完善** - RSI、MACD、ADX、布林带、ATR全套指标
- 🎯 **策略体系建立** - 三级别投资策略，动态参数调整
- ⚡ **性能优化** - 异步处理、缓存机制、批量操作

### v2.x 版本
- 重构版，功能完整实现
- 基础交易策略和风控体系
- 单AI信号支持

### v1.x 版本
- 原始版本，单文件实现
- 基础交易功能

---

**免责声明**：本项目仅供学习和研究使用，不构成投资建议。使用本软件进行交易产生的任何损失，作者和贡献者不承担任何责任。请理性投资，注意风险。"}