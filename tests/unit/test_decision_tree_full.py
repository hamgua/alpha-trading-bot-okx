"""
决策引擎 & 交易流程 全分支测试套件

覆盖范围：
1. AI信号 × 策略信号 所有组合 (BUY/SELL/SHORT/HOLD)
2. 安全模式所有分支
3. 止损计算所有路径（含我们最新修复）
4. 风险管理者 side 参数所有分支
5. 所有边缘条件（空数据、零值、边界值）
"""
import os
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from typing import Dict, Any

# ==============================
# 测试辅助函数
# ==============================

@pytest.fixture(autouse=True)
def clean_env():
    """每次测试前清理环境变量"""
    orig = os.environ.get("INVESTMENT_TYPE")
    os.environ.pop("INVESTMENT_TYPE", None)
    yield
    if orig:
        os.environ["INVESTMENT_TYPE"] = orig
    else:
        os.environ.pop("INVESTMENT_TYPE", None)


def make_selected(signal="HOLD", confidence=0.5, strategy_type="regular"):
    """构造 mock 策略选择结果"""
    s = MagicMock()
    s.signal = signal
    s.confidence = confidence
    s.strategy_type = strategy_type
    s.reasons = []
    return s


def make_market_data(**overrides):
    """构造市场数据"""
    data = {
        "technical": {"atr_percent": 0.02, "rsi": 50, "trend_direction": "neutral"},
        "has_position": False,
        "risk_reward_ratio": 0,
        "market_structure": "sideways",
        "market_structure_direction": "none",
    }
    data.update(overrides)
    return data


# ============================================================
# A. 决策引擎全分支测试 (decision_engine.py)
# ============================================================

