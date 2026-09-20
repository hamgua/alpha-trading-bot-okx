"""2026-09-20 loss-structure-fix 行为回归测试

基于 30 天实盘日志 (2026-08-21 ~ 2026-09-20) 的量化根因修复：

- R1 全仓止盈默认保持原目标（不再 50% 砍半，修复 R/R 结构性倒挂）
- R2 追踪止损手续费感知收紧门槛（锁定净浮盈 ≥ 2×往返手续费）
- R3 名义价值按合约规格计算（ctVal 修正，修复 100× 高估）
- R4 开仓张数按账户容量决策（不再硬编码最小张数死代码）
- R5 平仓审计查询止盈单 algo 历史（止盈触发不再落入"推断"）
- R6 止损重试保留原风险距离（不再塌缩到 0.1%/1USDT）
- R7 逆势做空门禁（24h 涨幅超上限禁止新开空单）
"""

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from alpha_trading_bot.config.models import (
    Config,
    ExchangeConfig,
    StopLossConfig,
    TradingConfig,
)


# =========================================================================
# R1: 全仓止盈默认保持原目标
# =========================================================================


class TestFullAmountTakeProfitKeepsTarget:
    """最小张数仓位 100% 走全仓止盈回退分支时必须保持原目标。"""

    def test_default_pull_ratio_is_one(self) -> None:
        config = StopLossConfig()
        assert config.take_profit_full_amount_pull_ratio == 1.0

    def test_validate_pull_ratio_bounds(self) -> None:
        assert StopLossConfig(take_profit_full_amount_pull_ratio=0.5).validate() == []
        errors = StopLossConfig(take_profit_full_amount_pull_ratio=0.0).validate()
        assert any("全仓止盈拉近比例" in e for e in errors)
        errors = StopLossConfig(take_profit_full_amount_pull_ratio=1.5).validate()
        assert any("全仓止盈拉近比例" in e for e in errors)

    @pytest.mark.asyncio
    async def test_full_amount_tp_keeps_structural_target(self) -> None:
        """结构位止盈 101.0988 不再被砍半成 100.5494 (旧行为)。"""
        from alpha_trading_bot.core.adaptive_bot import AdaptiveTradingBot

        config = Config(
            exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
            trading=TradingConfig(
                test_mode=False, real_trading_confirmed=True
            ),
            stop_loss=StopLossConfig(take_profit_min_notional=0.0),
        )
        bot = AdaptiveTradingBot(config)
        calls: List[Dict[str, Any]] = []

        class _Exchange:
            symbol = "BTC/USDT:USDT"

            def calculate_notional_usdt(self, amount: float, price: float) -> float:
                return amount * 0.01 * price  # ctVal=0.01 BTC/张

            async def create_take_profit(
                self, symbol: str, side: str, amount: float, take_profit_price: float
            ) -> str:
                calls.append(
                    {"amount": amount, "take_profit_price": take_profit_price}
                )
                return "tp-1"

        bot._exchange = _Exchange()  # type: ignore[assignment]
        bot.position_manager.update_position(0.01, 100.0, "BTC/USDT:USDT", "long")

        await bot._maybe_create_take_profit_order(
            position_side="long",
            amount=0.01,
            entry_price=100.0,
            symbol="BTC/USDT:USDT",
            market_data={"nearest_resistance": 101.2},
        )

        # 结构位目标 = 101.2 × (1 - 0.001) = 101.0988，保持不动
        assert calls[0]["take_profit_price"] == pytest.approx(101.0988)


# =========================================================================
# R2: 追踪止损手续费感知收紧门槛
# =========================================================================


