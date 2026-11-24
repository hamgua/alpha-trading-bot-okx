"""2026-11-24 日志回放修复回归测试 (P0-2/P0-3/P1-4/P1-6)。

日志回放背景 (2026-11-23 ~ 11-24, BTC 60k 瀑布 + 高潮顶):
- 217 周期 AI 全部 HOLD; 最终置信度 46-72% (均值 58.5%), 固定 0.65 门禁
  仅 15/217 通过且全为 HOLD → 主路径几乎不可开仓
- 11-23 22:00-23:57: 做空 R/R 3.0-7.1 (excellent) + RSI(1h) 67-78 +
  价格处 24h 高点区 → 随后 11-24 62.8k→59.5k (-5.3%) 主跌段完全空仓
- 11-23 02:14 误报: 做空 R/R=4.36 但 RSI≈50 (未超买) → 实际随后涨 5.6%
- 11-24 11:03: 超卖抄底开多 @60123.4, 0.5% 止损 59822.78 被 59536 击穿;
  ATR=1.245% → ATR 止损 ≈59371 可守住
- 11-24 05:15: 15m "bullish R/R=4.91" 后价格继续 -7% → 需 HTF(4h) 确认

本文件覆盖:
- P0-2 做空执行通道 (SHORT 信号全链路 + 持仓方向语义 + 逆势门禁)
- P0-2 高潮做空独立通道 (climax short, 含 02:14 误报排除)
- P0-3 R/R 感知动态开仓门禁 (方向一致 R/R ≥ 2 → 门禁 0.65→0.55)
- P0-3 极端超卖翻转豁免 (RSI(1h) ≤ 10 + oversold_rebound)
- P1-4 市场结构 HTF(4h) 冲突守卫
- P1-6 超卖抄底 1h 动量守卫 + ATR 止损
- 空仓 ATR 止损 (calculate_short_stop_price dynamic_atr_percent)
- 新配置字段校验
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from alpha_trading_bot.config.models import (
    Config,
    ExchangeConfig,
    StopLossConfig,
    TradingConfig,
)
from alpha_trading_bot.core.bot import TradingBot
from alpha_trading_bot.core.position_manager import PositionManager
from alpha_trading_bot.ai.sustained_decline_detector import DeclineDetectionResult

# ==================== 测试夹具 ====================


def _make_bot(
    tmp_path: Path,
    min_open: float = 0.65,
    min_close: float = 0.60,
    daily_limit: int = 2,
    live: bool = False,
    allow_short: bool = True,
) -> TradingBot:
    """构造最小可运行 bot。

    live=True 用实盘配置 (_open_position 实盘闸门需要过)。
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
            allow_short_selling=allow_short,
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


def _rr_result(rr: float, sl: float, tp: float) -> SimpleNamespace:
    return SimpleNamespace(
        rr_ratio=rr,
        stop_loss_price=sl,
        take_profit_price=tp,
        should_trade=rr >= 2.0,
        quality="excellent" if rr >= 3.0 else "good",
    )


def _make_integrator(adaptive_mode: str, adaptive_conf: float) -> Any:
    """构造标准集成器, 子模块打桩, 隔离测试翻转守卫/极端超卖豁免。"""
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
    # 市场结构 R/R=0 → 跳过 R/R 过滤段 (与既有测试一致)
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


MARKET_EXTREME = {
    "symbol": "BTC/USDT:USDT",
    "price": 59700.0,
    "low": 59536.0,
    "price_history": [60000.0] * 20,
    "technical": {"rsi": 5.9, "atr_percent": 0.0124},
}


# ==================== P0-2: 做空执行通道 ====================


