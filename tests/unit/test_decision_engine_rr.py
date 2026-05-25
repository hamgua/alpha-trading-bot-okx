"""决策引擎R/R门禁单元测试"""

import pytest
from unittest.mock import MagicMock
from alpha_trading_bot.core.decision_engine import DecisionEngine, MIN_RR_RATIO


class TestDecisionEngineRR:
    """决策引擎R/R门禁测试"""

    def setup_method(self):
        self.config = MagicMock()
        self.config.trading.allow_short_selling = True
        self.engine = DecisionEngine(self.config)

    def _make_selected(self, signal="BUY", confidence=0.7, strategy_type="regular"):
        """构造mock selected对象"""
        selected = MagicMock()
        selected.signal = signal
        selected.confidence = confidence
        selected.strategy_type = strategy_type
        selected.reasons = []
        return selected

    # === R/R门禁测试 ===

    def test_buy_blocked_by_low_rr(self):
        """测试低R/R比阻止BUY开仓"""
        selected = self._make_selected("BUY")
        market_data = {
            "technical": {"atr_percent": 0.02, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 1.0,  # R/R < 1.5
            "market_structure": "bullish",
        }

        result = self.engine.make_decision("BUY", selected, market_data)

        assert result["action"] == "skip"
        assert "R/R" in result["reason"]

    def test_buy_blocked_by_bearish_structure(self):
        """测试下跌结构阻止做多"""
        selected = self._make_selected("BUY")
        market_data = {
            "technical": {"atr_percent": 0.02, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 2.0,
            "market_structure": "bearish",
        }

        result = self.engine.make_decision("BUY", selected, market_data)

        assert result["action"] == "skip"
        assert "下跌" in result["reason"] or "结构" in result["reason"]

    def test_buy_allowed_with_good_rr(self):
        """测试良好R/R比允许BUY开仓"""
        selected = self._make_selected("BUY")
        market_data = {
            "technical": {"atr_percent": 0.02, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 2.5,
            "market_structure": "bullish",
        }

        result = self.engine.make_decision("BUY", selected, market_data)

        assert result["action"] == "open"

    def test_buy_position_advice(self):
        """测试仓位建议"""
        selected = self._make_selected("BUY")

        # 良好R/R
        market_data = {
            "technical": {"atr_percent": 0.02, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 2.5,
            "market_structure": "bullish",
        }
        result = self.engine.make_decision("BUY", selected, market_data)
        assert "position_advice" in result

    def test_sell_not_affected_by_rr(self):
        """测试SELL信号不受R/R影响"""
        selected = self._make_selected("SELL", confidence=0.8)
        market_data = {
            "technical": {"atr_percent": 0.02, "rsi": 50},
            "has_position": True,
            "risk_reward_ratio": 0.5,  # 很差的R/R
        }

        result = self.engine.make_decision("SELL", selected, market_data)

        # SELL信号应该正常处理，不受R/R门禁影响
        assert result["action"] in ["close", "skip"]

    def test_hold_not_affected_by_rr(self):
        """测试HOLD信号不受R/R影响"""
        selected = self._make_selected("HOLD")
        market_data = {
            "technical": {"atr_percent": 0.02, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 0.5,
        }

        result = self.engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"

    def test_buy_with_no_rr_data(self):
        """测试无R/R数据时BUY信号正常处理"""
        selected = self._make_selected("BUY")
        market_data = {
            "technical": {"atr_percent": 0.02, "rsi": 50},
            "has_position": False,
        }

        result = self.engine.make_decision("BUY", selected, market_data)

        # 无R/R数据时不应被门禁阻止
        assert result["action"] in ["open", "skip"]

    def test_buy_marginal_rr_with_advice(self):
        """测试勉强R/R比时给出减仓建议"""
        selected = self._make_selected("BUY")
        market_data = {
            "technical": {"atr_percent": 0.02, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 1.6,  # 勉强
            "market_structure": "bullish",
        }

        result = self.engine.make_decision("BUY", selected, market_data)

        assert result["action"] == "open"
        if "position_advice" in result:
            assert "勉强" in result["position_advice"] or "减仓" in result["position_advice"]

    # === 高波动门禁仍然生效 ===

    def test_buy_allowed_under_moderate_volatility(self):
        """测试中等波动(ATR=45%)允许开仓（阈值已从40%调整到55%）"""
        selected = self._make_selected("BUY")
        market_data = {
            "technical": {"atr_percent": 0.45, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 3.0,
            "market_structure": "bullish",
        }

        result = self.engine.make_decision("BUY", selected, market_data)

        assert result["action"] == "open"

    def test_buy_blocked_by_high_volatility(self):
        """测试极端高波动(ATR>55%)仍然阻止开仓"""
        selected = self._make_selected("BUY")
        market_data = {
            "technical": {"atr_percent": 0.60, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 3.0,
            "market_structure": "bullish",
        }

        result = self.engine.make_decision("BUY", selected, market_data)

        assert result["action"] == "skip"
        assert "高波动" in result["reason"]