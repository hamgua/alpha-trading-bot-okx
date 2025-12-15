# AI服务商Prompts配置说明

## 当前Prompt配置

### 主交易Prompt (AIClient._build_trading_prompt)
位于: `alpha_trading_bot/ai/client.py` (第127-153行)

```python
prompt = f"""你是一个专业的加密货币交易员。请基于以下市场数据给出交易建议：

当前价格: {price}
当日最高: {high}
当日最低: {low}
成交量: {volume}

请提供：
1. 交易信号 (BUY/SELL/HOLD)
2. 信心度 (0-1)
3. 理由分析
4. 建议持仓时间

请以JSON格式回复，包含以下字段：
{{
    "signal": "BUY/SELL/HOLD",
    "confidence": 0.8,
    "reason": "分析理由",
    "holding_time": "建议持仓时间"
}}"""
```

### 基础Provider Prompt (BaseAIProvider.build_prompt)
位于: `alpha_trading_bot/ai/providers/base.py` (第31-50行)

```python
return f"""基于以下市场数据提供交易建议：

当前价格: {price}
当日最高: {high}
当日最低: {low}
成交量: {volume}

请分析并提供：
1. 交易信号 (BUY/SELL/HOLD)
2. 信心度 (0-1)
3. 分析理由

请以JSON格式回复。"""
```

## Prompt使用流程

1. **AIClient.generate_signal()** 调用 `_build_trading_prompt(market_data)` 创建提示词
2. 根据提供商类型调用不同的API方法：
   - `_call_kimi()`
   - `_call_deepseek()`
   - `_call_qwen()`
   - `_call_openai()`
3. 每个提供商将prompt发送到各自的API
4. 响应通过 `_parse_ai_response()` 解析，提取JSON格式的信号

## 当前特点

- **统一Prompt**: 所有AI提供商使用相同的prompt模板
- **中文语言**: 主要prompt使用中文
- **基础数据**: 仅使用价格、最高价、最低价、成交量
- **JSON格式**: 要求返回包含特定字段的JSON响应
- **标准字段**: signal, confidence, reason, holding_time

## 可优化方向

1. **多语言支持**: 可根据提供商特点使用不同语言
2. **更丰富的数据**: 可加入技术指标、市场趋势等
3. **个性化Prompt**: 为不同提供商定制专业prompt
4. **动态Prompt**: 根据市场条件调整prompt内容
5. **配置化**: 将prompt移至配置文件便于调整