## Context

当前系统存在的架构问题：

1. **AdaptiveTradingBot 过大**：858行主类承担过多职责，包括市场检测、策略选择、参数管理、ML学习、风险管理等，导致代码难以维护和测试

2. **循环依赖风险**：`ai/optimizer` 模块依赖 `config/models`，可能存在循环引用

3. **异常处理不统一**：部分模块有详细异常处理，部分缺失

4. **类型提示不完整**：部分参数缺少类型注解

项目使用 Python 3.8+，采用模块化架构，核心模块包括 core、ai、exchange、config、utils。

## Goals / Non-Goals

**Goals:**
- 将 AdaptiveTradingBot 拆分为多个专门 Manager 类，降低耦合
- 通过接口抽象（Protocol）消除循环依赖
- 建立统一的异常处理规范
- 补充类型提示，提高代码可读性

**Non-Goals:**
- 不改变系统外部行为（无 breaking changes）
- 不改变现有的交易策略逻辑
- 不改变 AI 信号处理流程
- 不添加新功能，仅优化架构

## Decisions

### Decision 1: AdaptiveTradingBot 拆分方案

**选择**：委托模式（Delegation Pattern）

**方案**：
```python
class AdaptiveTradingBot:
    def __init__(self, config):
        # 委托给专门的 Manager
        self.market_manager = MarketRegimeManager()
        self.strategy_manager = StrategyExecutionManager()
        self.risk_manager = RiskControlManager()
        self.parameter_manager = ParameterManager()
        self.learning_manager = LearningManager()
        self.scheduler = TradingScheduler(config)
        self.position_manager = PositionManager(config)
```

**替代方案考虑**：
- **观察者模式**：各组件通过事件通信 → 过于复杂，不适合当前规模
- **策略模式**：将不同策略封装 → 已有 strategy_library，不需额外设计

**理由**：委托模式最简单，各 Manager 职责单一，通过接口与主类通信

---

### Decision 2: 循环依赖消除方案

**选择**：Protocol 接口抽象

**方案**：
```python
# config/models.py
from typing import Protocol, runtime_checkable

@runtime_checkable
class ConfigUpdaterProtocol(Protocol):
    """配置更新器接口"""
    async def update_parameters(self, params: Dict[str, float]) -> None: ...
    async def get_parameters(self) -> Dict[str, float]: ...

# ai/optimizer/config_updater.py
class ConfigUpdater:
    def __init__(self, config: Config):
        self._config = config
    
    async def update_parameters(self, params: Dict[str, float]) -> None:
        # 更新逻辑
        pass
```

**替代方案考虑**：
- **依赖注入**：通过构造函数传入 → 已有，足够
- **事件总线**：通过事件通信 → 过度设计

**理由**：Protocol 不需要继承，保持灵活性

---

### Decision 3: 异常处理规范

**选择**：统一的异常类层级 + 文档规范

**方案**：
```python
# core/exceptions.py
class TradingBotException(Exception):
    """基础异常"""
    pass

class ExchangeException(TradingBotException):
    """交易所相关异常"""
    pass

class AIException(TradingBotException):
    """AI 相关异常"""
    pass

class ConfigurationException(TradingBotException):
    """配置相关异常"""
    pass

class StrategyException(TradingBotException):
    """策略相关异常"""
    pass

class RiskControlException(TradingBotException):
    """风控相关异常"""
    pass
```

**异常处理模式**：
```python
try:
    result = await execute_trade()
except TradingBotException as e:
    logger.error(f"交易执行失败: {e}")
    raise
except Exception as e:
    logger.exception(f"未知错误: {e}")
    raise TradingBotException(f"未知错误: {e}") from e
```

---

### Decision 4: Manager 类职责划分

| Manager | 职责 | 提取自 |
|---------|------|--------|
| MarketRegimeManager | 市场状态检测和发布 | AdaptiveTradingBot._init_adaptive_components |
| StrategyExecutionManager | 策略选择和执行 | AdaptiveTradingBot + AdaptiveStrategyManager |
| RiskControlManager | 风险评估和控制 | AdaptiveTradingBot + RiskControlManager |
| ParameterManager | 参数自适应调整 | AdaptiveParameterManager + ConfigUpdater |
| LearningManager | ML 学习集成 | MLLearningIntegrator + PerformanceTracker |

---

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| 拆分后 Manager 间通信复杂化 | 使用简单接口，避免事件总线 |
| 重构过程中引入 bug | 每步重构后运行测试验证 |
| 重构时间过长影响业务 | 分阶段实施，P1 优先 |
| 类型补全工作量巨大 | 仅补充 public API 类型提示 |

---

## Migration Plan

**阶段一（P1）**：循环依赖修复 + AdaptiveTradingBot 拆分
1. 定义 ConfigUpdaterProtocol 接口
2. 重构 ai/optimizer 使用接口
3. 拆分 AdaptiveTradingBot 为多个 Manager
4. 运行测试验证

**阶段二（P2）**：异常处理统一
1. 完善异常类定义
2. 添加异常处理规范文档
3. 检查并修复主要模块异常处理

**阶段三（P3）**：类型提示补全
1. 添加 mypy strict 检查
2. 逐步补充缺失类型
3. 集成到 CI 流程

---

## Open Questions

1. Manager 类之间是否需要事件通信机制？
2. 是否需要保留 AdaptiveTradingBot 作为门面类（Facade）？
3. 类型检查是否强制要求通过 CI？
