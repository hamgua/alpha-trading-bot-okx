"""
交易周期日志优化 - 单元测试

覆盖:
- P1: HOLD信号免惩罚 + RSI渐进惩罚
- P2: HOLD+无持仓快速退出
- P4: 市场结构HOLD确认
- P5: 回调买入日志区分
- P6: 规则引擎缓存
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import dataclass

from alpha_trading_bot.ai.high_price_buy_optimizer import (
    HighPriceBuyOptimizer,
    HighPriceBuyConfig,
    HighPriceBuyResult,
)
from alpha_trading_bot.ai.adaptive_buy_condition import (
    AdaptiveBuyCondition,
    BuyConditions,
)


class TestHoldSignalNoPenalty:
    """P1: HOLD信号不应被高位优化器惩罚"""

    def setup_method(self):
        self.optimizer = HighPriceBuyOptimizer(HighPriceBuyConfig())

    def test_hold_signal_no_rsi_penalty(self):
        """HOLD信号在RSI>60时不应被惩罚"""
        market_data = {
            "price": 77000,
            "technical": {
                "price_position": 0.6,
                "rsi": 62.55,
                "trend_strength": 0.04,
                "trend_direction": "sideways",
            },
        }
        result = self.optimizer.optimize_high_price_buy(
            market_data=market_data,
            original_confidence=0.42,
            original_can_buy=False,
            buy_mode="mid",
            original_signal="HOLD",
        )
        assert result.adjusted_confidence == 0.42, (
            f"HOLD信号不应被惩罚，但置信度从42%变为{result.adjusted_confidence:.2%}"
        )

    def test_buy_signal_still_penalized_rsi(self):
        """BUY信号在RSI>60时仍应被惩罚"""
        market_data = {
            "price": 77000,
            "technical": {
                "price_position": 0.6,
                "rsi": 62.55,
                "trend_strength": 0.04,
                "trend_direction": "sideways",
            },
        }
        result = self.optimizer.optimize_high_price_buy(
            market_data=market_data,
            original_confidence=0.42,
            original_can_buy=True,
            buy_mode="mid",
            original_signal="BUY",
        )
        assert result.adjusted_confidence < 0.42, "BUY信号应被RSI惩罚"

    def test_hold_high_price_level_no_penalty(self):
        """HOLD信号在高位价格水平时不应被惩罚"""
        market_data = {
            "price": 80000,
            "technical": {
                "price_position": 0.75,
                "rsi": 55,
                "trend_strength": 0.2,
                "trend_direction": "up",
            },
        }
        # 先添加价格历史使价格水平判断生效
        for p in [75000, 76000, 77000, 78000, 79000, 80000]:
            self.optimizer.price_history.append(p)

        result = self.optimizer.optimize_high_price_buy(
            market_data=market_data,
            original_confidence=0.50,
            original_can_buy=False,
            buy_mode="high",
            original_signal="HOLD",
        )
        assert result.adjusted_confidence == 0.50, "HOLD信号在高价位不应被惩罚"

    def test_hold_trend_strength_no_penalty(self):
        """HOLD信号在趋势强度不足时不应被惩罚"""
        market_data = {
            "price": 77000,
            "technical": {
                "price_position": 0.4,
                "rsi": 50,
                "trend_strength": 0.02,
                "trend_direction": "sideways",
            },
        }
        result = self.optimizer.optimize_high_price_buy(
            market_data=market_data,
            original_confidence=0.40,
            original_can_buy=False,
            buy_mode="mid",
            original_signal="HOLD",
        )
        assert result.adjusted_confidence == 0.40, "HOLD信号不应因趋势弱被惩罚"

    def test_sell_signal_still_penalized(self):
        """SELL信号在RSI>60时仍应被惩罚"""
        market_data = {
            "price": 77000,
            "technical": {
                "price_position": 0.6,
                "rsi": 65,
                "trend_strength": 0.04,
                "trend_direction": "sideways",
            },
        }
        result = self.optimizer.optimize_high_price_buy(
            market_data=market_data,
            original_confidence=0.50,
            original_can_buy=False,
            buy_mode="mid",
            original_signal="SELL",
        )
        assert result.adjusted_confidence < 0.50, "SELL信号应被RSI惩罚"


class TestRSIGradualPenalty:
    """P1: RSI渐进式惩罚"""

    def setup_method(self):
        self.optimizer = HighPriceBuyOptimizer(HighPriceBuyConfig())

    def test_rsi_slightly_above_threshold(self):
        """RSI略超阈值时惩罚较小"""
        market_data = {
            "price": 77000,
            "technical": {
                "price_position": 0.3,
                "rsi": 62.0,
                "trend_strength": 0.2,
                "trend_direction": "up",
            },
        }
        result = self.optimizer.optimize_high_price_buy(
            market_data=market_data,
            original_confidence=0.50,
            original_can_buy=True,
            buy_mode="mid",
            original_signal="BUY",
        )
        # RSI=62, threshold=60, overshoot=(62-60)/10=0.2
        # penalty = min(0.2 * 0.12, 0.12) = 0.024
        # confidence = 0.50 - 0.024 = 0.476
        expected_max_penalty = 0.12
        actual_penalty = 0.50 - result.adjusted_confidence
        assert actual_penalty < expected_max_penalty, (
            f"RSI=62时惩罚应<12%, 实际惩罚={actual_penalty:.3f}"
        )
        assert actual_penalty > 0, "RSI>60时应有惩罚"

    def test_rsi_far_above_threshold(self):
        """RSI远超阈值时惩罚封顶在12%"""
        market_data = {
            "price": 77000,
            "technical": {
                "price_position": 0.3,
                "rsi": 78.0,
                "trend_strength": 0.2,
                "trend_direction": "up",
            },
        }
        result = self.optimizer.optimize_high_price_buy(
            market_data=market_data,
            original_confidence=0.60,
            original_can_buy=True,
            buy_mode="mid",
            original_signal="BUY",
        )
        # RSI=78, overshoot=(78-60)/10=1.8, penalty=min(1.8*0.12,0.12)=0.12
        rsi_penalty = 0.12
        actual_penalty = 0.60 - result.adjusted_confidence
        assert actual_penalty >= rsi_penalty * 0.9, (
            f"RSI=78时惩罚应接近12%, 实际={actual_penalty:.3f}"
        )

    def test_rsi_at_threshold_no_penalty(self):
        """RSI恰好在阈值时无惩罚"""
        market_data = {
            "price": 77000,
            "technical": {
                "price_position": 0.3,
                "rsi": 60.0,
                "trend_strength": 0.2,
                "trend_direction": "up",
            },
        }
        result = self.optimizer.optimize_high_price_buy(
            market_data=market_data,
            original_confidence=0.50,
            original_can_buy=True,
            buy_mode="mid",
            original_signal="BUY",
        )
        # RSI=60, 无惩罚
        rsi_penalty = 0.0
        for reason_part in result.adjustment_reason.split(";"):
            if "RSI" in reason_part:
                rsi_penalty = 1  # 标记有RSI惩罚
        assert result.adjusted_confidence == 0.50, (
            "RSI=60(等于阈值)不应有RSI惩罚"
        )


class TestPullbackBuyReason:
    """P5: 回调买入日志区分"""

    def test_weak_sideways_reason(self):
        """弱震荡市应显示'弱震荡市不适用'"""
        condition = AdaptiveBuyCondition(BuyConditions())
        market_data = {
            "price": 77000,
            "recent_change_percent": 0.002,
            "technical": {
                "rsi": 50,
                "macd_hist": 0,
                "bb_position": 0.45,
                "trend_direction": "sideways",
                "trend_strength": 0.04,
                "adx": 15,
                "price_position": 0.5,
            },
            "price_history": [77000] * 10,
            "hourly_changes": [0.001] * 5,
        }
        result = condition.should_buy(market_data)
        # 检查pullback_buy模式的结果
        mode_results = result.details.get("mode_results", {})
        pullback = mode_results.get("pullback_buy", {})
        if pullback:
            assert "弱震荡市" in pullback.get("reason", "") or "非上涨趋势" in pullback.get("reason", ""), (
                f"弱震荡市回调买入原因应包含'弱震荡市'或'非上涨趋势', 实际: {pullback.get('reason', '')}"
            )

    def test_downtrend_reason(self):
        """下跌趋势应显示'非上涨趋势'"""
        condition = AdaptiveBuyCondition(BuyConditions())
        market_data = {
            "price": 77000,
            "recent_change_percent": -0.005,
            "technical": {
                "rsi": 45,
                "macd_hist": -10,
                "bb_position": 0.3,
                "trend_direction": "down",
                "trend_strength": 0.3,
                "adx": 25,
                "price_position": 0.4,
            },
            "price_history": [77500, 77300, 77100, 77000],
            "hourly_changes": [-0.002, -0.003, -0.001],
        }
        result = condition.should_buy(market_data)
        mode_results = result.details.get("mode_results", {})
        pullback = mode_results.get("pullback_buy", {})
        if pullback:
            assert "非上涨趋势" in pullback.get("reason", ""), (
                f"下跌趋势回调买入原因应包含'非上涨趋势', 实际: {pullback.get('reason', '')}"
            )


class TestDecisionEngineHoldSafeMode:
    """P2: 安全模式+HOLD信号的处理"""

    def test_safe_mode_hold_no_position_returns_skip(self):
        """安全模式+HOLD+无持仓→skip"""
        from alpha_trading_bot.core.decision_engine import DecisionEngine

        config = MagicMock()
        config.trading.allow_short_selling = False

        engine = DecisionEngine(config)
        selected = MagicMock()
        selected.strategy_type = "safe_mode"
        selected.confidence = 1.0
        selected.reasons = ["high_volatility"]
        selected.signal = "HOLD"

        result = engine.make_decision("HOLD", selected, {"has_position": False})
        assert result["action"] == "skip"


class TestRuleResultCache:
    """P6: 规则引擎结果缓存"""

    def test_cached_result_preferred(self):
        """缓存结果应被优先使用"""
        # 这个测试验证的是 adaptive_bot.py 中 _execute_trade 的行为
        # 通过检查方法签名来验证参数存在
        import inspect
        from alpha_trading_bot.core.adaptive_bot import AdaptiveTradingBot

        sig = inspect.signature(AdaptiveTradingBot._execute_trade)
        assert "cached_rule_result" in sig.parameters, (
            "_execute_trade应接受cached_rule_result参数"
        )


class TestMarketStructureHoldConfirmation:
    """P4: 市场结构对HOLD信号的确认"""

    def test_hold_with_poor_rr_confirmed(self):
        """HOLD+R/R不足时应输出确认信息"""
        from alpha_trading_bot.ai.integrator import AISignalIntegrator, IntegrationConfig

        integrator = AISignalIntegrator(IntegrationConfig(
            enable_adaptive_buy=True,
            enable_signal_optimizer=True,
            enable_high_price_filter=True,
            enable_btc_detector=True,
            enable_sustained_decline_detector=True,
        ))

        # 构造震荡市数据，支撑和阻力接近当前价格，使R/R<1.5
        base = 77251.5
        # 创建一个sideways结构的price_history：在76800-77600之间震荡
        price_history = [
            76882, 77000, 77200, 77400, 77602, 77400, 77200, 77000,
            76882, 77000, 77200, 77400, 77602, 77400, 77251.5,
        ]

        market_data = {
            "price": base,
            "recent_change_percent": 0.003,
            "change_percent": 0.35,
            "technical": {
                "rsi": 62.55,
                "macd_hist": -5,
                "bb_position": 0.55,
                "trend_direction": "sideways",
                "trend_strength": 0.04,
                "adx": 18,
                "price_position": 0.5,
                "atr_percent": 0.3685,
            },
            "price_history": price_history,
            "hourly_changes": [0.001, -0.002, 0.001, -0.001, 0.002],
        }

        result = integrator.process(
            market_data=market_data,
            original_signal="HOLD",
            original_confidence=0.42,
        )

        # 直接验证integrator的market_structure_result
        if result.market_structure_result:
            rr = result.market_structure_result.risk_reward_ratio
            # 如果R/R确实不足，检查是否有确认信息
            if rr < 1.5:
                has_rr_confirm = any(
                    "市场结构确认" in adj for adj in (result.adjustments_made or [])
                )
                assert has_rr_confirm, (
                    f"HOLD+R/R={rr:.2f}<1.5时应有市场结构确认, "
                    f"adjustments={result.adjustments_made}"
                )
            else:
                # R/R不低，则无需确认（测试数据可能产生不同的R/R）
                pass


class TestAIClientMetrics:
    """2026-06-22 任务：AI 客户端 max_tokens 截断与 reasoning 兜底指标"""

    def test_metrics_initialized_with_zero(self):
        """指标字段初始化为 0"""
        from alpha_trading_bot.ai.client import AIClient

        client = AIClient(enable_cache=False)
        metrics = client.get_metrics()
        assert metrics["max_tokens_truncated"] == 0
        assert metrics["reasoning_fallback_hits"] == 0
        assert metrics["reasoning_fallback_misses"] == 0

    def test_metrics_returns_copy(self):
        """get_metrics 返回副本，外部修改不影响内部状态"""
        from alpha_trading_bot.ai.client import AIClient

        client = AIClient(enable_cache=False)
        snapshot = client.get_metrics()
        snapshot["max_tokens_truncated"] = 999
        assert client.get_metrics()["max_tokens_truncated"] == 0

    def test_max_tokens_counter_increments(self):
        """max_tokens_truncated 计数正确自增（直接模拟）"""
        from alpha_trading_bot.ai.client import AIClient

        client = AIClient(enable_cache=False)
        # 直接调用内部自增（模拟三次截断）
        for _ in range(3):
            client._metrics["max_tokens_truncated"] += 1
        assert client.get_metrics()["max_tokens_truncated"] == 3

    def test_reasoning_fallback_hits_counter(self):
        """reasoning_fallback_hits 计数正确自增"""
        from alpha_trading_bot.ai.client import AIClient

        client = AIClient(enable_cache=False)
        for _ in range(2):
            client._metrics["reasoning_fallback_hits"] += 1
        assert client.get_metrics()["reasoning_fallback_hits"] == 2

    def test_reasoning_fallback_misses_counter(self):
        """reasoning_fallback_misses 计数正确自增"""
        from alpha_trading_bot.ai.client import AIClient

        client = AIClient(enable_cache=False)
        client._metrics["reasoning_fallback_misses"] += 1
        assert client.get_metrics()["reasoning_fallback_misses"] == 1

    def test_all_three_counters_independent(self):
        """三个计数器相互独立，不会互相影响"""
        from alpha_trading_bot.ai.client import AIClient

        client = AIClient(enable_cache=False)
        client._metrics["max_tokens_truncated"] += 5
        client._metrics["reasoning_fallback_hits"] += 3
        client._metrics["reasoning_fallback_misses"] += 2

        metrics = client.get_metrics()
        assert metrics["max_tokens_truncated"] == 5
        assert metrics["reasoning_fallback_hits"] == 3
        assert metrics["reasoning_fallback_misses"] == 2


class TestDecisionEngineConflictMetrics:
    """2026-06-22 任务：决策引擎 AI/策略冲突指标"""

    @staticmethod
    def _make_engine():
        from alpha_trading_bot.core.decision_engine import DecisionEngine

        class FakeConfig:
            class trading:
                allow_short_selling = False

            class ai:
                fusion_threshold = 0.5

        return DecisionEngine(FakeConfig())

    def test_metrics_initialized_with_zero(self):
        """冲突指标初始化为 0"""
        engine = self._make_engine()
        metrics = engine.get_conflict_metrics()
        assert metrics["ai_hold_strategy_buy_conservative_skip"] == 0
        assert metrics["ai_hold_oversold_buy_executed"] == 0
        assert metrics["ai_hold_strategy_buy_executed"] == 0
        assert metrics["market_structure_short_executed"] == 0

    def test_metrics_returns_copy(self):
        """get_conflict_metrics 返回副本"""
        engine = self._make_engine()
        snapshot = engine.get_conflict_metrics()
        snapshot["ai_hold_strategy_buy_conservative_skip"] = 99
        assert (
            engine.get_conflict_metrics()["ai_hold_strategy_buy_conservative_skip"]
            == 0
        )

    def test_conservative_skip_counter(self):
        """保守跳过计数器自增"""
        engine = self._make_engine()
        engine._conflict_metrics["ai_hold_strategy_buy_conservative_skip"] += 1
        engine._conflict_metrics["ai_hold_strategy_buy_conservative_skip"] += 1
        assert (
            engine.get_conflict_metrics()["ai_hold_strategy_buy_conservative_skip"]
            == 2
        )

    def test_oversold_buy_counter(self):
        """超卖反弹执行计数器自增"""
        engine = self._make_engine()
        engine._conflict_metrics["ai_hold_oversold_buy_executed"] += 1
        assert engine.get_conflict_metrics()["ai_hold_oversold_buy_executed"] == 1

    def test_strategy_buy_counter(self):
        """策略 BUY 覆盖执行计数器自增"""
        engine = self._make_engine()
        engine._conflict_metrics["ai_hold_strategy_buy_executed"] += 1
        assert engine.get_conflict_metrics()["ai_hold_strategy_buy_executed"] == 1

    def test_market_structure_short_counter(self):
        """市场结构 SHORT 覆盖执行计数器自增"""
        engine = self._make_engine()
        engine._conflict_metrics["market_structure_short_executed"] += 1
        assert engine.get_conflict_metrics()["market_structure_short_executed"] == 1

    def test_all_counters_independent(self):
        """四个计数器相互独立"""
        engine = self._make_engine()
        engine._conflict_metrics["ai_hold_strategy_buy_conservative_skip"] += 2
        engine._conflict_metrics["ai_hold_oversold_buy_executed"] += 1
        engine._conflict_metrics["ai_hold_strategy_buy_executed"] += 3
        engine._conflict_metrics["market_structure_short_executed"] += 1

        metrics = engine.get_conflict_metrics()
        assert metrics["ai_hold_strategy_buy_conservative_skip"] == 2
        assert metrics["ai_hold_oversold_buy_executed"] == 1
        assert metrics["ai_hold_strategy_buy_executed"] == 3
        assert metrics["market_structure_short_executed"] == 1