class TestFeeAwareTrailingThreshold:
    """追踪止损收紧门槛 = max(配置值, 追踪距离 + 2×往返手续费)。"""

    def test_trailing_threshold_at_least_fee_covered(self) -> None:
        """taker 0.05% + 追踪 0.2% → 收紧门槛 ≥ 0.4%。"""
        config = StopLossConfig(
            stop_loss_profit_percent=0.002,
            min_profit_to_tighten_stop_percent=0.001,
            taker_fee_rate=0.0005,
        )
        round_trip_fee = 2 * config.taker_fee_rate
        threshold = max(
            config.min_profit_to_tighten_stop_percent,
            config.stop_loss_profit_percent + 2 * round_trip_fee,
        )
        assert threshold == pytest.approx(0.004)

    def test_taker_fee_rate_validation(self) -> None:
        assert StopLossConfig(taker_fee_rate=0.0).validate() == []
        errors = StopLossConfig(taker_fee_rate=0.5).validate()
        assert any("taker手续费率" in e for e in errors)

    @pytest.mark.asyncio
    async def test_update_stop_loss_uses_fee_aware_threshold(self, caplog) -> None:
        """传统模式日志中收紧门槛应体现手续费感知值 (0.40% 而非 0.10%)。"""
        import logging

        from alpha_trading_bot.core.adaptive_bot import AdaptiveTradingBot

        bot = MagicMock(spec=AdaptiveTradingBot)
        config = Config(
            exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
            trading=TradingConfig(test_mode=True),
            stop_loss=StopLossConfig(
                stop_loss_entry_based=False,
                min_profit_to_tighten_stop_percent=0.001,
                stop_loss_profit_percent=0.002,
                taker_fee_rate=0.0005,
            ),
        )
        bot.config = config
        bot.position_manager = MagicMock()
        bot.position_manager.highest_price_since_entry = 100.05  # +0.05% 浮盈
        bot.position_manager.lowest_price_since_entry = 99.0
        bot.position_manager.last_stop_price = 99.5
        bot._exchange = MagicMock()
        bot._exchange.symbol = "BTC/USDT:USDT"
        bot._get_existing_stop_order_id = AsyncMock(return_value=(None, None))
        bot._create_stop_loss_with_retry = AsyncMock(return_value="stop-1")
        bot._refresh_close_audit_stop = MagicMock()
        bot.param_manager = MagicMock()
        bot.param_manager.get_parameters.return_value = {
            "stop_loss_percent": 0.005,
            "stop_loss_profit_percent": 0.002,
        }

        with caplog.at_level(logging.INFO):
            await AdaptiveTradingBot._update_stop_loss(
                bot,
                current_price=100.05,
                position_data={
                    "side": "long",
                    "entry_price": 100.0,
                    "amount": 0.01,
                },
                market_data={"technical": {"atr_percent": 0.002}},
            )

        # 浮盈 0.05% < 0.40% 门槛 → 使用基础止损
        assert "使用基础止损" in caplog.text
        assert "收紧门槛=0.40%" in caplog.text


# =========================================================================
# R3: 名义价值按合约规格计算
# =========================================================================


