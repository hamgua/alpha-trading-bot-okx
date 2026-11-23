"""Profit / TP-SL post-optimization 新增单测

覆盖优先级：
- H1-fix：OpportunityAuditor._build_gate_context 在 metadata 缺 confidence_gate_blocked 时
  仍返回 9-key dict（market_data fallback），不再返回 {}。
- M2-fix：SignalThresholdsConfig.__post_init__ 校验 confidence_floor / confidence_ceiling
  区间及交叉约束。
- ATR-SL：PositionManager.calculate_stop_price 接受可选 dynamic_atr_percent；
  传入时取 max(dyn, 0.004)；未传入时走原有路径。

> 注意：本文件只新增，不修改任何已有用例。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from numbers import Number
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest


# ============================================================
# M2-fix: SignalThresholdsConfig 校验
# ============================================================
class TestSignalThresholdsConfigConfidenceFloorCeilingValidation:
    """SignalThresholdsConfig.__post_init__ 应该校验
    confidence_floor / confidence_ceiling 区间以及 floor <= ceiling。
    """

    def _build_config(self, **overrides):
        from alpha_trading_bot.ai.integrator_config import SignalThresholdsConfig

        kwargs = dict(
            confidence_floor=0.30,
            confidence_ceiling=0.97,
        )
        kwargs.update(overrides)
        return SignalThresholdsConfig(**kwargs)

    def test_default_config_is_valid(self):
        """默认 floor/ceiling 合法."""
        cfg = self._build_config()
        assert cfg.confidence_floor == 0.30
        assert cfg.confidence_ceiling == 0.97

    def test_floor_greater_than_ceiling_raises(self):
        """floor > ceiling 应该抛 ValueError."""
        with pytest.raises(ValueError):
            self._build_config(confidence_floor=0.8, confidence_ceiling=0.5)

    def test_ceiling_smaller_than_floor_raises(self):
        """ceiling < floor 应该抛 ValueError."""
        with pytest.raises(ValueError):
            self._build_config(confidence_floor=0.4, confidence_ceiling=0.3)

    def test_floor_below_zero_raises(self):
        """floor < 0 应该抛 ValueError."""
        with pytest.raises(ValueError):
            self._build_config(confidence_floor=-0.1, confidence_ceiling=0.9)

    def test_ceiling_above_upper_bound_raises(self):
        """ceiling > 2.0 应该抛 ValueError。"""
        with pytest.raises(ValueError):
            self._build_config(confidence_floor=0.3, confidence_ceiling=2.5)

    def test_floor_nan_raises(self):
        """floor 为 NaN 应该抛 ValueError。"""
        with pytest.raises(ValueError):
            self._build_config(confidence_floor=float("nan"), confidence_ceiling=0.97)


# ============================================================
# H1-fix: OpportunityAuditor._build_gate_context fallback
# ============================================================
class TestOpportunityAuditGateContextFallback:
    """metadata 缺 confidence_gate_blocked 时 _build_gate_context 也应当
    返回非空字段（market_data fallback），便于审计可观测性。
    """

    def _setup_auditor_and_market(
        self, *, gate_blocked: bool, metadata: Dict[str, Any]
    ):
        from alpha_trading_bot.core.opportunity_audit import OpportunityAuditor

        auditor = OpportunityAuditor()
        market_data = {
            "price": 64000.0,
            "final_confidence": 0.35,
            "min_trade_confidence": 0.5,
            "short_risk_reward_ratio": 0.6,
            "risk_reward_ratio": 0.4,
            "market_structure": "sideways",
            "market_structure_direction": "none",
            "technical": {
                "rsi": 55,
                "atr_percent": 0.012,
                "trend_strength": 0.05,
            },
        }
        decision = {
            "action": "skip",
            "reason": "测试 fallback",
            "metadata": dict(metadata) if metadata is not None else {},
        }
        if gate_blocked:
            decision["metadata"]["confidence_gate_blocked"] = True
            decision["metadata"]["gate_side"] = "short"
        return auditor, decision, market_data

    def test_gate_blocked_path_returns_full_dict(self):
        """旧路径：gate_blocked=True 必须返回 9-key dict."""
        auditor, decision, market_data = self._setup_auditor_and_market(
            gate_blocked=True,
            metadata={
                "final_confidence": 0.42,
                "min_trade_confidence": 0.5,
                "long_rr": 0.4,
                "short_rr": 1.2,
                "rsi": 70,
                "trend_strength": 0.1,
                "market_structure": "bullish",
                "market_structure_direction": "long",
            },
        )
        ctx = auditor._build_gate_context(decision, market_data)
        assert isinstance(ctx, dict)
        assert ctx.get("gate_blocked") is True
        assert ctx.get("final_confidence") == 0.42
        assert "rsi" in ctx
        assert "trend_strength" in ctx
        asserted_keys = {
            "gate_blocked",
            "final_confidence",
            "min_trade_confidence",
            "long_rr",
            "short_rr",
            "rsi",
            "trend_strength",
            "market_structure",
            "market_structure_direction",
        }
        missing = asserted_keys - set(ctx.keys())
        assert not missing, f"missing keys in gate_context: {missing}"

    def test_fallback_path_returns_dict_not_empty(self):
        """新行为：metadata 缺 confidence_gate_blocked 时也返回 dict（market_data fallback）。

        之前端口的 return {} 行为将导致 818 条审计 gate_context 完全空，破坏审计可观测性。
        """
        auditor, decision, market_data = self._setup_auditor_and_market(
            gate_blocked=False,  # metadata 没写 confidence_gate_blocked
            metadata={
                "final_confidence": 0.30,
                "long_rr": 0.5,
                "rsi": 60,
                "trend_strength": 0.05,
            },
        )
        ctx = auditor._build_gate_context(decision, market_data)
        assert isinstance(ctx, dict)
        assert ctx != {}, "fallback path 必须返回非空 dict"
        # gate_blocked 字段必须存在（即使为 false）
        assert "gate_blocked" in ctx
        assert ctx.get("gate_blocked") is False
        # metadata 给出的关键字段必须可读出来；market_data / metadata 二选一可覆盖。
        tech = market_data["technical"]
        assert ctx.get("rsi") in (60, tech.get("rsi"))
        assert ctx.get("market_structure") == "sideways"
        assert ctx.get("min_trade_confidence") == 0.5

    def test_fallback_records_serializable(self):
        """fallback 字段必须可 JSON 序列化（防止 NaN/Inf 串场）。"""
        auditor, decision, market_data = self._setup_auditor_and_market(
            gate_blocked=False,
            metadata={
                "final_confidence": float("nan"),
                "long_rr": float("inf"),
                "rsi": 60,
                "trend_strength": 0.05,
            },
        )
        ctx = auditor._build_gate_context(decision, market_data)
        for k, v in ctx.items():
            assert isinstance(v, (str, bool, int, float, type(None)))
        serialized = json.dumps(ctx, ensure_ascii=False, sort_keys=True)
        assert "NaN" not in serialized
        assert "Infinity" not in serialized
        assert ctx.get("final_confidence") == 0.0
        assert ctx.get("long_rr") == 0.0


# ============================================================
# ATR-SL: PositionManager.calculate_stop_price dynamic_atr_percent
# ============================================================
class TestPositionManagerDynamicAtrStopLoss:
    """calculate_stop_price 入参增加关键字参数 dynamic_atr_percent。

    - 不传入时：原路径不变（保留 _calculate_entry_based_stop_loss）。
    - 传入时：止损失效百分比 = max(dynamic_atr_percent, 0.004)，下限 0.30 %.
    """

    def _build_manager(self, *, dynamic_atr: Optional[float] = None):
        from alpha_trading_bot.core.position_manager import PositionManager, Position

        mgr = PositionManager.__new__(PositionManager)
        mgr.config = MagicMock()
        # 旧止损相关 0.5% 路径不会被使用（测试只走新路径或默认路径）。
        mgr.config.stop_loss.stop_loss_entry_based = True
        mgr.config.stop_loss.stop_loss_percent = 0.005
        mgr.config.stop_loss.min_profit_to_tighten_stop_percent = 0.0005
        mgr.config.stop_loss.price_vs_entry_tolerance_percent = 0.0001
        mgr.config.stop_loss.stop_loss_profit_percent = 0.002
        mgr.config.stop_loss.take_profit_percent = 0.006
        mgr.config.stop_loss.min_net_profit_to_close_percent = 0
        # 开仓信息：long 仓位，EntryPrice=71900.
        mgr._position = Position(
            symbol="BTC-USDT-SWAP",
            side="long",
            amount=0.01,
            entry_price=71900.0,
            unrealized_pnl=0.0,
        )
        mgr._entry_price = 71900.0
        mgr._highest_price_since_entry = 71900.0
        mgr._lowest_price_since_entry = 71900.0
        mgr._entry_dynamic_stop_loss_percent = None
        return mgr

    def test_default_path_uses_existing_logic(self):
        """不传入 dynamic_atr_percent 时与原路径完全一致。"""
        mgr = self._build_manager(dynamic_atr=None)
        cur = 71800.0
        stop = mgr.calculate_stop_price(cur)
        # 当前位置 < 入场 → 走 _calculate_entry_based_stop_loss 的亏损分支
        # 旧止损 0.5% → 71900 * 0.995 = 71540.5
        assert stop == pytest.approx(71540.5, rel=1e-6)

    def test_dynamic_atr_percent_above_floor_uses_atr(self):
        """传入 dynamic_atr_percent=0.012 (高于 0.004) → 取 0.012 → entry*0.988。"""
        mgr = self._build_manager()
        cur = 71800.0
        stop = mgr.calculate_stop_price(cur, dynamic_atr_percent=0.012)
        # stop = 71900 * (1 - 0.012) = 71037.2
        assert stop == pytest.approx(71037.2, rel=1e-4)

    def test_dynamic_atr_percent_below_floor_uses_floor(self):
        """传入 dynamic_atr_percent=0.002 (低于 0.003) → 取 0.003 → entry*0.997。"""
        mgr = self._build_manager()
        cur = 71800.0
        stop = mgr.calculate_stop_price(cur, dynamic_atr_percent=0.002)
        # stop = 71900 * (1 - 0.003) = 71684.3
        assert stop == pytest.approx(71684.3, rel=1e-4)

    def test_dynamic_atr_percent_lower_bound_3_pct_capped(self):
        """止损下限 ≥ 0.30 % 保护 (防止 0.001 这类过近距离)。"""
        mgr = self._build_manager()
        cur = 71800.0
        stop = mgr.calculate_stop_price(cur, dynamic_atr_percent=0.001)
        # stop = 71900 * (1 - 0.003) = 71684.3 (0.30 % 下限)
        expected = 71900.0 * (1 - 0.003)
        assert stop == pytest.approx(expected, rel=1e-4)
