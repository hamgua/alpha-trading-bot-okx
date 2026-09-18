"""P1: 结构性短 R/R 优质做空入口（dream 2026-09-14-okx-loss-round2）。

根因（日志证据 logs/alpha-trading-bot-okx.log.2026-09-13）:
下行趋势 4 天 (78990→76600)，6 笔开仓全 long，4 笔精确打在 -0.80% 止损。
09-13 01:18 周期: market_structure=sideways, direction=none,
short_risk_reward_ratio=2.13(good, 建议=交易), 24h 涨跌=-0.63%,
AI=HOLD(64%), 5 个策略全 HOLD(≤50%)。

压制点: decision_engine.make_decision 的 HOLD 分支中，
- market_structure_short 入口要求 direction=="short"（低波动恒 none）
- bearish_structure_short 要求 structure=="bearish"（低波动恒 sideways）
- 策略 SHORT/SELL 覆盖要求策略 confidence≥0.75（HOLD 策略只有 50%）
→ 所有做空入口全关，short_rr=2.13 的机会被浪费，只在多头方向被止损。

修复: HOLD 分支新增"结构性短 R/R 优质做空"入口（AI 和策略都 HOLD 时）:
short_rr ≥ 2.0 且 24h 市场确认为下跌 (change_percent < 0) 且 RSI>40
且 ATR 不超上限且通过 short confidence gate → 轻仓做空。
"""

from dataclasses import dataclass, field
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from alpha_trading_bot.core.decision_engine import DecisionEngine


def _config(allow_short: bool = True) -> MagicMock:
    config = MagicMock()
    config.trading.allow_short_selling = allow_short
    config.ai.fusion_threshold = 0.5
    return config


@dataclass
class _SelectedStub:
    signal: str = "HOLD"
    confidence: float = 0.5
    strategy_type: str = "trend_following"
    reasons: list = field(default_factory=list)


def _market_data(**overrides: Any) -> Dict[str, Any]:
    """构造 09-13 01:18 日志同款场景的 market_data 基线。"""
    base: Dict[str, Any] = {
        "technical": {
            "atr_percent": 0.0013,
            "rsi": 53.79,
            "trend_strength": 0.01,
        },
        "has_position": False,
        "market_structure": "sideways",
        "market_structure_direction": "none",
        "risk_reward_ratio": 0.29,
        "short_risk_reward_ratio": 2.13,
        "change_percent": -0.63,
        "min_trade_confidence": 0.40,
        "final_confidence": 0.62,
    }
    base.update(overrides)
    return base


class TestStructuralShortRROverride:
    """AI+策略都 HOLD 时，优质短 R/R + 24h 下跌确认 → 轻仓做空。"""

    def setup_method(self) -> None:
        self.config = _config()

    def test_u01_holds_with_good_short_rr_and_decline_shorts(self) -> None:
        """核心场景: 09-13 01:18 日志同款 → action=sell。"""
        engine = DecisionEngine(self.config)
        result = engine.make_decision("HOLD", _SelectedStub(), _market_data())
        assert result["action"] == "sell"
        assert result["strategy"] == "structural_short_rr_override"
        assert "覆盖AI-HOLD" in result["reason"]
        # 轻仓: 置信度被压缩
        assert result["confidence"] < 0.75

    def test_u02_rising_market_does_not_short(self) -> None:
        """24h 上涨 (change_percent>0) 时不开空。"""
        engine = DecisionEngine(self.config)
        result = engine.make_decision(
            "HOLD", _SelectedStub(), _market_data(change_percent=0.5)
        )
        assert result["action"] == "skip"

    def test_u03_zero_change_does_not_short(self) -> None:
        """change_percent=0（无方向确认）时不开空。"""
        engine = DecisionEngine(self.config)
        result = engine.make_decision(
            "HOLD", _SelectedStub(), _market_data(change_percent=0.0)
        )
        assert result["action"] == "skip"

    def test_u04_missing_change_percent_does_not_short(self) -> None:
        """缺 change_percent 字段（数据缺失）时不开空（保守默认）。"""
        data = _market_data()
        data.pop("change_percent")
        engine = DecisionEngine(self.config)
        result = engine.make_decision("HOLD", _SelectedStub(), data)
        assert result["action"] == "skip"

    def test_u05_short_rr_below_threshold_skips(self) -> None:
        """short_rr=1.5 < 2.0 时不开空。"""
        engine = DecisionEngine(self.config)
        result = engine.make_decision(
            "HOLD", _SelectedStub(), _market_data(short_risk_reward_ratio=1.5)
        )
        assert result["action"] == "skip"

    def test_u06_oversold_rsi_blocks_short(self) -> None:
        """RSI=38 < 40 超卖区禁止做空。"""
        engine = DecisionEngine(self.config)
        result = engine.make_decision(
            "HOLD",
            _SelectedStub(),
            _market_data(
                technical={"atr_percent": 0.0013, "rsi": 38.0, "trend_strength": 0.01}
            ),
        )
        assert result["action"] == "skip"

    def test_u07_high_volatility_blocks_short(self) -> None:
        """ATR=60% > 55% 高波动禁止做空。"""
        engine = DecisionEngine(self.config)
        result = engine.make_decision(
            "HOLD",
            _SelectedStub(),
            _market_data(
                technical={"atr_percent": 0.007, "rsi": 53.0, "trend_strength": 0.01}
            ),
        )
        assert result["action"] == "skip"

    def test_u08_has_position_skips_short_entry(self) -> None:
        """已有持仓时不新开空（平仓路径由其他分支负责）。"""
        engine = DecisionEngine(self.config)
        result = engine.make_decision(
            "HOLD", _SelectedStub(), _market_data(has_position=True)
        )
        assert result["action"] != "sell"

    def test_u09_short_selling_disabled_skips(self) -> None:
        """allow_short_selling=False 时不开空。"""
        engine = DecisionEngine(_config(allow_short=False))
        result = engine.make_decision("HOLD", _SelectedStub(), _market_data())
        assert result["action"] == "skip"

    def test_u10_confidence_gate_blocks_low_confidence(self) -> None:
        """final_confidence=0.30 < min_trade_confidence=0.40 时 gate 拦截。"""
        engine = DecisionEngine(self.config)
        result = engine.make_decision(
            "HOLD",
            _SelectedStub(),
            _market_data(final_confidence=0.30, min_trade_confidence=0.40),
        )
        assert result["action"] == "skip"
        assert result.get("metadata", {}).get("confidence_gate_blocked") is True

    def test_u11_ai_sell_no_position_still_skips(self) -> None:
        """回归: AI=SELL + 无持仓 仍走 skip 原路径（不改变既有行为）。"""
        engine = DecisionEngine(self.config)
        result = engine.make_decision("SELL", _SelectedStub("SELL"), _market_data())
        assert result["action"] == "skip"
        assert "SELL信号+无持仓" in result["reason"]

    def test_u12_bearish_structure_still_works(self) -> None:
        """回归: bearish 结构 + 高质量短 R/R 走原 bearish_structure_short 分支。"""
        engine = DecisionEngine(self.config)
        result = engine.make_decision(
            "HOLD",
            _SelectedStub(confidence=0.75),
            _market_data(
                market_structure="bearish",
                market_structure_direction="short",
                short_risk_reward_ratio=3.5,
                technical={"atr_percent": 0.003, "rsi": 60.0, "trend_strength": 0.30},
                final_confidence=0.75,
                mean_reversion_confirmed=True,
            ),
        )
        assert result["action"] == "sell"
