## Why

当前 Alpha Trading Bot OKX 系统存在架构性问题，主要体现在：1) AdaptiveTradingBot 主类过于庞大（858行）导致维护困难；2) 模块间存在循环依赖风险；3) 异常处理不统一；4) 类型提示不完整。这些问题会随着系统迭代加剧，影响系统的可维护性、稳定性和可扩展性。

## What Changes

### P1 - AdaptiveTradingBot 重构（职责拆分）

- 将 858 行 AdaptiveTradingBot 拆分为多个专门 Manager 类
- 提取 MarketRegimeManager（市场状态管理）
- 提取 StrategyExecutionManager（策略执行管理）
- 提取 RiskControlManager（风险管理）
- 提取 ParameterManager（参数管理）
- 提取 LearningManager（学习模块）

### P1 - 循环依赖修复

- 在 config/models.py 中定义配置更新接口（Protocol）
- 重构 ai/optimizer 模块对配置的依赖，消除循环引用
- 确保依赖单向流动

### P2 - 异常处理统一

- 完善 core/exceptions.py 异常类定义
- 统一所有模块的异常处理模式
- 添加异常处理检查清单

### P3 - 类型提示补全

- 在 mypy strict 模式下检查并修复类型错误
- 补充缺失的类型注解
- 添加类型检查到 CI 流程

## Capabilities

### New Capabilities

- `adaptive-bot-split`: 将 AdaptiveTradingBot 拆分为多个专门的 Manager 类，各司其职，通过事件或接口通信
- `interface-abstract`: 使用 Protocol/ABC 定义模块间接口，消除循环依赖
- `exception-standard`: 统一的异常处理规范和异常类定义

### Modified Capabilities

- 无（本次为内部架构重构，不改变外部行为）

## Impact

### 受影响代码

- `alpha_trading_bot/core/adaptive_bot.py` - 拆分重构
- `alpha_trading_bot/ai/optimizer/` - 接口抽象
- `alpha_trading_bot/config/models.py` - 添加接口定义
- `alpha_trading_bot/core/exceptions.py` - 完善异常类

### 系统影响

- 重构后系统行为保持一致（无 breaking changes）
- 模块间耦合度降低
- 可测试性提升
- 后续迭代效率提升
