# AI ML 模块集成指南

## 概述

本文档描述如何将新开发的 ML 模块集成到现有的 alpha-trading-bot-okx 系统中。

## 目录

1. [新增文件列表](#新增文件列表)
2. [快速集成](#快速集成)
3. [详细配置](#详细配置)
4. [API 参考](#api-参考)
5. [测试验证](#测试验证)

---

## 新增文件列表

```
alpha_trading_bot/ai/
├── ml/
│   ├── __init__.py                      # 模块导出
│   ├── prompt_optimizer.py              # 优化版 Prompt 构建器 ⭐
│   ├── trend_detector.py                # 增强趋势检测器
│   ├── adaptive_fusion.py               # 自适应融合策略
│   ├── weight_optimizer.py              # ML 权重优化器
│   ├── performance_tracker.py            # 信号表现追踪
│   ├── ab_test_framework.py             # A/B 测试框架
│   └── monitoring_dashboard.py           # 监控仪表盘
├── integration.py                       # 集成管理器 ⭐
└── ml_integration_example.py            # 使用示例 ⭐

config/
└── prompt_optimizer.yaml                # 配置文件

tests/unit/
└── test_ml_integration.py              # 单元测试
```

---

## 快速集成

### 方式 1: 使用集成管理器 (推荐)

```python
from alpha_trading_bot.ai.integration import AIIntegrationManager

# 初始化
manager = AIIntegrationManager({
    "sma_short": 5,
    "sma_long": 20,
    "fusion_mode": "moderate"
})

# 更新价格
manager.update_price(70849.9)

# 分析市场
market_data = {
    "price": 70849.9,
    "recent_change_percent": 0.003,
    "technical": {
        "trend_direction": "up",
        "trend_strength": 0.7,
        "rsi": 55,
        "macd_histogram": 0.01,
        "bb_position": 0.45
    }
}

# 构建优化 Prompt
prompt = manager.build_prompt(market_data)

# 融合信号
signals = [
    {"provider": "kimi", "signal": "buy", "confidence": 75},
    {"provider": "deepseek", "signal": "hold", "confidence": 70}
]
result = manager.fuse_signals(signals, market_data)

print(f"信号: {result['signal']}")
print(f"置信度: {result['confidence']}%")
print(f"市场状态: {result['regime']}")
```

### 方式 2: 使用便捷函数

```python
from alpha_trading_bot.ai import get_optimized_signal

market_data = {
    "price": 70849.9,
    "recent_change_percent": 0.003,
    "technical": {
        "trend_direction": "up",
        "trend_strength": 0.7
    }
}

import asyncio
signal_info = asyncio.run(get_optimized_signal(market_data))

print(signal_info)
```

### 方式 3: 独立使用各模块

```python
# 使用优化版 Prompt 构建器
from alpha_trading_bot.ai.ml import (
    OptimizedPromptBuilder,
    MarketContext,
    MarketRegime
)

builder = OptimizedPromptBuilder()
context = MarketContext(regime=MarketRegime.STRONG_UPTREND)
prompt = builder.build(market_data, context)

# 使用趋势检测器
from alpha_trading_bot.ai.ml import EnhancedTrendDetector

detector = EnhancedTrendDetector()
detector.add_price(70000)
detector.add_price(70500)
trend = detector.detect_trend()

# 使用自适应融合
from alpha_trading_bot.ai.ml import AdaptiveFusionStrategy

fusion = AdaptiveFusionStrategy()
result = fusion.fuse(signals, trend_context, momentum=0.005)
```

---

## 详细配置

### 配置文件 (`config/prompt_optimizer.yaml`)

```yaml
prompt_optimizer:
  enabled: true
  trend_sma_short: 5
  trend_sma_long: 20
  strong_trend_threshold: 0.6
  weak_trend_threshold: 0.3
  strong_momentum_threshold: 0.005
  weak_momentum_threshold: 0.002

adaptive_fusion:
  enabled: true
  fusion_mode: moderate
  base_threshold: 0.50
  weights:
    strong_uptrend:
      kimi: 0.55
      deepseek: 0.45
    weak_uptrend:
      kimi: 0.50
      deepseek: 0.50
    sideways:
      kimi: 0.50
      deepseek: 0.50
    weak_downtrend:
      kimi: 0.40
      deepseek: 0.60
    strong_downtrend:
      kimi: 0.30
      deepseek: 0.70

ml_optimization:
  enabled: true
  training_interval_hours: 24
  min_samples: 100
  ab_test_enabled: true
  traffic_split: 0.2
```

---

## API 参考

### AIIntegrationManager

#### 方法

| 方法 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `update_price()` | price: float | None | 更新价格数据 |
| `analyze_market()` | market_data: Dict | MarketContext | 分析市场状态 |
| `build_prompt()` | market_data: Dict | str | 构建优化 Prompt |
| `fuse_signals()` | signals: List, market_data: Dict | Dict | 融合 AI 信号 |
| `record_signal_outcome()` | ... | None | 记录信号结果 |
| `optimize_weights()` | None | Dict | 优化 AI 权重 |
| `get_status_report()` | None | Dict | 获取状态报告 |

### OptimizedPromptBuilder

| 方法 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `build()` | market_data, context | str | 构建 Prompt |
| `_analyze_context()` | market_data | MarketContext | 分析市场 |

### EnhancedTrendDetector

| 方法 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `add_price()` | price: float | None | 添加价格 |
| `detect_trend()` | None | TrendState | 检测趋势 |
| `get_market_context()` | None | Dict | 获取上下文 |

### AdaptiveFusionStrategy

| 方法 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `fuse()` | signals, trend_context, momentum | Dict | 融合信号 |
| `update_weights()` | regime: str, weights: Dict | None | 更新权重 |

---

## 测试验证

### 运行单元测试

```bash
# 运行 ML 集成测试
pytest tests/unit/test_ml_integration.py -v

# 运行所有测试
pytest tests/ -v
```

### 手动测试

```python
from alpha_trading_bot.ai.integration import AIIntegrationManager

# 创建管理器
manager = AIIntegrationManager()

# 测试价格更新
manager.update_price(70000)
manager.update_price(70500)

# 获取状态
status = manager.get_status_report()
print(status)
```

---

## 与现有系统集成

### 修改 bot.py

```python
# 在 bot.py 中添加
from alpha_trading_bot.ai.integration import AIIntegrationManager

class TradingBot:
    def __init__(self, config):
        self.ai_manager = AIIntegrationManager()
    
    async def get_ai_signal(self, market_data):
        # 使用优化后的信号获取
        return await self.ai_manager.get_signal(market_data)
```

### 修改 config.yaml

```yaml
ai:
  use_optimized_prompt: true
  adaptive_fusion: true
  ml_optimization: true
```

---

## 监控和告警

### 获取监控摘要

```python
from alpha_trading_bot.ai.integration import AIIntegrationManager

manager = AIIntegrationManager()
summary = manager.get_monitoring_summary()
print(summary)
```

### 检查告警

```python
from alpha_trading_bot.ai.ml import AlertManager

alerts = AlertManager()
warnings = alerts.check_alerts(
    win_rate=0.35,
    loss_streak=3,
    api_failure=0.05
)
print(warnings)
```

---

## 性能优化

### 批量处理

```python
# 批量更新价格
prices = [70000, 70500, 71000, 71500]
for price in prices:
    manager.update_price(price)

# 批量分析
results = []
for data in market_data_list:
    result = manager.analyze_market(data)
    results.append(result)
```

---

## 常见问题

### Q1: 集成后信号变得更频繁?

A: 优化后的系统在趋势行情中会更敏感，但会自动调整。如果希望保持保守，可以设置 `fusion_mode: conservative`

### Q2: 如何回退到原系统?

A: 设置 `use_optimized_prompt: false` 或直接使用原有的 `prompt_builder.py`

### Q3: 权重优化需要多长时间生效?

A: 默认收集 100 个样本后开始优化，可通过 `min_samples: 100` 配置

---

## 下一步

1. 运行单元测试验证功能
2. 在测试环境运行集成
3. 监控 A/B 测试结果
4. 根据数据调整参数
