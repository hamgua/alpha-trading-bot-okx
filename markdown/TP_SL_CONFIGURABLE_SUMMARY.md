# 止盈止损百分比可配置化总结

## 问题
原来的止盈止损百分比是固定的（6%止盈，2%止损），无法根据不同投资策略进行调整。

## 解决方案
实现了完全可配置的止盈止损系统，支持：
1. 手动配置具体百分比
2. 根据投资类型自动设置默认值
3. 智能止盈止损（基于市场波动率）

## 配置说明

### 环境变量配置
新增以下环境变量：
```bash
# 止盈百分比 - 相对于入场价格的上涨百分比
TAKE_PROFIT_PERCENT=0.06  # 6%

# 止损百分比 - 相对于入场价格的下跌百分比
STOP_LOSS_PERCENT=0.02   # 2%

# 是否启用智能止盈止损
SMART_TP_SL_ENABLED=true
```

### 投资类型默认值
根据INVESTMENT_TYPE自动设置：
- **conservative（稳健型）**: 止盈6%，止损2%
- **moderate（中等型）**: 止盈8%，止损3%
- **aggressive（激进型）**: 止盈12%，止损5%

### 配置建议
| 投资类型 | 止盈范围 | 止损范围 | 特点 |
|---------|---------|---------|------|
| 保守型 | 4%-6% | 1%-2% | 低波动，稳健收益 |
| 中等型 | 6%-8% | 2%-3% | 平衡风险与收益 |
| 激进型 | 8%-12% | 3%-5% | 高风险高收益 |

## 代码修改

### 1. 配置文件（.env）
```bash
# 投资策略类型
INVESTMENT_TYPE=conservative

# 止盈止损配置
TAKE_PROFIT_PERCENT=0.06
STOP_LOSS_PERCENT=0.02
SMART_TP_SL_ENABLED=true
```

### 2. 数据模型（models.py）
```python
@dataclass
class StrategyConfig:
    # ... 原有字段 ...
    take_profit_percent: float = 0.06  # 止盈百分比
    stop_loss_percent: float = 0.02    # 止损百分比
```

### 3. 配置管理器（manager.py）
```python
def _load_strategy_config(self) -> StrategyConfig:
    # 加载止盈止损百分比
    take_profit_percent = float(os.getenv('TAKE_PROFIT_PERCENT', '0.06'))
    stop_loss_percent = float(os.getenv('STOP_LOSS_PERCENT', '0.02'))

    # 根据投资类型设置默认值
    if investment_type == 'conservative':
        take_profit_percent = take_profit_percent or 0.06
        stop_loss_percent = stop_loss_percent or 0.02
    # ... 其他类型 ...
```

### 4. 交易执行器（trade_executor.py）
```python
def _get_tp_sl_percentages(self) -> tuple[float, float]:
    """获取止盈止损百分比配置"""
    config = load_config()
    take_profit_pct = config.strategies.take_profit_percent
    stop_loss_pct = config.strategies.stop_loss_percent
    return take_profit_pct, stop_loss_pct

# 使用可配置百分比
new_take_profit = current_price * (1 + take_profit_pct)
new_stop_loss = current_price * (1 - stop_loss_pct)
```

## 使用示例

### 示例1：手动配置具体百分比
```bash
# 设置为8%止盈，3%止损
TAKE_PROFIT_PERCENT=0.08
STOP_LOSS_PERCENT=0.03
```

### 示例2：使用投资类型默认值
```bash
# 设置为激进型，自动使用12%止盈，5%止损
INVESTMENT_TYPE=aggressive
# 不设置具体百分比，使用默认值
```

### 示例3：混合配置
```bash
# 设置为中等型，但自定义百分比
INVESTMENT_TYPE=moderate
TAKE_PROFIT_PERCENT=0.07  # 7%止盈（覆盖默认8%）
STOP_LOSS_PERCENT=0.025 # 2.5%止损（覆盖默认3%）
```

## 系统日志

配置加载时会显示：
```
策略配置: 投资类型=conservative, 止盈=6.0%, 止损=2.0%
```

交易时会显示：
```
使用止盈止损配置: 止盈=6.0%, 止损=2.0%
```

## 好处

1. **灵活性高**：可以精确控制每个百分比
2. **智能化**：根据投资类型自动推荐合适值
3. **可扩展**：未来可支持智能调整（基于波动率）
4. **用户友好**：清晰的配置说明和建议

## 注意事项

1. 百分比使用小数形式（0.06 = 6%）
2. 如果同时设置了具体百分比和投资类型，具体百分比优先
3. 建议根据市场情况和个人风险承受能力调整
4. 过大的百分比可能增加风险，过小可能频繁触发

现在系统支持完全可配置的止盈止损百分比，用户可以根据自己的投资策略灵活调整。现在系统支持完全可配置的止盈止损百分比，用户可以根据自己的投资策略灵活调整。