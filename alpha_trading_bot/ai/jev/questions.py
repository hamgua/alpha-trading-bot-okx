"""
Jev 问题集与市场状态序列化

- build_state: 把 market_data 序列化成紧凑结构化 state（目标 400-600 tokens；
  Jev 按 input token 计费，保持精简）
- JEV_QUESTIONS: 1 个主 Choice + 2 个辅助 Noul（官方最佳实践：一次请求问全、
  每个问题原子化；辅助问题只用于路由/上下文，不直接产生交易信号）

问题文案集中在此文件，便于按 shadow 观察结果迭代调参。
"""

from typing import Any, Dict, List

from .typesafe_client import JevChoiceQuestion, JevNoulQuestion, JevQuestion

# 主问题：四选项对齐 response_parser.VALID_SIGNALS
TRADE_DECISION = JevChoiceQuestion(
    instructions=(
        "根据当前加密货币市场状态（价格、技术指标、趋势、持仓），"
        "判断最合适的交易方向。仅基于数据判断，无明确优势时选 hold。"
    ),
    criteria={
        "buy": "趋势与技术指标支持做多入场（明确的上行结构与动能）",
        "hold": "无明确交易优势，趋势不明或信号不足，建议观望",
        "sell": "趋势与指标支持平多/减仓（上行结构破坏）",
        "short": "明确的看空结构，支持做空入场（下行动能持续）",
    },
)

# 安全旗标：反转风险（超过 risk_noul_gate → 强制升级 LLM）
IS_HIGH_RISK_REVERSAL = JevNoulQuestion(
    instructions=(
        "当前价格行为暗示即将发生急涨或急跌的反转风险"
        "（极端超买/超卖、剧烈插针、急速拉升等异常波动）"
    ),
)

# 上下文旗标：震荡无方向（升级 LLM 时的参考上下文）
IS_CHOPPY_NO_EDGE = JevNoulQuestion(
    instructions="市场处于无明确方向的震荡行情，缺乏交易优势",
)

JEV_QUESTIONS: Dict[str, JevQuestion] = {
    "trade_decision": TRADE_DECISION,
    "is_high_risk_reversal": IS_HIGH_RISK_REVERSAL,
    "is_choppy_no_edge": IS_CHOPPY_NO_EDGE,
}

# state 中输出的技术指标键（按优先级；macd_hist 与 macd_histogram 去重）
_TECH_KEYS = (
    "rsi",
    "macd",
    "macd_hist",
    "macd_histogram",
    "trend_direction",
    "trend_strength",
    "adx",
    "atr_percent",
    "bb_position",
)

# 持仓上下文中值得输出的键（bot.py 注入的 position 结构可能更大）
_POSITION_KEYS = (
    "side",
    "position_side",
    "amount",
    "size",
    "entry_price",
    "avg_entry_price",
    "pnl",
    "unrealized_pnl",
)


def _fmt(value: Any) -> str:
    """格式化单个指标值（float 用 .4g 精简）。"""
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def build_state(market_data: Dict[str, Any]) -> str:
    """
    把市场快照序列化成 Jev 的紧凑 state 文本。

    只取已有键，缺失键跳过不报错（上游数据服务可能不含 position/technical）。

    Args:
        market_data: AIClient.get_signal 接收的市场数据 dict

    Returns:
        紧凑结构化文本（每行一个信息块）
    """
    lines: List[str] = []

    symbol = market_data.get("symbol", "UNKNOWN")
    price = market_data.get("price", 0)
    lines.append(f"交易对: {symbol}")
    lines.append(
        f"价格: {price} | 24h高低: {market_data.get('high', 0)}/"
        f"{market_data.get('low', 0)} | 24h涨跌: "
        f"{market_data.get('change_percent', 0)}% | 成交量: "
        f"{market_data.get('volume', 0)}"
    )

    technical = market_data.get("technical") or {}
    parts: List[str] = []
    emitted_macd_hist = False
    for key in _TECH_KEYS:
        if key not in technical:
            continue
        if key == "macd_histogram" and emitted_macd_hist:
            continue  # macd_hist 与 macd_histogram 同指标，只取前者
        if key == "macd_hist":
            emitted_macd_hist = True
        parts.append(f"{key}={_fmt(technical[key])}")
    if parts:
        lines.append("技术指标: " + ", ".join(parts))

    for key, label in (
        ("recent_drop_percent", "最新跌幅"),
        ("short_term_drop_percent", "短期跌幅"),
        ("short_term_rise_percent", "短期涨幅"),
    ):
        value = market_data.get(key)
        if value is not None:
            lines.append(f"{label}: {value}%")

    position = market_data.get("position")
    if isinstance(position, dict) and position:
        pos_parts = [
            f"{key}={_fmt(position[key])}" for key in _POSITION_KEYS if key in position
        ]
        if pos_parts:
            lines.append("持仓: " + ", ".join(pos_parts))

    history = market_data.get("price_history") or []
    if isinstance(history, (list, tuple)) and history:
        recent = [float(p) for p in history[-20:] if isinstance(p, (int, float))]
        if recent:
            lines.append("近20根收盘价: " + " ".join(f"{p:g}" for p in recent))

    return "\n".join(lines)
