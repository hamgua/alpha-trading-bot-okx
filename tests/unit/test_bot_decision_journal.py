"""TradingBot × DecisionJournal 集成测试（P1）"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from alpha_trading_bot.config.models import Config, ExchangeConfig, TradingConfig
from alpha_trading_bot.core.bot import TradingBot


def _make_bot(tmp_path: Path) -> TradingBot:
    config = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(test_mode=True),
    )
    bot = TradingBot(config)
    bot._exchange = MagicMock()
    bot._exchange.get_balance = AsyncMock(return_value=1000.0)
    bot._exchange.create_order = AsyncMock(return_value="")
    bot._stop_loss_manager = None
    # 模拟 AIClient 溯源
    bot._ai_client = MagicMock()
    bot._ai_client.get_last_signal_trace = MagicMock(
        return_value={
            "cache_hit": False,
            "jev": {"choice": "hold", "confidence": 0.95, "reason": "adopt"},
            "llm": None,
            "integrator": {
                "original_signal": "hold",
                "original_confidence": 0.95,
                "final_signal": "HOLD",
                "final_confidence": 0.95,
                "adjustments": [],
            },
        }
    )
    return bot


def _journal_lines(tmp_path: Path) -> list:
    # conftest autouse fixture isolate_trading_state 将 TRADING_STATE_DIR 隔离到
    # tmp_path/trading-state，决策日志写入该目录
    state_dir = tmp_path / "trading-state"
    lines = []
    for f in state_dir.glob("decision_journal-*.jsonl"):
        lines += [
            json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l
        ]
    return lines


@pytest.mark.asyncio
async def test_cycle_writes_journal_entry(tmp_path) -> None:
    bot = _make_bot(tmp_path)
    market_data = {
        "price": 84000.0,
        "rsi": 50.0,
        "atr": 300.0,
        "change_24h_percent": 0.5,
    }
    await bot._record_decision(market_data, "HOLD", None)
    # 无持仓路径：execution 由调用方传入
    from alpha_trading_bot.core.bot import ExecutionResult

    await bot._record_decision(market_data, "HOLD", ExecutionResult("none"))
    entries = [l for l in _journal_lines(tmp_path) if l["type"] == "cycle"]
    assert len(entries) == 2
    e = entries[-1]
    assert e["market"]["price"] == 84000.0
    assert e["jev"]["choice"] == "hold"
    assert e["execution"]["action"] == "none"
    assert e["final"] == "HOLD"


@pytest.mark.asyncio
async def test_journal_disabled_writes_nothing(tmp_path, monkeypatch) -> None:
    bot = _make_bot(tmp_path)
    bot.config.trading.decision_journal_enabled = False
    bot._decision_journal = None  # 模拟未启用
    market_data = {"price": 84000.0}
    from alpha_trading_bot.core.bot import ExecutionResult

    await bot._record_decision(market_data, "HOLD", ExecutionResult("none"))
    assert _journal_lines(tmp_path) == []


@pytest.mark.asyncio
async def test_record_survives_journal_failure(tmp_path) -> None:
    # Review Focus #3：journal 内部抛异常也不得中断周期
    bot = _make_bot(tmp_path)
    import unittest.mock as mock

    with mock.patch.object(
        bot._decision_journal, "record_cycle", side_effect=RuntimeError("boom")
    ):
        from alpha_trading_bot.core.bot import ExecutionResult

        await bot._record_decision(
            {"price": 1.0}, "HOLD", ExecutionResult("none")
        )  # 不抛
