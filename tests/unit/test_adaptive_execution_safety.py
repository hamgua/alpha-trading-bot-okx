"""AdaptiveBot 执行安全回归测试。"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import pytest

from alpha_trading_bot.config.models import (
    Config,
    ExchangeConfig,
    StopLossConfig,
    TradingConfig,
)
from alpha_trading_bot.core.adaptive_bot import AdaptiveTradingBot
from alpha_trading_bot.core.position_manager import PositionManager
from alpha_trading_bot.core.position_recovery import PositionRecoveryManager
from alpha_trading_bot.exchange.models.orders import OrderResult, OrderStatus


def _live_config(stop_loss: Optional[StopLossConfig] = None) -> Config:
    return Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(
            test_mode=False,
            real_trading_confirmed=True,
            runtime_environment="prod",
            allow_short_selling=True,
        ),
        stop_loss=stop_loss or StopLossConfig(),
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

    def can_open_position(self, *args: Any, **kwargs: Any) -> Tuple[bool, str]:
        return True, "ok"


class _RiskBlocks(_RiskAllows):
    def can_open_position(self, *args: Any, **kwargs: Any) -> Tuple[bool, str]:
        return False, "risk_blocked"


class _RiskBlocksLargePlan(_RiskAllows):
    def __init__(self) -> None:
        self.seen_position_percent = 0.0

    def calculate_trade_params(self, *args: Any, **kwargs: Any) -> Dict[str, float]:
        return {
            "suggested_position": 0.15,
            "stop_loss_price": 99.0,
            "stop_loss_percent": 0.005,
        }

    def can_open_position(
        self, market_data: Dict[str, Any], position_data: Dict[str, Any]
    ) -> Tuple[bool, str]:
        self.seen_position_percent = position_data.get("position_percent", 0.0)
        if self.seen_position_percent > 0.1:
            return False, "planned_position_too_large"
        return True, "ok"


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

    def close_trade(self, **kwargs: Any) -> None:
        return None


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


class _StopLossFails(_StopLoss):
    async def create_stop_loss_with_retry(
        self,
        amount: float,
        stop_price: float,
        current_price: float,
        max_retries: int,
        position_side: str,
    ) -> str:
        return ""


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


def test_clear_position_clears_take_profit_state(tmp_path: Any) -> None:
    """清仓时必须同时清理止损和止盈本地状态。"""
    position_manager = PositionManager(_live_config(), data_dir=tmp_path)
    position_manager.update_position(0.01, 100.0, "BTC/USDT:USDT", "long")
    position_manager.set_stop_order("sl-1", 99.0)
    position_manager.set_take_profit_order("tp-1", 100.8)

    position_manager.clear_position()

    assert position_manager.stop_order_id is None
    assert position_manager.last_stop_price == 0.0
    assert position_manager.take_profit_order_id is None
    assert position_manager.last_take_profit_price == 0.0


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


@pytest.mark.asyncio
async def test_open_risk_gate_receives_planned_position_percent(
    tmp_path: Any,
) -> None:
    """风控闸门应看到本次计划仓位，不能只看到空仓状态。"""
    bot = AdaptiveTradingBot(_live_config())
    risk_manager = _RiskBlocksLargePlan()
    _wire_execution_deps(bot, tmp_path, risk_manager)
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

    assert risk_manager.seen_position_percent == pytest.approx(0.15)
    assert called["order"] is False


@pytest.mark.asyncio
async def test_open_closes_position_when_initial_stop_loss_fails(
    tmp_path: Any,
) -> None:
    """开仓后保护性止损未创建时，应立即反向市价平仓。"""
    bot = AdaptiveTradingBot(_live_config())
    _wire_execution_deps(bot, tmp_path, _RiskAllows())
    bot._adaptive_stop_loss = _StopLossFails()
    orders: List[str] = []

    class _Exchange:
        symbol = "BTC/USDT:USDT"

        async def create_order_with_status(
            self, symbol: str, side: str, amount: float, order_type: str = "market"
        ) -> OrderResult:
            orders.append(side)
            return OrderResult(
                order_id=f"ord-{len(orders)}",
                status=OrderStatus.CLOSED,
                symbol=symbol,
                side=side,
                order_type=order_type,
                requested_amount=amount,
                filled_amount=amount,
                remaining_amount=0.0,
                average_price=100.0,
            )

        async def get_algo_orders(self, symbol: str) -> List[Dict[str, Any]]:
            return []

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

    assert orders == ["buy", "sell"]
    assert bot.position_manager.position is None


@pytest.mark.asyncio
async def test_open_skips_take_profit_when_notional_below_threshold(
    tmp_path: Any,
) -> None:
    """小额交易只保留止损保护，不创建止盈算法单。"""
    config = _live_config(
        StopLossConfig(take_profit_percent=0.06, take_profit_min_notional=2.0)
    )
    bot = AdaptiveTradingBot(config)
    _wire_execution_deps(bot, tmp_path, _RiskAllows())

    class _Exchange:
        symbol = "BTC/USDT:USDT"

        def __init__(self) -> None:
            self.take_profit_calls: List[Dict[str, Any]] = []

        async def create_order_with_status(
            self, symbol: str, side: str, amount: float, order_type: str = "market"
        ) -> OrderResult:
            return OrderResult(
                order_id="ord-1",
                status=OrderStatus.CLOSED,
                symbol=symbol,
                side=side,
                order_type=order_type,
                requested_amount=amount,
                filled_amount=amount,
                remaining_amount=0.0,
                average_price=100.0,
            )

        async def create_take_profit(
            self, symbol: str, side: str, amount: float, take_profit_price: float
        ) -> str:
            self.take_profit_calls.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "amount": amount,
                    "take_profit_price": take_profit_price,
                }
            )
            return "tp-1"

    exchange = _Exchange()
    bot._exchange = exchange

    await bot._execute_trade(
        action="open",
        current_price=100.0,
        has_position=False,
        position_data={},
        market_data={"technical": {}},
        selected_strategy=None,
        cached_rule_result={"adjustments": {"position_multiplier": 1.0}},
    )

    assert bot.position_manager.stop_order_id == "stop-1"
    assert exchange.take_profit_calls == []
    assert bot.position_manager._take_profit_order_id is None


@pytest.mark.asyncio
async def test_open_creates_take_profit_when_notional_reaches_threshold(
    tmp_path: Any,
) -> None:
    """达到最小名义金额后，开仓止损成功才创建止盈算法单。"""
    config = _live_config(
        StopLossConfig(take_profit_percent=0.06, take_profit_min_notional=1.0)
    )
    bot = AdaptiveTradingBot(config)
    _wire_execution_deps(bot, tmp_path, _RiskAllows())

    class _Exchange:
        symbol = "BTC/USDT:USDT"

        def __init__(self) -> None:
            self.take_profit_calls: List[Dict[str, Any]] = []

        async def create_order_with_status(
            self, symbol: str, side: str, amount: float, order_type: str = "market"
        ) -> OrderResult:
            return OrderResult(
                order_id="ord-1",
                status=OrderStatus.CLOSED,
                symbol=symbol,
                side=side,
                order_type=order_type,
                requested_amount=amount,
                filled_amount=amount,
                remaining_amount=0.0,
                average_price=100.0,
            )

        async def create_take_profit(
            self, symbol: str, side: str, amount: float, take_profit_price: float
        ) -> str:
            self.take_profit_calls.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "amount": amount,
                    "take_profit_price": take_profit_price,
                }
            )
            return "tp-1"

    exchange = _Exchange()
    bot._exchange = exchange

    await bot._execute_trade(
        action="open",
        current_price=100.0,
        has_position=False,
        position_data={},
        market_data={"technical": {}},
        selected_strategy=None,
        cached_rule_result={"adjustments": {"position_multiplier": 1.0}},
    )

    assert exchange.take_profit_calls == [
        {
            "symbol": "BTC/USDT:USDT",
            "side": "sell",
            "amount": 0.01,
            "take_profit_price": pytest.approx(106.0),
        }
    ]
    assert bot.position_manager._take_profit_order_id == "tp-1"
    assert bot.position_manager._last_take_profit_price == pytest.approx(106.0)


@pytest.mark.asyncio
async def test_close_uses_confirmed_fill_and_clears_position(tmp_path: Any) -> None:
    """平仓必须确认成交后再清理本地仓位。"""
    bot = AdaptiveTradingBot(_live_config())
    _wire_execution_deps(bot, tmp_path, _RiskAllows())
    bot.position_manager.update_position(0.01, 100.0, "BTC/USDT:USDT", "short")
    orders: List[str] = []

    class _Exchange:
        symbol = "BTC/USDT:USDT"

        async def create_order_with_status(
            self, symbol: str, side: str, amount: float, order_type: str = "market"
        ) -> OrderResult:
            orders.append(side)
            return OrderResult(
                order_id="close-1",
                status=OrderStatus.CLOSED,
                symbol=symbol,
                side=side,
                order_type=order_type,
                requested_amount=amount,
                filled_amount=amount,
                remaining_amount=0.0,
                average_price=99.0,
            )

    bot._exchange = _Exchange()

    await bot._execute_trade(
        action="close",
        current_price=99.0,
        has_position=True,
        position_data={
            "symbol": "BTC/USDT:USDT",
            "side": "short",
            "amount": 0.01,
            "entry_price": 100.0,
        },
        market_data={"technical": {}},
        selected_strategy=None,
        cached_rule_result={"adjustments": {"position_multiplier": 1.0}},
    )

    assert orders == ["buy"]
    assert bot.position_manager.position is None


@pytest.mark.asyncio
async def test_close_cancels_stop_loss_and_take_profit_before_market_close(
    tmp_path: Any,
) -> None:
    """主动平仓前必须取消本地和交易所中的止损/止盈保护单。"""
    bot = AdaptiveTradingBot(_live_config())
    _wire_execution_deps(bot, tmp_path, _RiskAllows())
    bot.position_manager.update_position(0.01, 100.0, "BTC/USDT:USDT", "long")
    bot.position_manager.set_stop_order("sl-local", 99.5)
    bot.position_manager.set_take_profit_order("tp-local", 100.8)
    canceled: List[str] = []
    orders: List[str] = []

    class _Exchange:
        symbol = "BTC/USDT:USDT"

        async def get_algo_orders(self, symbol: str) -> List[Dict[str, Any]]:
            assert symbol == "BTC/USDT:USDT"
            return [
                {
                    "id": "sl-exchange",
                    "info": {"algoId": "sl-exchange", "slTriggerPx": "99.5"},
                },
                {
                    "id": "tp-exchange",
                    "info": {"algoId": "tp-exchange", "tpTriggerPx": "100.8"},
                },
            ]

        async def cancel_algo_order(
            self, algo_id: str, symbol: str
        ) -> Tuple[bool, str]:
            assert symbol == "BTC/USDT:USDT"
            canceled.append(algo_id)
            return True, "ok"

        async def create_order_with_status(
            self, symbol: str, side: str, amount: float, order_type: str = "market"
        ) -> OrderResult:
            orders.append(side)
            return OrderResult(
                order_id="close-1",
                status=OrderStatus.CLOSED,
                symbol=symbol,
                side=side,
                order_type=order_type,
                requested_amount=amount,
                filled_amount=amount,
                remaining_amount=0.0,
                average_price=100.2,
            )

    exchange = _Exchange()
    bot._exchange = exchange
    bot._position_recovery = PositionRecoveryManager(exchange, bot.position_manager)

    await bot._execute_trade(
        action="close",
        current_price=100.2,
        has_position=True,
        position_data={
            "symbol": "BTC/USDT:USDT",
            "side": "long",
            "amount": 0.01,
            "entry_price": 100.0,
        },
        market_data={"technical": {}},
        selected_strategy=None,
        cached_rule_result={"adjustments": {"position_multiplier": 1.0}},
    )

    assert set(canceled) == {"sl-local", "tp-local", "sl-exchange", "tp-exchange"}
    assert orders == ["sell"]
    assert bot.position_manager.stop_order_id is None
    assert bot.position_manager.take_profit_order_id is None
