"""
prompt_builder Jev 初读注入单元测试
"""

from alpha_trading_bot.ai.prompt_builder import PromptBuilder, build_prompt

MARKET_DATA = {
    "symbol": "BTC-USDT",
    "price": 118000.0,
    "technical": {
        "rsi": 55,
        "macd_hist": 1.0,
        "trend_direction": "up",
        "trend_strength": 0.2,
    },
}

JEV_CONTEXT = (
    "[Jev初读] 倾向=BUY (置信 0.62) 分布: buy=0.45 hold=0.35\n"
    "          反转风险=0.31 震荡无方向=0.60\n"
    "          快车道置信度不足未能直接决策，请基于完整市场数据独立判断，不必与初读一致。"
)


def test_none_context_prompt_unchanged() -> None:
    """jev_context=None：输出与旧行为一致（无初读小节）。"""
    base = PromptBuilder.build(MARKET_DATA, "default")
    with_none = PromptBuilder.build(MARKET_DATA, "default", jev_context=None)
    assert base == with_none
    assert "快速模型初读" not in base


def test_jev_context_appended_section() -> None:
    """jev_context 非空：prompt 尾部追加初读小节，原内容不变（前缀一致）。"""
    base = PromptBuilder.build(MARKET_DATA, "default")
    prompt = PromptBuilder.build(MARKET_DATA, "default", jev_context=JEV_CONTEXT)
    assert prompt.startswith(base)
    assert "## 快速模型初读（仅供参考，请独立判断）" in prompt
    assert "[Jev初读]" in prompt


def test_convenience_function_forwards_context() -> None:
    """便捷函数 build_prompt 透传 jev_context；provider 参数不受影响。"""
    prompt = build_prompt(MARKET_DATA, provider="default", jev_context=JEV_CONTEXT)
    assert "[Jev初读]" in prompt
    plain = build_prompt(MARKET_DATA)
    assert "快速模型初读" not in plain
    for provider in ("kimi", "deepseek", "default"):
        base = build_prompt(MARKET_DATA, provider=provider)
        assert build_prompt(MARKET_DATA, provider=provider, jev_context=None) == base
        assert build_prompt(
            MARKET_DATA, provider=provider, jev_context=JEV_CONTEXT
        ).startswith(base)
