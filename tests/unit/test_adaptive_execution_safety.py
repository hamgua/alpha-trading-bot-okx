"""AdaptiveBot 执行安全回归测试。"""

from dataclasses import dataclass
from typing import Any, Dict, List

import pytest

from alpha_trading_bot.config.models import Config, ExchangeConfig, TradingConfig
from alpha_trading_bot.core.adaptive_bot import AdaptiveTradingBot
from alpha_trading_bot.core.position_manager import PositionManager
from alpha_trading_bot.exchange.models.orders import OrderResult, OrderStatus


def _live_config() -> Config:
    return Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(
            test_mode=False,
            real_trading_confirmed=True,
            runtime_environment="prod",
            allow_short_selling=True,
        ),
    )


class _Params:
    def get_parameters(self) -> Dict[str, float]:
        return {"fusion_threshold": 0.5}


class _RiskAllows:
    def calculate_trade_params(self, *args: Any, **kwargs: Any) -> Dict[str, float]:
        return {
            "suggested_position": 0.01,
            "stop_loss_price": 101.5,
            "stop_loss_percent": 0.005,
        }

    def can_open_position(self, *args: Any, **kwargs: Any) -> tuple[bool, str]:
        return True, "ok"


class _RiskBlocks(_RiskAllows):
    def can_open_position(self, *args: Any, **kwargs: Any) -> tuple[bool, str]:
        return False, "risk_blocked"


@dataclass
class _Regime:
    value: str = "trend"


class _MarketState:
    regime = _Regime()


class _RegimeDetector:
    def detect(self, market_data: Dict[str, Any]) -> _MarketState:
        return _MarketState()


class _PerformanceTracker:
    def __init__(self) -> None:
        self.records: List[Dict[str, Any]] = []

    def get_performance_metrics(self) -> Dict[str, Any]:
        return {}

    def record_trade(self, **kwargs: Any) -> None:
        self.records.append(kwargs)


class _RulesEngine:
    def evaluate_all(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"adjustments": {}, "triggered_rules": []}


class _StopLoss:
    async def create_stop_loss_with_retry(
        self,
        amount: float,
        stop_price: float,
        current_price: float,
        max_retries: int,
        position_side: str,
    ) -> str:
        return "stop-1"


def _wire_execution_deps(
    bot: AdaptiveTradingBot, tmp_path: Any, risk_manager: Any
) -> _PerformanceTracker:
    bot.position_manager = PositionManager(bot.config, data_dir=tmp_path)
    bot.param_manager = _Params()
    bot.risk_manager = risk_manager
    bot.regime_detector = _RegimeDetector()
    tracker = _PerformanceTracker()
    bot.performance_tracker = tracker
    bot.rules_engine = _RulesEngine()
    bot._adaptive_stop_loss = _StopLoss()
    return tracker


@pytest.mark.asyncio
async def test_open_uses_confirmed_fill_for_position_state(tmp_path: Any) -> None:
    """开仓后必须用真实成交数量和均价更新本地仓位。"""
    bot = AdaptiveTradingBot(_live_config())
    tracker = _wire_execution_deps(bot, tmp_path, _RiskAllows())

    class _Exchange:
        symbol = "BTC/USDT:USDT"

        async def create_order_with_status(
            self, symbol: str, side: str, amount: float, order_type: str = "market"
        ) -> OrderResult:
            return OrderResult(
                order_id="ord-1",
                status=OrderStatus.OPEN,
                symbol=symbol,
                side=side,
                order_type=order_type,
                requested_amount=amount,
                filled_amount=0.0,
                remaining_amount=amount,
                average_price=0.0,
            )

        async def get_order_status(self, order_id: str, symbol: str) -> OrderResult:
            return OrderResult(
                order_id=order_id,
                status=OrderStatus.CLOSED,
                symbol=symbol,
                side="sell",
                order_type="market",
                requested_amount=0.01,
                filled_amount=0.007,
                remaining_amount=0.0,
                average_price=101.25,
            )

    bot._exchange = _Exchange()

    await bot._execute_trade(
        action="sell",
        current_price=100.0,
        has_position=False,
        position_data={},
        market_data={"technical": {}},
        selected_strategy=None,
        cached_rule_result={"adjustments": {"position_multiplier": 1.0}},
    )

    assert bot.position_manager.position is not None
    assert bot.position_manager.position.side == "short"
    assert bot.position_manager.position.amount == pytest.approx(0.007)
    assert bot.position_manager.entry_price == pytest.approx(101.25)
    assert tracker.records[0]["side"] == "sell"
    assert tracker.records[0]["signal_type"] == "sell"


@pytest.mark.asyncio
async def test_open_respects_risk_gate_before_order(tmp_path: Any) -> None:
    """风控闸门拒绝开仓时，执行层不能继续下单。"""
    bot = AdaptiveTradingBot(_live_config())
    _wire_execution_deps(bot, tmp_path, _RiskBlocks())
    called = {"order": False}

    class _Exchange:
        symbol = "BTC/USDT:USDT"

        async def create_order(self, **kwargs: Any) -> str:
            called["order"] = True
            return "ord-1"

    bot._exchange = _Exchange()

    await bot._execute_trade(
        action="open",
        current_price=100.0,
        has_position=False,
        position_data={},
        market_data={"technical": {}},
        selected_strategy=None,
        cached_rule_result={"adjustments": {"position_multiplier": 1.0}},
    )

    assert called["order"] is False
    assert bot.position_manager.position is None