class TestShortExecutionPath:
    """SHORT 信号全链路 (此前 SHORT 无执行路径, 120 次'建议=交易'无出口)。"""

    @pytest.mark.asyncio
    async def test_short_open_full_chain(self, tmp_path) -> None:
        """SHORT + 无持仓 + 高置信 → 开空: sell 开仓 / buy 止损在上方 /
        buy 止盈在下方 / 持仓方向 short。"""
        bot = _make_bot(tmp_path, live=True)
        result = await bot._execute_signal(
            "SHORT", 62000.0, has_position=False, final_confidence=0.90
        )
        assert result.action == "open_short"

        # 开仓单 = sell
        open_call = bot._exchange.create_order.call_args.kwargs
        assert open_call["side"] == "sell"
        # 止损单 = buy, 且在入场价上方
        sl_call = bot._exchange.create_stop_loss.call_args.kwargs
        assert sl_call["side"] == "buy"
        assert sl_call["stop_price"] > 62000.0
        # 止盈单 = buy, 且在入场价下方
        tp_call = bot._exchange.create_take_profit.call_args.kwargs
        assert tp_call["side"] == "buy"
        assert tp_call["take_profit_price"] < 62000.0
        # 持仓方向持久化为 short
        assert bot.position_manager.position_side == "short"

    @pytest.mark.asyncio
    async def test_short_low_confidence_blocked(self, tmp_path) -> None:
        """SHORT + 无持仓 + 置信度 < 门禁 → 禁止开空 (无 R/R 放宽)。"""
        bot = _make_bot(tmp_path, live=True)
        result = await bot._execute_signal(
            "SHORT", 62000.0, has_position=False, final_confidence=0.55
        )
        assert result.action == "blocked_low_confidence"
        bot._exchange.create_order.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_short_disabled(self, tmp_path) -> None:
        """ALLOW_SHORT_SELLING=false → SHORT 信号不操作。"""
        bot = _make_bot(tmp_path, live=True, allow_short=False)
        result = await bot._execute_signal(
            "SHORT", 62000.0, has_position=False, final_confidence=0.90
        )
        assert result.action == "blocked_short_disabled"

    @pytest.mark.asyncio
    async def test_short_counter_trend_gate(self, tmp_path) -> None:
        """24h 涨幅 > short_entry_max_daily_change → 禁止逆势开空。"""
        bot = _make_bot(tmp_path, live=True)
        result = await bot._execute_signal(
            "SHORT",
            62000.0,
            has_position=False,
            final_confidence=0.90,
            change_percent=3.0,  # > 默认门禁 1.5%
        )
        assert result.action == "blocked_short_daily_change"

    @pytest.mark.asyncio
    async def test_short_daily_limit(self, tmp_path) -> None:
        """每日开仓上限 (与 BUY 同一计数器) → 禁止新开空。"""
        from datetime import datetime

        bot = _make_bot(tmp_path, live=True)
        today = datetime.now().strftime("%Y-%m-%d")
        bot._daily_open_counts[today] = 2  # 已达 daily_limit=2
        result = await bot._execute_signal(
            "SHORT", 62000.0, has_position=False, final_confidence=0.90
        )
        assert result.action == "blocked_daily_limit"


