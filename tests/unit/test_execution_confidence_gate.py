"""执行层置信度门禁（P0-1）：低置信度 BUY 开仓 / SELL 平仓在执行层被拦。

2026-10-08 手续费出血修复 / Task 1。
证据: 10-06→10-08 共 8 个往返，信号毛利 +$0.0005，手续费 -$0.1351；
8 笔 SELL 平仓最终置信度 54-67%（全部 < 0.75），8 笔 BUY 开仓全部为
LLM hold 翻转（最终 51-79%）。执行层此前对 LLM 信号零门禁
（JEV_CONF_SELL=0.75 只约束快车道，且 AI_FAST_LANE=off）。
"""

from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest

from alpha_trading_bot.ai.client import AIClient
from alpha_trading_bot.config.models import (
    AIConfig,
    Config,
    ExchangeConfig,
    TradingConfig,
)
from alpha_trading_bot.core.bot import TradingBot
from alpha_trading_bot.core.position_manager import PositionManager

MARKET = {"symbol": "BTC/USDT:USDT", "price": 84000.0, "price_history": [84000.0] * 20}


def _make_bot(
    tmp_path: Path,
    min_open: float = 0.75,
    min_close: float = 0.75,
    live: bool = False,
) -> TradingBot:
    """live=True 用实盘配置（SELL 平仓路径需要过实盘闸门）。"""
    config = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(
            test_mode=not live,
            real_trading_confirmed=True,
            runtime_environment="prod" if live else "dev",
            min_confidence_open=min_open,
            min_confidence_close=min_close,
        ),
    )
    bot = TradingBot(config)
    # 持久化隔离到 tmp_path（不碰真实 data/trading_state）
    bot.position_manager = PositionManager(config, data_dir=tmp_path)
    bot._exchange = MagicMock()
    bot._exchange.get_balance = AsyncMock(return_value=1000.0)
    bot._exchange.create_order = AsyncMock(return_value="")
    bot._stop_loss_manager = None
    return bot


class TestBuyConfidenceGate:
    """BUY 开仓置信度门禁。"""

    @pytest.mark.asyncio
    async def test_buy_below_gate_blocked(self, tmp_path) -> None:
        bot = _make_bot(tmp_path)
        bot._open_position = AsyncMock()  # type: ignore[assignment]
        result = await bot._execute_signal(
            "BUY", 84000.0, has_position=False, final_confidence=0.51
        )
        assert result.action == "blocked_low_confidence"
        bot._open_position.assert_not_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_buy_at_gate_passes(self, tmp_path) -> None:
        """边界：置信度 == 门禁值 → 通过（门禁是严格小于才拦）。"""
        bot = _make_bot(tmp_path)
        bot._open_position = AsyncMock()  # type: ignore[assignment]
        result = await bot._execute_signal(
            "BUY", 84000.0, has_position=False, final_confidence=0.75
        )
        assert result.action == "open_long"
        bot._open_position.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_buy_above_gate_passes(self, tmp_path) -> None:
        bot = _make_bot(tmp_path)
        bot._open_position = AsyncMock()  # type: ignore[assignment]
        result = await bot._execute_signal(
            "BUY", 84000.0, has_position=False, final_confidence=0.79
        )
        assert result.action == "open_long"
        bot._open_position.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_gate_disabled_with_zero(self, tmp_path) -> None:
        bot = _make_bot(tmp_path, min_open=0.0)
        bot._open_position = AsyncMock()  # type: ignore[assignment]
        result = await bot._execute_signal(
            "BUY", 84000.0, has_position=False, final_confidence=0.51
        )
        assert result.action == "open_long"
        bot._open_position.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_legacy_call_without_confidence_not_gated(self, tmp_path) -> None:
        """3 参旧调用（final_confidence=None）：门禁不生效，零回归。"""
        bot = _make_bot(tmp_path)
        bot._open_position = AsyncMock()  # type: ignore[assignment]
        result = await bot._execute_signal("BUY", 84000.0, has_position=False)
        assert result.action == "open_long"
        bot._open_position.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_buy_with_position_not_gated(self, tmp_path) -> None:
        """BUY + 有持仓 = 更新止损，不走开仓门禁。"""
        bot = _make_bot(tmp_path)
        bot.position_manager.update_position(0.02, 84000.0, "BTC/USDT:USDT")
        result = await bot._execute_signal(
            "BUY", 84000.0, has_position=True, final_confidence=0.30
        )
        assert result.action == "update_stop"


