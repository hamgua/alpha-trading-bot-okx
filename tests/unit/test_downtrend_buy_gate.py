"""R9: 下跌趋势 BUY 门禁 (全场景波动矩阵测试发现)

场景矩阵 C5-下跌结构买入 暴露: 平滑下跌趋势 (trend_direction=down,
strength 0.4) + RSI 50 + AI BUY 80% → 直接开多。

根因: _make_buy_decision 仅拦截 market_structure == "bearish",
而 MarketStructureAnalyzer 基于 swing 点检测, 平滑单调下跌
(无 swing) 返回 "数据不足" → 回落 sideways → bearish 拦截失效。
趋势信息 (trend_direction/trend_strength) 在 technical 中可用,
但 BUY 路径从未检查 —— 恰好是"结构检测失败"时 (平滑急跌)
最危险的场景漏网。

修复: BUY 路径增加趋势门禁 —— 强下跌趋势 (down + strength ≥ 0.40)
禁止开多, RSI 超卖 (< 30) 除外 (保留均值回归/超卖反弹路径)。
"""

import logging

import pytest

from alpha_trading_bot.config.models import Config
from alpha_trading_bot.core.decision_engine import DecisionEngine

logger = logging.getLogger(__name__)


def _md(
    atr: float = 0.0015,
    rsi: float = 50.0,
    trend_direction: str = "down",
    trend_strength: float = 0.4,
    structure: str = "sideways",
    rr: float = 2.0,
) -> dict:
    return {
        "price": 77000.0,
        "change_percent": -0.01,
        "short_term_drop_percent": -0.01,
        "price_history": [77000.0 * (1 - 0.0005 * i) for i in range(60, 0, -1)],
        "technical": {
            "rsi": rsi,
            "atr_percent": atr,
            "trend_direction": trend_direction,
            "trend_strength": trend_strength,
            "adx": 25.0,
            "bb_position": 0.5,
            "price_position": 0.4,
            "macd_hist": -0.5,
        },
        "market_structure": structure,
        "risk_reward_ratio": rr,
        "ai_final_confidence": 0.8,
        "final_confidence": 0.8,
        "has_position": False,
    }


class _Selected:
    def __init__(self, signal="BUY", confidence=0.75, strategy_type="trend_following"):
        self.signal = signal
        self.confidence = confidence
        self.strategy_type = strategy_type


class TestDowntrendBuyGate:
    """强下跌趋势中 AI BUY 被拦截 (R9)。"""

    def test_smooth_downtrend_buy_blocked(self):
        """平滑下跌 (结构检测失败→sideways) + AI BUY → 禁止开多。"""
        engine = DecisionEngine(Config())
        decision = engine.make_decision("BUY", _Selected(), _md())
        assert decision["action"] == "skip", f"强下跌趋势中不应开多: {decision}"
        assert "趋势" in decision["reason"] or "下跌" in decision["reason"]

    def test_downtrend_buy_blocked_even_with_good_rr(self):
        """R/R 良好也不能绕过趋势门禁。"""
        engine = DecisionEngine(Config())
        decision = engine.make_decision("BUY", _Selected(), _md(rr=5.0))
        assert decision["action"] == "skip"

    def test_weak_downtrend_buy_allowed(self):
        """弱下跌 (strength 0.2 < 0.40) → 趋势门禁不触发, 正常放行。"""
        engine = DecisionEngine(Config())
        decision = engine.make_decision("BUY", _Selected(), _md(trend_strength=0.2))
        assert decision["action"] == "open", f"弱下跌不应被拦截: {decision}"

    def test_oversold_rsi_downtrend_buy_allowed(self):
        """RSI 超卖 (<30) 的下跌中保留均值回归买入路径。"""
        engine = DecisionEngine(Config())
        decision = engine.make_decision("BUY", _Selected(), _md(rsi=25.0))
        assert (
            decision["action"] == "open"
        ), f"超卖反弹路径不应被趋势门禁拦截: {decision}"

    def test_uptrend_unaffected(self):
        """上升趋势不受影响。"""
        engine = DecisionEngine(Config())
        decision = engine.make_decision(
            "BUY", _Selected(), _md(trend_direction="up", trend_strength=0.6)
        )
        assert decision["action"] == "open"

    def test_bearish_structure_still_blocked(self):
        """原 bearish 结构拦截继续生效 (优先级不变)。"""
        engine = DecisionEngine(Config())
        decision = engine.make_decision(
            "BUY", _Selected(), _md(structure="bearish", trend_direction="sideways")
        )
        assert decision["action"] == "skip"
        assert "结构" in decision["reason"]