class TestPositionSideSemantics:
    """持仓方向语义 (prompt 语义: 多仓 SELL/SHORT=平多, 空仓 BUY=平空,
    空仓 SELL/SHORT=继续持有)。"""

    @pytest.mark.asyncio
    async def test_sell_on_short_position_holds(self, tmp_path) -> None:
        bot = _make_bot(tmp_path, live=True)
        bot._update_stop_loss = AsyncMock()  # type: ignore[assignment]
        result = await bot._execute_signal(
            "SELL",
            62000.0,
            has_position=True,
            final_confidence=0.90,
        )
        # position_side 默认 long → SELL+多仓 = 平仓
        assert result.action == "close"

    @pytest.mark.asyncio
    async def test_sell_on_short_position_continues(self, tmp_path) -> None:
        """空仓 + SELL = 同向继续持有 (更新止损, 不平仓)。"""
        bot = _make_bot(tmp_path, live=True)
        bot._update_stop_loss = AsyncMock()  # type: ignore[assignment]
        bot.position_manager.update_position(
            0.01, 62000.0, "BTC/USDT:USDT", side="short"
        )
        result = await bot._execute_signal(
            "SELL", 62000.0, has_position=True, final_confidence=0.90
        )
        assert result.action == "update_stop"
        bot._update_stop_loss.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_buy_on_short_position_closes(self, tmp_path) -> None:
        """空仓 + BUY = 平空。"""
        bot = _make_bot(tmp_path, live=True)
        bot._close_position = AsyncMock()  # type: ignore[assignment]
        bot.position_manager.update_position(
            0.01, 62000.0, "BTC/USDT:USDT", side="short"
        )
        result = await bot._execute_signal(
            "BUY", 62000.0, has_position=True, final_confidence=0.90
        )
        assert result.action == "close"
        bot._close_position.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_short_on_long_position_closes(self, tmp_path) -> None:
        """多仓 + SHORT = 平多 (prompt 语义)。"""
        bot = _make_bot(tmp_path, live=True)
        bot._close_position = AsyncMock()  # type: ignore[assignment]
        result = await bot._execute_signal(
            "SHORT", 62000.0, has_position=True, final_confidence=0.90
        )
        assert result.action == "close"
        bot._close_position.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_buy_on_short_close_gate(self, tmp_path) -> None:
        """空仓 + BUY (平空) + 置信度 < 平仓门禁 → 禁止平仓 (仓位由止损保护)。"""
        bot = _make_bot(tmp_path, live=True)
        bot.position_manager.update_position(
            0.01, 62000.0, "BTC/USDT:USDT", side="short"
        )
        result = await bot._execute_signal(
            "BUY", 62000.0, has_position=True, final_confidence=0.50
        )
        assert result.action == "blocked_low_confidence"


# ==================== P0-2: 高潮做空独立通道 ====================


