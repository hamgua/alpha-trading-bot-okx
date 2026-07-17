from alpha_trading_bot.ai.prompt_builder import build_prompt


def _market_data(**overrides):
    data = {
        "price": 64000.0,
        "has_position": True,
        "position_side": "short",
        "risk_reward_ratio": 0.6,
        "short_risk_reward_ratio": 2.4,
        "market_structure": "bearish",
        "market_structure_direction": "short",
        "nearest_support": 63200.0,
        "nearest_resistance": 64800.0,
        "position_size_factor": 0.5,
        "technical": {
            "rsi": 58.0,
            "macd": -12.0,
            "macd_histogram": -0.02,
            "adx": 28.0,
            "atr_percent": 0.004,
            "bb_position": 0.72,
            "trend_direction": "down",
            "trend_strength": 0.24,
        },
    }
    data.update(overrides)
    return data


def test_prompt_includes_position_aware_signal_semantics() -> None:
    prompt = build_prompt(_market_data(), provider="deepseek")

    assert "当前持有空单时：SELL/SHORT 表示同向看空或继续持有，不是平仓" in prompt
    assert "当前持有空单时：BUY 表示平空" in prompt
    assert "当前为多仓时：SELL/SHORT 表示平多" in prompt


def test_prompt_exposes_long_and_short_risk_reward_separately() -> None:
    prompt = build_prompt(_market_data(), provider="deepseek")

    assert "做多风险收益比(long R/R): 0.60" in prompt
    assert "做空风险收益比(short R/R): 2.40" in prompt


def test_prompt_requires_json_output_and_caps_hold_confidence() -> None:
    prompt = build_prompt(_market_data(), provider="deepseek")

    assert "只输出一个 JSON 对象" in prompt
    assert '"signal": "short"' in prompt
    assert '"position_action": "continue_short"' in prompt
    assert "HOLD 置信度必须在 25-65" in prompt
