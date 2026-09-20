"""C1: TP 订单 R/R 下限保护（dream 2026-09-09-okx-loss-optimization）。

覆盖 task-card AC-1.1..AC-1.5。
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import pytest

from alpha_trading_bot.config.models import (
    Config,
    ConfigurationError,
    ExchangeConfig,
    StopLossConfig,
    TradingConfig,
)
from alpha_trading_bot.core.adaptive_bot import AdaptiveTradingBot
from alpha_trading_bot.core.position_manager import PositionManager
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


def _bot(rr: float, **sl_kwargs: Any) -> AdaptiveTradingBot:
    return AdaptiveTradingBot(
        _live_config(StopLossConfig(take_profit_min_rr_ratio=rr, **sl_kwargs))
    )


# ---- 集成测试依赖 ----


class _Params:
    def get_parameters(self) -> Dict[str, float]:
        return {"fusion_threshold": 0.5}


class _RiskStop:
    def __init__(self, stop_loss_price: float) -> None:
        self._stop = stop_loss_price

    def calculate_trade_params(self, *args: Any, **kwargs: Any) -> Dict[str, float]:
        return {
            "suggested_position": 0.01,
            "stop_loss_price": self._stop,
            "stop_loss_percent": 0.005,
        }

    def can_open_position(self, *args: Any, **kwargs: Any) -> Tuple[bool, str]:
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


class _TpExchange:
    symbol = "BTC/USDT:USDT"

    def __init__(self, fill_price: float = 100.0) -> None:
        self.take_profit_calls: List[Dict[str, Any]] = []
        self._fill = fill_price

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
            average_price=self._fill,
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


# ---- C1 helper 单测 ----


def test_c1_u01_long_tp_below_sl_expands() -> None:
    """AC-1.1: long TP 距离 < SL 距离时外扩到 entry + SL 距离。"""
    assert (
        _bot(1.0)._enforce_take_profit_rr_floor(100.0, 100.5, "long", 99.0)
        == pytest.approx(101.0)
    )


def test_c1_u02_long_tp_ge_sl_unchanged() -> None:
    """AC-1.2: TP 距离 >= SL 距离时不变。"""
    assert (
        _bot(1.0)._enforce_take_profit_rr_floor(100.0, 101.5, "long", 99.0)
        == pytest.approx(101.5)
    )


def test_c1_u03_boundary_equal_unchanged() -> None:
    """AC-1.2 边界: TP 距离 == SL 距离时不变（取等号）。"""
    assert (
        _bot(1.0)._enforce_take_profit_rr_floor(100.0, 101.0, "long", 99.0)
        == pytest.approx(101.0)
    )


def test_c1_u04_ratio_1_5_expands() -> None:
    """AC-1.1: ratio=1.5 时外扩到 SL 距离 × 1.5。"""
    assert (
        _bot(1.5)._enforce_take_profit_rr_floor(100.0, 100.4, "long", 99.5)
        == pytest.approx(100.75)
    )


def test_c1_u05_short_expands() -> None:
    """AC-1.1: short 方向对称外扩。"""
    assert (
        _bot(1.0)._enforce_take_profit_rr_floor(100.0, 99.5, "short", 101.0)
        == pytest.approx(99.0)
    )


def test_c1_u06_short_unchanged() -> None:
    """AC-1.2: short 距离满足时不变。"""
    assert (
        _bot(1.0)._enforce_take_profit_rr_floor(100.0, 98.0, "short", 101.0)
        == pytest.approx(98.0)
    )


def test_c1_u07_ratio_zero_unchanged() -> None:
    """AC-1.1(开关): ratio=0 关闭保护，保持原价。"""
    assert (
        _bot(0.0)._enforce_take_profit_rr_floor(100.0, 100.5, "long", 99.0)
        == pytest.approx(100.5)
    )


def test_c1_u08_ratio_negative_unchanged() -> None:
    """开关防御: 负值同走 ratio<=0 分支。"""
    assert (
        _bot(-0.5)._enforce_take_profit_rr_floor(100.0, 100.5, "long", 99.0)
        == pytest.approx(100.5)
    )


def test_c1_u09_stop_none_unchanged() -> None:
    """AC-1.5: stop=None 时不变（不 panic）。"""
    assert (
        _bot(1.0)._enforce_take_profit_rr_floor(100.0, 100.5, "long", None)
        == pytest.approx(100.5)
    )


def test_c1_u10_stop_nonpositive_unchanged() -> None:
    """AC-1.5: stop<=0 时不变。"""
    assert (
        _bot(1.0)._enforce_take_profit_rr_floor(100.0, 100.5, "long", 0.0)
        == pytest.approx(100.5)
    )


def test_c1_u11_sl_dist_nonpositive_unchanged() -> None:
    """AC-1.5: long 的 stop 在 entry 上方(sl_dist<=0)时不变。"""
    assert (
        _bot(1.0)._enforce_take_profit_rr_floor(100.0, 102.0, "long", 101.0)
        == pytest.approx(102.0)
    )


def test_c1_u12_tp_dist_nonpositive_unchanged() -> None:
    """AC-1.5: long 的 TP 在 entry 下方(tp_dist<=0)时不变。"""
    assert (
        _bot(1.0)._enforce_take_profit_rr_floor(100.0, 99.5, "long", 99.0)
        == pytest.approx(99.5)
    )


def test_c1_u13_short_sl_dist_zero_unchanged() -> None:
    """AC-1.5 边界: short sl_dist=0 时不变。"""
    assert (
        _bot(1.0)._enforce_take_profit_rr_floor(100.0, 99.0, "short", 100.0)
        == pytest.approx(99.0)
    )


# ---- C1 配置 ----


def test_c1_c01_default_ratio() -> None:
    """AC-1.5: 字段默认值 1.0。"""
    assert StopLossConfig().take_profit_min_rr_ratio == 1.0


def test_c1_c02_validate_negative() -> None:
    """AC-1.5: 负数校验报错，且 from_env 级 validate_or_raise 抛异常。"""
    cfg = StopLossConfig(take_profit_min_rr_ratio=-0.1)
    errs = cfg.validate()
    assert any("止盈R/R下限" in e for e in errs)
    full = Config(
        exchange=ExchangeConfig(api_key="k", secret="s", password="p"),
        trading=TradingConfig(
            test_mode=False, real_trading_confirmed=True, runtime_environment="prod"
        ),
        stop_loss=cfg,
    )
    with pytest.raises(ConfigurationError):
        full.validate_or_raise()


def test_c1_c03_validate_zero_ok() -> None:
    """AC-1.5: 0（关闭）不报错。"""
    errs = StopLossConfig(take_profit_min_rr_ratio=0.0).validate()
    assert not any("R/R" in e for e in errs)


def _set_base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OKX_API_KEY", "t")
    monkeypatch.setenv("OKX_SECRET", "t")
    monkeypatch.setenv("OKX_PASSWORD", "t")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "t")


def test_c1_c04_from_env_reads_ratio(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-1.5: from_env 读取 TAKE_PROFIT_MIN_RR_RATIO。"""
    _set_base_env(monkeypatch)
    monkeypatch.setenv("TAKE_PROFIT_MIN_RR_RATIO", "1.5")
    assert Config.from_env().stop_loss.take_profit_min_rr_ratio == pytest.approx(1.5)


