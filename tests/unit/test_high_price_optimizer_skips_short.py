"""HighPriceBuyOptimizer 对 SHORT/SELL 信号豁免回归测试 (task-card R2 / R3)

覆盖：
1. SHORT 信号 high_price_optimizer 不被调用 (integrator 短路)
2. SELL 信号 high_price_optimizer 不被调用
3. BUY 信号仍被正常调用 (向后兼容)
4. integrated_confidence_floor 在 BUY 路径上生效
"""

from dataclasses import dataclass, field
from typing import Dict, Any
from unittest.mock import patch

import pytest

from alpha_trading_bot.ai.integrator import AISignalIntegrator
from alpha_trading_bot.ai.integrator_config import IntegrationConfig
from alpha_trading_bot.ai.high_price_buy_optimizer import (
    HighPriceBuyConfig,
    HighPriceBuyOptimizer,
)


@dataclass
class _BaseData:
    _dummy: int = 0


def _market_data(sideways: bool = True) -> Dict[str, Any]:
    return {
        "price": 64000.0,
        "technical": {
            "trend_direction": "sideways" if sideways else "up",
            "trend_strength": 0.05,
            "rsi": 70,
            "atr_percent": 0.003,
            "price_position": 0.7,  # 价格位置偏高
        },
        "price_history": [64000.0] * 60,
        "hourly_changes": [0.0] * 24,
    }


class TestHighPriceOptimizerShortedForNonBuy:
    """验证：SHORT/SELL 信号在 integrator 内部被短路。"""

    def test_short_signal_does_not_call_high_price_optimizer(self) -> None:
        with patch.object(
            HighPriceBuyOptimizer,
            "optimize_high_price_buy",
            side_effect=AssertionError("SHORT 信号不应调用 high_price_optimizer"),
        ) as _:
            integrator = AISignalIntegrator(
                config=IntegrationConfig(
                    enable_adaptive_buy=True,
                    enable_signal_optimizer=True,
                    enable_high_price_filter=True,
                    enable_btc_detector=True,
                    enable_sustained_decline_detector=True,
                )
            )
            result = integrator.process(
                market_data=_market_data(),
                original_signal="SHORT",
                original_confidence=0.50,
            )
            assert result.final_signal in ("SHORT", "HOLD")

    def test_sell_signal_does_not_call_high_price_optimizer(self) -> None:
        with patch.object(
            HighPriceBuyOptimizer,
            "optimize_high_price_buy",
            side_effect=AssertionError("SELL 信号不应调用 high_price_optimizer"),
        ) as _:
            integrator = AISignalIntegrator()
            result = integrator.process(
                market_data=_market_data(),
                original_signal="SELL",
                original_confidence=0.50,
            )
            assert result.final_signal in ("SELL", "HOLD")

    def test_hold_signal_does_not_call_high_price_optimizer(self) -> None:
        """HOLD 信号本来就被 is_hold_signal=True 跳过，现在更彻底"""
        with patch.object(
            HighPriceBuyOptimizer,
            "optimize_high_price_buy",
            side_effect=AssertionError("HOLD 信号不应调用 high_price_optimizer"),
        ) as _:
            integrator = AISignalIntegrator()
            integrator.process(
                market_data=_market_data(),
                original_signal="HOLD",
                original_confidence=0.50,
            )

    def test_buy_signal_still_calls_high_price_optimizer(self) -> None:
        """向后兼容：BUY 信号仍走 high_price_optimizer 路径"""
        called = []

        def _spy(self, market_data, original_confidence, original_can_buy, buy_mode, original_signal):
            called.append(original_signal)
            from alpha_trading_bot.ai.high_price_buy_optimizer import HighPriceBuyResult
            return HighPriceBuyResult(
                adjusted_confidence=original_confidence,
                price_level="mid",
                adjustment_reason="无调整",
                should_buy=True,
                penalty_applied=False,
                details={},
            )

        with patch.object(
            HighPriceBuyOptimizer, "optimize_high_price_buy", _spy
        ):
            integrator = AISignalIntegrator()
            integrator.process(
                market_data=_market_data(),
                original_signal="BUY",
                original_confidence=0.65,
            )

        assert called == ["BUY"]


class TestHighPriceConfigIntegratedFloor:
    """验证：integrated_confidence_floor 字段生效"""

    def test_floor_default_value_matches_old_magic_35(self) -> None:
        cfg = HighPriceBuyConfig()
        assert cfg.integrated_confidence_floor == 0.35

    def test_floor_configurable(self) -> None:
        cfg = HighPriceBuyConfig(integrated_confidence_floor=0.5)
        assert cfg.integrated_confidence_floor == 0.5

    def test_floor_used_in_buy_optimization(self) -> None:
        """high_price_optimizer 的 BUY 路径 floor 仍生效"""
        cfg = HighPriceBuyConfig(integrated_confidence_floor=0.42)
        opt = HighPriceBuyOptimizer(cfg)
        market_data = {
            "price": 65000.0,
            "technical": {
                "rsi": 80,  # 远超 rsi_threshold_high=70 → 触发 RSI 惩罚
                "trend_strength": 0.05,  # 远低于 trend_threshold
                "price_position": 0.85,  # 远超 price_position_threshold_high=0.70
                "trend_direction": "sideways",
            },
            "price_history": [65000.0] * 60,
        }
        result = opt.optimize_high_price_buy(
            market_data=market_data,
            original_confidence=0.65,  # 高于 0.75 检查不会触发 6.1
            original_can_buy=True,
            buy_mode="high",  # 强制 high 路径
            original_signal="BUY",
        )

        # 多个惩罚叠加，但 floor 是 0.42，所以不应低于 0.42
        assert result.adjusted_confidence >= 0.42