class TestNotionalCtVal:
    """notional 必须走 exchange.calculate_notional_usdt (ctVal 修正)。"""

    def test_uses_exchange_notional_when_available(self) -> None:
        from alpha_trading_bot.core.adaptive_bot import AdaptiveTradingBot

        bot = AdaptiveTradingBot(
            Config(
                exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
                trading=TradingConfig(test_mode=True),
            )
        )

        class _Exchange:
            def calculate_notional_usdt(self, amount: float, price: float) -> float:
                return amount * 0.01 * price  # ctVal=0.01

        bot._exchange = _Exchange()  # type: ignore[assignment]
        # 0.01 张 @ 78000 → $7.8，而非旧实现的 780.0 (100× 高估)
        assert bot._calculate_notional_usdt(0.01, 78000.0) == pytest.approx(7.8)

    def test_falls_back_to_amount_times_price(self) -> None:
        from alpha_trading_bot.core.adaptive_bot import AdaptiveTradingBot

        bot = AdaptiveTradingBot(
            Config(
                exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
                trading=TradingConfig(test_mode=True),
            )
        )

        class _Exchange:
            def calculate_notional_usdt(self, amount: float, price: float) -> float:
                raise RuntimeError("spec unavailable")

        bot._exchange = _Exchange()  # type: ignore[assignment]
        assert bot._calculate_notional_usdt(0.01, 78000.0) == pytest.approx(780.0)

    @pytest.mark.asyncio
    async def test_min_notional_gate_uses_real_notional(self, caplog) -> None:
        """$7.5 实际名义 < 50 USDT 门槛时必须跳过止盈单 (ctVal 修正后)。"""
        import logging

        from alpha_trading_bot.core.adaptive_bot import AdaptiveTradingBot

        config = Config(
            exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
            trading=TradingConfig(test_mode=True),
            stop_loss=StopLossConfig(take_profit_min_notional=50.0),
        )
        bot = AdaptiveTradingBot(config)

        class _Exchange:
            symbol = "BTC/USDT:USDT"

            def calculate_notional_usdt(self, amount: float, price: float) -> float:
                return amount * 0.01 * price

        bot._exchange = _Exchange()  # type: ignore[assignment]
        with caplog.at_level(logging.INFO):
            await bot._maybe_create_take_profit_order(
                position_side="long",
                amount=0.01,
                entry_price=78000.0,
                symbol="BTC/USDT:USDT",
            )

        assert "名义金额过小，跳过止盈单" in caplog.text
        assert "notional=7.8" in caplog.text


# =========================================================================
# R4: 开仓张数按账户容量决策
# =========================================================================


class TestOpenAmountSizing:
    """开仓张数 = clamp(容量×建议比例, 最小张数, 容量)。"""

    @pytest.mark.asyncio
    async def test_scales_with_account_capacity(self) -> None:
        from alpha_trading_bot.core.adaptive_bot import AdaptiveTradingBot

        config = Config(
            exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
            trading=TradingConfig(test_mode=True),
        )
        config.exchange.leverage = 10
        bot = AdaptiveTradingBot(config)

        class _Exchange:
            async def calculate_max_contracts(
                self, price: float, leverage: int
            ) -> float:
                return 0.3846  # 账户容量

            def normalize_order_size(self, amount: float) -> float:
                return round(amount, 2)

        bot._exchange = _Exchange()  # type: ignore[assignment]
        amount = await bot._calculate_open_amount(0.1, 78000.0)
        # 0.3846 × 0.1 = 0.03846 → 归一化 0.04
        assert amount == pytest.approx(0.04)

    @pytest.mark.asyncio
    async def test_falls_back_to_min_size_on_capacity_failure(self) -> None:
        from alpha_trading_bot.core.adaptive_bot import AdaptiveTradingBot

        bot = AdaptiveTradingBot(
            Config(
                exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
                trading=TradingConfig(test_mode=True),
            )
        )

        class _Exchange:
            async def calculate_max_contracts(
                self, price: float, leverage: int
            ) -> float:
                raise RuntimeError("api down")

        bot._exchange = _Exchange()  # type: ignore[assignment]
        assert await bot._calculate_open_amount(0.1, 78000.0) == 0.01

    @pytest.mark.asyncio
    async def test_falls_back_when_capacity_below_minimum(self) -> None:
        from alpha_trading_bot.core.adaptive_bot import AdaptiveTradingBot

        bot = AdaptiveTradingBot(
            Config(
                exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
                trading=TradingConfig(test_mode=True),
            )
        )

        class _Exchange:
            async def calculate_max_contracts(
                self, price: float, leverage: int
            ) -> float:
                return 0.005  # 低于最小张数

        bot._exchange = _Exchange()  # type: ignore[assignment]
        assert await bot._calculate_open_amount(0.1, 78000.0) == 0.01

    @pytest.mark.asyncio
    async def test_never_exceeds_capacity(self) -> None:
        from alpha_trading_bot.core.adaptive_bot import AdaptiveTradingBot

        bot = AdaptiveTradingBot(
            Config(
                exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
                trading=TradingConfig(test_mode=True),
            )
        )

        class _Exchange:
            async def calculate_max_contracts(
                self, price: float, leverage: int
            ) -> float:
                return 0.05

            def normalize_order_size(self, amount: float) -> float:
                return amount

        bot._exchange = _Exchange()  # type: ignore[assignment]
        # 建议比例被截断到 [0.05, 1.0]，但张数永远 ≤ 容量
        amount = await bot._calculate_open_amount(0.9, 78000.0)
        assert amount <= 0.05


