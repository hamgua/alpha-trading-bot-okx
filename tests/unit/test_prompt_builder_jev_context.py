"""
build_prompt 的 jev_context 注入单元测试（prompt_builder.build_prompt）
"""

from alpha_trading_bot.ai.prompt_builder import build_prompt

MARKET_DATA = {
    "symbol": "BTC-USDT",
    "price": 118000.0,
    "high": 119000.0,
    "low": 116000.0,
    "volume": 12345.6,
    "change_percent": 1.2,
    "recent_drop_percent": -0.01,
    "recent_rise_percent": 0.008,
    "technical": {
        "rsi": 55.5,
        "macd": 12.3,
        "macd_histogram": 12.3456,
        "adx": 18.0,
        "atr_percent": 0.02,
        "bb_position": 0.45,
        "trend_direction": "up",
        "trend_strength": 0.25,
    },
    "position": {
        "side": "long",
        "amount": 0.05,
        "entry_price": 115000.0,
        "unrealized_pnl": 150.0,
        "pnl_percent": 2.6,
    },
    "price_history": [117000.0 + i for i in range(30)],
    "market_structure": "bullish",
    "market_structure_direction": "long",
    "risk_reward_ratio": 2.5,
    "nearest_support": 116500.0,
    "nearest_resistance": 119200.0,
    "position_size_factor": 1.0,
}


def test_none_keeps_old_behavior_exactly() -> None:
    """jev_context=None → 输出与旧版逐字节一致（回归保障）。"""
    old = build_prompt(MARKET_DATA, provider="deepseek")
    new = build_prompt(MARKET_DATA, provider="deepseek", jev_context=None)
    assert new == old
    assert "[Jev初读]" not in old


def test_jev_context_appended_at_end() -> None:
    """jev_context 追加在 prompt 末尾，原有内容逐字节保留。"""
    jev = (
        "[Jev初读] signal=buy conf=0.70 probabilities: buy=0.70; "
        "反转风险Noul=0.20; 震荡无方向Noul=0.30. "
        "以上为快速模型的初步判断，仅供参考，请以你的完整分析为准。"
    )
    without_ctx = build_prompt(MARKET_DATA, provider="deepseek")
    with_ctx = build_prompt(MARKET_DATA, provider="deepseek", jev_context=jev)
    assert with_ctx.startswith(without_ctx)  # 仅追加，不改原有内容
    assert with_ctx.endswith(jev)  # 追加在末尾


def test_jev_context_behavior_across_providers() -> None:
    """kimi/deepseek/default 各 provider 下同样保持 None→原样、有值→追加末尾。"""
    jev = "[Jev初读] x"
    for provider in ("kimi", "deepseek", "default"):
        base = build_prompt(MARKET_DATA, provider=provider)
        assert build_prompt(MARKET_DATA, provider=provider, jev_context=None) == base
        assert build_prompt(MARKET_DATA, provider=provider, jev_context=jev).endswith(
            jev
        )
