"""标准 bot 1-2R 止盈单（P1-3）：开仓即挂交易所侧止盈，止损/止盈兜底。

2026-10-08 手续费出血修复 / Task 3。
证据: BOT_MODE=standard 从不下止盈单（create_take_profit 仅 adaptive 调用），
8 笔全部由 AI SELL 信号平仓，浮盈被提前砍掉（T6 峰值 +0.0343 → 实际
+0.0117）；.env 的 TAKE_PROFIT_PERCENT=0.06（12R）对 standard 是死配置。
P0-1 门禁上线后低置信 SELL 被拦，仓位更需要交易所侧止盈兜底。
"""

from pathlib import Path
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

SYMBOL = "BTC/USDT:USDT"


def _make_bot(
    tmp_path: Path,
    rr_mult: float = 2.0,
    stop_pct: float = 0.005,
    min_notional: float = 0.0,
    min_rr: float = 1.0,
    live: bool = True,
) -> TradingBot:
    config = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(
            test_mode=not live,
            real_trading_confirmed=True,
            runtime_environment="prod" if live else "dev",
            decision_journal_enabled=False,
        ),
        stop_loss=StopLossConfig(
            stop_loss_percent=stop_pct,
            take_profit_rr_multiple=rr_mult,
            take_profit_min_notional=min_notional,
            take_profit_min_rr_ratio=min_rr,
        ),
    )
    bot = TradingBot(config)
    bot.position_manager = PositionManager(config, data_dir=tmp_path)
    bot._exchange = MagicMock()
    bot._exchange.get_balance = AsyncMock(return_value=1000.0)
    bot._exchange.get_market_data = AsyncMock(
        return_value={"price": 84000.0, "change_percent": 0.0}
    )
    bot._exchange.get_position = AsyncMock(return_value=None)
    bot._exchange.calculate_max_contracts = AsyncMock(return_value=0.02)
    bot._exchange.normalize_order_size = MagicMock(return_value=0.02)
    bot._exchange.create_order = AsyncMock(return_value="ORD-1")
    bot._exchange.create_stop_loss = AsyncMock(return_value="SL-1")
    bot._exchange.create_take_profit = AsyncMock(return_value="TP-1")
    bot._exchange.cancel_algo_order = AsyncMock(return_value=(True, ""))
    bot._exchange.calculate_notional_usdt = MagicMock(return_value=17.0)
    bot._stop_loss_manager = None
    return bot


class TestTakeProfitConfig:
    def test_default_2r(self) -> None:
        assert StopLossConfig().take_profit_rr_multiple == 2.0

    def test_env_mapping(self, monkeypatch) -> None:
        for k, v in (
            ("OKX_API_KEY", "k"),
            ("OKX_SECRET", "s"),
            ("OKX_PASSWORD", "p"),
            ("TAKE_PROFIT_RR_MULTIPLE", "3.0"),
        ):
            monkeypatch.setenv(k, v)
        assert Config.from_env().stop_loss.take_profit_rr_multiple == 3.0

    def test_validation(self) -> None:
        assert not StopLossConfig(take_profit_rr_multiple=0.0).validate()
        assert not StopLossConfig(take_profit_rr_multiple=2.0).validate()
        assert StopLossConfig(take_profit_rr_multiple=-1.0).validate()