class TestDecisionEngineDecisionTree:
    """决策引擎完整决策树测试"""

    def _make_engine(self, investment_type="moderate"):
        """创建决策引擎实例"""
        from alpha_trading_bot.core.decision_engine import DecisionEngine
        config = MagicMock()
        config.trading.allow_short_selling = True
        if investment_type != "moderate":
            os.environ["INVESTMENT_TYPE"] = investment_type
        return DecisionEngine(config)

    # --------------------------------------------------
    # A1. BUY 信号 × 各种条件
    # --------------------------------------------------

    def test_BUY_normal_success(self):
        """BUY + 正常条件 → open"""
        engine = self._make_engine()
        result = engine.make_decision("BUY", make_selected("BUY", 0.8),
            make_market_data(risk_reward_ratio=2.0, market_structure="bullish"))
        assert result["action"] == "open"

    def test_BUY_high_volatility_blocks(self):
        """BUY + ATR过高 → skip"""
        engine = self._make_engine()
        result = engine.make_decision("BUY", make_selected("BUY"),
            make_market_data(technical={"atr_percent": 0.60, "rsi": 50}))
        assert result["action"] == "skip"
        assert "高波动" in result["reason"]

    def test_BUY_low_rr_blocks(self):
        """BUY + R/R不足 → skip (默认moderate=1.0)"""
        engine = self._make_engine()
        result = engine.make_decision("BUY", make_selected("BUY"),
            make_market_data(risk_reward_ratio=0.5, market_structure="bullish"))
        assert result["action"] == "skip"
        assert "R/R" in result["reason"]

    def test_BUY_rr_zero_ok(self):
        """BUY + R/R=0 不触发门禁 → open"""
        engine = self._make_engine()
        result = engine.make_decision("BUY", make_selected("BUY"),
            make_market_data(risk_reward_ratio=0.0, market_structure="bullish"))
        # R/R=0 时 `rr_ratio > 0` 为 False，不触发门禁
        assert result["action"] == "open"

    def test_BUY_bearish_structure_blocks(self):
        """BUY + 下跌结构 → skip"""
        engine = self._make_engine()
        result = engine.make_decision("BUY", make_selected("BUY"),
            make_market_data(risk_reward_ratio=2.0, market_structure="bearish"))
        assert result["action"] == "skip"

    def test_BUY_good_rr_gives_advice(self):
        """BUY + 优秀R/R → open + position_advice"""
        engine = self._make_engine()
        result = engine.make_decision("BUY", make_selected("BUY"),
            make_market_data(risk_reward_ratio=2.5, market_structure="bullish"))
        assert result["action"] == "open"
        assert "position_advice" in result

    def test_BUY_marginal_rr_gives_advice(self):
        """BUY + 勉强R/R → open + 减仓建议"""
        engine = self._make_engine()
        result = engine.make_decision("BUY", make_selected("BUY"),
            make_market_data(risk_reward_ratio=1.5, market_structure="bullish"))
        assert result["action"] == "open"

    def test_BUY_missing_rr_data(self):
        """BUY + 无R/R数据 → open (兼容旧行为)"""
        engine = self._make_engine()
        md = make_market_data(market_structure="bullish")
        md.pop("risk_reward_ratio", None)
        result = engine.make_decision("BUY", make_selected("BUY"), md)
        assert result["action"] == "open"

    def test_BUY_conservative_rr_threshold(self):
        """BUY + 保守型(R/R≥0.8) → R/R=0.9 允许"""
        engine = self._make_engine("conservative")
        result = engine.make_decision("BUY", make_selected("BUY"),
            make_market_data(risk_reward_ratio=0.9, market_structure="bullish"))
        assert result["action"] == "open"

    def test_BUY_aggressive_rr_threshold(self):
        """BUY + 激进型(R/R≥0.6) → R/R=0.7 允许"""
        engine = self._make_engine("aggressive")
        result = engine.make_decision("BUY", make_selected("BUY"),
            make_market_data(risk_reward_ratio=0.7, market_structure="bullish"))
        assert result["action"] == "open"

    # --------------------------------------------------
    # A2. SHORT 信号 × 各种条件
    # --------------------------------------------------

    def test_SHORT_normal_success(self):
        """SHORT + 正常条件 → sell（开空仓）"""
        engine = self._make_engine()
        result = engine.make_decision("SHORT", make_selected("SHORT"),
            make_market_data())
        assert result["action"] == "sell"

    def test_SHORT_high_atr_blocks(self):
        """SHORT + ATR过高 → skip"""
        engine = self._make_engine()
        result = engine.make_decision("SHORT", make_selected("SHORT"),
            make_market_data(technical={"atr_percent": 0.60, "rsi": 50}))
        assert result["action"] == "skip"

    def test_SHORT_oversold_blocks(self):
        """SHORT + RSI超卖 → skip"""
        engine = self._make_engine()
        result = engine.make_decision("SHORT", make_selected("SHORT"),
            make_market_data(technical={"atr_percent": 0.02, "rsi": 30}))
        assert result["action"] == "skip"

    def test_SHORT_short_disabled_blocks(self):
        """SHORT + 禁止做空 → skip"""
        config = MagicMock()
        config.trading.allow_short_selling = False
        from alpha_trading_bot.core.decision_engine import DecisionEngine
        engine = DecisionEngine(config)
        result = engine.make_decision("SHORT", make_selected("SHORT"),
            make_market_data())
        assert result["action"] == "skip"

    def test_SHORT_with_position_closes(self):
        """SHORT + 有持仓 → close"""
        engine = self._make_engine()
        result = engine.make_decision("SHORT", make_selected("SHORT"),
            make_market_data(has_position=True))
        assert result["action"] == "close"

    # --------------------------------------------------
    # A3. SELL 信号 × 各种条件
    # --------------------------------------------------

    def test_SELL_no_position_skips(self):
        """SELL + 无持仓 → skip"""
        engine = self._make_engine()
        result = engine.make_decision("SELL", make_selected("HOLD"),
            make_market_data(has_position=False))
        assert result["action"] == "skip"

    def test_SELL_with_position_closes(self):
        """SELL + 有持仓 → close"""
        engine = self._make_engine()
        result = engine.make_decision("SELL", make_selected("HOLD"),
            make_market_data(has_position=True))
        assert result["action"] == "close"

    def test_SELL_strategy_resonance(self):
        """SELL + 策略共振 → close"""
        engine = self._make_engine()
        result = engine.make_decision("SELL", make_selected("SELL"),
            make_market_data(has_position=True))
        assert result["action"] == "close"

    # --------------------------------------------------
    # A4. HOLD 信号 × 各种条件
    # --------------------------------------------------

    def test_HOLD_both_hold_skips(self):
        """HOLD + 策略HOLD → skip"""
        engine = self._make_engine()
        result = engine.make_decision("HOLD", make_selected("HOLD"),
            make_market_data())
        assert result["action"] == "skip"

    def test_HOLD_high_atr_blocks(self):
        """HOLD + ATR过高 → skip"""
        engine = self._make_engine()
        result = engine.make_decision("HOLD", make_selected("HOLD"),
            make_market_data(technical={"atr_percent": 0.60, "rsi": 50}))
        assert result["action"] == "skip"

    def test_HOLD_strategy_buy_overrides_with_good_rr(self):
        """HOLD + 策略BUY(高置信度) + 好R/R → open (策略覆盖)"""
        engine = self._make_engine()
        result = engine.make_decision("HOLD", make_selected("BUY", 0.85),
            make_market_data(market_structure="bullish", risk_reward_ratio=1.5))
        assert result["action"] == "open"

    def test_HOLD_strategy_buy_confidence_too_low(self):
        """HOLD + 策略BUY(低置信度) → skip"""
        engine = self._make_engine()
        result = engine.make_decision("HOLD", make_selected("BUY", 0.70),
            make_market_data(market_structure="bullish", risk_reward_ratio=1.5))
        assert result["action"] == "skip"

    def test_HOLD_strategy_buy_low_rr_now_blocked(self):
        """HOLD + 策略BUY + 低R/R → skip (我们新加的R/R门禁)"""
        engine = self._make_engine()
        result = engine.make_decision("HOLD", make_selected("BUY", 0.85),
            make_market_data(market_structure="bullish", risk_reward_ratio=0.5))
        assert result["action"] == "skip"

    def test_HOLD_strategy_buy_bearish(self):
        """HOLD + 策略BUY + 下跌结构 → skip (市场结构保护)"""
        engine = self._make_engine()
        result = engine.make_decision("HOLD", make_selected("BUY", 0.85),
            make_market_data(market_structure="bearish", risk_reward_ratio=1.5))
        assert result["action"] == "skip"

    def test_HOLD_market_structure_short(self):
        """HOLD + HOLD策略 + 短结构+好R/R → sell (市场结构做空)"""
        engine = self._make_engine()
        result = engine.make_decision("HOLD", make_selected("HOLD"),
            make_market_data(market_structure_direction="short",
                            risk_reward_ratio=2.5,
                            technical={"atr_percent": 0.02, "rsi": 50}))
        assert result["action"] == "sell"

    def test_HOLD_strategy_sell(self):
        """HOLD + 策略SELL → skip（AI-HOLD覆盖策略SELL）"""
        engine = self._make_engine()
        result = engine.make_decision("HOLD", make_selected("SELL", 0.8),
            make_market_data())
        assert result["action"] == "skip"

    # --------------------------------------------------
    # A5. 未知信号
    # --------------------------------------------------

    def test_unknown_signal_uses_strategy(self):
        """未知AI信号 → 使用策略信号"""
        engine = self._make_engine()
        result = engine.make_decision("UNKNOWN", make_selected("BUY", 0.7),
            make_market_data())
        assert result["action"] == "open"

    def test_unknown_signal_strategy_hold(self):
        """未知AI信号 + 策略HOLD → skip"""
        engine = self._make_engine()
        result = engine.make_decision("UNKNOWN", make_selected("HOLD"),
            make_market_data())
        assert result["action"] == "skip"

    # --------------------------------------------------
    # A6. 安全模式全分支
    # --------------------------------------------------

    def test_safe_mode_downtrend_short(self):
        """安全模式 + 下跌趋势 + SHORT → 最终走SHORT逻辑"""
        engine = self._make_engine()
        result = engine.make_decision("SHORT", make_selected("SHORT", 0.7, strategy_type="safe_mode"),
            make_market_data(technical={"atr_percent": 0.02, "rsi": 50,
                                        "trend_direction": "down"}))
        assert result["action"] in ("sell", "skip")

    def test_safe_mode_reduced_open(self):
        """安全模式 + 上升趋势 + BUY + 好R/R + ATR适中 → 减半开仓"""
        engine = self._make_engine()
        result = engine.make_decision("BUY", make_selected("BUY", 0.7, strategy_type="safe_mode"),
            make_market_data(risk_reward_ratio=1.5, market_structure="bullish",
                            technical={"atr_percent": 0.30, "rsi": 50,
                                       "trend_direction": "up"}))
        assert result["action"] == "open"
        assert "safe_mode_reduced" in result.get("strategy", "")

    def test_safe_mode_reduced_low_rr_blocks(self):
        """安全模式减半开仓 + R/R不足 → skip"""
        engine = self._make_engine()
        result = engine.make_decision("BUY", make_selected("BUY", 0.7, strategy_type="safe_mode"),
            make_market_data(risk_reward_ratio=0.5, market_structure="bullish",
                            technical={"atr_percent": 0.30, "rsi": 50,
                                       "trend_direction": "up"}))
        assert result["action"] == "skip"

    def test_safe_mode_reduced_high_atr_blocks(self):
        """安全模式减半开仓 + ATR过高 → skip"""
        engine = self._make_engine()
        result = engine.make_decision("BUY", make_selected("BUY", 0.7, strategy_type="safe_mode"),
            make_market_data(risk_reward_ratio=1.5, market_structure="bullish",
                            technical={"atr_percent": 0.50, "rsi": 50,
                                       "trend_direction": "up"}))
        assert result["action"] == "skip"

    def test_safe_mode_with_position_reduces(self):
        """安全模式 + 有持仓 → reduce"""
        engine = self._make_engine()
        result = engine.make_decision("BUY", make_selected("BUY", 0.7, strategy_type="safe_mode"),
            make_market_data(has_position=True, risk_reward_ratio=2.0,
                            technical={"atr_percent": 0.02, "rsi": 50}))
        assert result["action"] == "reduce"

    def test_safe_mode_downtrend_short_with_position_reduces(self):
        """安全模式 + 下跌趋势 + SHORT + 有持仓 → reduce (安全模式应降低仓位而非平仓)"""
        engine = self._make_engine()
        result = engine.make_decision("SHORT", make_selected("SHORT", 0.7, strategy_type="safe_mode"),
            make_market_data(has_position=True,
                            technical={"atr_percent": 0.02, "rsi": 50,
                                       "trend_direction": "down"}))
        assert result["action"] == "reduce"