# =========================================================================
# R5: 平仓审计查询止盈单历史
# =========================================================================


class TestCloseAuditTakeProfitHistory:
    """止盈触发的持仓消失必须按止盈成交价确认，不再落入推断。"""

    @pytest.mark.asyncio
    async def test_tp_confirmed_close_beats_inference(self) -> None:
        from alpha_trading_bot.core.position_close_audit import (
            PositionCloseAuditContext,
            PositionCloseAuditor,
        )

        context = PositionCloseAuditContext()
        context.remember(
            side="short",
            entry_price=100.0,
            amount=0.01,
            stop_order_id="sl-1",
            stop_price=100.5,
            take_profit_order_id="tp-1",
            take_profit_price=97.0,
        )
        auditor = PositionCloseAuditor(context)

        class _Exchange:
            symbol = "BTC/USDT:USDT"

            async def get_algo_order_history(
                self,
                symbol: str,
                algo_id: str = "",
                limit: int = 20,
                ord_types: Optional[list] = None,
            ) -> list:
                if algo_id == "sl-1":
                    return []  # 止损单无成交
                return [
                    {
                        "id": "tp-1",
                        "info": {
                            "algoId": "tp-1",
                            "tpTriggerPx": "97.0",
                            "avgPx": "97.02",
                            "sz": "0.01",
                            "triggerTime": "1787000000000",
                        },
                    }
                ]

        result = await auditor.log_disappeared_position_close_event(
            _Exchange(), "BTC/USDT:USDT"
        )
        assert result["handled"] is True
        assert result["close_type"] == "confirmed"
        assert result["quality"] == "confirmed_algo"
        assert result["match_strategy"] == "exact_algo_id"
        assert result["exit_price"] == pytest.approx(97.02)
        # 空单 entry=100 exit=97.02 → +2.98%
        assert result["pnl_percent"] == pytest.approx(2.98)

    @pytest.mark.asyncio
    async def test_tp_fuzzy_match_does_not_backfill(self) -> None:
        """algo_id 不匹配时只记日志，不返回补记结果。"""
        from alpha_trading_bot.core.position_close_audit import (
            PositionCloseAuditContext,
            PositionCloseAuditor,
        )

        context = PositionCloseAuditContext()
        context.remember(
            side="short",
            entry_price=100.0,
            amount=0.01,
            stop_order_id="sl-1",
            stop_price=100.5,
            take_profit_order_id="tp-1",
            take_profit_price=97.0,
        )
        auditor = PositionCloseAuditor(context)

        class _Exchange:
            symbol = "BTC/USDT:USDT"

            async def get_algo_order_history(
                self,
                symbol: str,
                algo_id: str = "",
                limit: int = 20,
                ord_types: Optional[list] = None,
            ) -> list:
                if algo_id == "sl-1":
                    return []
                # 价格接近但 algo_id 不同 → 模糊匹配
                return [
                    {
                        "id": "tp-other",
                        "info": {
                            "algoId": "tp-other",
                            "tpTriggerPx": "97.0",
                            "avgPx": "97.0",
                            "triggerTime": "1787000000000",
                        },
                    }
                ]

        result = await auditor.log_disappeared_position_close_event(
            _Exchange(), "BTC/USDT:USDT"
        )
        # 未确认 → 回退估算路径 (按止损价 100.5 估算)
        assert result["close_type"] == "estimated"

    @pytest.mark.asyncio
    async def test_estimated_falls_back_to_tp_price_when_stop_missing(self) -> None:
        """止损价缺失时用止盈价估算 (而非放弃补记)。"""
        from alpha_trading_bot.core.position_close_audit import (
            PositionCloseAuditContext,
            PositionCloseAuditor,
        )

        context = PositionCloseAuditContext()
        context.remember(
            side="short",
            entry_price=100.0,
            amount=0.01,
            stop_order_id="sl-1",
            stop_price=0.0,  # 止损价缺失
            take_profit_order_id="tp-1",
            take_profit_price=97.0,
        )
        auditor = PositionCloseAuditor(context)

        class _Exchange:
            symbol = "BTC/USDT:USDT"

            async def get_algo_order_history(
                self,
                symbol: str,
                algo_id: str = "",
                limit: int = 20,
                ord_types: Optional[list] = None,
            ) -> list:
                return []

        result = await auditor.log_disappeared_position_close_event(
            _Exchange(), "BTC/USDT:USDT"
        )
        assert result["handled"] is True
        assert result["exit_price"] == pytest.approx(97.0)
        assert result["pnl_percent"] == pytest.approx(3.0)