class TestSellConfidenceGate:
    """SELL 平仓置信度门禁（被拦时持仓保留，由止损单兜底）。"""

    @pytest.mark.asyncio
    async def test_sell_below_gate_blocked_position_kept(self, tmp_path) -> None:
        bot = _make_bot(tmp_path, live=True)
        bot.position_manager.update_position(0.02, 84000.0, "BTC/USDT:USDT")
        result = await bot._execute_signal(
            "SELL", 83900.0, has_position=True, final_confidence=0.54
        )
        assert result.action == "blocked_low_confidence"
        bot._exchange.create_order.assert_not_awaited()
        assert bot.position_manager.has_position(), "被拦 SELL 不得清空持仓"

    @pytest.mark.asyncio
    async def test_sell_at_gate_closes(self, tmp_path) -> None:
        bot = _make_bot(tmp_path, live=True)
        bot.position_manager.update_position(0.02, 84000.0, "BTC/USDT:USDT")
        result = await bot._execute_signal(
            "SELL", 83900.0, has_position=True, final_confidence=0.75
        )
        assert result.action == "close"
        bot._exchange.create_order.assert_awaited()
        assert not bot.position_manager.has_position()

    @pytest.mark.asyncio
    async def test_sell_gate_disabled_with_zero(self, tmp_path) -> None:
        bot = _make_bot(tmp_path, min_close=0.0, live=True)
        bot.position_manager.update_position(0.02, 84000.0, "BTC/USDT:USDT")
        result = await bot._execute_signal(
            "SELL", 83900.0, has_position=True, final_confidence=0.55
        )
        assert result.action == "close"

    @pytest.mark.asyncio
    async def test_sell_without_position_not_gated(self, tmp_path) -> None:
        bot = _make_bot(tmp_path, live=True)
        result = await bot._execute_signal(
            "SELL", 83900.0, has_position=False, final_confidence=0.54
        )
        assert result.action == "none"


class TestConfigDefaultsAndEnv:
    def test_defaults_are_075(self) -> None:
        cfg = TradingConfig()
        assert cfg.min_confidence_open == 0.75
        assert cfg.min_confidence_close == 0.75

    def test_env_mapping(self, monkeypatch) -> None:
        monkeypatch.setenv("MIN_CONFIDENCE_OPEN", "0.6")
        monkeypatch.setenv("MIN_CONFIDENCE_CLOSE", "0.9")
        for k, v in (
            ("OKX_API_KEY", "k"),
            ("OKX_SECRET", "s"),
            ("OKX_PASSWORD", "p"),
        ):
            monkeypatch.setenv(k, v)
        cfg = Config.from_env()
        assert cfg.trading.min_confidence_open == 0.6
        assert cfg.trading.min_confidence_close == 0.9

    def test_invalid_value_rejected(self) -> None:
        cfg = TradingConfig(min_confidence_open=1.2)
        assert any("min_confidence_open" in e for e in cfg.validate())


class TestCacheHitConfidence:
    """缓存命中路径同样必须给门禁提供置信度（否则缓存 SELL/BUY 永失置信度）。"""

    @pytest.mark.asyncio
    async def test_cache_hit_sets_final_confidence(self) -> None:
        client = AIClient(config=AIConfig(), api_keys={}, enable_cache=True)
        assert client._cache is not None
        client._cache.set(MARKET, "SELL", 0.6)
        market_data: Dict[str, Any] = dict(MARKET)
        signal = await client.get_signal(market_data)
        assert signal == "SELL"
        assert market_data.get("final_confidence") == 0.6
        trace = client.get_last_signal_trace()
        assert trace.get("cache_hit") is True
        assert (trace.get("integrator") or {}).get("final_confidence") == 0.6
