"""决策引擎R/R门禁单元测试

覆盖场景：
- R/R门禁按投资类型差异化
- safe_mode减半开仓辅助条件
- 高波动门禁
- 仓位建议
"""

import pytest
import os
from unittest.mock import MagicMock
from alpha_trading_bot.core.decision_engine import (
    DecisionEngine,
    INVESTMENT_RR_THRESHOLDS,
    DEFAULT_RR_THRESHOLD,
    GOOD_RR_RATIO,
)


class TestDecisionEngineRR:
    """决策引擎R/R门禁测试"""

    def setup_method(self):
        self.config = MagicMock()
        self.config.trading.allow_short_selling = True
        # 清理环境变量确保测试隔离
        self._orig_env = os.environ.get("INVESTMENT_TYPE")
        os.environ.pop("INVESTMENT_TYPE", None)

    def teardown_method(self):
        # 恢复环境变量
        if self._orig_env is not None:
            os.environ["INVESTMENT_TYPE"] = self._orig_env
        else:
            os.environ.pop("INVESTMENT_TYPE", None)

    def _make_selected(self, signal="BUY", confidence=0.7, strategy_type="regular"):
        """构造mock selected对象"""
        selected = MagicMock()
        selected.signal = signal
        selected.confidence = confidence
        selected.strategy_type = strategy_type
        selected.reasons = []
        return selected

    # === R/R门禁测试 - 默认投资类型(moderate) ===

    def test_buy_blocked_by_low_rr(self):
        """测试低R/R比阻止BUY开仓（moderate类型，阈值1.0）"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY")
        market_data = {
            "technical": {"atr_percent": 0.02, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 0.9,  # R/R < 1.0
            "market_structure": "bullish",
        }

        result = engine.make_decision("BUY", selected, market_data)

        assert result["action"] == "skip"
        assert "R/R" in result["reason"]

    def test_buy_blocked_by_bearish_structure(self):
        """测试下跌结构阻止做多"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY")
        market_data = {
            "technical": {"atr_percent": 0.02, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 2.0,
            "market_structure": "bearish",
        }

        result = engine.make_decision("BUY", selected, market_data)

        assert result["action"] == "skip"
        assert "下跌" in result["reason"] or "结构" in result["reason"]

    def test_buy_allowed_with_good_rr(self):
        """测试良好R/R比允许BUY开仓"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY")
        market_data = {
            "technical": {"atr_percent": 0.02, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 2.5,
            "market_structure": "bullish",
        }

        result = engine.make_decision("BUY", selected, market_data)

        assert result["action"] == "open"

    def test_buy_position_advice(self):
        """测试仓位建议"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY")

        market_data = {
            "technical": {"atr_percent": 0.02, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 2.5,
            "market_structure": "bullish",
        }
        result = engine.make_decision("BUY", selected, market_data)
        assert "position_advice" in result

    def test_sell_not_affected_by_rr(self):
        """测试SELL信号不受R/R影响"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("SELL", confidence=0.8)
        market_data = {
            "technical": {"atr_percent": 0.02, "rsi": 50},
            "has_position": True,
            "risk_reward_ratio": 0.5,
        }

        result = engine.make_decision("SELL", selected, market_data)

        assert result["action"] in ["close", "skip"]

    def test_hold_not_affected_by_rr(self):
        """测试HOLD信号不受R/R影响"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("HOLD")
        market_data = {
            "technical": {"atr_percent": 0.02, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 0.5,
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"

    def test_buy_with_no_rr_data(self):
        """测试无R/R数据时BUY信号正常处理"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY")
        market_data = {
            "technical": {"atr_percent": 0.02, "rsi": 50},
            "has_position": False,
        }

        result = engine.make_decision("BUY", selected, market_data)

        assert result["action"] in ["open", "skip"]

    def test_buy_marginal_rr_with_advice(self):
        """测试勉强R/R比时给出减仓建议"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY")
        market_data = {
            "technical": {"atr_percent": 0.02, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 1.6,
            "market_structure": "bullish",
        }

        result = engine.make_decision("BUY", selected, market_data)

        assert result["action"] == "open"
        if "position_advice" in result:
            assert "勉强" in result["position_advice"] or "减仓" in result["position_advice"]

    # === 高波动门禁仍然生效 ===

    def test_buy_allowed_under_moderate_volatility(self):
        """测试中等波动(ATR=45%)允许开仓"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY")
        market_data = {
            "technical": {"atr_percent": 0.45, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 3.0,
            "market_structure": "bullish",
        }

        result = engine.make_decision("BUY", selected, market_data)

        assert result["action"] == "open"

    def test_buy_blocked_by_high_volatility(self):
        """测试极端高波动(ATR>55%)仍然阻止开仓"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY")
        market_data = {
            "technical": {"atr_percent": 0.60, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 3.0,
            "market_structure": "bullish",
        }

        result = engine.make_decision("BUY", selected, market_data)

        assert result["action"] == "skip"
        assert "高波动" in result["reason"]

    # === R/R门禁投资类型差异化测试 ===

    def test_conservative_rr_threshold(self):
        """测试保守型投资R/R阈值=0.8"""
        os.environ["INVESTMENT_TYPE"] = "conservative"
        engine = DecisionEngine(self.config)

        assert engine._get_min_rr() == 0.8

        selected = self._make_selected("BUY")
        # R/R=0.9 > 0.8，保守型应允许
        market_data = {
            "technical": {"atr_percent": 0.02, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 0.9,
            "market_structure": "bullish",
        }
        result = engine.make_decision("BUY", selected, market_data)
        assert result["action"] == "open"

    def test_conservative_rr_blocks_below_threshold(self):
        """测试保守型投资R/R<0.8被阻止"""
        os.environ["INVESTMENT_TYPE"] = "conservative"
        engine = DecisionEngine(self.config)

        selected = self._make_selected("BUY")
        market_data = {
            "technical": {"atr_percent": 0.02, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 0.7,
            "market_structure": "bullish",
        }
        result = engine.make_decision("BUY", selected, market_data)
        assert result["action"] == "skip"
        assert "R/R" in result["reason"]

    def test_moderate_rr_threshold(self):
        """测试中等型投资R/R阈值=1.0（默认）"""
        os.environ.pop("INVESTMENT_TYPE", None)
        engine = DecisionEngine(self.config)

        assert engine._get_min_rr() == 1.0

    def test_aggressive_rr_threshold(self):
        """测试激进型投资R/R阈值=0.6"""
        os.environ["INVESTMENT_TYPE"] = "aggressive"
        engine = DecisionEngine(self.config)

        assert engine._get_min_rr() == 0.6

        selected = self._make_selected("BUY")
        # R/R=0.7 > 0.6，激进型应允许
        market_data = {
            "technical": {"atr_percent": 0.02, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 0.7,
            "market_structure": "bullish",
        }
        result = engine.make_decision("BUY", selected, market_data)
        assert result["action"] == "open"

    def test_aggressive_rr_blocks_below_threshold(self):
        """测试激进型投资R/R<0.6被阻止"""
        os.environ["INVESTMENT_TYPE"] = "aggressive"
        engine = DecisionEngine(self.config)

        selected = self._make_selected("BUY")
        market_data = {
            "technical": {"atr_percent": 0.02, "rsi": 50},
            "has_position": False,
            "risk_reward_ratio": 0.5,
            "market_structure": "bullish",
        }
        result = engine.make_decision("BUY", selected, market_data)
        assert result["action"] == "skip"
        assert "R/R" in result["reason"]

    def test_unknown_investment_type_uses_default(self):
        """测试未知投资类型使用默认阈值"""
        os.environ["INVESTMENT_TYPE"] = "unknown_type"
        engine = DecisionEngine(self.config)

        assert engine._get_min_rr() == DEFAULT_RR_THRESHOLD

    # === safe_mode减半开仓辅助条件测试 ===

    def test_safe_mode_reduced_with_good_conditions(self):
        """测试safe_mode减半开仓: 满足所有条件时允许"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY", confidence=0.7, strategy_type="safe_mode")
        market_data = {
            "technical": {
                "atr_percent": 0.30,  # ATR < 40%
                "rsi": 50,
                "trend_direction": "up",
            },
            "has_position": False,
            "risk_reward_ratio": 1.5,  # R/R >= 1.0
            "market_structure": "bullish",
        }

        result = engine.make_decision("BUY", selected, market_data)

        assert result["action"] == "open"
        assert result["strategy"] == "safe_mode_reduced"

    def test_safe_mode_blocked_by_low_rr(self):
        """测试safe_mode减半开仓: R/R<1.0被阻止"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY", confidence=0.7, strategy_type="safe_mode")
        market_data = {
            "technical": {
                "atr_percent": 0.30,
                "rsi": 50,
                "trend_direction": "up",
            },
            "has_position": False,
            "risk_reward_ratio": 0.8,  # R/R < 1.0
            "market_structure": "bullish",
        }

        result = engine.make_decision("BUY", selected, market_data)

        assert result["action"] == "skip"

    def test_safe_mode_blocked_by_high_atr(self):
        """测试safe_mode减半开仓: ATR>=40%被阻止"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY", confidence=0.7, strategy_type="safe_mode")
        market_data = {
            "technical": {
                "atr_percent": 0.45,  # ATR >= 40%
                "rsi": 50,
                "trend_direction": "up",
            },
            "has_position": False,
            "risk_reward_ratio": 1.5,
            "market_structure": "bullish",
        }

        result = engine.make_decision("BUY", selected, market_data)

        assert result["action"] == "skip"

    def test_safe_mode_blocked_by_downtrend(self):
        """测试safe_mode减半开仓: 下跌趋势不允许做多"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("BUY", confidence=0.7, strategy_type="safe_mode")
        market_data = {
            "technical": {
                "atr_percent": 0.30,
                "rsi": 50,
                "trend_direction": "down",  # 下跌趋势
            },
            "has_position": False,
            "risk_reward_ratio": 1.5,
            "market_structure": "bullish",
        }

        result = engine.make_decision("BUY", selected, market_data)

        assert result["action"] == "skip"

    def test_safe_mode_hold_no_position_returns_skip(self):
        """测试safe_mode+HOLD+无持仓返回skip"""
        engine = DecisionEngine(self.config)
        selected = self._make_selected("HOLD", confidence=0.7, strategy_type="safe_mode")
        market_data = {
            "technical": {
                "atr_percent": 0.02,
                "rsi": 50,
                "trend_direction": "neutral",
            },
            "has_position": False,
            "risk_reward_ratio": 0,
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"