# =========================================================================
# R6: 止损重试保留原风险距离
# =========================================================================


class TestStopRetryKeepsDistance:
    """重试不得把 0.5%~1.5% 风险距离塌缩到 0.1%/1USDT。"""

    def test_long_valid_stop_reused_on_retry(self) -> None:
        from alpha_trading_bot.core.adaptive_stop_loss import (
            AdaptiveStopLossManager,
        )

        # 原止损 78000 在当前价 79000 正确一侧 → 原样保留
        assert (
            AdaptiveStopLossManager._rebase_stop_price_for_retry(
                78000.0, 79000.0, "long"
            )
            == 78000.0
        )

    def test_long_crossed_stop_clamps_below_current(self) -> None:
        from alpha_trading_bot.core.adaptive_stop_loss import (
            AdaptiveStopLossManager,
        )

        # 价格跌破原止损 → 夹到 current - max(0.1%, 1USDT)
        assert (
            AdaptiveStopLossManager._rebase_stop_price_for_retry(
                78000.0, 77500.0, "long"
            )
            == pytest.approx(77500.0 - 77.5)
        )

    def test_short_valid_stop_reused_on_retry(self) -> None:
        from alpha_trading_bot.core.adaptive_stop_loss import (
            AdaptiveStopLossManager,
        )

        assert (
            AdaptiveStopLossManager._rebase_stop_price_for_retry(
                81000.0, 80000.0, "short"
            )
            == 81000.0
        )

    def test_short_crossed_stop_clamps_above_current(self) -> None:
        from alpha_trading_bot.core.adaptive_stop_loss import (
            AdaptiveStopLossManager,
        )

        assert (
            AdaptiveStopLossManager._rebase_stop_price_for_retry(
                80000.0, 80500.0, "short"
            )
            == pytest.approx(80500.0 + 80.5)
        )

    def test_invalid_prices_return_original(self) -> None:
        from alpha_trading_bot.core.adaptive_stop_loss import (
            AdaptiveStopLossManager,
        )

        assert (
            AdaptiveStopLossManager._rebase_stop_price_for_retry(
                78000.0, 0.0, "long"
            )
            == 78000.0
        )
        assert (
            AdaptiveStopLossManager._rebase_stop_price_for_retry(
                0.0, 79000.0, "long"
            )
            == 0.0
        )


# =========================================================================
# R7: 逆势做空门禁
# =========================================================================


def _real_config(short_gate: float = 1.5) -> Config:
    return Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(
            test_mode=True,
            allow_short_selling=True,
            short_entry_max_daily_change=short_gate,
        ),
    )