class TestOpenCreatesTakeProfit:
    @pytest.mark.asyncio
    async def test_open_creates_tp_at_2r(self, tmp_path) -> None:
        """默认 2R：止损 0.5% → TP 距离 1.0% → 84000×1.01=84840。"""
        bot = _make_bot(tmp_path)
        await bot._open_position(84000.0)
        bot._exchange.create_take_profit.assert_awaited_once()
        kwargs = bot._exchange.create_take_profit.await_args.kwargs
        assert kwargs["side"] == "sell"
        assert kwargs["amount"] == 0.02
        assert kwargs["take_profit_price"] == pytest.approx(84840.0)
        assert bot.position_manager.take_profit_order_id == "TP-1"
        assert bot.position_manager.last_take_profit_price == pytest.approx(84840.0)
        # 止损单不受影响
        assert bot.position_manager.stop_order_id == "SL-1"

    @pytest.mark.asyncio
    async def test_tp_disabled_with_zero(self, tmp_path) -> None:
        bot = _make_bot(tmp_path, rr_mult=0.0)
        await bot._open_position(84000.0)
        bot._exchange.create_take_profit.assert_not_awaited()
        assert bot.position_manager.has_position()

    @pytest.mark.asyncio
    async def test_tp_min_notional_gate(self, tmp_path) -> None:
        bot = _make_bot(tmp_path, min_notional=100.0)  # 名义 17 < 100
        await bot._open_position(84000.0)
        bot._exchange.create_take_profit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_tp_distance_floored_at_min_rr(self, tmp_path) -> None:
        """RR 下限不变式：TP 距离 >= 止损距离×take_profit_min_rr_ratio（1R）。"""
        bot = _make_bot(tmp_path, rr_mult=0.5, min_rr=1.0)
        await bot._open_position(84000.0)
        kwargs = bot._exchange.create_take_profit.await_args.kwargs
        # 0.5×max(0.5, 1.0) = 0.5% → 84420
        assert kwargs["take_profit_price"] == pytest.approx(84420.0)

    @pytest.mark.asyncio
    async def test_tp_failure_keeps_position_with_stop(self, tmp_path) -> None:
        """止盈单失败不回滚仓位（止损单已存在，安全不变式保持）。"""
        bot = _make_bot(tmp_path)
        bot._exchange.create_take_profit = AsyncMock(return_value="")
        await bot._open_position(84000.0)
        assert bot.position_manager.has_position()
        assert bot.position_manager.stop_order_id == "SL-1"
        assert bot.position_manager.take_profit_order_id is None

    @pytest.mark.asyncio
    async def test_tp_exception_keeps_position(self, tmp_path) -> None:
        bot = _make_bot(tmp_path)
        bot._exchange.create_take_profit = AsyncMock(
            side_effect=RuntimeError("api down")
        )
        await bot._open_position(84000.0)
        assert bot.position_manager.has_position()
        assert bot.position_manager.stop_order_id == "SL-1"


class TestCloseCancelsTakeProfit:
    @pytest.mark.asyncio
    async def test_close_cancels_stop_and_tp(self, tmp_path) -> None:
        bot = _make_bot(tmp_path)
        bot.position_manager.update_position(0.02, 84000.0, SYMBOL)
        bot.position_manager.set_stop_order("SL-OLD")
        bot.position_manager.set_take_profit_order("TP-OLD", 84840.0)
        await bot._close_position(83900.0)
        assert not bot.position_manager.has_position()
        cancelled = [c.args[0] for c in bot._exchange.cancel_algo_order.await_args_list]
        assert "SL-OLD" in cancelled
        assert "TP-OLD" in cancelled


class TestRecovery:
    @pytest.mark.asyncio
    async def test_recovery_recreates_missing_tp(self, tmp_path) -> None:
        """有持仓但无止盈单 → 按入场价重建（与止损重建对称）。"""
        bot = _make_bot(tmp_path)
        bot.position_manager.update_position(0.02, 84000.0, SYMBOL)
        bot._exchange.get_position = AsyncMock(
            return_value={
                "symbol": SYMBOL,
                "side": "long",
                "amount": 0.02,
                "entry_price": 84000.0,
            }
        )
        bot._stop_loss_manager = MagicMock()
        bot._stop_loss_manager.get_existing_stop_order_id = AsyncMock(
            return_value="SL-EXIST"
        )
        await bot._check_stop_order_recovery()
        bot._exchange.create_take_profit.assert_awaited_once()
        kwargs = bot._exchange.create_take_profit.await_args.kwargs
        assert kwargs["take_profit_price"] == pytest.approx(84840.0)
        assert bot.position_manager.take_profit_order_id == "TP-1"

    @pytest.mark.asyncio
    async def test_recovery_skips_when_tp_present(self, tmp_path) -> None:
        bot = _make_bot(tmp_path)
        bot.position_manager.update_position(0.02, 84000.0, SYMBOL)
        bot.position_manager.set_take_profit_order("TP-OLD", 84840.0)
        bot._exchange.get_position = AsyncMock(
            return_value={
                "symbol": SYMBOL,
                "side": "long",
                "amount": 0.02,
                "entry_price": 84000.0,
            }
        )
        bot._stop_loss_manager = MagicMock()
        bot._stop_loss_manager.get_existing_stop_order_id = AsyncMock(
            return_value="SL-EXIST"
        )
        await bot._check_stop_order_recovery()
        bot._exchange.create_take_profit.assert_not_awaited()