def test_c1_c05_from_env_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-1.5: env 缺省 → 1.0。"""
    _set_base_env(monkeypatch)
    monkeypatch.delenv("TAKE_PROFIT_MIN_RR_RATIO", raising=False)
    assert Config.from_env().stop_loss.take_profit_min_rr_ratio == pytest.approx(1.0)


def test_c1_c06_from_env_negative_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-1.5: env 负值 → from_env 抛 ConfigurationError。"""
    _set_base_env(monkeypatch)
    monkeypatch.setenv("TAKE_PROFIT_MIN_RR_RATIO", "-1")
    with pytest.raises(ConfigurationError):
        Config.from_env()


# ---- C1 集成 ----


@pytest.mark.asyncio
async def test_c1_i01_execute_trade_long_rr_floor_applies(tmp_path: Any) -> None:
    """AC-1.1: 开仓链路 stop=90 → TP 外扩到 110.0 (全仓止盈默认保持原目标 106.0)。"""
    config = _live_config(
        StopLossConfig(
            take_profit_percent=0.06,
            take_profit_min_notional=1.0,
            take_profit_min_rr_ratio=1.0,
        )
    )
    bot = AdaptiveTradingBot(config)
    _wire_execution_deps(bot, tmp_path, _RiskStop(90.0))
    exchange = _TpExchange(fill_price=100.0)
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
            "take_profit_price": pytest.approx(110.0),
        }
    ]


