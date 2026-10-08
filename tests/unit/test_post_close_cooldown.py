"""平仓后冷却（P0-2）：平仓后 N 分钟内禁止重新开仓，斩断高频 churn。

2026-10-08 手续费出血修复 / Task 2。
证据: 平仓后 5 分钟即重开（T3→T4），T7 持仓仅 4.4 分钟；
每个 churn 往返固定流出 ≈ $0.0195（taker 费 + 滑点）。
"""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from alpha_trading_bot.config.models import Config, ExchangeConfig, TradingConfig
from alpha_trading_bot.core.bot import TradingBot
from alpha_trading_bot.core.position_manager import PositionManager
from alpha_trading_bot.core.state_persistence import StatePersistence


def _make_bot(
    tmp_path: Path,
    cooldown_minutes: int = 30,
    live: bool = False,
) -> TradingBot:
    config = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(
            test_mode=not live,
            real_trading_confirmed=True,
            runtime_environment="prod" if live else "dev",
            post_close_cooldown_minutes=cooldown_minutes,
            decision_journal_enabled=False,
        ),
    )
    bot = TradingBot(config)
    bot.position_manager = PositionManager(config, data_dir=tmp_path)
    bot._exchange = MagicMock()
    bot._exchange.get_balance = AsyncMock(return_value=1000.0)
    bot._exchange.get_market_data = AsyncMock(
        return_value={
            "price": 84000.0,
            "change_percent": 0.0,
            "recent_drop_percent": 0.0,
            "technical": {},
        }
    )
    bot._exchange.get_position = AsyncMock(return_value=None)
    bot._exchange.create_order = AsyncMock(return_value="")
    bot._stop_loss_manager = None
    return bot


class TestCooldownConfig:
    def test_default_30_minutes(self) -> None:
        assert TradingConfig().post_close_cooldown_minutes == 30

    def test_env_mapping(self, monkeypatch) -> None:
        for k, v in (
            ("OKX_API_KEY", "k"),
            ("OKX_SECRET", "s"),
            ("OKX_PASSWORD", "p"),
            ("POST_CLOSE_COOLDOWN_MINUTES", "45"),
        ):
            monkeypatch.setenv(k, v)
        assert Config.from_env().trading.post_close_cooldown_minutes == 45

    def test_validation(self) -> None:
        assert TradingConfig(post_close_cooldown_minutes=-1).validate()
        assert TradingConfig(post_close_cooldown_minutes=1441).validate()
        assert not TradingConfig(post_close_cooldown_minutes=0).validate()
        assert not TradingConfig(post_close_cooldown_minutes=30).validate()


class TestStatePersistenceLastCloseAt:
    def test_mark_and_reload(self, tmp_path: Path) -> None:
        p1 = StatePersistence(tmp_path)
        assert p1.load_state().last_close_at == ""
        p1.mark_last_close()
        assert p1.load_state().last_close_at != ""
        # 新实例（重启场景）能恢复
        p2 = StatePersistence(tmp_path)
        assert p2.load_state().last_close_at == p1.load_state().last_close_at


class TestPositionManagerCooldown:
    def test_no_stamp_not_in_cooldown(self, tmp_path: Path) -> None:
        pm = PositionManager(Config(), data_dir=tmp_path)
        assert not pm.is_in_post_close_cooldown(30)

    def test_fresh_stamp_in_cooldown(self, tmp_path: Path) -> None:
        pm = PositionManager(Config(), data_dir=tmp_path)
        pm.mark_last_close()
        assert pm.is_in_post_close_cooldown(30)

    def test_zero_cooldown_disabled(self, tmp_path: Path) -> None:
        pm = PositionManager(Config(), data_dir=tmp_path)
        pm.mark_last_close()
        assert not pm.is_in_post_close_cooldown(0)

    def test_old_stamp_out_of_cooldown(self, tmp_path: Path) -> None:
        pm = PositionManager(Config(), data_dir=tmp_path)
        pm.mark_last_close()
        pm._last_close_at = (datetime.now() - timedelta(hours=2)).isoformat()
        assert not pm.is_in_post_close_cooldown(30)

    def test_bad_timestamp_fail_open(self, tmp_path: Path) -> None:
        pm = PositionManager(Config(), data_dir=tmp_path)
        pm._last_close_at = "not-a-timestamp"
        assert not pm.is_in_post_close_cooldown(30)

    def test_restored_from_persistence(self, tmp_path: Path) -> None:
        pm1 = PositionManager(Config(), data_dir=tmp_path)
        pm1.mark_last_close()
        pm2 = PositionManager(Config(), data_dir=tmp_path)
        assert pm2.is_in_post_close_cooldown(30), "重启后冷却状态必须恢复"


class TestBotCooldownGate:
    @pytest.mark.asyncio
    async def test_buy_blocked_during_cooldown(self, tmp_path) -> None:
        bot = _make_bot(tmp_path)
        bot._open_position = AsyncMock()  # type: ignore[assignment]
        bot.position_manager.mark_last_close()
        result = await bot._execute_signal("BUY", 84000.0, has_position=False)
        assert result.action == "blocked_cooldown"
        bot._open_position.assert_not_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_buy_allowed_after_cooldown(self, tmp_path) -> None:
        bot = _make_bot(tmp_path)
        bot._open_position = AsyncMock()  # type: ignore[assignment]
        bot.position_manager.mark_last_close()
        bot.position_manager._last_close_at = (
            datetime.now() - timedelta(hours=1)
        ).isoformat()
        result = await bot._execute_signal("BUY", 84000.0, has_position=False)
        assert result.action == "open_long"
        bot._open_position.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_cooldown_zero_allows_immediate_reopen(self, tmp_path) -> None:
        bot = _make_bot(tmp_path, cooldown_minutes=0)
        bot._open_position = AsyncMock()  # type: ignore[assignment]
        bot.position_manager.mark_last_close()
        result = await bot._execute_signal("BUY", 84000.0, has_position=False)
        assert result.action == "open_long"

    @pytest.mark.asyncio
    async def test_close_stamps_last_close(self, tmp_path) -> None:
        """SELL 平仓成功后必须盖平仓时间戳。"""
        bot = _make_bot(tmp_path, live=True)
        bot.position_manager.update_position(0.02, 84000.0, "BTC/USDT:USDT")
        result = await bot._execute_signal("SELL", 83900.0, has_position=True)
        assert result.action == "close"
        assert bot.position_manager.is_in_post_close_cooldown(30)
        # 持久化文件里也有（重启不丢）
        assert bot.position_manager._persistence.load_state().last_close_at != ""

    @pytest.mark.asyncio
    async def test_external_close_stamps_last_close(self, tmp_path) -> None:
        """本地有持仓但 API 无持仓（交易所侧止损/止盈触发）→ 同样盖章。"""
        bot = _make_bot(tmp_path)
        bot.position_manager.update_position(0.02, 84000.0, "BTC/USDT:USDT")
        bot._ai_client = MagicMock()
        bot._ai_client.get_signal = AsyncMock(return_value="HOLD")
        bot._ai_client.get_last_signal_trace = MagicMock(return_value={})
        await bot._execute_trading_cycle()
        assert bot.position_manager.is_in_post_close_cooldown(30)
        assert not bot.position_manager.has_position()