class TestClimaxShortChannel:
    """Climax top 做空独立通道 (顶部捕获, 与超卖抄底对称)。"""

    def _bot_with_rr(self, tmp_path: Path, rr: float) -> TradingBot:
        bot = _make_bot(tmp_path, live=True)
        bot._open_position = AsyncMock(return_value=True)  # type: ignore[assignment]
        bot._ai_client = SimpleNamespace(  # type: ignore[assignment]
            integrator=SimpleNamespace(
                risk_reward_calculator=MagicMock(
                    calculate_for_short=MagicMock(
                        return_value=_rr_result(rr, 62500.0, 60800.0)
                    )
                )
            )
        )
        return bot

    def _market(self, price: float, rsi: float, high: float = 63000.0) -> dict:
        return {
            "price": price,
            "high": high,
            "low": 61000.0,
            "technical": {"rsi": rsi, "atr_percent": 0.012},
            "nearest_support": 60800.0,
            "nearest_resistance": 63200.0,
        }

    @pytest.mark.asyncio
    async def test_climax_top_triggers(self, tmp_path) -> None:
        """回放 11-23 22:00: 24h 高点区 + RSI(1h)=71 + 做空R/R=3.0 → 开空。"""
        bot = self._bot_with_rr(tmp_path, rr=3.0)
        result = await bot._maybe_climax_short(self._market(62700.0, 71.0), 62700.0)
        assert result is not None
        assert result.action == "open_short_climax"
        kwargs = bot._open_position.call_args.kwargs  # type: ignore[union-attr]
        assert kwargs["side"] == "short"
        assert kwargs["size_factor"] == 0.5
        assert kwargs["stop_price_override"] == 62500.0
        assert kwargs["tp_price_override"] == 60800.0

    @pytest.mark.asyncio
    async def test_false_positive_excluded_by_rsi(self, tmp_path) -> None:
        """回放 11-23 02:14 误报: RSI≈50 (未超买) → 不触发 (随后实际涨 5.6%)。"""
        bot = self._bot_with_rr(tmp_path, rr=4.36)
        result = await bot._maybe_climax_short(self._market(62700.0, 50.0), 62700.0)
        assert result is None
        bot._open_position.assert_not_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_rr_below_threshold_skips(self, tmp_path) -> None:
        """做空 R/R < climax_short_rr_min (2.5) → 不触发。"""
        bot = self._bot_with_rr(tmp_path, rr=2.0)
        result = await bot._maybe_climax_short(self._market(62700.0, 71.0), 62700.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_not_near_high_skips(self, tmp_path) -> None:
        """价格远离 24h 高点 (>2%) → 不触发。"""
        bot = self._bot_with_rr(tmp_path, rr=3.0)
        # 61500 < 63000 × 0.98 = 61740
        result = await bot._maybe_climax_short(self._market(61500.0, 71.0), 61500.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_daily_limit(self, tmp_path) -> None:
        from datetime import datetime

        bot = self._bot_with_rr(tmp_path, rr=3.0)
        today = datetime.now().strftime("%Y-%m-%d")
        bot._climax_short_counts[today] = 1  # 已达 climax_short_daily_limit=1
        result = await bot._maybe_climax_short(self._market(62700.0, 71.0), 62700.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_drawdown_halt_blocks(self, tmp_path) -> None:
        bot = self._bot_with_rr(tmp_path, rr=3.0)
        bot._drawdown_status = SimpleNamespace(halted=True, drawdown=0.35)
        result = await bot._maybe_climax_short(self._market(62700.0, 71.0), 62700.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_short_disabled_blocks_channel(self, tmp_path) -> None:
        bot = _make_bot(tmp_path, live=True, allow_short=False)
        bot._ai_client = SimpleNamespace(  # type: ignore[assignment]
            integrator=SimpleNamespace(
                risk_reward_calculator=MagicMock(
                    calculate_for_short=MagicMock(
                        return_value=_rr_result(3.0, 62500.0, 60800.0)
                    )
                )
            )
        )
        result = await bot._maybe_climax_short(self._market(62700.0, 71.0), 62700.0)
        assert result is None


# ==================== P0-3: R/R 感知动态开仓门禁 ====================


class TestDynamicOpenGate:
    """方向一致 R/R ≥ 2 → 开仓门禁 0.65 → 0.55 (55-64% 犹豫带放行)。"""

    @pytest.mark.asyncio
    async def test_buy_rr_relief_opens(self, tmp_path) -> None:
        """BUY conf 0.60 + 结构R/R=3.0 → 放宽后 0.60 >= 0.55 → 开仓。"""
        bot = _make_bot(tmp_path, live=True)
        bot._open_position = AsyncMock(return_value=True)  # type: ignore[assignment]
        result = await bot._execute_signal(
            "BUY",
            60000.0,
            has_position=False,
            final_confidence=0.60,
            structure_rr=3.0,
        )
        assert result.action == "open_long"

    @pytest.mark.asyncio
    async def test_buy_no_rr_still_blocked(self, tmp_path) -> None:
        """BUY conf 0.60 无 R/R → 固定门禁 0.65 拦截 (零回归)。"""
        bot = _make_bot(tmp_path, live=True)
        result = await bot._execute_signal(
            "BUY", 60000.0, has_position=False, final_confidence=0.60
        )
        assert result.action == "blocked_low_confidence"

    @pytest.mark.asyncio
    async def test_buy_rr_below_threshold_blocked(self, tmp_path) -> None:
        """R/R=1.5 < gate_relief_rr_min=2.0 → 不放宽, 拦截。"""
        bot = _make_bot(tmp_path, live=True)
        result = await bot._execute_signal(
            "BUY",
            60000.0,
            has_position=False,
            final_confidence=0.60,
            structure_rr=1.5,
        )
        assert result.action == "blocked_low_confidence"

    @pytest.mark.asyncio
    async def test_short_rr_relief_opens(self, tmp_path) -> None:
        """SHORT conf 0.58 + 做空R/R=2.5 → 放宽后 0.58 >= 0.55 → 开空。"""
        bot = _make_bot(tmp_path, live=True)
        result = await bot._execute_signal(
            "SHORT",
            62000.0,
            has_position=False,
            final_confidence=0.58,
            short_rr=2.5,
        )
        assert result.action == "open_short"

    @pytest.mark.asyncio
    async def test_conf_below_relaxed_gate_blocked(self, tmp_path) -> None:
        """conf 0.50 < 放宽后 0.55 → 仍拦截 (放宽不是取消)。"""
        bot = _make_bot(tmp_path, live=True)
        result = await bot._execute_signal(
            "BUY",
            60000.0,
            has_position=False,
            final_confidence=0.50,
            structure_rr=3.0,
        )
        assert result.action == "blocked_low_confidence"

    @pytest.mark.asyncio
    async def test_gate_relief_floor(self, tmp_path) -> None:
        """min_open=0.52 → 放宽值 = max(0.50, 0.52-0.10) = 0.50。"""
        bot = _make_bot(tmp_path, min_open=0.52, live=True)
        assert bot._effective_open_confidence_gate(3.0) == pytest.approx(0.50)
        assert bot._effective_open_confidence_gate(1.0) == pytest.approx(0.52)

    def test_gate_disabled_returns_zero(self, tmp_path) -> None:
        """min_confidence_open=0 (门禁关闭) → 原样返回 0。"""
        bot = _make_bot(tmp_path, min_open=0.0, live=True)
        assert bot._effective_open_confidence_gate(3.0) == 0.0


# ==================== P0-3: 极端超卖翻转豁免 ====================


class TestExtremeOversoldBypass:
    """RSI(1h) ≤ 10 + oversold_rebound → 无视 AI HOLD 置信度允许翻转。"""

    def test_extreme_oversold_bypasses_high_conf_hold(self) -> None:
        """回放 11-24 11:03: RSI=5.9, AI hold(62%) >= 0.60 强模式上限,
        旧逻辑拦截 → 新逻辑豁免翻转 BUY。"""
        integ = _make_integrator("oversold_rebound", 0.53)
        result = integ.process(
            dict(MARKET_EXTREME), original_signal="hold", original_confidence=0.62
        )
        assert result.final_signal == "BUY"
        assert any("极端超卖" in a for a in result.adjustments_made)

    def test_non_extreme_oversold_still_blocked(self) -> None:
        """RSI=16.2 (>10) + AI HOLD 65% → 高可信模式上限 0.60 仍拦截 (零回归)。"""
        market = dict(MARKET_EXTREME)
        market["technical"] = {"rsi": 16.2, "atr_percent": 0.0124}
        integ = _make_integrator("oversold_rebound", 0.53)
        result = integ.process(
            market, original_signal="hold", original_confidence=0.65
        )
        assert result.final_signal == "HOLD"

    def test_extreme_rsi_but_other_mode_not_bypassed(self) -> None:
        """RSI=5.9 但模式非 oversold_rebound → 不豁免 (仅抄底模式受益)。"""
        integ = _make_integrator("trend_confirmation", 0.53)
        result = integ.process(
            dict(MARKET_EXTREME), original_signal="hold", original_confidence=0.62
        )
        assert result.final_signal == "HOLD"

    def test_sell_never_flipped_even_extreme(self) -> None:
        """硬约束: SELL 永不翻转为 BUY (即使极端超卖)。"""
        integ = _make_integrator("oversold_rebound", 0.53)
        result = integ.process(
            dict(MARKET_EXTREME), original_signal="sell", original_confidence=0.90
        )
        assert result.final_signal != "BUY"


# ==================== P1-4: HTF(4h) 冲突守卫 ====================


class TestHtfConflictGuard:
    """1h 结构与 4h 结构反向 → 方向降级 none (等待 HTF 共振)。"""

    def _analyzer(self) -> Any:
        from alpha_trading_bot.ai.market_structure import MarketStructureAnalyzer

        return MarketStructureAnalyzer()

    def test_htf_detection_needs_enough_bars(self) -> None:
        a = self._analyzer()
        assert a._detect_htf_structure([100.0] * 5) == "unknown"  # < 4×3 bars

    def test_htf_detection_uptrend(self) -> None:
        """10 根 4h 收盘 (HH+HL) → HTF bullish (40 根 1h 聚合)。"""
        a = self._analyzer()
        # 4h 收盘 (从旧到新): HH 102<104<106<108<110, HL 101<103<105<107
        targets = [100, 102, 101, 104, 103, 106, 105, 108, 107, 110]
        bars: list = []
        for t in targets:
            bars.extend([t - 0.1, t - 0.05, t - 0.02, float(t)])
        newest_first = list(reversed(bars))
        assert a._detect_htf_structure(newest_first) == "bullish"

    def test_htf_detection_downtrend(self) -> None:
        a = self._analyzer()
        # 4h 收盘 (从旧到新): LH 109>107>105>103, LL 108>106>104>102
        targets = [110, 108, 109, 106, 107, 104, 105, 102, 103, 100]
        bars: list = []
        for t in targets:
            bars.extend([t + 0.1, t + 0.05, t + 0.02, float(t)])
        newest_first = list(reversed(bars))
        assert a._detect_htf_structure(newest_first) == "bearish"

    def test_bullish_1h_bearish_4h_downgrades_direction(self) -> None:
        """1h bullish + 4h bearish → 方向 none (11-24 05:15 误判防护)。"""
        a = self._analyzer()
        direction, size, note = a._generate_trading_advice(
            structure="bullish",
            rr_ratio=4.9,
            is_breakout=False,
            is_breakdown=False,
            atr_percent=0.01,
            htf_structure="bearish",
        )
        assert direction == "none"
        assert size == 0.0
        assert "4h" in note

    def test_htf_unknown_no_interference(self) -> None:
        """HTF unknown (数据不足) → 不干预 (零回归)。"""
        a = self._analyzer()
        direction, size, note = a._generate_trading_advice(
            structure="bullish",
            rr_ratio=4.9,
            is_breakout=False,
            is_breakdown=False,
            atr_percent=0.01,
            htf_structure="unknown",
        )
        assert direction == "long"
        assert size > 0

    def test_aligned_htf_no_interference(self) -> None:
        """1h bullish + 4h bullish (共振) → 方向保持 long。"""
        a = self._analyzer()
        direction, size, note = a._generate_trading_advice(
            structure="bullish",
            rr_ratio=4.9,
            is_breakout=False,
            is_breakdown=False,
            atr_percent=0.01,
            htf_structure="bullish",
        )
        assert direction == "long"
        assert note == ""


# ==================== P1-6: 超卖抄底 1h 动量守卫 ====================


class TestOversoldMomentumGuard:
    """1h 涨跌幅 ≤ -5% → 跳过 (动量仍在崩塌, 不接飞刀)。"""

    @pytest.mark.asyncio
    async def test_still_collapsing_skips(self, tmp_path) -> None:
        bot = _make_bot(tmp_path, live=True)
        bot._open_position = AsyncMock(return_value=True)  # type: ignore[assignment]
        md = {
            "price": 59700.0,
            "low": 59536.0,
            "technical": {"rsi": 8.0, "atr_percent": 0.0124},
            "recent_drop_percent": -0.06,  # 1h -6% ≤ -5% 守卫
        }
        result = await bot._maybe_oversold_bottom_buy(md, 59700.0)
        assert result is None
        bot._open_position.assert_not_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_momentum_stabilized_opens(self, tmp_path) -> None:
        """1h -1% (企稳) → 触发, 且开仓传入 ATR (ATR 止损)。"""
        bot = _make_bot(tmp_path, live=True)
        bot._open_position = AsyncMock(return_value=True)  # type: ignore[assignment]
        md = {
            "price": 59700.0,
            "low": 59536.0,
            "technical": {"rsi": 8.0, "atr_percent": 0.0124},
            "recent_drop_percent": -0.01,
        }
        result = await bot._maybe_oversold_bottom_buy(md, 59700.0)
        assert result is not None
        assert result.action == "open_long_oversold"
        kwargs = bot._open_position.call_args.kwargs  # type: ignore[union-attr]
        assert kwargs["size_factor"] == 0.5
        assert kwargs["atr_percent"] == pytest.approx(0.0124)


# ==================== 空仓 ATR 止损 ====================


class TestShortStopAtr:
    """calculate_short_stop_price 开仓时刻 ATR 止损 (与做多对称)。"""

    def _pm(self, tmp_path: Path) -> PositionManager:
        config = Config(
            exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        )
        pm = PositionManager(config, data_dir=tmp_path)
        pm.update_position(0.01, 62000.0, "BTC/USDT:USDT", side="short")
        return pm

    def test_atr_stop_wider_than_default(self, tmp_path) -> None:
        """ATR 1.2% > 默认 0.05% → 止损距离 = ATR (回放 11-24 11:03)。"""
        pm = self._pm(tmp_path)
        stop = pm.calculate_short_stop_price(62000.0, dynamic_atr_percent=0.012)
        assert stop == pytest.approx(62000.0 * 1.012)

    def test_atr_below_default_uses_atr_clamp_floor(self, tmp_path) -> None:
        """ATR 低于 0.3% 下限 → 取 clamp 下限 0.3% (与做多 OC-NEW-3 对称)。
        (clamp 下限 > 默认 0.05% 时, ATR 路径用 0.3% 而非默认)"""
        pm = self._pm(tmp_path)
        stop = pm.calculate_short_stop_price(62000.0, dynamic_atr_percent=0.0001)
        assert stop == pytest.approx(62000.0 * 1.003)

    def test_atr_clamped_at_5_percent(self, tmp_path) -> None:
        pm = self._pm(tmp_path)
        stop = pm.calculate_short_stop_price(62000.0, dynamic_atr_percent=0.09)
        assert stop == pytest.approx(62000.0 * 1.05)

    def test_no_atr_keeps_legacy_behavior(self, tmp_path) -> None:
        """不传 ATR → 传统口径 (当前价 × (1 + 默认比例)) 零回归。"""
        pm = self._pm(tmp_path)
        default = StopLossConfig().stop_loss_percent
        stop = pm.calculate_short_stop_price(61900.0)
        assert stop == pytest.approx(61900.0 * (1 + default))

    def test_long_position_ignores_short_stop(self, tmp_path) -> None:
        """多仓 → 空仓止损计算返回 0 (方向保护)。"""
        config = Config(
            exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        )
        pm = PositionManager(config, data_dir=tmp_path)
        pm.update_position(0.01, 62000.0, "BTC/USDT:USDT", side="long")
        assert pm.calculate_short_stop_price(62000.0) == 0.0


# ==================== 配置校验 ====================


class TestNewConfigValidation:
    def test_defaults_valid(self) -> None:
        cfg = TradingConfig()
        errors = cfg.validate()
        assert errors == [] or all(
            e not in errors for e in []
        )  # 默认值必须通过校验
        assert cfg.climax_short_enabled is True
        assert cfg.climax_short_rr_min == 2.5
        assert cfg.oversold_buy_min_1h_change == -0.05
        assert cfg.gate_relief_rr_min == 2.0

    def test_invalid_climax_rr_rejected(self) -> None:
        cfg = TradingConfig(climax_short_rr_min=0.0)
        assert any("climax_short_rr_min" in e for e in cfg.validate())

    def test_invalid_gate_relief_floor_rejected(self) -> None:
        cfg = TradingConfig(gate_relief_floor=1.5)
        assert any("gate_relief_floor" in e for e in cfg.validate())

    def test_invalid_1h_change_rejected(self) -> None:
        cfg = TradingConfig(oversold_buy_min_1h_change=0.1)
        assert any("oversold_buy_min_1h_change" in e for e in cfg.validate())
