"""完整 SHORT 信号流端到端回归测试 (task-card §6 DoD)

覆盖：
1. SHORT 在 trend=up + short_rr=2.5 + ATR=3% → 能穿过 confidence_gate 进入 R/R 检查
2. SHORT 在 trend=sideways 不会再被永久封印
3. 决策引擎 R/R 后续检查仍然把关（不会被无脑放过）
"""

from dataclasses import dataclass, field
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from alpha_trading_bot.ai.integrator import AISignalIntegrator
from alpha_trading_bot.ai.integrator_config import IntegrationConfig
from alpha_trading_bot.core.decision_engine import DecisionEngine


@dataclass
class _Selected:
    signal: str = "SHORT"
    confidence: float = 0.55
    strategy_type: str = "mean_reversion"
    reasons: list = field(default_factory=list)


def _make_engine() -> DecisionEngine:
    config = MagicMock()
    config.trading.allow_short_selling = True
    config.ai.fusion_threshold = 0.5
    return DecisionEngine(config)


def _make_integrator() -> AISignalIntegrator:
    return AISignalIntegrator(
        config=IntegrationConfig(
            enable_adaptive_buy=True,
            enable_signal_optimizer=True,
            enable_high_price_filter=True,
            enable_btc_detector=True,
            enable_sustained_decline_detector=True,
        )
    )


class TestShortFlowCanPassGate:
    """端到端：SHORT 信号经过完整链路后能否离开 confidence_gate"""

    def test_short_with_good_short_rr_passes_confidence_gate(self) -> None:
        """trend=sideways (旧 bug 必然 fail), short_rr=2.5, conf=0.40 → 应能 gate 通过"""
        engine = _make_engine()
        market_data = {
            "technical": {
                "atr_percent": 0.30,
                "rsi": 60,
                "trend_strength": 0.05,
            },
            "has_position": False,
            "short_risk_reward_ratio": 2.5,
            "risk_reward_ratio": 0.5,
            "min_trade_confidence": 0.45,
            "ai_final_confidence": 0.55,  # > min_trade_confidence
            "final_confidence": 0.55,
            "market_structure": "sideways",
        }

        result = engine.make_decision("SHORT", _Selected(), market_data)

        # gate 应该通过（conf 0.55 > min 0.45）
        # 后续可能因为 R/R 不足被 RR_check 拦截，但 action 不会是 confidence_gate skip
        assert result["action"] in ("sell", "skip")
        if result["action"] == "skip":
            # 不应是 confidence_gate skip（不能含"低于阈值"）
            assert "低于阈值" not in result.get("reason", "")

    def test_short_original_35_confidence_now_clamped_to_40(self) -> None:
        """原 bug 复现：SHORT 0.50 → 经过集成后给涨到不低于 0.40"""
        integrator = _make_integrator()
        market_data = {
            "price": 64000.0,
            "technical": {
                "atr_percent": 0.003,
                "rsi": 66,
                "trend_strength": 0.05,
                "trend_direction": "sideways",
                "price_position": 0.6,
            },
            "price_history": [64000.0] * 60,
            "hourly_changes": [0.0] * 24,
            "market_structure": "sideways",
        }

        result = integrator.process(
            market_data=market_data,
            original_signal="SHORT",
            original_confidence=0.50,
        )

        # 不再是 0.35 → 至少 0.40
        assert result.final_confidence >= 0.40, (
            f"SHORT 在 sideways 不应被 floor 截断到 0.35，仍 trace 到 0.40+: "
            f"got {result.final_confidence}"
        )

    def test_short_after_integration_can_pass_gate_under_vol_rule(self) -> None:
        """真实场景：min_trade_confidence=0.40 (VolatilityRule)，SHORT conf=0.45 进入 gate"""
        engine = _make_engine()
        market_data = {
            "technical": {
                "atr_percent": 0.08,
                "rsi": 60,
                "trend_strength": 0.05,
            },
            "has_position": False,
            "short_risk_reward_ratio": 1.6,  # ≥ SHORT_RR_MODERATE_MIN=1.0 的合理水平
            "risk_reward_ratio": 0.5,
            "min_trade_confidence": 0.40,  # 模拟 VolatilityRule 输出
            "ai_final_confidence": 0.45,
            "final_confidence": 0.45,
            "market_structure": "sideways",
            "market_structure_direction": "none",
        }

        result = engine.make_decision("SHORT", _Selected(), market_data)

        # 不能是 "confidence_gate skip"
        if result["action"] == "skip":
            reason = result.get("reason", "")
            assert "低于阈值" not in reason, (
                f"VolatilityRule 0.40 + SHORT conf 0.45 应能穿过 gate: got skip={reason}"
            )

    def test_short_still_blocked_by_rr_when_short_rr_low(self) -> None:
        """验证：决策引擎的 R/R 检查未失效——short_rr=0.4 仍会被 R/R gate 拒绝"""
        engine = _make_engine()
        market_data = {
            "technical": {
                "atr_percent": 0.08,
                "rsi": 60,
                "trend_strength": 0.05,
            },
            "has_position": False,
            "short_risk_reward_ratio": 0.4,  # 远低于 SHORT_RR threshold
            "risk_reward_ratio": 0.5,
            "min_trade_confidence": 0.40,
            "ai_final_confidence": 0.50,
            "final_confidence": 0.50,
            "market_structure": "bearish",
        }

        result = engine.make_decision("SHORT", _Selected(), market_data)

        # gate 通过 → 但 R/R 检查应拦截
        assert result["action"] == "skip"
        # 不应是 confidence_gate skip
        assert "低于阈值" not in result.get("reason", "")

    def test_short_still_blocked_by_rsi_oversold(self) -> None:
        """验证：RSI<40 仍会被 RSI 超卖检查拒绝"""
        engine = _make_engine()
        market_data = {
            "technical": {
                "atr_percent": 0.08,
                "rsi": 25,  # RSI 超卖
                "trend_strength": 0.05,
            },
            "has_position": False,
            "short_risk_reward_ratio": 5.0,
            "risk_reward_ratio": 0.5,
            "min_trade_confidence": 0.40,
            "ai_final_confidence": 0.80,
            "final_confidence": 0.80,
            "market_structure": "bearish",
        }

        result = engine.make_decision("SHORT", _Selected(), market_data)

        # gate 通过 → RSI 超卖应拦截
        assert result["action"] == "skip"
        assert (
            "RSI超卖" in result.get("reason", "")
            or "RSI" in result.get("reason", "")
        )


class TestBackwardCompat:
    """确保旧路径未被破坏"""

    def test_long_with_high_confidence_still_opens(self) -> None:
        """LONG + 高置信 + 良好 R/R → 仍能 open"""
        engine = _make_engine()
        market_data = {
            "technical": {
                "atr_percent": 0.30,
                "rsi": 50,
                "trend_strength": 0.10,
            },
            "has_position": False,
            "short_risk_reward_ratio": 0,
            "risk_reward_ratio": 2.0,
            "min_trade_confidence": 0.45,
            "ai_final_confidence": 0.70,
            "final_confidence": 0.70,
        }

        selected = _Selected(signal="BUY", strategy_type="trend_following")
        result = engine.make_decision("BUY", selected, market_data)

        assert result["action"] == "open"
