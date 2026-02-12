# LoRA 微调方案：训练专属加密货币交易模型

> 本指南详细说明如何训练一个适用于加密货币自动交易系统的 AI 模型。

## 目录

1. [方案概述](#方案概述)
2. [环境准备](#环境准备)
3. [准备训练数据](#准备训练数据)
4. [数据格式化](#数据格式化)
5. [配置并启动 LoRA 训练](#配置并启动-lora-训练)
6. [模型测试和评估](#模型测试和评估)
7. [集成到交易系统](#集成到交易系统)
8. [持续优化](#持续优化)
9. [成本与时间估算](#成本与时间估算)

---

## 方案概述

### 为什么选择 LoRA？

LoRA（Low-Rank Adaptation）是一种参数高效的微调技术：

| 特性 | 全量微调 | LoRA 微调 |
|------|----------|-----------|
| 参数量 | 100% | 1-5% |
| 显存占用 | 高 | 低（可低至 8GB） |
| 训练速度 | 慢 | 快 |
| 保留原有能力 | 可能遗忘 | 保持 |
| 实现复杂度 | 高 | 低 |

### 推荐模型

| 模型 | 参数量 | 推理显存 | 微调显存 | 特点 |
|------|--------|----------|----------|------|
| **Qwen2.5-7B-Instruct** | 7B | 8GB | 16GB | 中文友好，效果好 |
| **Llama-3-8B-Instruct** | 8B | 8GB | 16GB | 社区活跃，英文为主 |
| **Mistral-7B-Instruct** | 7B | 8GB | 16GB | 推理速度快 |
| **Gemma-2-9B-It** | 9B | 10GB | 20GB | Google 生态 |

### 技术栈

- **PEFT**：Hugging Face 参数高效微调库
- **Unsloth**：加速训练，显存减半
- **Transformers**：模型加载和推理
- **BitsAndBytes**：8bit/4bit 量化

---

## 环境准备

### 1.1 创建虚拟环境

```bash
# 使用 Conda
conda create -n trading-llm python=3.10 -y
conda activate trading-llm

# 或使用 venv
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate  # Windows
```

### 1.2 安装依赖

```bash
# 安装 PyTorch（CUDA 11.8）
pip install torch==2.1.0 torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cu118

# 安装基础依赖
pip install transformers>=4.40.0
pip install accelerate>=0.25.0

# 安装 LoRA 相关
pip install peft>=0.10.0
pip install bitsandbytes>=0.42.0

# 安装 Unsloth（强烈推荐）
pip install unsloth[colab] @ https://github.com/unslothai/unsloth/releases/download/v0.3.4/unsloth-0.3.4-py3-none-any.whl

# 安装数据处理
pip install datasets>=2.14.0
pip install pandas numpy scikit-learn

# 验证安装
python -c "import torch; print(f'PyTorch: {torch.__version__}')"
python -c "import transformers; print(f'Transformers: {transformers.__version__}')"
python -c "import peft; print(f'PEFT: {peft.__version__}')"
python -c "import unsloth; print(f'Unsloth: {unsloth.__version__}')"
```

### 1.3 硬件要求

```bash
# 检查 GPU
nvidia-smi

# 推荐配置
# - GPU: RTX 4080 16GB 或 RTX 4090 24GB
# - 内存: 32GB RAM
# - 存储: 50GB SSD

# 验证 CUDA
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
python -c "import torch; print(f'GPU count: {torch.cuda.device_count()}')"
python -c "import torch; print(f'GPU name: {torch.cuda.get_device_name(0)}')"
```

### 1.4 项目结构

```
alpha-trading-bot-okx/
├── scripts/
│   └── training/
│       ├── prepare_data.py        # 数据收集
│       ├── convert_format.py      # 格式转换
│       ├── train_lora.py         # 训练脚本
│       ├── test_model.py          # 测试脚本
│       └── evaluate.py            # 评估脚本
├── trading-llm-lora/             # 训练输出目录
│   ├── final_lora/               # 最终模型
│   └── logs/                     # 训练日志
└── training_data/
    ├── raw/                      # 原始数据
    ├── processed/                 # 处理后数据
    ├── train_data.json           # 训练集
    ├── val_data.json             # 验证集
    └── test_data.json            # 测试集
```

---

## 准备训练数据

### 2.1 数据来源

1. **历史交易记录**：数据库中的交易日志
2. **K 线数据**：OKX API 获取的历史数据
3. **AI 信号记录**：每次 AI 分析的 market_data 和结果
4. **市场标注**：专业的交易标注

### 2.2 数据格式要求

**Instruction Tuning 格式**：

```json
{
    "instruction": "分析市场数据，给出交易建议",
    "input": "当前价格: 50000\nRSI(14): 45\nMACD: 金叉\n趋势: 上升\nATR%: 2.5%",
    "output": "BUY - 上升趋势 + RSI健康，建议买入"
}
```

**ChatML 格式**：

```json
{
    "messages": [
        {
            "role": "system",
            "content": "你是一个专业的加密货币交易助手"
        },
        {
            "role": "user",
            "content": "BTC价格50000，RSI45，MACD金叉，建议？"
        },
        {
            "role": "assistant",
            "content": "建议 BUY，置信度 75%"
        }
    ]
}
```

### 2.3 数据收集脚本

创建 `scripts/training/prepare_data.py`：

```python
"""
数据收集脚本
从交易数据库中收集训练数据
"""
import json
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Any
import pandas as pd

def collect_training_data(
    db_path: str = "trades.db",
    output_path: str = "training_data/raw/collected_data.json",
    limit: int = 1000
) -> List[Dict[str, Any]]:
    """
    从数据库收集训练数据
    
    Args:
        db_path: 数据库路径
        output_path: 输出文件路径
        limit: 最大收集条数
    
    Returns:
        训练数据列表
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        query = """
        SELECT 
            t.timestamp,
            t.symbol,
            t.entry_price,
            t.exit_price,
            t.pnl_percent,
            s.market_data,
            s.ai_signal,
            s.signal_confidence,
            t.action_taken,
            t.position_size,
            t.leverage,
            t.status
        FROM trades t
        LEFT JOIN signals s ON t.timestamp = s.timestamp
        WHERE t.pnl_percent IS NOT NULL
        AND t.status = 'closed'
        ORDER BY t.timestamp DESC
        LIMIT ?
        """
        
        cursor.execute(query, (limit,))
        records = cursor.fetchall()
        conn.close()
        
        training_data = []
        
        for record in records:
            (
                timestamp, symbol, entry_price, exit_price, pnl,
                market_data_str, ai_signal, confidence, action,
                position_size, leverage, status
            ) = record
            
            # 标记结果
            if pnl and pnl > 5:
                result_label = "盈利信号"
                result_quality = "high"
            elif pnl and pnl < -3:
                result_label = "亏损信号"
                result_quality = "low"
            elif pnl and pnl > 0:
                result_label = "小幅盈利信号"
                result_quality = "medium"
            else:
                result_label = "持平信号"
                result_quality = "medium"
            
            # 构建训练样本
            sample = {
                "timestamp": timestamp,
                "symbol": symbol,
                "instruction": f"分析{symbol}的市场数据，给出交易建议。结果标注：{result_label}",
                "input": market_data_str or "",
                "output": f"信号：{ai_signal or 'HOLD'}，置信度：{confidence or 70}%，建议操作：{action or '观察'}",
                "metadata": {
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl_percent": pnl,
                    "result_quality": result_quality,
                    "position_size": position_size,
                    "leverage": leverage
                }
            }
            training_data.append(sample)
        
        # 保存
        import os
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(training_data, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 已收集 {len(training_data)} 条训练数据")
        print(f"📁 保存至: {output_path}")
        
        return training_data
        
    except Exception as e:
        print(f"❌ 数据收集失败: {e}")
        return []


def collect_from_market_data(
    market_data_list: List[Dict[str, Any]],
    output_path: str = "training_data/raw/market_data.json"
) -> List[Dict[str, Any]]:
    """
    从实时市场数据生成训练样本
    
    Args:
        market_data_list: 市场数据列表
        output_path: 输出路径
    
    Returns:
        训练数据列表
    """
    training_data = []
    
    for market_data in market_data_list:
        technical = market_data.get("technical", {})
        price = market_data.get("price", 0)
        rsi = technical.get("rsi", 50)
        trend_dir = technical.get("trend_direction", "neutral")
        trend_strength = technical.get("trend_strength", 0)
        
        # 自动生成标注
        if rsi < 35 and trend_dir == "bullish":
            suggested_signal = "BUY"
            reason = "超卖 + 上升趋势"
        elif rsi > 65 and trend_dir == "bearish":
            suggested_signal = "SELL"
            reason = "超买 + 下降趋势"
        elif trend_dir == "bullish" and trend_strength > 0.6:
            suggested_signal = "BUY"
            reason = "强上升趋势"
        elif trend_dir == "bearish" and trend_strength > 0.6:
            suggested_signal = "SELL"
            reason = "强下降趋势"
        else:
            suggested_signal = "HOLD"
            reason = "市场震荡，建议观望"
        
        sample = {
            "instruction": f"分析{market_data.get('symbol', 'BTC')}市场数据，给出交易建议",
            "input": json.dumps(market_data, ensure_ascii=False),
            "output": f"建议：{suggested_signal}，理由：{reason}",
            "metadata": {
                "source": "auto_generated",
                "price": price,
                "rsi": rsi,
                "trend": trend_dir
            }
        }
        training_data.append(sample)
    
    # 保存
    import os
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(training_data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 已生成 {len(training_data)} 条训练数据")
    return training_data


if __name__ == "__main__":
    # 示例用法
    data = collect_training_data(
        db_path="trades.db",
        output_path="training_data/raw/collected_data.json",
        limit=500
    )
```

### 2.4 数据增强

创建 `scripts/training/augment_data.py`：

```python
"""
数据增强脚本
对已有数据进行增强，扩充数据量
"""
import json
import random
from typing import List, Dict, Any

VARIATIONS = [
    ("简洁模式", "请简洁回答"),
    ("详细模式", "请详细分析原因"),
    ("技术分析模式", "重点分析技术指标"),
    ("风险提示模式", "请包含风险提示"),
    ("新手友好模式", "请解释专业术语")
]

SIGNALS = ["BUY", "SELL", "HOLD"]

def augment_data(
    input_path: str,
    output_path: str,
    multiplier: int = 3
) -> List[Dict[str, Any]]:
    """
    数据增强
    
    Args:
        input_path: 输入文件路径
        output_path: 输出文件路径
        multiplier: 增强倍数
    
    Returns:
        增强后的数据列表
    """
    with open(input_path, 'r', encoding='utf-8') as f:
        original_data = json.load(f)
    
    augmented = []
    
    for sample in original_data:
        base_instruction = sample["instruction"]
        base_input = sample["input"]
        base_output = sample["output"]
        
        for i in range(multiplier):
            variation_type, prefix = VARIATIONS[i % len(VARIATIONS)]
            
            # 随机变换信号（保持输出一致性）
            if random.random() > 0.7:
                # 轻微修改输入格式
                new_input = f"[{variation_type}]\n{base_input}"
            else:
                new_input = base_input
            
            augmented_sample = {
                "instruction": f"{prefix} {base_instruction}",
                "input": new_input,
                "output": base_output,
                "metadata": {
                    **sample.get("metadata", {}),
                    "augmented": True,
                    "variation_type": variation_type
                }
            }
            augmented.append(augmented_sample)
    
    # 保存
    import os
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(augmented, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 增强完成: {len(original_data)} → {len(augmented)} 条")
    return augmented


def add_noise(
    input_path: str,
    output_path: str,
    noise_ratio: float = 0.1
) -> List[Dict[str, Any]]:
    """
    添加噪声数据（提高模型鲁棒性）
    
    Args:
        input_path: 输入文件路径
        output_path: 输出文件路径
        noise_ratio: 噪声比例
    """
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    noisy_data = []
    
    for sample in data:
        # 添加噪声到数值
        input_text = sample["input"]
        
        # 随机修改数值（±10%）
        import re
        def modify_number(match):
            value = float(match.group())
            noise = value * noise_ratio * (random.random() * 2 - 1)
            return str(int(value + noise))
        
        noisy_text = re.sub(r'\d+', modify_number, input_text)
        
        noisy_sample = {
            **sample,
            "input": noisy_text,
            "metadata": {
                **sample.get("metadata", {}),
                "noisy": True
            }
        }
        noisy_data.append(noisy_sample)
    
    # 保存
    import os
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(noisy_data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 噪声数据添加完成: {len(noisy_data)} 条")
    return noisy_data


if __name__ == "__main__":
    # 使用示例
    augment_data(
        "training_data/raw/collected_data.json",
        "training_data/raw/augmented_data.json",
        multiplier=3
    )
```

### 2.5 数据分割

创建 `scripts/training/split_data.py`：

```python
"""
数据分割脚本
将数据分割为训练集、验证集、测试集
"""
import json
from sklearn.model_selection import train_test_split
from typing import Tuple

def split_data(
    input_path: str,
    train_path: str,
    val_path: str,
    test_path: str,
    test_size: float = 0.2,
    val_size: float = 0.1,
    random_state: int = 42
) -> Tuple[list, list, list]:
    """
    分割数据
    
    Args:
        input_path: 输入文件路径
        train_path: 训练集输出路径
        val_path: 验证集输出路径
        test_path: 测试集输出路径
        test_size: 测试集比例
        val_size: 验证集比例（相对于非测试数据）
        random_state: 随机种子
    
    Returns:
        训练集、验证集、测试集
    """
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print(f"📊 总数据量: {len(data)} 条")
    
    # 分割
    train_data, temp_data = train_test_split(
        data,
        test_size=test_size,
        random_state=random_state
    )
    
    val_data, test_data = train_test_split(
        temp_data,
        test_size=val_size / (1 - test_size),  # 调整验证集比例
        random_state=random_state
    )
    
    # 保存
    import os
    os.makedirs(os.path.dirname(train_path), exist_ok=True)
    
    with open(train_path, 'w', encoding='utf-8') as f:
        json.dump(train_data, f, ensure_ascii=False, indent=2)
    
    with open(val_path, 'w', encoding='utf-8') as f:
        json.dump(val_data, f, ensure_ascii=False, indent=2)
    
    with open(test_path, 'w', encoding='utf-8') as f:
        json.dump(test_data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 数据分割完成:")
    print(f"   训练集: {len(train_data)} 条 ({len(train_data)/len(data)*100:.1f}%)")
    print(f"   验证集: {len(val_data)} 条 ({len(val_data)/len(data)*100:.1f}%)")
    print(f"   测试集: {len(test_data)} 条 ({len(test_data)/len(data)*100:.1f}%)")
    
    return train_data, val_data, test_data


def analyze_data_balance(
    data_path: str,
    label_key: str = "output"
) -> dict:
    """
    分析数据分布
    
    Args:
        data_path: 数据文件路径
        label_key: 标签字段
    
    Returns:
        分布统计
    """
    with open(data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 统计信号分布
    signal_counts = {"BUY": 0, "SELL": 0, "HOLD": 0}
    
    for sample in data:
        output = sample.get(label_key, "")
        if "BUY" in output:
            signal_counts["BUY"] += 1
        elif "SELL" in output:
            signal_counts["SELL"] += 1
        else:
            signal_counts["HOLD"] += 1
    
    total = len(data)
    print(f"📊 数据分布:")
    for signal, count in signal_counts.items():
        ratio = count / total * 100
        bar = "█" * int(ratio / 2)
        print(f"   {signal}: {count} ({ratio:.1f}%) {bar}")
    
    return signal_counts


if __name__ == "__main__":
    split_data(
        "training_data/raw/augmented_data.json",
        "training_data/train_data.json",
        "training_data/val_data.json",
        "training_data/test_data.json"
    )
    
    analyze_data_balance("training_data/train_data.json")
```

---

## 数据格式化

### 3.1 转换为标准格式

创建 `scripts/training/convert_format.py`：

```python
"""
数据格式转换脚本
转换为模型训练所需的格式
"""
import json
from datasets import Dataset
from typing import List, Dict, Any

def convert_to_chatml(
    data: List[Dict[str, Any]],
    system_prompt: str = None
) -> List[Dict[str, Any]]:
    """
    转换为 ChatML 格式
    
    Args:
        data: 原始数据列表
        system_prompt: 系统提示词
    
    Returns:
        ChatML 格式数据
    """
    default_system = """你是一个专业的加密货币交易助手。根据技术指标和市场数据，给出简洁明确的交易建议。

请遵循以下原则：
1. 仅给出信号：BUY / SELL / HOLD
2. 提供置信度：0-100%
3. 说明主要理由
4. 包含风险提示（如适用）"""
    
    if system_prompt is None:
        system_prompt = default_system
    
    chatml_data = []
    
    for item in data:
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"{item['instruction']}\n\n市场数据：\n{item['input']}"
            },
            {"role": "assistant", "content": item['output']}
        ]
        
        chatml_data.append({"messages": messages})
    
    return chatml_data


def convert_to_alpaca(
    data: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    转换为 Alpaca 格式
    
    Args:
        data: 原始数据列表
    
    Returns:
        Alpaca 格式数据
    """
    alpaca_data = []
    
    for item in data:
        alpaca_data.append({
            "instruction": item['instruction'],
            "input": item['input'],
            "output": item['output']
        })
    
    return alpaca_data


def convert_to_huggingface_dataset(
    data: List[Dict[str, Any]],
    format_type: str = "chatml"
) -> Dataset:
    """
    转换为 Hugging Face Dataset
    
    Args:
        data: 原始数据列表
        format_type: 格式类型 ('chatml', 'alpaca')
    
    Returns:
        Hugging Face Dataset
    """
    if format_type == "chatml":
        converted = convert_to_chatml(data)
    else:
        converted = convert_to_alpaca(data)
    
    dataset = Dataset.from_list(converted)
    return dataset


def format_with_template(
    data: List[Dict[str, Any]],
    template_name: str = "qwen"
) -> List[Dict[str, Any]]:
    """
    使用特定模板格式化数据
    
    Args:
        data: 原始数据列表
        template_name: 模板名称 ('qwen', 'llama', 'mistral')
    
    Returns:
        格式化后的数据
    """
    templates = {
        "qwen": {
            "system": "你是一个专业的加密货币交易助手。",
            "user_template": "### 分析任务\n{instruction}\n\n### 市场数据\n{input}",
            "assistant_template": "### 交易建议\n{output}"
        },
        "llama": {
            "system": "[INST] 你是一个专业的加密货币交易助手。 [/INST]",
            "user_template": "[INST] {instruction}\n\n{input} [/INST]",
            "assistant_template": "[/INST] {output} [/INST]"
        },
        "mistral": {
            "system": "<s>System: 你是一个专业的加密货币交易助手。</s>",
            "user_template": "<s>User: {instruction}\n\n{input}</s>",
            "assistant_template": "<s>Assistant: {output}</s>"
        }
    }
    
    template = templates.get(template_name, templates["qwen"])
    formatted_data = []
    
    for item in data:
        formatted = {
            "messages": [
                {"role": "system", "content": template["system"]},
                {
                    "role": "user",
                    "content": template["user_template"].format(
                        instruction=item['instruction'],
                        input=item['input']
                    )
                },
                {
                    "role": "assistant",
                    "content": template["assistant_template"].format(
                        output=item['output']
                    )
                }
            ]
        }
        formatted_data.append(formatted)
    
    return formatted_data


def apply_chat_template(
    dataset: Dataset,
    tokenizer,
    max_length: int = 2048
) -> Dataset:
    """
    应用 tokenizer 的 chat template
    
    Args:
        dataset: Hugging Face Dataset
        tokenizer: 分词器
        max_length: 最大长度
    
    Returns:
        处理后的 Dataset
    """
    def formatting_prompts_func(examples):
        texts = []
        for messages in examples["messages"]:
            text = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=False
            )
            texts.append(text)
        return {"text": texts}
    
    dataset = dataset.map(
        formatting_prompts_func,
        batched=True,
        remove_columns=["messages"]
    )
    
    # 截断过长的文本
    def truncate(example):
        if len(example["input_ids"]) > max_length:
            example["input_ids"] = example["input_ids"][:max_length]
            example["attention_mask"] = example["attention_mask"][:max_length]
        return example
    
    dataset = dataset.map(truncate)
    
    return dataset


if __name__ == "__main__":
    # 使用示例
    with open("training_data/train_data.json", 'r') as f:
        train_data = json.load(f)
    
    # 转换为 ChatML 格式
    chatml_data = convert_to_chatml(train_data)
    
    # 转换为 Dataset
    train_dataset = convert_to_huggingface_dataset(chatml_data, "chatml")
    
    print(f"✅ 数据格式化完成: {len(train_dataset)} 条")
    print(f"📝 示例:")
    print(train_dataset[0]["messages"][0])
```

### 3.2 质量检查

创建 `scripts/training/quality_check.py`：

```python
"""
数据质量检查脚本
确保训练数据质量
"""
import json
from typing import List, Dict, Any
import re

class DataQualityChecker:
    """数据质量检查器"""
    
    def __init__(self):
        self.errors = []
        self.warnings = []
    
    def check(self, data: List[Dict[str, Any]]) -> bool:
        """
        检查数据质量
        
        Args:
            data: 数据列表
        
        Returns:
            是否通过所有检查
        """
        self.errors = []
        self.warnings = []
        
        for i, sample in enumerate(data):
            self._check_sample(sample, i)
        
        # 输出检查结果
        print(f"\n📊 质量检查结果:")
        print(f"   总样本数: {len(data)}")
        print(f"   错误数: {len(self.errors)}")
        print(f"   警告数: {len(self.warnings)}")
        
        if self.errors:
            print(f"\n❌ 错误 (必须修复):")
            for error in self.errors[:10]:  # 只显示前10个
                print(f"   - {error}")
        
        if self.warnings:
            print(f"\n⚠️ 警告 (建议修复):")
            for warning in self.warnings[:10]:
                print(f"   - {warning}")
        
        return len(self.errors) == 0
    
    def _check_sample(self, sample: Dict[str, Any], index: int):
        """检查单个样本"""
        # 检查必要字段
        for field in ["instruction", "input", "output"]:
            if field not in sample:
                self.errors.append(f"[{index}] 缺少字段: {field}")
                return
        
        # 检查 instruction 长度
        if len(sample["instruction"]) < 5:
            self.warnings.append(f"[{index}] instruction 过短")
        
        # 检查 input 长度
        if len(sample["input"]) < 10:
            self.warnings.append(f"[{index}] input 过短")
        
        # 检查 output 格式
        output = sample["output"]
        if not any(signal in output for signal in ["BUY", "SELL", "HOLD"]):
            self.errors.append(f"[{index}] output 缺少有效信号: {output[:50]}...")
        
        # 检查 JSON 格式
        try:
            if sample.get("input", "").startswith("{"):
                json.loads(sample["input"])
        except json.JSONDecodeError:
            self.warnings.append(f"[{index}] input 不是有效 JSON")


def check_label_distribution(data: List[Dict[str, Any]]) -> dict:
    """
    检查标签分布
    
    Args:
        data: 数据列表
    
    Returns:
        分布统计
    """
    distribution = {"BUY": 0, "SELL": 0, "HOLD": 0}
    
    for sample in data:
        output = sample.get("output", "")
        if "BUY" in output:
            distribution["BUY"] += 1
        elif "SELL" in output:
            distribution["SELL"] += 1
        else:
            distribution["HOLD"] += 1
    
    total = len(data)
    print("\n📊 标签分布:")
    for label, count in distribution.items():
        ratio = count / total * 100
        bar = "█" * int(ratio / 2)
        print(f"   {label}: {count:4d} ({ratio:5.1f}%) {bar}")
    
    # 检查是否平衡
    max_count = max(distribution.values())
    min_count = min(distribution.values())
    balance_ratio = min_count / max_count if max_count > 0 else 0
    
    if balance_ratio < 0.3:
        print(f"\n⚠️ 警告: 数据不平衡 (比例: {balance_ratio:.2f})")
        print("   建议进行数据增强或重采样")
    
    return distribution


def remove_duplicates(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    去除重复数据
    
    Args:
        data: 数据列表
    
    Returns:
        去重后的数据列表
    """
    seen = set()
    unique_data = []
    
    for sample in data:
        # 使用 input 作为去重键
        key = sample.get("input", "")
        if key not in seen:
            seen.add(key)
            unique_data.append(sample)
    
    removed = len(data) - len(unique_data)
    print(f"\n✅ 去重完成: {removed} 条重复数据被移除")
    print(f"   原始: {len(data)} → 去重后: {len(unique_data)}")
    
    return unique_data


if __name__ == "__main__":
    with open("training_data/train_data.json", 'r') as f:
        data = json.load(f)
    
    # 质量检查
    checker = DataQualityChecker()
    checker.check(data)
    
    # 标签分布
    check_label_distribution(data)
    
    # 去重
    unique_data = remove_duplicates(data)
```

---

## 配置并启动 LoRA 训练

### 4.1 训练脚本

创建 `scripts/training/train_lora.py`：

```python
"""
LoRA 训练脚本
使用 Qwen2.5-7B-Instruct 进行微调
"""
import os
import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TrainingArguments,
    Trainer,
    DataCollatorForSeq2Seq,
    BitsAndBytesConfig
)
from peft import (
    LoraConfig,
    get_peft_model,
    TaskType,
    prepare_model_for_int8_training
)
from unsloth import UnslothModel
from datasets import load_dataset
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============ 配置参数 ============
MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"  # 或 "meta-llama/Llama-3-8B-Instruct"
OUTPUT_DIR = "./trading-llm-lora"
MAX_SEQ_LENGTH = 2048

# LoRA 参数
LORA_R = 16
LORA_ALPHA = 32
LORA_DROPOUT = 0.05
LORA_TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj"]

# 训练参数
NUM_TRAIN_EPOCHS = 3
PER_DEVICE_TRAIN_BATCH_SIZE = 2
GRADIENT_ACCUMULATION_STEPS = 4
LEARNING_RATE = 1e-4
MAX_STEPS = 1000
EVAL_STEPS = 50
SAVE_STEPS = 100
LOGGING_STEPS = 10


def print_model_info(model):
    """打印模型信息"""
    trainable_params = 0
    all_params = 0
    
    for _, param in model.named_parameters():
        num_params = param.numel()
        all_params += num_params
        if param.requires_grad:
            trainable_params += num_params
    
    print(f"\n{'='*50}")
    print(f"模型参数统计:")
    print(f"  总参数: {all_params:,}")
    print(f"  可训练参数: {trainable_params:,}")
    print(f"  训练比例: {trainable_params/all_params*100:.2f}%")
    print(f"{'='*50}\n")


def main():
    """主函数"""
    
    # 1. 加载模型和分词器
    logger.info("正在加载模型...")
    
    model, tokenizer = UnslothModel.from_pretrained(
        MODEL_NAME,
        max_seq_length=MAX_SEQ_LENGTH,
        dtype=torch.float16,  # 或 torch.bfloat16
        load_in_4bit=True,    # 4bit 量化
    )
    
    logger.info(f"✅ 模型加载完成: {MODEL_NAME}")
    logger.info(f"   序列长度: {MAX_SEQ_LENGTH}")
    
    # 2. 配置 LoRA
    logger.info("正在配置 LoRA...")
    
    lora_config = LoraConfig(
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        target_modules=LORA_TARGET_MODULES,
        lora_dropout=LORA_DROPOUT,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )
    
    model = get_peft_model(model, lora_config)
    
    print_model_info(model)
    
    # 3. 加载数据集
    logger.info("正在加载数据集...")
    
    train_dataset = load_dataset("json", data_files="training_data/train_data.json", split="train")
    val_dataset = load_dataset("json", data_files="training_data/val_data.json", split="train")
    
    logger.info(f"✅ 训练集: {len(train_dataset)} 条")
    logger.info(f"✅ 验证集: {len(val_dataset)} 条")
    
    # 4. 格式化数据
    logger.info("正在格式化数据...")
    
    def formatting_prompts_func(examples):
        texts = []
        for messages in examples["messages"]:
            text = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=False
            )
            texts.append(text)
        return {"text": texts}
    
    train_dataset = train_dataset.map(
        formatting_prompts_func,
        batched=True,
        remove_columns=["messages"]
    )
    
    val_dataset = val_dataset.map(
        formatting_prompts_func,
        batched=True,
        remove_columns=["messages"]
    )
    
    # 5. 配置训练参数
    logger.info("正在配置训练参数...")
    
    training_args = TrainingArguments(
        output_dir=OUTPUT_DIR,
        num_train_epochs=NUM_TRAIN_EPOCHS,
        per_device_train_batch_size=PER_DEVICE_TRAIN_BATCH_SIZE,
        per_device_eval_batch_size=2,
        gradient_accumulation_steps=GRADIENT_ACCUMULATION_STEPS,
        learning_rate=LEARNING_RATE,
        weight_decay=0.01,
        warmup_steps=10,
        max_steps=MAX_STEPS,
        logging_steps=LOGGING_STEPS,
        eval_steps=EVAL_STEPS,
        save_steps=SAVE_STEPS,
        eval_strategy="steps",
        save_strategy="steps",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        report_to="tensorboard",
        fp16=True,  # 混合精度
        optim="adamw_8bit",  # 8bit 优化器
        lr_scheduler_type="linear",
        save_total_limit=3,  # 最多保存3个checkpoint
    )
    
    # 6. 创建 DataCollator
    data_collator = DataCollatorForSeq2Seq(
        tokenizer=tokenizer,
        padding=True,
        return_tensors="pt"
    )
    
    # 7. 创建 Trainer
    logger.info("正在创建 Trainer...")
    
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        data_collator=data_collator,
    )
    
    # 8. 开始训练
    logger.info("\n" + "="*50)
    logger.info("🚀 开始训练...")
    logger.info("="*50)
    
    train_result = trainer.train()
    
    # 输出训练结果
    metrics = train_result.metrics
    logger.info(f"\n📊 训练完成:")
    logger.info(f"   总步数: {metrics['train_steps']}")
    logger.info(f"   最终损失: {metrics['train_loss']:.4f}")
    logger.info(f"   学习率: {training_args.learning_rate}")
    
    # 9. 保存模型
    logger.info("\n正在保存模型...")
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    model.save_pretrained(f"{OUTPUT_DIR}/final_lora")
    tokenizer.save_pretrained(f"{OUTPUT_DIR}/final_lora")
    
    # 保存训练配置
    config_info = {
        "model_name": MODEL_NAME,
        "lora_r": LORA_R,
        "lora_alpha": LORA_ALPHA,
        "max_seq_length": MAX_SEQ_LENGTH,
        "train_samples": len(train_dataset),
        "eval_samples": len(val_dataset),
        "final_loss": metrics.get('train_loss'),
    }
    
    with open(f"{OUTPUT_DIR}/config.json", 'w') as f:
        json.dump(config_info, f, indent=2)
    
    logger.info(f"\n✅ 训练完成！")
    logger.info(f"📁 模型保存在: {OUTPUT_DIR}/final_lora")
    logger.info(f"📊 训练日志: tensorboard --logdir {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
```

### 4.2 启动训练

```bash
# 设置环境变量（可选，提升稳定性）
export CUDA_VISIBLE_DEVICES=0
export TOKENIZERS_PARALLELISM=false

# 创建输出目录
mkdir -p trading-llm-lora

# 启动训练
python scripts/training/train_lora.py
```

### 4.3 显存优化配置

如果遇到显存不足问题，修改 `train_lora.py` 中的配置：

```python
# 方案1：更激进的量化
load_in_4bit=True   # 4bit 量化（更省显存）
load_in_8bit=False

# 方案2：减小序列长度
MAX_SEQ_LENGTH = 1024  # 从 2048 降到 1024

# 方案3：减小 batch size
PER_DEVICE_TRAIN_BATCH_SIZE = 1  # 从 2 降到 1

# 方案4：增大梯度累积
GRADIENT_ACCUMULATION_STEPS = 8  # 从 4 增到 8

# 方案5：使用 DeepSpeed ZeRO（高级）
# 在命令行添加
# deepspeed --num_gpus=2 scripts/training/train_lora.py
```

### 4.4 监控训练

```bash
# 终端1：启动训练
python scripts/training/train_lora.py

# 终端2：监控显存
nvidia-smi -l 1

# 终端3：使用 TensorBoard
pip install tensorboard
tensorboard --logdir ./trading-llm-lora --port 6006
```

---

## 模型测试和评估

### 5.1 推理测试

创建 `scripts/training/test_model.py`：

```python
"""
模型测试脚本
测试训练好的模型效果
"""
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel
import json
from typing import Dict, List, Any

# 配置
MODEL_PATH = "./trading-llm-lora/final_lora"
BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"

def load_model():
    """加载训练好的模型"""
    print("正在加载模型...")
    
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    
    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.float16,
        load_in_4bit=True,
        device_map="auto",
    )
    
    model = PeftModel.from_pretrained(base_model, MODEL_PATH)
    
    print("✅ 模型加载完成")
    return model, tokenizer


def build_prompt(market_data: Dict[str, Any]) -> str:
    """构建提示词"""
    technical = market_data.get("technical", {})
    
    prompt = f"""你是专业的加密货币交易助手。

当前市场数据：
- 交易对：{market_data.get('symbol', 'BTC/USDT')}
- 当前价格：{market_data.get('price', 0)}
- 24h涨跌幅：{market_data.get('change_percent', 0)}%
- RSI(14)：{technical.get('rsi', 50)}
- MACD状态：{technical.get('macd_state', 'normal')}
- 趋势方向：{technical.get('trend_direction', 'neutral')}
- 趋势强度：{technical.get('trend_strength', 0)}
- ATR%：{technical.get('atr_percent', 0)}
- 价格位置：{technical.get('bb_position', 0)}%

请分析以上数据，给出交易信号（仅限：BUY / SELL / HOLD），并说明理由。"""
    
    return prompt


def generate_signal(model, tokenizer, market_data: Dict[str, Any]) -> Dict[str, Any]:
    """生成交易信号"""
    
    prompt = build_prompt(market_data)
    
    messages = [{"role": "user", "content": prompt}]
    
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True
    )
    
    inputs = tokenizer([text], return_tensors="pt").to(model.device)
    
    outputs = model.generate(
        **inputs,
        max_new_tokens=256,
        temperature=0.1,  # 低温度，更稳定的输出
        top_p=0.9,
        do_sample=False,  # 交易场景用 greedy
    )
    
    response = tokenizer.decode(
        outputs[0],
        skip_special_tokens=True
    )
    
    # 解析结果
    full_response = response
    
    # 提取 assistant 部分
    if "assistant" in response:
        signal_text = response.split("assistant")[-1].strip()
    else:
        signal_text = response
    
    # 提取信号
    signal = "HOLD"
    if "BUY" in signal_text.upper() and "SELL" not in signal_text.upper():
        signal = "BUY"
    elif "SELL" in signal_text.upper():
        signal = "SELL"
    
    # 提取置信度
    confidence = 70
    import re
    match = re.search(r'(\d+)%?', signal_text)
    if match:
        confidence = min(100, max(0, int(match.group(1))))
    
    return {
        "signal": signal,
        "confidence": confidence,
        "full_response": signal_text,
        "market_data": market_data
    }


def test_on_samples(model, tokenizer, test_data_path: str):
    """在测试集上测试"""
    
    with open(test_data_path, 'r') as f:
        test_data = json.load(f)
    
    print(f"\n📊 测试样本数: {len(test_data)}")
    
    correct = 0
    results = []
    
    for i, sample in enumerate(test_data[:50]):  # 测试前50条
        # 解析 market_data
        market_data = json.loads(sample["input"])
        
        result = generate_signal(model, tokenizer, market_data)
        
        # 对比预期
        expected = sample["output"]
        actual = result["signal"]
        
        is_correct = expected.split()[0] == actual
        if is_correct:
            correct += 1
        
        results.append({
            "expected": expected,
            "actual": result,
            "correct": is_correct
        })
        
        print(f"[{i+1}] 预期: {expected.split()[0]:4s} | 实际: {actual:4s} | {'✅' if is_correct else '❌'}")
    
    accuracy = correct / min(50, len(test_data))
    print(f"\n📊 测试准确率: {accuracy:.2%} ({correct}/{min(50, len(test_data))})")
    
    return accuracy, results


def interactive_test(model, tokenizer):
    """交互式测试"""
    
    print("\n" + "="*50)
    print("🧪 交互式测试")
    print("="*50)
    print("输入市场数据（JSON格式），输入 q 退出\n")
    
    while True:
        user_input = input("市场数据 (JSON): ").strip()
        
        if user_input.lower() == 'q':
            break
        
        try:
            market_data = json.loads(user_input)
            result = generate_signal(model, tokenizer, market_data)
            print(f"\n📤 结果:")
            print(f"   信号: {result['signal']}")
            print(f"   置信度: {result['confidence']}%")
            print(f"   详细: {result['full_response'][:200]}...")
            print()
        except json.JSONDecodeError:
            print("❌ JSON 格式错误\n")


if __name__ == "__main__":
    model, tokenizer = load_model()
    
    # 自动测试
    accuracy, results = test_on_samples(
        model, tokenizer,
        "training_data/test_data.json"
    )
    
    # 交互式测试（可选）
    # interactive_test(model, tokenizer)
```

### 5.2 对比测试

创建 `scripts/training/compare_models.py`：

```python
"""
模型对比脚本
对比原始模型和微调后模型的效果
"""
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel
import json
from typing import Dict, List

BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"
FINETUNED_PATH = "./trading-llm-lora/final_lora"

def load_base_model():
    """加载原始模型"""
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.float16,
        load_in_4bit=True,
        device_map="auto",
    )
    return model, tokenizer

def load_finetuned_model():
    """加载微调后模型"""
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.float16,
        load_in_4bit=True,
        device_map="auto",
    )
    model = PeftModel.from_pretrained(base_model, FINETUNED_PATH)
    return model, tokenizer

def generate(model, tokenizer, prompt: str) -> str:
    """生成响应"""
    messages = [{"role": "user", "content": prompt}]
    
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True
    )
    
    inputs = tokenizer([text], return_tensors="pt").to(model.device)
    
    outputs = model.generate(
        **inputs,
        max_new_tokens=200,
        temperature=0.1,
        do_sample=False,
    )
    
    response = tokenizer.decode(outputs[0], skip_special_tokens=True)
    
    if "assistant" in response:
        return response.split("assistant")[-1].strip()
    return response

def compare():
    """对比两个模型"""
    
    print("正在加载模型...")
    base_model, base_tokenizer = load_base_model()
    finetuned_model, finetuned_tokenizer = load_finetuned_model()
    
    # 测试问题
    test_cases = [
        {
            "name": "正常上涨趋势",
            "market_data": {
                "symbol": "BTC/USDT",
                "price": 52000,
                "change_percent": 2.5,
                "technical": {
                    "rsi": 55,
                    "trend_direction": "bullish",
                    "trend_strength": 0.7,
                    "atr_percent": 0.025
                }
            }
        },
        {
            "name": "超卖反弹",
            "market_data": {
                "symbol": "BTC/USDT",
                "price": 48000,
                "change_percent": -3.5,
                "technical": {
                    "rsi": 28,
                    "trend_direction": "bullish",
                    "trend_strength": 0.4,
                    "atr_percent": 0.035
                }
            }
        },
        {
            "name": "高位震荡",
            "market_data": {
                "symbol": "BTC/USDT",
                "price": 58000,
                "change_percent": 0.5,
                "technical": {
                    "rsi": 68,
                    "trend_direction": "neutral",
                    "trend_strength": 0.3,
                    "atr_percent": 0.02
                }
            }
        }
    ]
    
    print("\n" + "="*70)
    print("🔍 模型对比测试")
    print("="*70)
    
    for case in test_cases:
        print(f"\n📌 测试场景: {case['name']}")
        print("-"*70)
        
        prompt = f"""分析以下市场数据，给出交易建议。

价格: {case['market_data']['price']}
趋势: {case['market_data']['technical']['trend_direction']}
强度: {case['market_data']['technical']['trend_strength']}
RSI: {case['market_data']['technical']['rsi']}"""

        # 原始模型
        base_response = generate(base_model, base_tokenizer, prompt)
        print(f"原始模型:\n{base_response[:300]}...")
        print()
        
        # 微调模型
        finetuned_response = generate(finetuned_model, finetuned_tokenizer, prompt)
        print(f"微调模型:\n{finetuned_response[:300]}...")
        print()
    
    print("="*70)
    print("✅ 对比测试完成")


if __name__ == "__main__":
    compare()
```

---

## 集成到交易系统

### 6.1 创建本地模型提供商

在 `alpha_trading_bot/ai/` 目录下创建 `local_provider.py`：

```python
"""
本地微调模型提供商
集成训练好的 LoRA 模型到交易系统
"""
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel
from typing import Dict, Any, Optional, Tuple
import logging
import re

logger = logging.getLogger(__name__)


class LocalLLMProvider:
    """本地微调模型提供商"""
    
    def __init__(
        self,
        model_path: str,
        base_model_name: str = "Qwen/Qwen2.5-7B-Instruct",
        device: str = "auto",
        system_prompt: str = None
    ):
        """
        初始化本地模型提供商
        
        Args:
            model_path: LoRA 模型路径
            base_model_name: 基础模型名称
            device: 设备 ("auto", "cuda", "cpu")
            system_prompt: 系统提示词
        """
        self.model_path = model_path
        self.base_model_name = base_model_name
        self.system_prompt = system_prompt or self._default_system_prompt()
        
        logger.info(f"[LocalLLM] 正在加载模型: {model_path}")
        
        # 加载分词器
        self.tokenizer = AutoTokenizer.from_pretrained(base_model_name)
        
        # 加载模型
        self.model = AutoModelForCausalLM.from_pretrained(
            base_model_name,
            torch_dtype=torch.float16,
            load_in_4bit=True,
            device_map=device,
        )
        
        # 加载 LoRA 适配器
        self.model = PeftModel.from_pretrained(self.model, model_path)
        
        logger.info(f"[LocalLLM] ✅ 模型加载完成")
    
    def _default_system_prompt(self) -> str:
        """默认系统提示词"""
        return """你是一个专业的加密货币交易助手。根据技术指标和市场数据，给出简洁明确的交易建议。

请遵循以下格式回复：
1. 信号：BUY / SELL / HOLD
2. 置信度：0-100%
3. 主要理由（1-2句话）
4. 风险提示（如适用）"""
    
    async def get_signal(
        self,
        market_data: Dict[str, Any],
        api_key: str = ""
    ) -> Tuple[str, int]:
        """
        生成交易信号
        
        Args:
            market_data: 市场数据
            api_key: API密钥（本地模型不需要）
        
        Returns:
            (signal, confidence): 信号和置信度
        """
        try:
            prompt = self._build_prompt(market_data)
            
            # 生成
            response = self._generate(prompt)
            
            # 解析
            signal = self._parse_signal(response)
            confidence = self._extract_confidence(response)
            
            logger.info(f"[LocalLLM] 信号: {signal}, 置信度: {confidence}%")
            
            return signal, confidence
            
        except Exception as e:
            logger.error(f"[LocalLLM] 生成信号失败: {e}")
            return "HOLD", 50  # 默认返回 HOLD
    
    def _build_prompt(self, market_data: Dict[str, Any]) -> str:
        """构建提示词"""
        technical = market_data.get("technical", {})
        
        return f"""{self.system_prompt}

当前市场数据：
- 交易对：{market_data.get('symbol', 'BTC/USDT')}
- 当前价格：{market_data.get('price', 0)}
- 24h涨跌幅：{market_data.get('change_percent', 0)}%
- RSI(14)：{technical.get('rsi', 50)}
- MACD：{technical.get('macd_state', 'normal')}
- 趋势方向：{technical.get('trend_direction', 'neutral')}
- 趋势强度：{technical.get('trend_strength', 0)}
- ATR%：{technical.get('atr_percent', 0)}
- 价格布林带位置：{technical.get('bb_position', 0)}%"""
    
    def _generate(self, prompt: str) -> str:
        """生成响应"""
        messages = [{"role": "user", "content": prompt}]
        
        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )
        
        inputs = self.tokenizer([text], return_tensors="pt").to(self.model.device)
        
        outputs = self.model.generate(
            **inputs,
            max_new_tokens=256,
            temperature=0.1,
            top_p=0.9,
            do_sample=False,
        )
        
        response = self.tokenizer.decode(
            outputs[0],
            skip_special_tokens=True
        )
        
        # 提取 assistant 部分
        if "assistant" in response:
            return response.split("assistant")[-1].strip()
        return response
    
    def _parse_signal(self, response: str) -> str:
        """解析信号"""
        response_upper = response.upper()
        
        if "BUY" in response_upper and "SELL" not in response_upper:
            return "BUY"
        elif "SELL" in response_upper:
            return "SELL"
        else:
            return "HOLD"
    
    def _extract_confidence(self, response: str) -> int:
        """提取置信度"""
        match = re.search(r'(\d+)%?', response)
        if match:
            return min(100, max(0, int(match.group(1))))
        return 70  # 默认置信度
    
    def batch_generate(
        self,
        market_data_list: List[Dict[str, Any]]
    ) -> List[Tuple[str, int]]:
        """
        批量生成信号
        
        Args:
            market_data_list: 市场数据列表
        
        Returns:
            信号列表
        """
        results = []
        
        for market_data in market_data_list:
            signal, confidence = self.get_signal(market_data)
            results.append((signal, confidence))
        
        return results


# 使用示例
if __name__ == "__main__":
    import asyncio
    
    provider = LocalLLMProvider(
        model_path="./trading-llm-lora/final_lora",
        base_model_name="Qwen/Qwen2.5-7B-Instruct"
    )
    
    market_data = {
        "symbol": "BTC/USDT",
        "price": 50000,
        "change_percent": 2.5,
        "technical": {
            "rsi": 45,
            "trend_direction": "bullish",
            "trend_strength": 0.65,
            "atr_percent": 0.025,
            "bb_position": 50
        }
    }
    
    signal, confidence = asyncio.run(provider.get_signal(market_data))
    print(f"信号: {signal}, 置信度: {confidence}%")
```

### 6.2 更新配置

更新 `alpha_trading_bot/ai/providers.py`：

```python
"""
AI提供商配置
"""

PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-chat",
        "type": "remote",
    },
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1/chat/completions",
        "model": "moonshot-v1-8k",
        "type": "remote",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o-mini",
        "type": "remote",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-turbo",
        "type": "remote",
    },
    # 本地模型
    "local_trading": {
        "type": "local",
        "model_path": "./trading-llm-lora/final_lora",
        "base_model": "Qwen/Qwen2.5-7B-Instruct",
        "description": "本地微调交易模型",
    },
}


def get_provider_config(provider: str) -> dict:
    """获取提供商配置"""
    return PROVIDERS.get(provider, PROVIDERS["deepseek"])
```

### 6.3 更新 AI 客户端

更新 `alpha_trading_bot/ai/client.py` 中的 `_get_single_signal` 方法：

```python
class AIClient:
    # ... 其他代码 ...
    
    async def _get_single_signal(self, market_data: Dict[str, Any]) -> str:
        """单AI模式"""
        provider = self.config.default_provider
        provider_config = get_provider_config(provider)
        
        # 判断是否本地模型
        if provider_config.get("type") == "local":
            # 导入本地模型提供商
            from .local_provider import LocalLLMProvider
            
            if not hasattr(self, '_local_provider'):
                self._local_provider = LocalLLMProvider(
                    model_path=provider_config["model_path"],
                    base_model_name=provider_config["base_model"],
                )
            
            signal, confidence = await self._local_provider.get_signal(market_data)
            
            logger.info(f"[AI] 本地模型: {signal} (置信度: {confidence}%)")
            
            return signal
        
        # 远程API调用（原有逻辑）
        api_key = self.api_keys.get(provider, "")
        response = await self._call_ai_with_retry(provider, market_data, api_key)
        signal, confidence = parse_response(response)
        
        return signal
```

---

## 持续优化

### 7.1 增量训练

当积累新数据后，可以增量训练：

```python
# scripts/training/incremental_train.py

def incremental_train(
    new_data_path: str,
    base_model_path: str,
    output_path: str,
    learning_rate: float = 5e-5
):
    """
    增量训练
    
    Args:
        new_data_path: 新数据路径
        base_model_path: 基础模型路径
        output_path: 输出路径
        learning_rate: 学习率（比初始训练小）
    """
    from unsloth import UnslothModel
    from transformers import TrainingArguments, Trainer
    from datasets import load_dataset
    
    # 加载模型
    model, tokenizer = UnslothModel.from_pretrained(
        base_model_path,
        max_seq_length=2048,
        dtype=torch.float16,
        load_in_4bit=True,
    )
    
    # 加载新数据
    dataset = load_dataset("json", data_files=new_data_path, split="train")
    
    # 格式化
    def formatting_prompts_func(examples):
        texts = []
        for messages in examples["messages"]:
            text = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=False
            )
            texts.append(text)
        return {"text": texts}
    
    dataset = dataset.map(
        formatting_prompts_func,
        batched=True,
        remove_columns=["messages"]
    )
    
    # 训练参数（更小的学习率）
    training_args = TrainingArguments(
        output_dir=output_path,
        num_train_epochs=2,
        per_device_train_batch_size=2,
        learning_rate=learning_rate,
        fp16=True,
        optim="adamw_8bit",
    )
    
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
    )
    
    trainer.train()
    
    # 保存
    model.save_pretrained(output_path)
    tokenizer.save_pretrained(output_path)
    
    print(f"✅ 增量训练完成: {output_path}")


if __name__ == "__main__":
    incremental_train(
        new_data_path="training_data/new_data.json",
        base_model_path="./trading-llm-lora/final_lora",
        output_path="./trading-llm-lora/v2",
        learning_rate=5e-5
    )
```

### 7.2 模型评估指标

建议监控以下指标：

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 信号准确率 | > 60% | 预测正确的比例 |
| 盈利信号比例 | > 55% | BUY/SELL 信号的盈利比例 |
| 平均置信度 | 60-80% | 置信度不宜过低或过高 |
| 响应延迟 | < 2秒 | 单次推理时间 |

### 7.3 A/B 测试

```python
# scripts/training/ab_test.py

def ab_test(provider_a: str, provider_b: str, test_data_path: str):
    """
    A/B 测试两个模型/提供商
    
    Args:
        provider_a: 提供商A标识
        provider_b: 提供商B标识
        test_data_path: 测试数据路径
    """
    # 实现两个模型的对比测试
    # 记录准确率、延迟、盈利信号比例等
    pass
```

---

## 成本与时间估算

### 硬件要求

| 配置 | 显存 | 训练时间 | 成本/小时 |
|------|------|----------|----------|
| RTX 4090 24GB | 16GB | 2-4小时 | $0.5-1 |
| RTX 4080 16GB | 12GB | 3-5小时 | $0.4-0.8 |
| A100 40GB | 32GB | 1-2小时 | $1-2 |
| Google Colab Pro | 16GB | 4-8小时 | $10/月 |

### 时间规划

| 阶段 | 时间 | 说明 |
|------|------|------|
| 环境准备 | 30分钟 | 安装依赖 |
| 数据收集 | 2-4小时 | 收集和标注 |
| 数据格式化 | 1小时 | 格式转换 |
| 训练 | 2-4小时 | LoRA微调 |
| 测试 | 1小时 | 效果验证 |
| 集成 | 1小时 | 接入系统 |
| **总计** | **8-12小时** | - |

### 成本估算

| 项目 | 费用 |
|------|------|
| GPU租用（RTX 4090，4小时） | $2-4 |
| 云存储 | $1-2/月 |
| API调用（测试时） | $0-5 |
| **总计** | **$5-10** |

---

## 快速启动清单

- [ ] 安装 Python 3.10+ 和 CUDA
- [ ] 创建 conda/venv 虚拟环境
- [ ] 安装 PEFT、Unsloth、Transformers
- [ ] 准备 300+ 条标注数据
- [ ] 运行 `python scripts/training/prepare_data.py`
- [ ] 运行 `python scripts/training/split_data.py`
- [ ] 运行 `python scripts/training/train_lora.py`
- [ ] 运行 `python scripts/training/test_model.py`
- [ ] 集成到交易系统
- [ ] 小资金实盘测试 1-2 周

---

## 常见问题

### Q1: 显存不足怎么办？

A: 修改以下配置：
```python
load_in_4bit=True  # 4bit量化
MAX_SEQ_LENGTH = 1024  # 减小序列长度
PER_DEVICE_TRAIN_BATCH_SIZE = 1  # 减小batch size
```

### Q2: 训练loss不下降怎么办？

A: 检查：
1. 数据质量是否OK
2. 学习率是否合适（尝试 1e-4 或 5e-4）
3. 数据是否正确格式化

### Q3: 模型输出不稳定怎么办？

A: 推理时使用：
```python
temperature=0.1  # 低温度
do_sample=False  # greedy解码
```

### Q4: 如何提高准确率？

A:
1. 增加高质量训练数据
2. 使用更好的标注
3. 尝试更大的模型（如 14B）
4. 调整 LoRA 参数

---

## 参考资源

- [PEFT 文档](https://huggingface.co/docs/peft)
- [Unsloth GitHub](https://github.com/unslothai/unsloth)
- [Qwen2.5-Instruct](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct)
- [Llama-3-Instruct](https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct)
- [Hugging Face 微调指南](https://huggingface.co/docs/transformers/en/training)

---

> **免责声明**: 本模型仅供学习和研究使用，不构成投资建议。加密货币交易存在高风险，请谨慎决策。
