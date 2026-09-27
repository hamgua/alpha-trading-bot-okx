"""
Jev 问题集与状态序列化单元测试
"""

from alpha_trading_bot.ai.jev.questions import JEV_QUESTIONS, build_state
from alpha_trading_bot.ai.jev.typesafe_client import (
    JevChoiceQuestion,
    JevNoulQuestion,
)


def test_question_set_structure() -> None:
    """问题集：1 个主 Choice（4 选项对齐 VALID_SIGNALS）+ 2 个辅助 Noul。"""
    assert set(JEV_QUESTIONS.keys()) == {
        "trade_decision",
        "is_high_risk_reversal",
        "is_choppy_no_edge",
    }
    decision = JEV_QUESTIONS["trade_decision"]
    assert isinstance(decision, JevChoiceQuestion)
    assert set(decision.criteria.keys()) == {"buy", "hold", "sell", "short"}
    # 每个选项必须有判别性描述（官方最佳实践：描述用于区分选项）
    for description in decision.criteria.values():
        assert isinstance(description, str) and len(description) > 5
    assert isinstance(JEV_QUESTIONS["is_high_risk_reversal"], JevNoulQuestion)
    assert isinstance(JEV_QUESTIONS["is_choppy_no_edge"], JevNoulQuestion)


def test_build_state_includes_key_fields() -> None:
    market_data = {
        "symbol": "BTC-USDT",
        "price": 118000.5,
        "high": 119000.0,
        "low": 116000.0,
        "volume": 12345.6,
        "change_percent": 1.2,
        "technical": {
            "rsi": 55.5,
            "macd_hist": 12.3456,
            "trend_direction": "up",
            "trend_strength": 0.3,
            "adx": 18.0,
        },
        "recent_drop_percent": -0.1,
        "short_term_rise_percent": 0.8,
        "position": {"side": "long", "amount": 0.05, "entry_price": 115000.0},
        "price_history": [117000.0 + i for i in range(30)],
    }
    state = build_state(market_data)
    assert "BTC-USDT" in state
    assert "118000" in state
    assert "rsi=55.5" in state
    assert "trend_direction=up" in state
    assert "macd_hist=12.35" in state  # _fmt 用 .4g
    assert "持仓" in state
    assert "近20根收盘价" in state
    assert len(state) < 4000  # 紧凑状态，不塞整段价格历史


def test_build_state_missing_keys_no_error() -> None:
    """缺 technical/position/price_history（数据服务降级）→ 不抛错、输出已有字段。
    Review Focus #2。"""
    state = build_state({"symbol": "ETH-USDT", "price": 3500.0})
    assert "ETH-USDT" in state
    assert "3500" in state

    empty = build_state({})
    assert "UNKNOWN" in empty


def test_build_state_skips_empty_position_and_history() -> None:
    state = build_state(
        {"symbol": "X-USDT", "price": 1.0, "position": {}, "price_history": []}
    )
    assert "持仓:" not in state
    assert "近20根收盘价" not in state


def test_build_state_dedupes_macd_hist_keys() -> None:
    """macd_hist 与 macd_histogram 指向同一指标，不同时输出。"""
    state = build_state(
        {
            "symbol": "X-USDT",
            "price": 1.0,
            "technical": {"macd_hist": 1.5, "macd_histogram": 1.5},
        }
    )
    assert "macd_histogram" not in state
    assert "macd_hist=1.5" in state
