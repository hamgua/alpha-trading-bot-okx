"""P2: 波动率自适应 TP 外扩上限（dream 2026-09-14-okx-loss-round2）。

根因（日志证据 logs/alpha-trading-bot-okx.log.2026-09-10..13）:
低波动横盘市 (atr_percent≈0.0013) 中 C1 R/R 下限把止盈从可达的 0.25~0.53×SL
强制外扩到 1.0×SL（≈6×ATR），4/7 笔最终精确打在 -0.80% 止损上；
09-11 07:46 一笔原始止盈目标已到达（77059.48 → 77070.55 离场），
但因 TP 被外扩到 77346.07 未挂单，利润未兑现。

修复: 外扩目标 = min(SL距离×R/R下限, k×ATR, 结构阻力/支撑位距离)，
低波动市保留可达止盈，高波动市仍保 R/R 下限。

覆盖:
- U: _enforce_take_profit_rr_floor 带 market_data 的 cap 计算（long/short/边界/开关）
- C: StopLossConfig.take_profit_max_atr_multiplier 默认值/校验/from_env
- I: _execute_trade 开仓链路集成（cap 生效 / 无 ATR 数据向后兼容）
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


def _bot(rr: float = 1.0, max_atr: float = 4.0, **sl_kwargs: Any) -> AdaptiveTradingBot:
    return AdaptiveTradingBot(
        _live_config(
            StopLossConfig(
                take_profit_min_rr_ratio=rr,
                take_profit_max_atr_multiplier=max_atr,
                **sl_kwargs,
            )
        )
    )


# ---- 集成测试依赖（与 test_tp_rr_floor 相同的 stub） ----


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


# ---- P2 helper 单测 ----


def test_p2_u01_low_vol_long_tp_capped_by_atr() -> None:
    """低波动: atr=0.13%, k=4 → cap=0.52 < sl_dist×1.0=1.0，TP=100.52。"""
    market_data = {"technical": {"atr_percent": 0.0013}}
    result = _bot(1.0, 4.0)._enforce_take_profit_rr_floor(
        100.0, 100.5, "long", 99.0, market_data
    )
    assert result == pytest.approx(100.52)


def test_p2_u02_high_vol_keeps_rr_floor() -> None:
    """高波动: atr=5%, k=4 → cap=2.0 > 1.0，仍按 R/R 下限外扩到 101.0。"""
    market_data = {"technical": {"atr_percent": 0.05}}
    result = _bot(1.0, 4.0)._enforce_take_profit_rr_floor(
        100.0, 100.5, "long", 99.0, market_data
    )
    assert result == pytest.approx(101.0)


def test_p2_u03_no_market_data_backward_compatible() -> None:
    """无 market_data: 行为与 C1 完全一致（向后兼容）。"""
    result = _bot(1.0, 4.0)._enforce_take_profit_rr_floor(
        100.0, 100.5, "long", 99.0, None
    )
    assert result == pytest.approx(101.0)


def test_p2_u04_zero_atr_backward_compatible() -> None:
    """atr_percent=0（无 ATR 数据）: 不做 cap，保持 C1 行为。"""
    market_data = {"technical": {"atr_percent": 0.0}}
    result = _bot(1.0, 4.0)._enforce_take_profit_rr_floor(
        100.0, 100.5, "long", 99.0, market_data
    )
    assert result == pytest.approx(101.0)


def test_p2_u05_cap_tighter_than_original_tp_no_expand() -> None:
    """cap(0.52) 比原 TP 距离(0.8) 还近: 不外扩，保留可达原 TP。"""
    market_data = {"technical": {"atr_percent": 0.0013}}
    result = _bot(1.0, 4.0)._enforce_take_profit_rr_floor(
        100.0, 100.8, "long", 99.0, market_data
    )
    assert result == pytest.approx(100.8)


def test_p2_u06_resistance_caps_long_tp() -> None:
    """阻力位 cap 收紧外扩: tp_dist=0.2, ATR cap=0.6,
    resistance=100.4(buffer 0.001 → cap 0.3996) 比 ATR cap 更紧且 < sl_dist×1.0。"""
    market_data = {
        "technical": {"atr_percent": 0.0015},
        "nearest_resistance": 100.4,
    }
    result = _bot(1.0, 4.0)._enforce_take_profit_rr_floor(
        100.0, 100.2, "long", 99.0, market_data
    )
    assert result == pytest.approx(100.0 + (100.4 * (1 - 0.001) - 100.0))


def test_p2_u07_resistance_below_entry_ignored() -> None:
    """阻力位 <= entry（无效）时忽略阻力 cap，仍按 ATR cap。"""
    market_data = {
        "technical": {"atr_percent": 0.0013},
        "nearest_resistance": 99.9,
    }
    result = _bot(1.0, 4.0)._enforce_take_profit_rr_floor(
        100.0, 100.5, "long", 99.0, market_data
    )
    assert result == pytest.approx(100.52)


def test_p2_u08_short_capped_by_support() -> None:
    """short 对称: tp_dist=0.3, ATR cap=0.52, support=99.5 → structural cap=0.4005 收紧外扩。"""
    market_data = {
        "technical": {"atr_percent": 0.0013},
        "nearest_support": 99.5,
    }
    result = _bot(1.0, 4.0)._enforce_take_profit_rr_floor(
        100.0, 99.7, "short", 101.0, market_data
    )
    # TP 目标 = support × (1 + buffer) = 99.5995, 距离 = 100 - 99.5995 = 0.4005
    # short new_price = entry - target_dist = 100 - 0.4005 = 99.5995 = support×(1+buffer)
    assert result == pytest.approx(99.5 * 1.001)


def test_p2_u09_kill_switch_ratio_zero() -> None:
    """ratio=0 关闭 R/R 保护时 cap 也不生效，保持原价。"""
    market_data = {"technical": {"atr_percent": 0.0013}}
    result = _bot(0.0, 4.0)._enforce_take_profit_rr_floor(
        100.0, 100.5, "long", 99.0, market_data
    )
    assert result == pytest.approx(100.5)


def test_p2_u10_kill_switch_max_atr_zero() -> None:
    """k=0 关闭波动率 cap（恢复 C1 行为）。"""
    market_data = {"technical": {"atr_percent": 0.0013}}
    result = _bot(1.0, 0.0)._enforce_take_profit_rr_floor(
        100.0, 100.5, "long", 99.0, market_data
    )
    assert result == pytest.approx(101.0)


def test_p2_u11_stop_none_unchanged() -> None:
    """stop=None 时不变（不 panic）。"""
    market_data = {"technical": {"atr_percent": 0.0013}}
    result = _bot(1.0, 4.0)._enforce_take_profit_rr_floor(
        100.0, 100.5, "long", None, market_data
    )
    assert result == pytest.approx(100.5)


# ---- P2 配置 ----


def test_p2_c01_default_max_atr_multiplier() -> None:
    """默认 take_profit_max_atr_multiplier=4.0。"""
    assert StopLossConfig().take_profit_max_atr_multiplier == pytest.approx(4.0)


def test_p2_c02_validate_negative() -> None:
    """负值 → validate 报错。"""
    errs = StopLossConfig(take_profit_max_atr_multiplier=-1.0).validate()
    assert any("take_profit_max_atr_multiplier" in e for e in errs)


def test_p2_c03_validate_zero_ok() -> None:
    """0（关闭 cap）不报错。"""
    errs = StopLossConfig(take_profit_max_atr_multiplier=0.0).validate()
    assert not any("take_profit_max_atr_multiplier" in e for e in errs)


def _set_base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OKX_API_KEY", "t")
    monkeypatch.setenv("OKX_SECRET", "t")
    monkeypatch.setenv("OKX_PASSWORD", "t")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "t")


def test_p2_c04_from_env_reads_multiplier(monkeypatch: pytest.MonkeyPatch) -> None:
    """from_env 读取 TAKE_PROFIT_MAX_ATR_MULTIPLIER。"""
    _set_base_env(monkeypatch)
    monkeypatch.setenv("TAKE_PROFIT_MAX_ATR_MULTIPLIER", "3.0")
    assert Config.from_env().stop_loss.take_profit_max_atr_multiplier == pytest.approx(
        3.0
    )


def test_p2_c05_from_env_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """env 缺省 → 4.0。"""
    _set_base_env(monkeypatch)
    monkeypatch.delenv("TAKE_PROFIT_MAX_ATR_MULTIPLIER", raising=False)
    assert Config.from_env().stop_loss.take_profit_max_atr_multiplier == pytest.approx(
        4.0
    )


def test_p2_c06_from_env_negative_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """env 负值 → from_env 抛 ConfigurationError。"""
    _set_base_env(monkeypatch)
    monkeypatch.setenv("TAKE_PROFIT_MAX_ATR_MULTIPLIER", "-1")
    with pytest.raises(ConfigurationError):
        Config.from_env()


# ---- P2 集成 ----


@pytest.mark.asyncio
async def test_p2_i01_execute_trade_low_vol_tp_capped(tmp_path: Any) -> None:
    """开仓链路: entry=100, stop=90, atr=1% → TP 由 110.0 收回到 104.0。"""
    config = _live_config(
        StopLossConfig(
            take_profit_percent=0.06,
            take_profit_min_notional=1.0,
            take_profit_min_rr_ratio=1.0,
            take_profit_max_atr_multiplier=4.0,
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
        market_data={"technical": {"atr_percent": 0.01}},
        selected_strategy=None,
        cached_rule_result={"adjustments": {"position_multiplier": 1.0}},
    )

    assert exchange.take_profit_calls == [
        {
            "symbol": "BTC/USDT:USDT",
            "side": "sell",
            "amount": 0.01,
            "take_profit_price": pytest.approx(104.0),
        }
    ]


@pytest.mark.asyncio
async def test_p2_i02_execute_trade_no_atr_data_unchanged(tmp_path: Any) -> None:
    """开仓链路: 无 ATR 数据 → 与 C1 一致，TP=110.0（向后兼容）。"""
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

    assert exchange.take_profit_calls[0]["take_profit_price"] == pytest.approx(110.0)
