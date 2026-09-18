"""实盘亏损根因修复测试 (dream 2026-09-16-loss-root-cause)

基于 2026-09-09 ~ 2026-09-13 实盘日志的证据分析:
- 5天6笔平仓, 胜率33%, 平均盈利+0.51% vs 平均亏损-0.80%, 净 -2.17%
- 所有亏损均为 -0.80% (VolatilityRule 低波动分支固定 SL=0.8%, 单位错误)
- 09-13 05:17 案例: AI 明确 HOLD(56%) + 5策略全 HOLD (safe_mode: 极端市场),
  但 AdaptiveBuyCondition 无条件翻转 HOLD→BUY(42.6%), 规则引擎把置信度门禁
  降到 40%, 导致低于抛硬币的置信度通过门禁开仓, 最终 -0.80% 止损

根因与修复:
- R1: VolatilityRule 单位混淆 (高波动阈值 0.60/0.35/0.20 与小数 atr_percent
      比较永远不触发; 低波动分支 atr<0.015 几乎恒触发, SL 固定 0.8% + 仓位 1.2x)
      → 修复: 阈值改为小数; 低波动 SL 改为 3×ATR 自适应 (clamp 0.3%~0.5%)
- R2: 置信度门禁可被规则降到抛硬币以下 (40%)
      → 修复: MIN_TRADE_CONFIDENCE_FLOOR=0.50 绝对下限; 规则阈值 clamp 到 [0.5, 0.9]
- R3: AdaptiveBuyCondition 无条件 HOLD→BUY 翻转 (甚至 SELL→BUY)
      → 修复: AI 明确 HOLD (≥55%) 时禁止翻转; SELL 永不翻转为 BUY
- R4: 学习闭环失效 (TradeRecord 无 signal_provider 属性 → 永远更新 "unknown";
      策略权重匹配 "buy_following" 永远不命中)
      → 修复: TradeRecord 增加 signal_provider/strategy_name; 按实际策略名更新
- R5: MAX_TRADE_ATR_PERCENT=0.55 (55% ATR) 死代码
      → 修复: 0.0055 (0.55% ATR)
- R6: 置信度日志格式错误 ("confidence: 0.5%" 实为 50%)
      → 修复: 百分比格式化
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from alpha_trading_bot.ai.adaptive.market_regime import (
    MarketRegime,
    MarketRegimeState,
)
from alpha_trading_bot.ai.adaptive.performance_tracker import (
    PerformanceMetrics,
    PerformanceTracker,
    TradeRecord,
    TradeOutcome,
)
from alpha_trading_bot.ai.adaptive.rules_engine import VolatilityRule
from alpha_trading_bot.config.thresholds import (
    ADAPTIVE_BUY_HOLD_FLIP_MAX_HOLD_CONFIDENCE,
    MAX_TRADE_ATR_PERCENT,
    MIN_TRADE_CONFIDENCE_FLOOR,
)


def _make_market_state(atr_percent: float) -> MarketRegimeState:
    return MarketRegimeState(
        regime=MarketRegime.NORMAL,
        confidence=0.5,
        trend_strength=0.0,
        volatility_level=0.0,
        rsi_level=50.0,
        atr_percent=atr_percent,
        trend_direction="sideways",
        regime_changes=0,
        timestamp="",
    )


def _make_perf() -> PerformanceMetrics:
    return PerformanceMetrics()


# ============================================================
# R1: VolatilityRule 单位修复 + ATR 比例止损
# ============================================================


class TestVolatilityRuleUnits:
    """日志证据: ATR%=0.14% (0.0014) 时 SL 被固定为 0.8%, 导致每笔亏损 -0.80%。"""

    def test_low_vol_atr_uses_atr_proportional_stop(self):
        """低波动 (ATR 0.14%): SL = 3×ATR ≈ 0.42%, 不再是固定 0.8%。"""
        rule = VolatilityRule()
        result = rule.evaluate(_make_market_state(0.0014), _make_perf())
        assert result.triggered is True
        sl = result.adjustment["stop_loss_percent"]
        assert sl == pytest.approx(0.0042, abs=1e-6)

    def test_low_vol_stop_clamped_min(self):
        """极低波动 (ATR 0.05%): 3×ATR=0.15% < 下限 0.3% → clamp 到 0.3%。"""
        rule = VolatilityRule()
        result = rule.evaluate(_make_market_state(0.0005), _make_perf())
        assert result.triggered is True
        assert result.adjustment["stop_loss_percent"] == pytest.approx(0.003)

    def test_low_vol_stop_clamped_max(self):
        """接近中等波动带边界 (ATR 0.17%): 3×ATR=0.51% > 上限 0.5% → clamp 到 0.5%。"""
        rule = VolatilityRule()
        result = rule.evaluate(_make_market_state(0.0017), _make_perf())
        assert result.triggered is True
        assert result.adjustment["stop_loss_percent"] == pytest.approx(0.005)

    def test_low_vol_position_multiplier_is_one(self):
        rule = VolatilityRule()
        result = rule.evaluate(_make_market_state(0.0014), _make_perf())
        assert result.adjustment["position_multiplier"] == 1.0

    def test_high_vol_branch_now_reachable(self):
        """高波动阈值单位修复: ATR 0.7% 触发极高波动分支 (原 0.60 永远不触发)。"""
        rule = VolatilityRule()
        result = rule.evaluate(_make_market_state(0.007), _make_perf())
        assert result.triggered is True
        assert result.adjustment["stop_loss_percent"] == 0.015
        assert result.adjustment["position_multiplier"] == 0.5

    def test_medium_vol_branch(self):
        """ATR 0.3% 触发中等波动分支 (0.20% < atr <= 0.35%)。"""
        rule = VolatilityRule()
        result = rule.evaluate(_make_market_state(0.003), _make_perf())
        assert result.triggered is True
        assert result.adjustment["stop_loss_percent"] == 0.007

    def test_medium_high_vol_branch(self):
        """ATR 0.5% 触发高波动分支 (0.35% < atr <= 0.6%)。"""
        rule = VolatilityRule()
        result = rule.evaluate(_make_market_state(0.005), _make_perf())
        assert result.triggered is True
        assert result.adjustment["stop_loss_percent"] == 0.01

    def test_normal_band_uses_atr_proportional_stop(self):
        """正常波动带 (0.10%~0.20%): ATR 比例止损, 不再不触发后用默认值。"""
        rule = VolatilityRule()
        result = rule.evaluate(_make_market_state(0.0015), _make_perf())
        assert result.triggered is True
        assert result.adjustment["stop_loss_percent"] == pytest.approx(0.0045, abs=1e-6)

    def test_fusion_threshold_never_below_floor(self):
        """规则引擎输出的 fusion_threshold 不得低于抛硬币下限 0.50。"""
        rule = VolatilityRule()
        for atr in (0.0005, 0.0014, 0.003, 0.005, 0.007):
            result = rule.evaluate(_make_market_state(atr), _make_perf())
            if result.triggered and "fusion_threshold" in result.adjustment:
                assert (
                    result.adjustment["fusion_threshold"] >= MIN_TRADE_CONFIDENCE_FLOOR
                ), f"ATR={atr} 时门禁被降到 {result.adjustment['fusion_threshold']}"

    def test_merge_higher_priority_wins(self):
        """合并顺序修复: 高优先级规则 (ConsecutiveLoss=15) 覆盖低优先级 (Volatility=10)。"""
        from alpha_trading_bot.ai.adaptive.rules_engine import AdaptiveRulesEngine

        engine = AdaptiveRulesEngine()
        state = _make_market_state(0.0014)  # 低波动带 → SL 0.42%, pos 1.0x
        perf = PerformanceMetrics()
        perf.consecutive_losses = 5  # 触发 ConsecutiveLoss (SL 0.3%, pos 0.2x)

        result = engine.evaluate_all(state, perf)
        adjustments = result["adjustments"]
        # ConsecutiveLoss (优先级15) 应覆盖 VolatilityRule (优先级10)
        assert adjustments["stop_loss_percent"] == 0.003
        assert adjustments["position_multiplier"] == 0.2


# ============================================================
# R2: 置信度绝对下限
# ============================================================


class TestConfidenceFloor:
    """日志证据: 规则把门禁降到 40%, 42.6% 置信度的 BUY (低于抛硬币) 通过开仓。"""

    def test_threshold_constant_is_coin_flip(self):
        assert MIN_TRADE_CONFIDENCE_FLOOR == 0.50

    def _make_engine(self, min_trade_confidence: float):
        from alpha_trading_bot.core.decision_engine import DecisionEngine

        config = SimpleNamespace(
            ai=SimpleNamespace(fusion_threshold=0.5),
            trading=SimpleNamespace(
                investment_type="moderate", allow_short_selling=True
            ),
        )
        engine = DecisionEngine(config)
        market_data = {"min_trade_confidence": min_trade_confidence}
        selected = SimpleNamespace(
            confidence=0.426,
            signal="BUY",
            strategy_type="trend_following",
        )
        return engine, selected, market_data

    def test_buy_below_coin_flip_blocked_even_if_rule_lowered_gate(self):
        """规则把门禁降到 0.40, 但 42.6% 置信度仍必须被拦截。"""
        engine, selected, market_data = self._make_engine(0.40)
        block = engine._confidence_gate("long", selected, market_data)
        assert block["action"] == "skip"

    def test_buy_at_exactly_floor_allowed(self):
        engine, selected, market_data = self._make_engine(0.40)
        selected.confidence = 0.50
        assert engine._confidence_gate("long", selected, market_data) == {}

    def test_rule_threshold_clamped_in_bot(self):
        """adaptive_bot._apply_rule_threshold_to_market_data 将规则阈值 clamp 到 [0.5, 0.9]。"""
        from alpha_trading_bot.core.adaptive_bot import AdaptiveTradingBot

        bot = AdaptiveTradingBot.__new__(AdaptiveTradingBot)
        market_data = {}
        rule_result = {"adjustments": {"fusion_threshold": 0.40}}
        AdaptiveTradingBot._apply_rule_threshold_to_market_data(
            bot, market_data, rule_result
        )
        assert market_data["min_trade_confidence"] == 0.50

    def test_rule_threshold_higher_passes_through(self):
        from alpha_trading_bot.core.adaptive_bot import AdaptiveTradingBot

        bot = AdaptiveTradingBot.__new__(AdaptiveTradingBot)
        market_data = {}
        AdaptiveTradingBot._apply_rule_threshold_to_market_data(
            bot, market_data, {"adjustments": {"fusion_threshold": 0.65}}
        )
        assert market_data["min_trade_confidence"] == 0.65


# ============================================================
# R3: HOLD→BUY 翻转守卫
# ============================================================


class TestHoldFlipGuard:
    """日志证据: AI HOLD(56%) + 全策略 HOLD, 被 AdaptiveBuy 翻转为 BUY(42.6%) 开仓亏损。"""

    def _make_integrator(self):
        from alpha_trading_bot.ai.integrator import AISignalIntegrator
        from alpha_trading_bot.ai.integrator_config import IntegrationConfig

        integrator = AISignalIntegrator(
            config=IntegrationConfig(
                enable_adaptive_buy=True,
                enable_signal_optimizer=False,
                enable_high_price_filter=False,
                enable_btc_detector=False,
                enable_sustained_decline_detector=False,
            )
        )
        return integrator

    def _market_data(self, price: float = 77131.9) -> dict:
        return {
            "price": price,
            "technical": {
                "rsi": 50,
                "trend_direction": "up",
                "trend_strength": 0.02,
                "atr_percent": 0.0014,
            },
            "price_history": [price - 100, price - 50, price, price + 50, price + 100],
        }

    def test_explicit_ai_hold_not_flipped(self):
        """AI 明确 HOLD (56% >= 55%): 禁止翻转, 保持 HOLD。"""
        integrator = self._make_integrator()
        buy_result = SimpleNamespace(
            can_buy=True,
            confidence=0.733,
            mode="trend_confirmation",
        )
        integrator.adaptive_buy = MagicMock()
        integrator.adaptive_buy.should_buy.return_value = buy_result

        result = integrator.process(
            self._market_data(), original_signal="hold", original_confidence=0.56
        )
        assert result.final_signal == "HOLD"

    def test_weak_ai_hold_still_flippable(self):
        """AI 模糊 HOLD (40% < 55%): 允许自适应买入翻转 (保留原入场能力)。"""
        integrator = self._make_integrator()
        buy_result = SimpleNamespace(
            can_buy=True,
            confidence=0.733,
            mode="trend_confirmation",
        )
        integrator.adaptive_buy = MagicMock()
        integrator.adaptive_buy.should_buy.return_value = buy_result

        result = integrator.process(
            self._market_data(), original_signal="hold", original_confidence=0.40
        )
        assert result.final_signal == "BUY"

    def test_sell_never_flipped_to_buy(self):
        """AI SELL: 永不翻转为 BUY (SELL 必须执行平仓, 翻转会导致反向开仓)。"""
        integrator = self._make_integrator()
        buy_result = SimpleNamespace(
            can_buy=True,
            confidence=0.9,
            mode="trend_confirmation",
        )
        integrator.adaptive_buy = MagicMock()
        integrator.adaptive_buy.should_buy.return_value = buy_result

        result = integrator.process(
            self._market_data(), original_signal="sell", original_confidence=0.9
        )
        assert result.final_signal != "BUY"

    def test_guard_threshold_is_documented(self):
        assert 0.5 <= ADAPTIVE_BUY_HOLD_FLIP_MAX_HOLD_CONFIDENCE < 0.8


# ============================================================
# R4: 学习闭环修复
# ============================================================


class TestLearningLoop:
    """日志证据: [在线学习] 更新 unknown / 策略权重从未更新 (匹配 buy_following 永不命中)。"""

    def test_trade_record_has_provider_and_strategy_fields(self):
        trade = TradeRecord(
            entry_time="2026-09-13T05:17:00",
            exit_time=None,
            entry_price=77131.9,
            exit_price=None,
            side="buy",
            pnl=None,
            pnl_percent=None,
            outcome=TradeOutcome.PENDING,
            confidence=0.426,
            signal_type="buy",
            market_regime="normal",
            used_threshold=0.5,
            used_stop_loss=0.0042,
            signal_provider="deepseek",
            strategy_name="trend_following",
        )
        assert trade.signal_provider == "deepseek"
        assert trade.strategy_name == "trend_following"

    def test_trade_record_backward_compatible_defaults(self):
        trade = TradeRecord(
            entry_time="t",
            exit_time=None,
            entry_price=1.0,
            exit_price=None,
            side="buy",
            pnl=None,
            pnl_percent=None,
            outcome=TradeOutcome.PENDING,
            confidence=0.5,
            signal_type="buy",
            market_regime="normal",
            used_threshold=0.5,
            used_stop_loss=0.005,
        )
        assert trade.signal_provider == "unknown"
        assert trade.strategy_name == ""

    def test_strategy_weight_updated_by_real_strategy_name(self):
        """平仓后按交易记录的实际策略名更新权重 (原来永远不命中)。"""
        from alpha_trading_bot.core.strategy_weight_manager import (
            StrategyWeightManager,
        )

        library = MagicMock()
        strat = MagicMock()
        strat.strategy_type = SimpleNamespace(value="trend_following")
        strat.name = "趋势跟踪"
        strat.weight = 0.9
        strat.update_weight = MagicMock()
        library.strategies = {"trend_following": strat}

        simple_learning = MagicMock()
        manager = StrategyWeightManager(library, simple_learning)

        trade = SimpleNamespace(
            outcome=TradeOutcome.LOSS,
            pnl_percent=-0.0042,
            signal_type="buy",
            signal_provider="deepseek",
            strategy_name="trend_following",
            confidence=0.426,
        )
        manager.update_strategy_weights(trade)

        strat.update_weight.assert_called_once()
        score = strat.update_weight.call_args.args[0]
        assert score < 0.5  # 亏损 → 降权
        simple_learning.online_update.assert_called_once()
        kwargs = simple_learning.online_update.call_args.kwargs
        assert kwargs["provider"] == "deepseek"  # 不再是 "unknown"

    def test_online_learning_not_updated_for_unknown(self):
        """无 provider 信息时不再污染 unknown 桶 (直接跳过在线学习)。"""
        from alpha_trading_bot.core.strategy_weight_manager import (
            StrategyWeightManager,
        )

        library = MagicMock()
        library.strategies = {}
        simple_learning = MagicMock()
        manager = StrategyWeightManager(library, simple_learning)

        trade = SimpleNamespace(
            outcome=TradeOutcome.LOSS,
            pnl_percent=-0.0042,
            signal_type="buy",
            signal_provider="unknown",
            strategy_name="",
            confidence=0.5,
        )
        manager.update_strategy_weights(trade)
        simple_learning.online_update.assert_not_called()

    def test_tracker_persists_new_fields(self, tmp_path):
        tracker = PerformanceTracker(data_dir=str(tmp_path))
        trade = tracker.record_trade(
            entry_time="2026-09-13T05:17:00",
            entry_price=77131.9,
            side="buy",
            confidence=0.426,
            signal_type="buy",
            market_regime="normal",
            used_threshold=0.5,
            used_stop_loss=0.0042,
            signal_provider="deepseek",
            strategy_name="trend_following",
        )
        assert trade.signal_provider == "deepseek"
        assert trade.strategy_name == "trend_following"

        # 平仓后持久化, 重新加载后字段保留
        tracker.close_trade(
            exit_time="2026-09-13T17:47:00", exit_price=76514.8, reason="stop"
        )
        tracker2 = PerformanceTracker(data_dir=str(tmp_path))
        loaded = list(tracker2._trades)
        assert len(loaded) == 1
        assert loaded[0].signal_provider == "deepseek"
        assert loaded[0].strategy_name == "trend_following"


# ============================================================
# R5: ATR 死代码门禁
# ============================================================


class TestAtrGate:
    def test_max_trade_atr_is_reachable(self):
        """原 0.55 (55% ATR) 永远不触发; 修复后 0.55% ATR 可触发。"""
        assert MAX_TRADE_ATR_PERCENT == 0.0055


# ============================================================
# R6: 置信度日志格式
# ============================================================


class TestConfidenceLogFormat:
    def test_open_log_shows_percentage(self, tmp_path, caplog):
        import logging

        tracker = PerformanceTracker(data_dir=str(tmp_path))
        with caplog.at_level(
            logging.INFO, logger="alpha_trading_bot.ai.adaptive.performance_tracker"
        ):
            tracker.record_trade(
                entry_time="t",
                entry_price=77131.9,
                side="buy",
                confidence=0.5,
                signal_type="buy",
                market_regime="normal",
                used_threshold=0.5,
                used_stop_loss=0.005,
            )
        open_logs = [r for r in caplog.records if "记录开仓" in r.getMessage()]
        assert open_logs, "未找到记录开仓日志"
        msg = open_logs[0].getMessage()
        assert "50%" in msg
        assert "0.5%" not in msg


# ============================================================
# 生产事故复现: 2026-09-13 05:17 实盘亏损案例
# ============================================================


class TestProductionIncidentReplay:
    """2026-09-13 05:17 实盘事故复现 (dream 2026-09-16-loss-root-cause)

    日志证据 (alpha-trading-bot-okx.log.2026-09-13):
    - [市场] 当前价格: 77131.9, ATR%: 0.14%
    - [AI响应] 提供商=deepseek, 信号=hold, 置信度=56%
    - [自适应买入条件] can_buy=True, mode=trend_confirmation, 置信度=73.33%
    - [市场结构] 结构=sideways, 支撑=77021.10, 阻力=77250.00
    - [信号集成] 原始=hold(56%) → 最终=BUY(43%)   ← 本不应翻转
    - [策略] 5 个策略全 HOLD (safe_mode 100% "极端市场: 趋势混乱")
    - [规则] 本周期交易置信度门禁: 40% (43% 通过门禁)
    - [执行] 开仓 long @ 77131.9, 止损 76514.8 (-0.80%)
    - 17:47 止损触发, pnl=-0.80% 亏损

    修复后: 该案例必须在至少一层被拦截, 且止损宽度从 0.80% 降为 0.42%。
    """

    def _incident_market_data(self) -> dict:
        return {
            "price": 77131.9,
            "technical": {
                "rsi": 50.0,
                "atr_percent": 0.0014,
                "trend_direction": "neutral",
                "trend_strength": 0.02,
                "adx": 20.0,
                "bb_position": 0.5,
                "price_position": 0.5,
                "macd_hist": 0.0,
            },
            # 震荡区间 77021~77250 附近的 15 分钟历史
            "price_history": [
                77100.0,
                77120.0,
                77150.0,
                77180.0,
                77160.0,
                77140.0,
                77170.0,
                77130.0,
                77090.0,
                77110.0,
                77190.0,
                77220.0,
                77240.0,
                77210.0,
                77180.0,
                77150.0,
                77130.0,
                77100.0,
                77140.0,
                77160.0,
            ],
            "hourly_changes": [0.0] * 24,
        }

    def _make_engine(self) -> "DecisionEngine":
        from alpha_trading_bot.core.decision_engine import DecisionEngine

        return DecisionEngine(
            SimpleNamespace(
                ai=SimpleNamespace(fusion_threshold=0.5),
                trading=SimpleNamespace(
                    investment_type="moderate", allow_short_selling=True
                ),
            )
        )

    def _hold_selection(self, confidence: float = 0.5):
        return SimpleNamespace(
            signal="HOLD",
            confidence=confidence,
            strategy_type="trend_following",
            reasons=[],
        )

    def test_incident_ai_hold_is_not_flipped_to_buy(self):
        """修复点 R3: AI 明确 HOLD (56%) 时, 自适应买入条件不得翻转为 BUY。"""
        from alpha_trading_bot.ai.integrator import AISignalIntegrator
        from alpha_trading_bot.ai.integrator_config import IntegrationConfig

        integrator = AISignalIntegrator(
            config=IntegrationConfig(
                enable_adaptive_buy=True,
                enable_signal_optimizer=False,
                enable_high_price_filter=False,
                enable_btc_detector=False,
                enable_sustained_decline_detector=False,
            )
        )
        # 日志中 AdaptiveBuyCondition 的实际输出
        integrator.adaptive_buy = MagicMock()
        integrator.adaptive_buy.should_buy.return_value = SimpleNamespace(
            can_buy=True, confidence=0.7333, mode="trend_confirmation"
        )

        result = integrator.process(
            self._incident_market_data(),
            original_signal="hold",
            original_confidence=0.56,
        )
        assert (
            result.final_signal == "HOLD"
        ), f"AI 明确 HOLD 不应被翻转为 {result.final_signal}"

    def test_incident_decision_is_skip(self):
        """修复点 R3 全链路: AI=HOLD + 策略=HOLD → 决策必须 skip (原为 open)。"""
        engine = self._make_engine()
        result = engine.make_decision(
            "HOLD", self._hold_selection(), self._incident_market_data()
        )
        assert result["action"] == "skip"

    def test_incident_buy_below_floor_blocked(self):
        """修复点 R2: 即使信号管线仍产出 BUY(42.6%), 门禁也必须拦截。

        (旧管线最终置信度 43% + 旧门禁 40% → 放行; 新门禁下限 50% → 拦截)
        """
        engine = self._make_engine()
        buy_selection = SimpleNamespace(
            signal="BUY", confidence=0.426, strategy_type="trend_following", reasons=[]
        )
        market_data = self._incident_market_data()
        market_data["ai_final_confidence"] = 0.426
        market_data["final_confidence"] = 0.426
        market_data["min_trade_confidence"] = 0.40  # 旧规则门禁
        result = engine.make_decision("BUY", buy_selection, market_data)
        assert result["action"] == "skip"
        assert "低于阈值" in result["reason"]

    def test_incident_stop_loss_width_halved(self):
        """修复点 R1: 同场景 (ATR 0.14%) 止损宽度 0.42%, 不再是 0.80%。"""
        rule = VolatilityRule()
        state = _make_market_state(0.0014)
        result = rule.evaluate(state, _make_perf())
        sl = result.adjustment["stop_loss_percent"]
        assert sl == pytest.approx(0.0042, abs=1e-6)
        # 单笔风险敞口: 1.0x × 0.42% = 0.42% (原 1.2x × 0.80% = 0.96%)
        risk_before = 1.2 * 0.008
        risk_after = result.adjustment["position_multiplier"] * sl
        assert risk_after < risk_before / 2
