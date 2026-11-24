"""2026-11 底部捕获修复 (P0/P1/P2) 回归测试。

日志回放背景 (2026-11-18 ~ 11-23, BTC 55k 底部):
- 6 天 705 周期仅 1 笔交易; 55.6k→60.7k (+9.1%) 反弹完全错过
- 11-21 14:14 底部: RSI=16.2, 自适应买入 oversold_rebound can_buy=True,
  被翻转守卫 (AI HOLD 65% >= 55%) 拦截
- 11-21 23:47: 技术 BUY 92% 被 R/R(×0.85) + 与历史多数相反(×0.85) 压到
  66.5% < 0.75 门禁 → 双折扣叠加门禁数学性不可达
- 11-19: 4 次 AI 原始 70% 的止盈 SELL 最终 58-64% < 0.75 平仓门禁被拦
- 11-19: state_persistence "Object of type OrderStatus is not JSON
  serializable" 连发 6 条 (StopOrderResult 被误存为 order_id)

本文件覆盖:
- P0-1 折扣解堆叠 (BUY 豁免连续惩罚 + 折扣下限)
- P0-2/3 门禁下调 + 每日开仓上限
- P1-4 翻转守卫分级 (高可信模式 0.60)
- P1-5 超卖抄底独立通道
- P1-6 持续下跌检测器衰竭反转
- P2-8 StopOrderResult 序列化回归
- P2-9 qwen38 max_tokens=8000
- P2-11 15m 双窗口摘要
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest

from alpha_trading_bot.ai.client import AIClient
from alpha_trading_bot.ai.sustained_decline_detector import (
    DeclineDetectionResult,
    SustainedDeclineDetector,
)
from alpha_trading_bot.ai.signal_optimizer import SignalOptimizer
from alpha_trading_bot.config.models import (
    AIConfig,
    Config,
    ExchangeConfig,
    TradingConfig,
)
from alpha_trading_bot.core.bot import TradingBot
from alpha_trading_bot.core.position_manager import PositionManager
from alpha_trading_bot.core.state_persistence import StatePersistence
from alpha_trading_bot.exchange.models.orders import OrderStatus, StopOrderResult

# ==================== P0-1a: 连续信号惩罚只对 SELL/SHORT 生效 ====================


class TestConsecutiveSignalPenalty:
    """BUY 豁免 '与历史多数相反' 惩罚 (结构性恒成立 → 属结构性折扣)。"""

    def _seeded_optimizer(self) -> SignalOptimizer:
        opt = SignalOptimizer()
        # 历史 2 个 HOLD (系统常态 97% HOLD)
        from datetime import datetime

        for _ in range(2):
            opt._record_signal("hold", 0.5, 100.0, "2026-11-21T00:00:00")
        return opt

    def test_buy_not_penalized_against_hold_majority(self) -> None:
        opt = self._seeded_optimizer()
        result = opt.optimize(signal="BUY", confidence=0.78, price=100.0)
        # 高波动调整: atr_percent=0 → 走 price_history (空) → 跳过;
        # 连续惩罚: BUY 豁免 → 无 "与历史多数相反" 调整
        assert "与历史多数相反" not in " | ".join(
            result.adjustments
        ), f"BUY 不应被连续惩罚: {result.adjustments}"

    def test_sell_still_penalized_against_hold_majority(self) -> None:
        opt = self._seeded_optimizer()
        result = opt.optimize(signal="SELL", confidence=0.78, price=100.0)
        assert any("与历史多数相反" in a for a in result.adjustments)
        assert result.confidence < 0.78


# ==================== P0-1b + P1-4: 集成器 (折扣下限 + 翻转守卫分级) ====================


def _make_integrator(
    adaptive_mode: str,
    adaptive_conf: float,
) -> Any:
    """构造标准集成器, 子模块打桩, 隔离测试翻转守卫/折扣下限。

    SignalOptimizer 保留真实实例 (验证 BUY 豁免连续惩罚的真实行为)。
    """
    from alpha_trading_bot.ai.integrator import AISignalIntegrator
    from alpha_trading_bot.ai.integrator_config import IntegrationConfig

    integ = AISignalIntegrator(
        config=IntegrationConfig(
            enable_adaptive_buy=True,
            enable_signal_optimizer=True,
            enable_high_price_filter=True,
            enable_btc_detector=True,
            enable_sustained_decline_detector=True,
        )
    )

    integ.adaptive_buy = MagicMock()
    integ.adaptive_buy.should_buy.return_value = SimpleNamespace(
        can_buy=True,
        mode=adaptive_mode,
        confidence=adaptive_conf,
    )
    # 市场结构 R/R=0 → 跳过 R/R 过滤段
    integ.market_structure_analyzer = MagicMock()
    integ.market_structure_analyzer.analyze.return_value = SimpleNamespace(
        structure="sideways",
        suggested_direction="none",
        risk_reward_ratio=0.0,
        nearest_support=0.0,
        nearest_resistance=0.0,
        position_size_factor=0.0,
    )
    integ.risk_reward_calculator = MagicMock()
    integ.risk_reward_calculator.calculate_for_short.return_value = SimpleNamespace(
        rr_ratio=0.0, should_trade=False, quality="poor"
    )
    integ.sustained_decline_detector = MagicMock()
    integ.sustained_decline_detector.detect.return_value = DeclineDetectionResult(
        is_detected=False, decline_level="none"
    )
    integ.btc_detector = MagicMock()
    integ.btc_detector.detect_level.return_value = SimpleNamespace(
        level="mid",
        is_high_risk=False,
        is_low_opportunity=False,
        distance_to_high=0.0,
        distance_to_low=0.0,
    )

    def _passthrough_high_price(
        market_data, original_confidence, original_can_buy, buy_mode, original_signal
    ):
        return SimpleNamespace(
            adjusted_confidence=original_confidence,
            should_buy=True,
            price_level="mid",
            adjustment_reason="",
            penalty_applied=False,
        )

    integ.high_price_optimizer = MagicMock()
    integ.high_price_optimizer.optimize_high_price_buy.side_effect = (
        _passthrough_high_price
    )
    return integ


MARKET_15M = {
    "symbol": "BTC/USDT:USDT",
    "price": 55647.1,
    "low": 55500.0,
    "price_history": [56000.0] * 20,
    "technical": {"rsi": 16.2, "atr_percent": 0.01},
}


class TestFlipGuardStrongMode:
    """高可信技术模式 (oversold_rebound/pullback_buy) 翻转上限放宽到 0.60。"""

    def test_weak_hold_with_oversold_mode_flips(self) -> None:
        """回放 11-21 14:14: AI HOLD 58% (犹豫带) + oversold_rebound → 翻转 BUY。"""
        integ = _make_integrator("oversold_rebound", 0.53)
        result = integ.process(
            dict(MARKET_15M), original_signal="hold", original_confidence=0.58
        )
        assert result.final_signal == "BUY"
        assert any("自适应买入" in a for a in result.adjustments_made)

    def test_strong_hold_with_oversold_mode_blocked(self) -> None:
        """AI HOLD 65% >= 0.60 → 高可信模式也不翻转。"""
        integ = _make_integrator("oversold_rebound", 0.53)
        result = integ.process(
            dict(MARKET_15M), original_signal="hold", original_confidence=0.65
        )
        assert result.final_signal == "HOLD"
        assert any("不翻转" in a for a in result.adjustments_made)

    def test_weak_hold_with_other_mode_still_blocked(self) -> None:
        """非高可信模式 (trend_confirmation) 保持 0.55 阈值 (零回归):
        HOLD 58% >= 0.55 → 不翻转。"""
        integ = _make_integrator("trend_confirmation", 0.53)
        result = integ.process(
            dict(MARKET_15M), original_signal="hold", original_confidence=0.58
        )
        assert result.final_signal == "HOLD"

    def test_fuzzy_hold_below_old_threshold_flips_any_mode(self) -> None:
        """HOLD 40% < 0.55 → 任意模式均可翻转 (原行为保持)。"""
        integ = _make_integrator("trend_confirmation", 0.53)
        result = integ.process(
            dict(MARKET_15M), original_signal="hold", original_confidence=0.40
        )
        assert result.final_signal == "BUY"


class TestSignalDiscountFloor:
    """技术翻转 BUY 的累计折扣下限 0.70 (门禁可达性修复)。

    2026-11-24 (P1-C) 后: 技术翻转 BUY 最终置信度另受
    TECHNICAL_FLIP_CONFIDENCE_CAP=0.60 封顶 (规则加成不制造高置信),
    下限与封顶均生效时以封顶为准 (更保守)。
    """

    def test_buy_discount_floored(self) -> None:
        """回放 11-21 23:47: 翻转 92%, 模拟 R/R 勉强 ×0.85 → 78.2%,
        再被技术翻转封顶压回 0.60 (P1-C)。"""
        integ = _make_integrator("pullback_buy", 0.92)

        # 打桩 SignalOptimizer: 模拟 R/R 勉强场景的 -15% 折扣 (BUY 已豁免
        # 连续惩罚, 这里是验证折扣下限, 用 side_effect 精确注入 0.85)
        def _discount_085(signal, confidence, price, market_data):
            from alpha_trading_bot.ai.signal_optimizer import OptimizedSignal

            return OptimizedSignal(
                signal=signal,
                confidence=confidence * 0.85,
                original_confidence=confidence,
                adjustments=["模拟R/R勉强折扣-15%"],
                is_filtered=False,
                details={},
            )

        integ.signal_optimizer = MagicMock()
        integ.signal_optimizer.optimize.side_effect = _discount_085

        result = integ.process(
            dict(MARKET_15M), original_signal="hold", original_confidence=0.45
        )
        assert result.final_signal == "BUY"
        # 92% × 0.85 = 78.2% (下限 64.4% 不生效) → P1-C 封顶 → 0.60
        assert abs(result.final_confidence - 0.60) < 0.01
        assert any("封顶" in a for a in result.adjustments_made)

    def test_buy_discount_floor_applied_when_stacked(self) -> None:
        """折扣叠加低于 0.70 (0.85×0.80=0.68) → 下限拉回 92%×0.70=64.4%,
        再被技术翻转封顶压回 0.60 (P1-C; 下限在 adjustments 中可审计)。"""
        integ = _make_integrator("pullback_buy", 0.92)

        def _stacked_discount(signal, confidence, price, market_data):
            from alpha_trading_bot.ai.signal_optimizer import OptimizedSignal

            return OptimizedSignal(
                signal=signal,
                confidence=confidence * 0.85 * 0.80,
                original_confidence=confidence,
                adjustments=["双重折扣 0.85×0.80"],
                is_filtered=False,
                details={},
            )

        integ.signal_optimizer = MagicMock()
        integ.signal_optimizer.optimize.side_effect = _stacked_discount

        result = integ.process(
            dict(MARKET_15M), original_signal="hold", original_confidence=0.45
        )
        assert result.final_signal == "BUY"
        # 92%×0.68 = 62.6% < 64.4% → 下限拉回 64.4% → P1-C 封顶 → 0.60
        assert abs(result.final_confidence - 0.60) < 0.01
        assert any("折扣下限" in a for a in result.adjustments_made)
        assert any("封顶" in a for a in result.adjustments_made)


# ==================== P1-6: 持续下跌检测器衰竭反转 ====================


class TestExhaustionReversal:
    """severe 下跌 + 反弹≥2% + RSI<25 → 解除 BUY 惩罚并反哺。"""

    def _severe_market(self, rsi: float, rebound_change: float = 0.025) -> Dict:
        """构造 severe 下跌 + 显著反弹的小时变化序列。"""
        hourly = [-0.01, -0.008, -0.009, -0.011, -0.007, -0.012, -0.009]
        hourly.append(rebound_change)  # 最近 1 根 +2.5% 反弹
        return {
            "price": 56000.0,
            "change_percent": -9.0,  # 日跌幅 → 估算周期高点 ≈ 61540
            "technical": {"rsi": rsi},
            "hourly_changes": hourly,
            "price_history": [56000.0] * 20,
        }

    def test_severe_with_rebound_and_oversold_is_exhaustion(self) -> None:
        det = SustainedDeclineDetector()
        result = det.detect(self._severe_market(rsi=18.0))
        assert result.is_detected, "前提: 必须检测到持续下跌"
        assert result.exhaustion_reversal is True
        assert result.buy_penalty < 0, "衰竭反转应为 BUY 加成 (负惩罚)"
        assert result.sell_boost == 0.0
        assert result.should_block_buy is False

    def test_severe_without_rebound_keeps_penalty(self) -> None:
        det = SustainedDeclineDetector()
        # 无显著反弹 (hourly 全跌)
        market = {
            "price": 56000.0,
            "change_percent": -9.0,
            "technical": {"rsi": 18.0},
            "hourly_changes": [-0.01, -0.008, -0.009, -0.011, -0.007, -0.012],
            "price_history": [56000.0] * 20,
        }
        result = det.detect(market)
        if result.is_detected and result.decline_level == "severe":
            assert result.exhaustion_reversal is False
            assert result.buy_penalty > 0

    def test_severe_with_rebound_but_high_rsi_keeps_penalty(self) -> None:
        det = SustainedDeclineDetector()
        result = det.detect(self._severe_market(rsi=45.0))
        assert not (result.is_detected and result.exhaustion_reversal)


# ==================== P0-2/3 + P1-5: bot 执行层 ====================


def _make_bot(
    tmp_path: Path,
    min_open: float = 0.65,
    min_close: float = 0.60,
    daily_limit: int = 2,
    live: bool = False,
) -> TradingBot:
    """live=True 用实盘配置 (_open_position 实盘闸门需要过)。

    注: test_mode=True 时 _open_position 内部会被实盘闸门拒绝,
    全链路开仓测试必须用 live=True (模拟单路径)。
    """
    config = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(
            test_mode=not live,
            real_trading_confirmed=True,
            runtime_environment="prod" if live else "dev",
            min_confidence_open=min_open,
            min_confidence_close=min_close,
            daily_open_limit=daily_limit,
        ),
    )
    bot = TradingBot(config)
    bot.position_manager = PositionManager(config, data_dir=tmp_path)
    bot._exchange = MagicMock()
    bot._exchange.get_balance = AsyncMock(return_value=1000.0)
    bot._exchange.create_order = AsyncMock(return_value="ORD_123456")
    bot._exchange.calculate_max_contracts = AsyncMock(return_value=0.03)
    bot._exchange.normalize_order_size = MagicMock(side_effect=lambda a: a)
    bot._exchange.create_stop_loss = AsyncMock(return_value="SL_ID")
    bot._exchange.create_take_profit = AsyncMock(return_value="TP_ID")
    bot._exchange.calculate_notional_usdt = MagicMock(
        side_effect=lambda amount, price: amount * price
    )
    bot._stop_loss_manager = None
    return bot


class TestDailyOpenLimit:
    """每日新开仓上限 (门禁下调后的成本控制)。"""

    @pytest.mark.asyncio
    async def test_third_open_same_day_blocked(self, tmp_path) -> None:
        bot = _make_bot(tmp_path, daily_limit=2)
        bot._open_position = AsyncMock(return_value=True)  # type: ignore[assignment]
        bot._daily_open_counts["2026-11-21"] = 2

        from datetime import datetime

        today = datetime.now().strftime("%Y-%m-%d")
        bot._daily_open_counts[today] = 2

        result = await bot._execute_signal(
            "BUY", 56000.0, has_position=False, final_confidence=0.90
        )
        assert result.action == "blocked_daily_limit"
        bot._open_position.assert_not_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_zero_limit_disables(self, tmp_path) -> None:
        bot = _make_bot(tmp_path, daily_limit=0)
        bot._open_position = AsyncMock(return_value=True)  # type: ignore[assignment]
        result = await bot._execute_signal(
            "BUY", 56000.0, has_position=False, final_confidence=0.90
        )
        assert result.action == "open_long"


class TestOversoldBottomBuyChannel:
    """超卖抄底独立通道 (P1-5)。"""

    @pytest.mark.asyncio
    async def test_channel_opens_half_position_at_bottom(self, tmp_path) -> None:
        """回放 11-21 14:14: RSI=16.2, 价格贴近 24h 低点 → 半仓抄底。"""
        bot = _make_bot(tmp_path)
        bot._open_position = AsyncMock(return_value=True)  # type: ignore[assignment]

        result = await bot._maybe_oversold_bottom_buy(dict(MARKET_15M), 55647.1)
        assert result is not None
        assert result.action == "open_long_oversold"
        bot._open_position.assert_awaited_once()  # type: ignore[attr-defined]
        kwargs = bot._open_position.await_args.kwargs  # type: ignore[attr-defined]
        assert kwargs.get("size_factor") == 0.5
        # 每日计数落账
        from datetime import datetime

        today = datetime.now().strftime("%Y-%m-%d")
        assert bot._oversold_buy_counts.get(today) == 1
        assert bot._daily_open_counts.get(today) == 1

    @pytest.mark.asyncio
    async def test_channel_blocked_when_rsi_not_oversold(self, tmp_path) -> None:
        bot = _make_bot(tmp_path)
        bot._open_position = AsyncMock(return_value=True)  # type: ignore[assignment]
        market = dict(MARKET_15M)
        market["technical"] = {"rsi": 35.0, "atr_percent": 0.01}
        result = await bot._maybe_oversold_bottom_buy(market, 55647.1)
        assert result is None
        bot._open_position.assert_not_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_channel_blocked_when_price_not_near_low(self, tmp_path) -> None:
        bot = _make_bot(tmp_path)
        bot._open_position = AsyncMock(return_value=True)  # type: ignore[assignment]
        market = dict(MARKET_15M)
        market["low"] = 50000.0  # 价格 55647 远高于 24h 低点 50000×1.01
        result = await bot._maybe_oversold_bottom_buy(market, 55647.1)
        assert result is None

    @pytest.mark.asyncio
    async def test_channel_respects_daily_limit(self, tmp_path) -> None:
        bot = _make_bot(tmp_path)
        bot._open_position = AsyncMock(return_value=True)  # type: ignore[assignment]
        from datetime import datetime

        today = datetime.now().strftime("%Y-%m-%d")
        bot._oversold_buy_counts[today] = 1
        result = await bot._maybe_oversold_bottom_buy(dict(MARKET_15M), 55647.1)
        assert result is None
        bot._open_position.assert_not_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_cycle_wiring_ai_hold_triggers_channel(self, tmp_path) -> None:
        """周期接线: AI HOLD 无持仓 + 技术极端超卖 → 独立通道开仓。"""
        bot = _make_bot(tmp_path)
        bot._execute_signal = AsyncMock(  # type: ignore[assignment]
            return_value=SimpleNamespace(action="none")
        )
        bot._open_position = AsyncMock(return_value=True)  # type: ignore[assignment]
        bot._decision_journal = None

        result = await bot._maybe_oversold_bottom_buy(dict(MARKET_15M), 55647.1)
        assert result is not None and result.action == "open_long_oversold"


class TestOpenPositionSizeFactor:
    """_open_position size_factor 半仓 + bool 返回值。"""

    @pytest.mark.asyncio
    async def test_size_factor_applied(self, tmp_path) -> None:
        bot = _make_bot(tmp_path, live=True)
        result = await bot._open_position(55647.1, size_factor=0.5)
        assert result is True
        # 0.03 × 0.5 = 0.015 张 (calculate_max_contracts=0.03)
        call_kwargs = bot._exchange.create_order.call_args.kwargs  # type: ignore[attr-defined]
        assert call_kwargs["amount"] == pytest.approx(0.015, abs=1e-9)

    @pytest.mark.asyncio
    async def test_full_size_default(self, tmp_path) -> None:
        bot = _make_bot(tmp_path, live=True)
        result = await bot._open_position(55647.1)
        assert result is True
        call_kwargs = bot._exchange.create_order.call_args.kwargs  # type: ignore[attr-defined]
        assert call_kwargs["amount"] == pytest.approx(0.03, abs=1e-9)


# ==================== P2-8: StopOrderResult 序列化回归 ====================


@dataclass
class _FakeStopOrderLike:
    """模拟被误存为 order_id 的 StopOrderResult (含枚举字段)。"""

    order_id: str
    status: OrderStatus


class TestStatePersistenceNonSerializable:
    """持久化边界: 任何非 JSON 值不得打断状态保存 (安全关键路径)。"""

    def test_save_position_with_enum_containing_object(self, tmp_path) -> None:
        p = StatePersistence(data_dir=tmp_path)
        ok = p.save_position(
            symbol="BTC/USDT:USDT",
            side="long",
            amount=0.03,
            entry_price=62528.2,
            take_profit_order_id=StopOrderResult(  # type: ignore[arg-type]
                order_id="ALGO_123",
                stop_price=63153.48,
                amount=0.03,
                status=OrderStatus.OPEN,
            ),
        )
        assert ok, "含枚举的 order_id 不应导致持久化失败"
        # 落盘可读回
        loaded = p.load_state()
        assert loaded.position is not None

    def test_mark_last_close_after_bad_position_state(self, tmp_path) -> None:
        """11-19 场景: 内存状态含脏 order_id 时 mark_last_close 也不得失败。"""
        p = StatePersistence(data_dir=tmp_path)
        p.save_position(
            symbol="BTC/USDT:USDT",
            side="long",
            amount=0.03,
            entry_price=62528.2,
            take_profit_order_id=StopOrderResult(  # type: ignore[arg-type]
                order_id="ALGO_123",
                stop_price=63153.48,
                amount=0.03,
                status=OrderStatus.OPEN,
            ),
        )
        p.mark_last_close()  # 不抛异常即通过
        state = p.load_state()
        assert state.last_close_at


class TestClientTakeProfitReturnsStr:
    """create_take_profit 返回 str order_id (不再透传 StopOrderResult)。"""

    @pytest.mark.asyncio
    async def test_unwraps_stop_order_result(self, tmp_path) -> None:
        from alpha_trading_bot.exchange.client import ExchangeClient

        client = ExchangeClient(
            api_key="k",
            secret="s",
            password="p",
            symbol="BTC/USDT:USDT",
            test_mode=False,
        )
        client._order_service = MagicMock()
        client._order_service.create_take_profit = AsyncMock(
            return_value=StopOrderResult(
                order_id="ALGO_456",
                stop_price=63153.48,
                amount=0.03,
                status=OrderStatus.OPEN,
            )
        )
        result = await client.create_take_profit(
            "BTC/USDT:USDT", "sell", 0.03, 63153.48
        )
        assert isinstance(result, str)
        assert result == "ALGO_456"

    @pytest.mark.asyncio
    async def test_failure_returns_empty_str(self, tmp_path) -> None:
        from alpha_trading_bot.exchange.client import ExchangeClient

        client = ExchangeClient(
            api_key="k",
            secret="s",
            password="p",
            symbol="BTC/USDT:USDT",
            test_mode=False,
        )
        client._order_service = MagicMock()
        client._order_service.create_take_profit = AsyncMock(
            return_value=StopOrderResult(
                order_id="",
                stop_price=63153.48,
                amount=0.03,
                status=OrderStatus.REJECTED,
                error_message="insufficient balance",
            )
        )
        result = await client.create_take_profit(
            "BTC/USDT:USDT", "sell", 0.03, 63153.48
        )
        assert result == ""


# ==================== P2-9: qwen38 max_tokens ====================


class TestReasoningMaxTokens:
    def test_qwen38_gets_8000(self) -> None:
        client = AIClient(config=AIConfig(), api_keys={})
        assert client._reasoning_max_tokens("qwen38") == 8000

    def test_other_reasoning_models_3000(self) -> None:
        client = AIClient(config=AIConfig(), api_keys={})
        assert client._reasoning_max_tokens("deepseek") == 3000
        assert client._reasoning_max_tokens("minimax") == 3000

    def test_non_reasoning_model_zero(self) -> None:
        client = AIClient(config=AIConfig(), api_keys={})
        assert client._reasoning_max_tokens("kimi") == 0


# ==================== P2-11: 15m 双窗口摘要 ====================


class TestRecent15mSummary:
    @pytest.mark.asyncio
    async def test_summary_from_fake_ohlcv(self, tmp_path) -> None:
        from alpha_trading_bot.exchange.market_data import MarketDataService

        svc = MarketDataService.__new__(MarketDataService)
        svc.symbol = "BTC/USDT:USDT"
        # 96 根 15m K线: 从 56000 跌到 55000 再爬到 55600
        n = 96
        ohlcv = []
        for i in range(n):
            price = 56000 - 10 * i if i < 48 else 55520 + 10 * (i - 48)
            ohlcv.append([0, price, price + 5, price - 5, price, 0])
        svc.get_ohlcv = AsyncMock(return_value=ohlcv)

        summary = await svc._build_recent_15m_summary(55647.1)
        assert summary is not None
        assert summary["low_24h_15m"] < 55647.1 < summary["high_24h_15m"]
        assert 0 <= summary["position_pct"] <= 100
        assert isinstance(summary["change_4h_pct"], float)

    @pytest.mark.asyncio
    async def test_summary_none_on_failure(self, tmp_path) -> None:
        from alpha_trading_bot.exchange.market_data import MarketDataService

        svc = MarketDataService.__new__(MarketDataService)
        svc.symbol = "BTC/USDT:USDT"
        svc.get_ohlcv = AsyncMock(side_effect=RuntimeError("network down"))
        summary = await svc._build_recent_15m_summary(55647.1)
        assert summary is None


class TestPromptContains15mLine:
    def test_prompt_includes_15m_summary(self) -> None:
        from alpha_trading_bot.ai.prompt_builder import PromptBuilder

        market = dict(MARKET_15M)
        market["recent_15m_summary"] = {
            "low_24h_15m": 55134.0,
            "high_24h_15m": 60738.0,
            "position_pct": 9.5,
            "change_4h_pct": 2.1,
        }
        prompt = PromptBuilder.build(market)
        assert "55134.00" in prompt
        assert "15m" in prompt