@pytest.mark.asyncio
async def test_c1_i02_execute_trade_short_rr_floor_applies(tmp_path: Any) -> None:
    """AC-1.1: short 开仓链路 stop=110 → TP 外扩到 90.0。"""
    config = _live_config(
        StopLossConfig(
            take_profit_percent=0.06,
            take_profit_min_notional=1.0,
            take_profit_min_rr_ratio=1.0,
        )
    )
    bot = AdaptiveTradingBot(config)
    _wire_execution_deps(bot, tmp_path, _RiskStop(110.0))
    exchange = _TpExchange(fill_price=100.0)
    bot._exchange = exchange

    await bot._execute_trade(
        action="sell",
        current_price=100.0,
        has_position=False,
        position_data={},
        market_data={"technical": {}},
        selected_strategy=None,
        cached_rule_result={"adjustments": {"position_multiplier": 1.0}},
    )

    assert exchange.take_profit_calls[0]["side"] == "buy"
    assert exchange.take_profit_calls[0]["take_profit_price"] == pytest.approx(90.0)


@pytest.mark.asyncio
async def test_c1_i03_kill_switch_ratio_zero_keeps_original(tmp_path: Any) -> None:
    """AC-1.1(开关): ratio=0 → 保持止盈原目标 106.0，不外扩。"""
    config = _live_config(
        StopLossConfig(
            take_profit_percent=0.06,
            take_profit_min_notional=1.0,
            take_profit_min_rr_ratio=0.0,
        )
    )
    bot = AdaptiveTradingBot(config)
    _wire_execution_deps(bot, tmp_path, _RiskStop(90.0))
    exchange = _TpExchange(fill_price=100.0)
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

    # 2026-09-20 loss-structure-fix / R1: 全仓止盈默认保持原目标 (fixed 6% = 106.0)
    assert exchange.take_profit_calls[0]["take_profit_price"] == pytest.approx(106.0)


@pytest.mark.asyncio
async def test_c1_i04_direct_stop_none_unchanged(tmp_path: Any) -> None:
    """AC-1.5: _maybe_create_take_profit_order 直调 stop=None → 不变(101.5)。"""
    config = _live_config(
        StopLossConfig(
            take_profit_percent=0.06,
            take_profit_min_notional=1.0,
            take_profit_min_rr_ratio=1.0,
        )
    )
    bot = AdaptiveTradingBot(config)
    bot.position_manager = PositionManager(config, data_dir=tmp_path)
    bot._exchange = _TpExchange(fill_price=100.0)

    await bot._maybe_create_take_profit_order(
        position_side="long",
        amount=0.01,
        entry_price=100.0,
        symbol="BTC/USDT:USDT",
        market_data={"technical": {"atr_percent": 0.01}},
    )

    # 2026-09-20 loss-structure-fix / R1: 自适应 TP (ATR 1%×1.5) = 101.5，
    # 全仓回退默认保持原目标 (旧值 100.75 是砍半结果)
    assert (
        bot._exchange.take_profit_calls[0]["take_profit_price"]
        == pytest.approx(101.5)
    )


@pytest.mark.asyncio
async def test_c1_i06_direct_stop_expands(tmp_path: Any) -> None:
    """AC-1.1: _maybe_create_take_profit_order 直调 stop=90 → 外扩到 110.0。

    显式关闭 P2 波动率 cap (take_profit_max_atr_multiplier=0.0)，
    隔离验证纯 C1 R/R 外扩逻辑；P2 cap 收紧路径见 test_tp_volatility_cap.py。
    """
    config = _live_config(
        StopLossConfig(
            take_profit_percent=0.06,
            take_profit_min_notional=1.0,
            take_profit_min_rr_ratio=1.0,
            take_profit_max_atr_multiplier=0.0,
        )
    )
    bot = AdaptiveTradingBot(config)
    bot.position_manager = PositionManager(config, data_dir=tmp_path)
    bot._exchange = _TpExchange(fill_price=100.0)

    await bot._maybe_create_take_profit_order(
        position_side="long",
        amount=0.01,
        entry_price=100.0,
        symbol="BTC/USDT:USDT",
        market_data={"technical": {"atr_percent": 0.01}},
        stop_loss_price=90.0,
    )

    assert (
        bot._exchange.take_profit_calls[0]["take_profit_price"]
        == pytest.approx(110.0)
    )