class TestShortEntryTrendGate:
    """24h 涨幅超过上限时禁止新开空单 (2026-09-18 -1.02% 根因)。"""

    def test_sell_override_blocked_on_strong_up_day(self) -> None:
        from alpha_trading_bot.core.decision_engine import DecisionEngine

        engine = DecisionEngine(_real_config())
        selected = MagicMock()
        selected.signal = "SELL"
        selected.confidence = 0.80
        selected.strategy_type = "mean_reversion"
        selected.reasons = []
        market_data = {
            "technical": {
                "atr_percent": 0.003,
                "rsi": 80,
                "reversal_confirmed": True,
            },
            "has_position": False,
            "risk_reward_ratio": 8.0,
            "short_risk_reward_ratio": 3.2,
            "market_structure_direction": "short",
            "market_structure": "bearish",
            "change_percent": 5.0,  # +5.0% 大阳线日
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "skip"
        assert "逆势做空R/R极差" in result["reason"]
        assert result["metadata"]["short_entry_trend_blocked"] is True

    def test_sell_override_allowed_on_down_day(self) -> None:
        from alpha_trading_bot.core.decision_engine import DecisionEngine

        engine = DecisionEngine(_real_config())
        selected = MagicMock()
        selected.signal = "SELL"
        selected.confidence = 0.80
        selected.strategy_type = "mean_reversion"
        selected.reasons = []
        market_data = {
            "technical": {
                "atr_percent": 0.003,
                "rsi": 80,
                "reversal_confirmed": True,
            },
            "has_position": False,
            "risk_reward_ratio": 8.0,
            "short_risk_reward_ratio": 3.2,
            "market_structure_direction": "short",
            "market_structure": "bearish",
            "change_percent": -1.2,
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "sell"

    def test_gate_disabled_with_zero(self) -> None:
        from alpha_trading_bot.core.decision_engine import DecisionEngine

        engine = DecisionEngine(_real_config(short_gate=0.0))
        selected = MagicMock()
        selected.signal = "SELL"
        selected.confidence = 0.80
        selected.strategy_type = "mean_reversion"
        selected.reasons = []
        market_data = {
            "technical": {
                "atr_percent": 0.003,
                "rsi": 80,
                "reversal_confirmed": True,
            },
            "has_position": False,
            "risk_reward_ratio": 8.0,
            "short_risk_reward_ratio": 3.2,
            "market_structure_direction": "short",
            "market_structure": "bearish",
            "change_percent": 5.0,
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "sell"

    def test_boundary_change_at_limit_allowed(self) -> None:
        """涨幅恰好等于上限 → 放行 (严格大于才拦截)。"""
        from alpha_trading_bot.core.decision_engine import DecisionEngine

        engine = DecisionEngine(_real_config())
        selected = MagicMock()
        selected.signal = "SELL"
        selected.confidence = 0.80
        selected.strategy_type = "mean_reversion"
        selected.reasons = []
        market_data = {
            "technical": {
                "atr_percent": 0.003,
                "rsi": 80,
                "reversal_confirmed": True,
            },
            "has_position": False,
            "risk_reward_ratio": 8.0,
            "short_risk_reward_ratio": 3.2,
            "market_structure_direction": "short",
            "market_structure": "bearish",
            "change_percent": 1.5,  # 恰好等于上限
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "sell"

    def test_missing_change_percent_allows(self) -> None:
        """24h 涨跌缺失时不误拦 (fail-open)。"""
        from alpha_trading_bot.core.decision_engine import DecisionEngine

        engine = DecisionEngine(_real_config())
        selected = MagicMock()
        selected.signal = "SELL"
        selected.confidence = 0.80
        selected.strategy_type = "mean_reversion"
        selected.reasons = []
        market_data = {
            "technical": {
                "atr_percent": 0.003,
                "rsi": 80,
                "reversal_confirmed": True,
            },
            "has_position": False,
            "risk_reward_ratio": 8.0,
            "short_risk_reward_ratio": 3.2,
            "market_structure_direction": "short",
            "market_structure": "bearish",
            # 无 change_percent
        }

        result = engine.make_decision("HOLD", selected, market_data)

        assert result["action"] == "sell"

    def test_config_validation(self) -> None:
        errors = TradingConfig(
            short_entry_max_daily_change=-1.0
        ).validate()
        assert any("short_entry_max_daily_change" in e for e in errors)
