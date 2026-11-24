"""2026-11-24 13:43-14:15 亏损交易回放修复回归测试 (P0-A/P0-B/P1-C/P1-D)。

回放背景 (11-24 13:30-14:15, 账户 7.3 USDT):
- 13:30  AI HOLD 45% → 技术翻转 BUY 50%, 结构 R/R=81.38 触发门禁放宽
         (0.65→0.55), 50% < 55% 侥幸被拦 (BTC 高位检测 -70% 压掉了它)
- 13:43  AI HOLD 55% → 翻转 BUY, +15% 规则加成 → 61.8% > 放宽门禁 0.55
         → 开多 0.03 @ 60664 (止损 60033 -1.07%, 止盈 61988 +2.15%)
         结构 R/R=4.03 (底部区几何伪影: 距支撑仅 102 USDT);
         同周期 ATR 口径做多 R/R 仅 1.27 (marginal)
- 13:48/13:57/14:03  AI SELL 60/65/75% → 最终 51/55/57% < 平仓门禁 0.60
         全部被拦 (UPL 已 -0.21%/-0.43%)
- 14:15  AI SELL 78% → 最终 60.03% 刚好过门禁 → 平仓 @ 60409
         净亏 ≈ -0.094 USDT ≈ 账户 -1.3%

本文件覆盖:
- P0-A 亏损态平仓门禁下移 (UPL<0 → 0.60→0.50; 浮盈/平价不放宽)
- P0-B 动态门禁放宽改用 ATR 口径 R/R (integrator 无条件暴露
  market_data["long_risk_reward_ratio"])
- P1-C 技术翻转置信度封顶 0.60 + oversold_rebound 翻转开仓半仓
- P1-D BTC 价格水平滞回带 (high/low 进入用基础判定, 退出需越 band)
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from alpha_trading_bot.ai.btc_price_detector import (
    BTCPriceLevelConfig,
    BTCPriceLevelDetector,
)
from alpha_trading_bot.config.models import (
    Config,
    ExchangeConfig,
    TradingConfig,
)
from alpha_trading_bot.core.bot import TradingBot
from alpha_trading_bot.core.position_manager import PositionManager


# ==================== 测试夹具 ====================


def _make_bot(
    tmp_path: Path,
    min_open: float = 0.65,
    min_close: float = 0.60,
    daily_limit: int = 2,
    live: bool = False,
    allow_short: bool = True,
) -> TradingBot:
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


def _make_integrator(adaptive_mode: str, adaptive_conf: float) -> Any:
    """构造标准集成器 (与 test_bottom_capture_fixes 同模式)。"""
    from alpha_trading_bot.ai.integrator import AISignalIntegrator
    from alpha_trading_bot.ai.integrator_config import IntegrationConfig
    from alpha_trading_bot.ai.sustained_decline_detector import (
        DeclineDetectionResult,
    )

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
    # 市场结构 R/R=0 + 支撑/阻力=0 → R/R 过滤段跳过, 无条件长 R/R 也被守卫跳过
    integ.market_structure_analyzer = MagicMock()
    integ.market_structure_analyzer.analyze.return_value = SimpleNamespace(
        structure="bullish",
        suggested_direction="long",
        risk_reward_ratio=0.0,
        nearest_support=0.0,
        nearest_resistance=0.0,
        position_size_factor=0.0,
        htf_structure="unknown",
        htf_note="",
    )
    integ.risk_reward_calculator = MagicMock()
    integ.risk_reward_calculator.calculate_for_short.return_value = (
        SimpleNamespace(rr_ratio=0.0, should_trade=False, quality="poor")
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


# ==================== P0-A: 亏损态平仓门禁下移 ====================


class TestCloseGateLossRelief:
    """UPL < 0 时平仓门禁 0.60 → 0.50 (回放: 13:57 SELL 55.2% 应放行)。"""

    def _bot_with_long(self, tmp_path: Path, entry: float) -> TradingBot:
        bot = _make_bot(tmp_path, live=True)
        bot._close_position = AsyncMock()  # type: ignore[assignment]
        bot.position_manager.update_position(
            0.03, entry, "BTC/USDT:USDT", side="long"
        )
        return bot

    @pytest.mark.asyncio
    async def test_losing_position_close_relaxed(self, tmp_path) -> None:
        """回放 13:57: 入场 60664, 现价 60537 (UPL -0.21%),
        SELL 最终 55.2% ≥ 放宽门禁 0.50 → 平仓 (原 0.60 门禁会拦截)。"""
        bot = self._bot_with_long(tmp_path, 60664.0)
        result = await bot._execute_signal(
            "SELL", 60537.0, has_position=True, final_confidence=0.552
        )
        assert result.action == "close"
        bot._close_position.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_profitable_position_gate_unchanged(self, tmp_path) -> None:
        """回放 13:48: UPL +0.01% (≥0) → 门禁保持 0.60, 51% 仍拦截 (零回归)。"""
        bot = self._bot_with_long(tmp_path, 60664.0)
        result = await bot._execute_signal(
            "SELL", 60672.0, has_position=True, final_confidence=0.51
        )
        assert result.action == "blocked_low_confidence"
        bot._close_position.assert_not_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_losing_but_below_relaxed_gate_blocked(self, tmp_path) -> None:
        """UPL < 0 但置信度 < 放宽后门禁 (0.45 < 0.50) → 仍拦截。"""
        bot = self._bot_with_long(tmp_path, 60664.0)
        result = await bot._execute_signal(
            "SELL", 60404.0, has_position=True, final_confidence=0.45
        )
        assert result.action == "blocked_low_confidence"

    @pytest.mark.asyncio
    async def test_short_losing_position_close_relaxed(self, tmp_path) -> None:
        """空仓 UPL 口径对称: 入场 60664, 现价 60800 (空仓浮亏 -0.22%),
        BUY(平空) 55% ≥ 0.50 → 平仓。"""
        bot = _make_bot(tmp_path, live=True)
        bot._close_position = AsyncMock()  # type: ignore[assignment]
        bot.position_manager.update_position(
            0.03, 60664.0, "BTC/USDT:USDT", side="short"
        )
        result = await bot._execute_signal(
            "BUY", 60800.0, has_position=True, final_confidence=0.55
        )
        assert result.action == "close"

    def test_upl_percent_long(self, tmp_path) -> None:
        bot = self._bot_with_long(tmp_path, 60664.0)
        assert abs(bot._position_upl_percent(60537.0) - (-127 / 60664)) < 1e-9
        assert abs(bot._position_upl_percent(60700.0) - (36 / 60664)) < 1e-9

    def test_upl_percent_short_and_invalid(self, tmp_path) -> None:
        bot = _make_bot(tmp_path, live=True)
        bot.position_manager.update_position(
            0.03, 60664.0, "BTC/USDT:USDT", side="short"
        )
        assert abs(bot._position_upl_percent(60800.0) - (-136 / 60664)) < 1e-9
        assert abs(bot._position_upl_percent(60500.0) - (164 / 60664)) < 1e-9
        # 无持仓/无效价 → None (门禁不放宽)。用独立 data_dir 避免恢复
        # 上一个 bot 的持久化持仓状态。
        empty = _make_bot(Path(tmp_path) / "empty", live=True)
        assert empty._position_upl_percent(60000.0) is None
        assert bot._position_upl_percent(0.0) is None


# ==================== P0-B: 动态门禁放宽改用 ATR 口径 R/R ====================


class TestAtrBasedGateRelief:
    """integrator 无条件暴露 ATR 口径做多 R/R (long_risk_reward_ratio)。"""

    def test_long_rr_exposed_unconditionally(self) -> None:
        """HOLD 信号周期也计算并暴露做多 R/R (回放 12:47-13:15 只有做空
        R/R 被计算, 做多 R/R 缺失 → 执行层拿不到 ATR 口径数据)。"""
        integ = _make_integrator("oversold_rebound", 0.40)
        # 用真实计算器验证 ATR 口径 (风险=max(支撑距离, ATR×0.5))
        from alpha_trading_bot.ai.risk_reward_calculator import RiskRewardCalculator

        integ.risk_reward_calculator = RiskRewardCalculator()
        # 支撑/阻力有效 → 触发无条件计算 (回放 13:43 数值)
        integ.market_structure_analyzer.analyze.return_value = SimpleNamespace(
            structure="bullish",
            suggested_direction="long",
            risk_reward_ratio=4.03,  # 底部区结构伪影
            nearest_support=60583.0,
            nearest_resistance=61097.0,
            position_size_factor=1.0,
            htf_structure="unknown",
            htf_note="",
        )
        market_data = {
            "price": 60685.0,
            "price_history": [60600.0] * 20,
            "technical": {
                "rsi": 21.4,
                "atr_percent": 0.0107,
                "price_history": [60600.0] * 20,
            },
        }
        result = integ.process(
            market_data, original_signal="hold", original_confidence=0.65
        )
        # 0.65 ≥ 强模式翻转上限 0.60 → 明确 HOLD 不翻转;
        # ATR 口径做多 R/R 仍无条件暴露 (P0-B 核心)
        assert result.final_signal == "HOLD"
        # ATR 口径: 风险=max(102, 60685×0.0107×0.5=324.6)=324.6,
        # 收益=412 → R/R≈1.27 (与回放日志一致), 远低于结构伪影 4.03
        assert "long_risk_reward_ratio" in market_data
        assert market_data["long_risk_reward_ratio"] == pytest.approx(1.27, abs=0.05)
        assert market_data["long_risk_reward_ratio"] < 4.03, (
            "ATR 口径 R/R 必须低于底部区结构伪影值 (回放: 1.27 vs 4.03)"
        )

    def test_long_rr_skipped_when_levels_invalid(self) -> None:
        """支撑/阻力无效 (0) → 跳过计算, 不写脏数据。"""
        integ = _make_integrator("oversold_rebound", 0.40)
        market_data = {
            "price": 60685.0,
            "price_history": [60600.0] * 20,
            "technical": {"rsi": 21.4, "atr_percent": 0.0107, "price_history": [60600.0] * 20},
        }
        integ.process(market_data, original_signal="hold", original_confidence=0.55)
        assert "long_risk_reward_ratio" not in market_data

    @pytest.mark.asyncio
    async def test_entry_blocked_when_atr_rr_low(self, tmp_path) -> None:
        """回放 13:43 完整链路: 方向一致但 ATR 口径 R/R=1.27 < 2.0 →
        门禁不放宽 (0.65), BUY 61.8% < 0.65 → 拦截 (原逻辑用结构 R/R=4.03
        放宽到 0.55 放行了这笔亏损交易)。"""
        bot = _make_bot(tmp_path, live=True)
        result = await bot._execute_signal(
            "BUY",
            60685.0,
            has_position=False,
            final_confidence=0.618,
            structure_rr=1.27,  # 周期现在传 ATR 口径值
        )
        assert result.action == "blocked_low_confidence"

    @pytest.mark.asyncio
    async def test_entry_allowed_when_atr_rr_high(self, tmp_path) -> None:
        """ATR 口径 R/R=2.5 ≥ 2.0 → 放宽 0.55, 61.8% 放行 (真机会不误杀)。"""
        bot = _make_bot(tmp_path, live=True)
        bot._open_position = AsyncMock(return_value=True)  # type: ignore[assignment]
        result = await bot._execute_signal(
            "BUY",
            60685.0,
            has_position=False,
            final_confidence=0.618,
            structure_rr=2.5,
        )
        assert result.action == "open_long"


# ==================== P1-C: 技术翻转置信度封顶 + 逆势半仓 ====================


class TestFlipConfidenceCap:
    """技术翻转 BUY/SHORT 最终置信度 ≤ 0.60; AI 原生信号不受限。"""

    def test_flip_with_rule_bonus_capped(self) -> None:
        """回放 13:43: AI HOLD 55% + 翻转 + "+15% 严重超卖" 规则加成
        → 61.8% → 封顶 0.60。"""
        integ = _make_integrator("oversold_rebound", 0.40)

        def _bonus_15pct(
            market_data, original_confidence, original_can_buy, buy_mode, original_signal
        ):
            return SimpleNamespace(
                adjusted_confidence=original_confidence + 0.15,
                should_buy=True,
                price_level="mid",
                adjustment_reason="严重超卖(RSI<25): 置信度+15%",
                penalty_applied=False,
            )

        integ.high_price_optimizer.optimize_high_price_buy.side_effect = (
            _bonus_15pct
        )
        result = integ.process(
            {
                "price": 60685.0,
                "price_history": [60600.0] * 20,
                "technical": {"rsi": 21.4, "atr_percent": 0.0107, "price_history": [60600.0] * 20},
            },
            original_signal="hold",
            original_confidence=0.55,
        )
        assert result.final_signal == "BUY"
        assert result.final_confidence <= 0.60 + 1e-9
        assert any("封顶" in a for a in result.adjustments_made)

    def test_native_ai_buy_not_capped(self) -> None:
        """AI 原生 BUY 0.70 → 不受翻转封顶约束 (保持高置信路径)。"""
        integ = _make_integrator("oversold_rebound", 0.40)
        result = integ.process(
            {
                "price": 60685.0,
                "price_history": [60600.0] * 20,
                "technical": {"rsi": 21.4, "atr_percent": 0.0107, "price_history": [60600.0] * 20},
            },
            original_signal="buy",
            original_confidence=0.70,
        )
        assert result.final_signal == "BUY"
        assert result.final_confidence > 0.60
        assert not any("封顶" in a for a in result.adjustments_made)

    def test_flip_below_cap_unchanged(self) -> None:
        """翻转后置信度 0.55 < 0.60 → 不触发封顶 (零回归)。"""
        integ = _make_integrator("oversold_rebound", 0.40)
        result = integ.process(
            {
                "price": 60685.0,
                "price_history": [60600.0] * 20,
                "technical": {"rsi": 21.4, "atr_percent": 0.0107, "price_history": [60600.0] * 20},
            },
            original_signal="hold",
            original_confidence=0.50,
        )
        assert result.final_signal == "BUY"
        assert not any("封顶" in a for a in result.adjustments_made)


class TestOversoldFlipHalfSize:
    """oversold_rebound 翻转开仓用半仓 (与超卖抄底通道同口径)。"""

    @pytest.mark.asyncio
    async def test_oversold_flip_uses_half_size(self, tmp_path) -> None:
        bot = _make_bot(tmp_path, live=True)
        bot._open_position = AsyncMock(return_value=True)  # type: ignore[assignment]
        result = await bot._execute_signal(
            "BUY",
            60685.0,
            has_position=False,
            final_confidence=0.90,
            buy_mode="oversold_rebound",
        )
        assert result.action == "open_long"
        kwargs = bot._open_position.call_args.kwargs  # type: ignore[union-attr]
        assert kwargs["size_factor"] == 0.5

    @pytest.mark.asyncio
    async def test_other_mode_full_size(self, tmp_path) -> None:
        """非 oversold_rebound 模式 (如 trend_confirmation) → 全仓 (零回归)。"""
        bot = _make_bot(tmp_path, live=True)
        bot._open_position = AsyncMock(return_value=True)  # type: ignore[assignment]
        result = await bot._execute_signal(
            "BUY",
            60685.0,
            has_position=False,
            final_confidence=0.90,
            buy_mode="trend_confirmation",
        )
        assert result.action == "open_long"
        kwargs = bot._open_position.call_args.kwargs  # type: ignore[union-attr]
        assert kwargs["size_factor"] == 1.0

    def test_adaptive_buy_mode_exposed(self) -> None:
        """integrator 将自适应买入模式写入 market_data 供执行层使用。"""
        integ = _make_integrator("oversold_rebound", 0.40)
        market_data = {
            "price": 60685.0,
            "price_history": [60600.0] * 20,
            "technical": {"rsi": 21.4, "atr_percent": 0.0107, "price_history": [60600.0] * 20},
        }
        integ.process(market_data, original_signal="hold", original_confidence=0.50)
        assert market_data["adaptive_buy_mode"] == "oversold_rebound"


# ==================== P1-D: BTC 价格水平滞回带 ====================


class TestBtcLevelHysteresis:
    """进入 high/low 用基础判定, 退出需越过阈值 ± band (24h 区间 × 10%)。

    合成区间 [50, 100] (range=50): high 阈值=98.5, low 阈值=51.5,
    band=5.0 → high 退出边 93.5, low 退出边 56.5。
    区间宽度足够大, 3% 邻近确认与 relative_high(0.85) 确认不会污染
    滞回带内的基础判定 (滞回带内基础判定=mid)。
    """

    def _detector(self) -> BTCPriceLevelDetector:
        det = BTCPriceLevelDetector(BTCPriceLevelConfig())
        # 种子历史: 49 根在 [50.0, 100.0] 内振荡 → range=50
        det.price_history = [50.0 if i % 2 == 0 else 100.0 for i in range(49)]
        return det

    def test_mid_price_stays_mid(self) -> None:
        """价格远离阈值 (90: 非 is_high/非 relative_high/非邻近) → mid。"""
        det = self._detector()
        result = det.detect_level(90.0)
        assert result.level == "mid"

    def test_high_entry_then_persistence(self) -> None:
        """进入 high 后, 价格回落至阈值-band 之上 (96 ∈ [93.5, 98.5),
        基础判定 mid: 距离高点 4% > 3% 无邻近确认) → 滞回保持 high,
        消除 13:30 high → 13:43 mid 的振荡。"""
        det = self._detector()
        # 99.0: is_high (≥98.5) + 距离高点 1% < 3% → 2 确认 → 进入 high
        assert det.detect_level(99.0).level == "high"
        # 96.0: 基础判定 mid, 但 ≥ 98.5 - 5.0 = 93.5 → 滞回保持 high
        assert det.detect_level(96.0).level == "high"

    def test_high_exit_after_decisive_drop(self) -> None:
        """价格跌破 阈值-band (93.5) → 退出 high。"""
        det = self._detector()
        det.detect_level(99.0)  # → high
        det.detect_level(96.0)  # → 保持 high
        assert det.detect_level(93.0).level == "mid"  # < 93.5 → 退出

    def test_low_entry_then_persistence(self) -> None:
        det = self._detector()
        # 51.0: is_low (≤51.5) + relative_low (100-51)/50=0.98 ≥ 0.30
        # → 2 确认 → 进入 low
        assert det.detect_level(51.0).level == "low"
        # 53.0: 基础判定 mid, 但 ≤ 51.5 + 5.0 = 56.5 → 滞回保持 low
        assert det.detect_level(53.0).level == "low"

    def test_low_exit_after_decisive_rise(self) -> None:
        det = self._detector()
        det.detect_level(51.0)  # → low
        det.detect_level(53.0)  # → 保持 low
        assert det.detect_level(57.0).level == "mid"  # > 56.5 → 退出

    def test_band_configurable_to_zero(self) -> None:
        """hysteresis_band=0 → 退化为原行为 (无滞回): 96 < 阈值 98.5 → 立即退出。"""
        det = BTCPriceLevelDetector(BTCPriceLevelConfig(hysteresis_band=0.0))
        det.price_history = [50.0 if i % 2 == 0 else 100.0 for i in range(49)]
        det.detect_level(99.0)  # → high
        assert det.detect_level(96.0).level == "mid"  # 96 < 98.5 - 0 → 退出


# ==================== 配置 ====================


class TestCloseReliefConfig:
    def test_defaults_valid(self) -> None:
        cfg = TradingConfig()
        assert cfg.validate() == []
        assert cfg.close_relief_amount == 0.10
        assert cfg.close_relief_floor == 0.40

    def test_invalid_close_relief_rejected(self) -> None:
        assert any(
            "close_relief_amount" in e
            for e in TradingConfig(close_relief_amount=0.9).validate()
        )
        assert any(
            "close_relief_floor" in e
            for e in TradingConfig(close_relief_floor=1.5).validate()
        )
