"""决策引擎 HOLD 分支策略覆盖测试

针对 2026-06-15-no-trades-63590-to-66000 dream 任务的修复单测：
覆盖 HOLD+有策略信号场景下的"覆盖"路径，避免"零交易"问题回归。

包含三类用例：
1. 正常路径：均值回归超卖反弹、趋势策略 BUY 覆盖、SHORT 覆盖
2. 异常路径：HOLD+无持仓/HOLD+HOLD、有持仓、超阈值 RSI、ATR 过高等
3. 边界条件：投资类型切换（moderate/conservative/aggressive）、confidence 阈值
"""

import os
from unittest.mock import MagicMock

import pytest

from alpha_trading_bot.core.decision_engine import DecisionEngine


class TestHoldOversoldOverride:
    """均值回归超卖反弹覆盖 AI-HOLD 测试"""

    def setup_method(self):
        self.config = MagicMock()
        self.config.trading.allow_short_selling = True
        self._orig_env = os.environ.get("INVESTMENT_TYPE")
        os.environ.pop("INVESTMENT_TYPE", None)

    def teardown_method(self):
        if self._orig_env is not None:
            os.environ["INVESTMENT_TYPE"] = self._orig_env
        else:
            os.environ.pop("INVESTMENT_TYPE", None)

    def _make_selected(
        self, signal="BUY", confidence=0.85, strategy_type="mean_reversion"
    ):
        selected = MagicMock()
        selected.signal = signal
        selected.confidence = confidence
        selected.strategy_type = strategy_type
        selected.reasons = []
        return selected

    def test_hold_oversold_buy_overrides_with_confirmation(self):
        """HOLD + mean_reversion BUY 需要超卖反转确认后才可开仓"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY", confidence=0.85)
        market_data = {
            "technical": {
                "atr_percent": 0.35,
                "rsi": 27.9,
                "reversal_confirmed": True,
            },
            "has_position": False,
            "risk_reward_ratio": 1.2,
            "market_structure": "sideways",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "open"
        assert result["strategy"] == "mean_reversion_oversold_override"
        assert result["confidence"] == pytest.approx(0.68)
        assert "RSI" in result["reason"]

    def test_hold_oversold_buy_without_confirmation_stays_observation(self):
        """只有 RSI 超卖时不再直接覆盖 AI-HOLD。"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY", confidence=0.85)
        market_data = {
            "technical": {"atr_percent": 0.35, "rsi": 27.9},
            "has_position": False,
            "risk_reward_ratio": 1.2,
            "market_structure": "sideways",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"
        assert result["strategy"] != "mean_reversion_oversold_override"

    def test_hold_oversold_buy_blocked_in_bearish(self):
        """HOLD + 超卖反弹 + market_structure=bearish → 跳过（禁止下跌结构中做多）"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY", confidence=0.85)
        market_data = {
            "technical": {"atr_percent": 0.35, "rsi": 27.9},
            "has_position": False,
            "risk_reward_ratio": 1.2,
            "market_structure": "bearish",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"
        assert result["strategy"] != "mean_reversion_oversold_override"

    def test_hold_oversold_buy_blocked_by_rr_below_1_0(self):
        """HOLD + 超卖反弹 + R/R<1.0 → 不走超卖通道，走strategy buy override"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY", confidence=0.85)
        market_data = {
            "technical": {"atr_percent": 0.35, "rsi": 27.9},
            "has_position": False,
            "risk_reward_ratio": 0.8,
            "market_structure": "sideways",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["strategy"] != "mean_reversion_oversold_override"

    def test_hold_oversold_buy_blocked_by_has_position(self):
        """HOLD + 超卖反弹 + 已有持仓 → 不走超卖通道"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY", confidence=0.85)
        market_data = {
            "technical": {"atr_percent": 0.35, "rsi": 27.9},
            "has_position": True,
            "risk_reward_ratio": 1.2,
            "market_structure": "sideways",
            "min_trade_confidence": 0.40,
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["strategy"] != "mean_reversion_oversold_override"

    def test_hold_oversold_buy_blocked_by_high_atr(self):
        """HOLD + 超卖反弹 + ATR>55% → 高波动停仓"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY", confidence=0.85)
        market_data = {
            "technical": {"atr_percent": 0.60, "rsi": 27.9},
            "has_position": False,
            "risk_reward_ratio": 1.2,
            "market_structure": "sideways",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"
        assert "高波动" in result["reason"]

    def test_hold_oversold_buy_blocked_by_low_rr(self):
        """HOLD + 超卖反弹 + R/R<1.0 → 不满足最低阈值"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY", confidence=0.85)
        market_data = {
            "technical": {"atr_percent": 0.35, "rsi": 27.9},
            "has_position": False,
            "risk_reward_ratio": 0.4,
            "market_structure": "sideways",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"

    def test_hold_oversold_buy_requires_mean_reversion(self):
        """非 mean_reversion 策略的 BUY 不走超卖通道"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected(
            "BUY", confidence=0.85, strategy_type="trend_following"
        )
        market_data = {
            "technical": {"atr_percent": 0.35, "rsi": 27.9},
            "has_position": False,
            "risk_reward_ratio": 1.2,
            "market_structure": "sideways",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["strategy"] != "mean_reversion_oversold_override"

    def test_hold_oversold_buy_requires_rsi_below_threshold(self):
        """RSI 在 [30, ∞) 不触发超卖通道（按 RSI=30 边界）"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY", confidence=0.85)
        market_data = {
            "technical": {"atr_percent": 0.35, "rsi": 30.0},
            "has_position": False,
            "risk_reward_ratio": 1.2,
            "market_structure": "sideways",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["strategy"] != "mean_reversion_oversold_override"

    def test_hold_oversold_buy_requires_buy_signal(self):
        """mean_reversion 策略但信号是 SELL 时不触发 BUY 通道"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("SELL", confidence=0.80)
        market_data = {
            "technical": {"atr_percent": 0.35, "rsi": 27.9},
            "has_position": False,
            "risk_reward_ratio": 1.2,
            "market_structure": "sideways",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["strategy"] != "mean_reversion_oversold_override"


class TestHoldStrategyBuyOverride:
    """策略 BUY 覆盖 AI-HOLD 测试（含 R/R 阈值放宽）"""

    def setup_method(self):
        self.config = MagicMock()
        self.config.trading.allow_short_selling = True
        self._orig_env = os.environ.get("INVESTMENT_TYPE")
        os.environ.pop("INVESTMENT_TYPE", None)

    def teardown_method(self):
        if self._orig_env is not None:
            os.environ["INVESTMENT_TYPE"] = self._orig_env
        else:
            os.environ.pop("INVESTMENT_TYPE", None)

    def _make_selected(
        self, signal="BUY", confidence=0.82, strategy_type="trend_following"
    ):
        selected = MagicMock()
        selected.signal = signal
        selected.confidence = confidence
        selected.strategy_type = strategy_type
        selected.reasons = []
        return selected

    def test_hold_strategy_buy_blocked_below_full_rr_threshold(self):
        """moderate 投资类型下 BUY 覆盖 AI-HOLD 不再放宽到 R/R=0.7。"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY", confidence=0.82)
        market_data = {
            "technical": {"atr_percent": 0.35, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 0.7,
            "market_structure": "sideways",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"

    def test_hold_strategy_buy_overrides_at_full_rr_threshold(self):
        """BUY 覆盖 AI-HOLD 至少需要 R/R>=1.0。"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY", confidence=0.82)
        market_data = {
            "technical": {"atr_percent": 0.35, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 1.0,
            "market_structure": "sideways",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "open"
        assert result["strategy"] == "trend_following"
        assert result["confidence"] == pytest.approx(0.656)

    def test_hold_strategy_buy_blocked_below_floor(self):
        """R/R < 0.6（地板） 仍被阻止"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY", confidence=0.82)
        market_data = {
            "technical": {"atr_percent": 0.35, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 0.5,
            "market_structure": "sideways",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"

    def test_hold_strategy_buy_blocked_by_bearish(self):
        """市场结构 bearish 仍然阻止 BUY 覆盖（非超卖反弹场景）"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY", confidence=0.82)
        market_data = {
            "technical": {"atr_percent": 0.35, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 0.7,
            "market_structure": "bearish",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"

    def test_hold_strategy_buy_blocked_by_low_confidence(self):
        """策略置信度 < 0.80 仍被阻止"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY", confidence=0.75)
        market_data = {
            "technical": {"atr_percent": 0.35, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 0.7,
            "market_structure": "sideways",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"

    def test_hold_strategy_buy_position_advice_good(self):
        """R/R>=2.0 时给出"良好，正常仓位"建议"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY", confidence=0.85)
        market_data = {
            "technical": {"atr_percent": 0.35, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 2.4,
            "market_structure": "bullish",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "open"
        assert "position_advice" in result
        assert "良好" in result["position_advice"]


class TestHoldStrategyShortOverride:
    """策略 SHORT 覆盖 AI-HOLD 测试"""

    def setup_method(self):
        self.config = MagicMock()
        self.config.trading.allow_short_selling = True
        self._orig_env = os.environ.get("INVESTMENT_TYPE")
        os.environ.pop("INVESTMENT_TYPE", None)

    def teardown_method(self):
        if self._orig_env is not None:
            os.environ["INVESTMENT_TYPE"] = self._orig_env
        else:
            os.environ.pop("INVESTMENT_TYPE", None)

    def _make_selected(
        self, signal="SHORT", confidence=0.80, strategy_type="breakdown"
    ):
        selected = MagicMock()
        selected.signal = signal
        selected.confidence = confidence
        selected.strategy_type = strategy_type
        selected.reasons = []
        return selected

    def test_hold_strategy_short_overrides_in_bearish(self):
        """HOLD + 策略 SHORT + bearish + R/R>=0.6 → 做空"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("SHORT", confidence=0.80)
        market_data = {
            "technical": {"atr_percent": 0.03, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 0.7,
            "market_structure": "bearish",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "sell"
        assert result["strategy"] == "breakdown"

    def test_hold_strategy_short_blocked_when_allow_short_false(self):
        """ALLOW_SHORT_SELLING=false 时阻止 SHORT 覆盖"""
        self.config.trading.allow_short_selling = False
        engine = DecisionEngine(self.config)
        selected = self._make_selected("SHORT", confidence=0.80)
        market_data = {
            "technical": {"atr_percent": 0.03, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 0.7,
            "market_structure": "bearish",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"

    def test_hold_strategy_short_blocked_by_low_rr(self):
        """R/R < 0.5（短做空地板）仍被阻止"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("SHORT", confidence=0.80)
        market_data = {
            "technical": {"atr_percent": 0.03, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 0.4,
            "market_structure": "bearish",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"

    def test_hold_strategy_short_blocked_by_high_atr(self):
        """ATR > 55% 阻止 SHORT"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("SHORT", confidence=0.80)
        market_data = {
            "technical": {"atr_percent": 0.60, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 0.7,
            "market_structure": "bearish",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"
        assert "高波动" in result["reason"]

    def test_hold_strategy_short_blocked_by_oversold_rsi(self):
        """RSI < 40 阻止 SHORT"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("SHORT", confidence=0.80)
        market_data = {
            "technical": {"atr_percent": 0.03, "rsi": 30},
            "has_position": False,
            "risk_reward_ratio": 0.7,
            "market_structure": "bearish",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"


class TestHoldStrategySellOverride:
    """策略 SELL 覆盖 AI-HOLD 测试"""

    def setup_method(self):
        self.config = MagicMock()
        self.config.trading.allow_short_selling = True
        self._orig_env = os.environ.get("INVESTMENT_TYPE")
        os.environ.pop("INVESTMENT_TYPE", None)

    def teardown_method(self):
        if self._orig_env is not None:
            os.environ["INVESTMENT_TYPE"] = self._orig_env
        else:
            os.environ.pop("INVESTMENT_TYPE", None)

    def _make_selected(
        self, signal="SELL", confidence=0.80, strategy_type="mean_reversion"
    ):
        selected = MagicMock()
        selected.signal = signal
        selected.confidence = confidence
        selected.strategy_type = strategy_type
        selected.reasons = []
        return selected

    def test_hold_strategy_sell_overrides_with_position(self):
        """HOLD + 策略 SELL + 置信度≥75% + 有持仓 → close（平仓）"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("SELL", confidence=0.80)
        market_data = {
            "technical": {"atr_percent": 0.03, "rsi": 70},
            "has_position": True,
            "risk_reward_ratio": 0.7,
            "market_structure": "bearish",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "close"
        assert "策略SELL覆盖AI-HOLD" in result["reason"]
        assert result["confidence"] == pytest.approx(0.64)

    def test_hold_strategy_sell_overrides_no_position_short(self):
        """HOLD + 策略 SELL + 已确认短 R/R + 无持仓 + 允许做空 → sell"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("SELL", confidence=0.80)
        market_data = {
            "technical": {"atr_percent": 0.03, "rsi": 70, "reversal_confirmed": True},
            "has_position": False,
            "risk_reward_ratio": 8.0,
            "short_risk_reward_ratio": 0.7,
            "market_structure_direction": "short",
            "market_structure": "bearish",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "sell"
        assert "策略SELL覆盖AI-HOLD" in result["reason"]

    def test_hold_strategy_sell_without_confirmation_stays_observation(self):
        """只有 RSI 超买时不再直接覆盖 AI-HOLD 做空。"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("SELL", confidence=0.80)
        market_data = {
            "technical": {"atr_percent": 0.03, "rsi": 70},
            "has_position": False,
            "short_risk_reward_ratio": 0.7,
            "market_structure_direction": "short",
            "market_structure": "bearish",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"

    def test_hold_strategy_sell_excellent_short_rr_overrides_without_confirmation(self):
        """高质量短 R/R + 策略 SELL 可轻量覆盖 AI-HOLD 做空。"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("SELL", confidence=0.80)
        market_data = {
            "technical": {"atr_percent": 0.03, "rsi": 70},
            "has_position": False,
            "short_risk_reward_ratio": 3.2,
            "market_structure_direction": "short",
            "market_structure": "bearish",
            "min_trade_confidence": 0.40,
            "final_confidence": 0.80,
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "sell"
        assert result["strategy"] == "mean_reversion_short_rr_override"

    def test_hold_strategy_sell_does_not_reuse_long_rr_for_short(self):
        """长方向 R/R 很高但短方向未确认时，SELL 不应开空。"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("SELL", confidence=0.80)
        market_data = {
            "technical": {"atr_percent": 0.03, "rsi": 70},
            "has_position": False,
            "risk_reward_ratio": 102.8,
            "market_structure_direction": "long",
            "market_structure": "bullish",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"

    def test_hold_strategy_sell_blocked_by_low_confidence(self):
        """策略 SELL 置信度 < 75% → skip"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("SELL", confidence=0.70)
        market_data = {
            "technical": {"atr_percent": 0.03, "rsi": 70},
            "has_position": False,
            "risk_reward_ratio": 0.7,
            "market_structure": "bearish",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"

    def test_hold_strategy_sell_blocked_when_allow_short_false_no_position(self):
        """ALLOW_SHORT_SELLING=false + 无持仓 → skip（不能做空）"""
        self.config.trading.allow_short_selling = False
        engine = DecisionEngine(self.config)
        selected = self._make_selected("SELL", confidence=0.80)
        market_data = {
            "technical": {"atr_percent": 0.03, "rsi": 70},
            "has_position": False,
            "risk_reward_ratio": 0.7,
            "market_structure": "bearish",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"

    def test_hold_strategy_sell_blocked_by_high_atr_no_position(self):
        """ATR > 55% + 无持仓 → skip（高波动不能做空）"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("SELL", confidence=0.80)
        market_data = {
            "technical": {"atr_percent": 0.60, "rsi": 70},
            "has_position": False,
            "risk_reward_ratio": 0.7,
            "market_structure": "bearish",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"

    def test_hold_strategy_sell_blocked_by_oversold_rsi_no_position(self):
        """RSI < 40 + 无持仓 → skip（超卖不能做空）"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("SELL", confidence=0.80)
        market_data = {
            "technical": {"atr_percent": 0.03, "rsi": 30},
            "has_position": False,
            "risk_reward_ratio": 0.7,
            "market_structure": "bearish",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"

    def test_hold_strategy_sell_blocked_by_low_rr_no_position(self):
        """R/R < 0.5（短做空地板）+ 无持仓 → skip"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("SELL", confidence=0.80)
        market_data = {
            "technical": {"atr_percent": 0.03, "rsi": 70},
            "has_position": False,
            "risk_reward_ratio": 0.3,
            "market_structure": "bearish",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"

    def test_hold_strategy_sell_with_position_bypasses_short_gates(self):
        """有持仓时跳过做空安全门禁仍可平仓（allow_short_selling=False）"""
        self.config.trading.allow_short_selling = False
        engine = DecisionEngine(self.config)
        selected = self._make_selected("SELL", confidence=0.80)
        market_data = {
            "technical": {"atr_percent": 0.03, "rsi": 30},
            "has_position": True,
            "risk_reward_ratio": 0.3,
            "market_structure": "bullish",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "close"
        assert "策略SELL覆盖AI-HOLD" in result["reason"]


class TestHoldBothHold:
    """HOLD + HOLD 仍 skip（保持原行为）"""

    def setup_method(self):
        self.config = MagicMock()
        self.config.trading.allow_short_selling = True
        self._orig_env = os.environ.get("INVESTMENT_TYPE")
        os.environ.pop("INVESTMENT_TYPE", None)

    def teardown_method(self):
        if self._orig_env is not None:
            os.environ["INVESTMENT_TYPE"] = self._orig_env
        else:
            os.environ.pop("INVESTMENT_TYPE", None)

    def test_both_hold_returns_skip(self):
        engine = DecisionEngine(self.config)
        selected = MagicMock()
        selected.signal = "HOLD"
        selected.confidence = 0.7
        selected.strategy_type = "trend_following"
        selected.reasons = []
        market_data = {
            "technical": {"atr_percent": 0.02, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 2.0,
            "market_structure": "bullish",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"
        assert "AI和策略都是HOLD" in result["reason"]

    def test_market_structure_short_uses_explicit_short_rr(self):
        """市场结构做空覆盖 AI-HOLD 必须使用短方向 R/R。"""
        engine = DecisionEngine(self.config)
        selected = MagicMock()
        selected.signal = "HOLD"
        selected.confidence = 0.8
        selected.strategy_type = "trend_following"
        selected.reasons = []
        market_data = {
            "technical": {"atr_percent": 0.03, "rsi": 50, "trend_strength": 0.3},
            "has_position": False,
            "risk_reward_ratio": 5.0,
            "short_risk_reward_ratio": 0.4,
            "market_structure_direction": "short",
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"

    def test_bearish_structure_short_overrides_ai_hold_with_marginal_rr(self):
        """下跌结构 + 可接受短 R/R + 趋势确认时允许小仓位做空。"""
        engine = DecisionEngine(self.config)
        selected = MagicMock()
        selected.signal = "HOLD"
        selected.confidence = 0.72
        selected.strategy_type = "trend_following"
        selected.reasons = []
        market_data = {
            "technical": {"atr_percent": 0.03, "rsi": 48, "trend_strength": 0.08},
            "has_position": False,
            "short_risk_reward_ratio": 1.25,
            "market_structure": "bearish",
            "market_structure_direction": "none",
            "min_trade_confidence": 0.40,
            "final_confidence": 0.72,
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "sell"
        assert result["strategy"] == "bearish_structure_short"


class TestHoldBuyConfidenceGate:
    """置信度门禁在 HOLD 分支也应生效"""

    def setup_method(self):
        self.config = MagicMock()
        self.config.trading.allow_short_selling = True
        self._orig_env = os.environ.get("INVESTMENT_TYPE")
        os.environ.pop("INVESTMENT_TYPE", None)

    def teardown_method(self):
        if self._orig_env is not None:
            os.environ["INVESTMENT_TYPE"] = self._orig_env
        else:
            os.environ.pop("INVESTMENT_TYPE", None)

    def test_oversold_buy_blocked_by_low_final_confidence(self):
        """BTC 高位 + is_high_risk=True + 置信度<0.55 阻止 BUY"""
        engine = DecisionEngine(self.config)
        selected = MagicMock()
        selected.signal = "BUY"
        selected.confidence = 0.50
        selected.strategy_type = "mean_reversion"
        selected.reasons = []
        market_data = {
            "technical": {
                "atr_percent": 0.35,
                "rsi": 27.9,
                "reversal_confirmed": True,
            },
            "has_position": False,
            "risk_reward_ratio": 1.2,
            "market_structure": "sideways",
            "is_high_risk": True,
            "final_confidence": 0.50,
            "min_trade_confidence": 0.40,
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"
        assert "置信度" in result["reason"]
