"""全场景波动矩阵驱动层

用真实组件 (MarketRegimeDetector / AdaptiveRulesEngine / StrategyLibrary /
StrategyExecutionManager / AISignalIntegrator / DecisionEngine /
RiskControlManager / TakeProfitCalculator / PerformanceTracker) 驱动每个
市场波动场景, 仅 AI 提供商响应按场景注入 (模拟 AI 输出)。

用于:
- tests/unit/test_volatility_scenario_matrix.py (断言各场景业务处理)
- scripts/run_volatility_scenario_report.py (输出波动→处理 报告)
"""

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from alpha_trading_bot.ai.adaptive.market_regime import MarketRegimeDetector
from alpha_trading_bot.ai.adaptive.performance_tracker import (
    PerformanceMetrics,
    PerformanceTracker,
)
from alpha_trading_bot.ai.adaptive.risk_manager import (
    RiskConfig,
    RiskControlManager,
)
from alpha_trading_bot.ai.adaptive.rules_engine import AdaptiveRulesEngine
from alpha_trading_bot.ai.adaptive.strategy_library import StrategyLibrary
from alpha_trading_bot.ai.integrator import AISignalIntegrator
from alpha_trading_bot.config.thresholds import (
    MIN_TRADE_CONFIDENCE_FLOOR,
    RULE_FUSION_THRESHOLD_MAX,
)
from alpha_trading_bot.core.decision_engine import DecisionEngine
from alpha_trading_bot.core.managers.strategy_manager import StrategyExecutionManager
from alpha_trading_bot.core.take_profit_calculator import TakeProfitCalculator

logger = logging.getLogger(__name__)

PRICE = 77000.0


# ============================================================
# 场景定义
# ============================================================


@dataclass
class Scenario:
    """一个市场波动场景 (输入快照 + AI 响应 + 期望行为)"""

    name: str
    group: str
    description: str
    # --- 市场状态 ---
    price: float = PRICE
    atr_percent: float = 0.0014  # 15分钟 ATR (小数)
    rsi: float = 50.0
    trend_direction: str = "sideways"
    trend_strength: float = 0.05
    adx: float = 20.0
    bb_position: float = 0.5
    price_position: float = 0.5
    macd_hist: float = 0.0
    change_percent: float = 0.0  # 24h 涨跌 (小数)
    price_shape: str = "flat"  # flat/up/down/crash/v_bounce/chop
    shape_amp: float = 0.0015  # 形状每bar幅度 (小数)
    short_term_drop: float = 0.0  # 最近3根K线跌幅 (小数)
    # --- AI 响应 (提供商级注入) ---
    ai_signal: str = "hold"
    ai_confidence: float = 0.5
    provider: str = "qwen38"
    # --- 持仓状态 ---
    position: Optional[Dict[str, Any]] = None
    # --- 风险/绩效状态 ---
    consecutive_losses: int = 0
    daily_pnl_percent: float = 0.0
    # --- 期望 (供测试断言) ---
    expect: Dict[str, Any] = field(default_factory=dict)


def build_price_history(shape: str, amp: float, base: float = PRICE) -> List[float]:
    """按形状生成 60 根 15 分钟收盘价。"""
    n = 60
    bars: List[float] = []
    if shape == "flat":
        for i in range(n):
            bars.append(base * (1 + (0.0004 if i % 2 == 0 else -0.0004)))
    elif shape == "up":
        for i in range(n):
            bars.append(base * (1 + amp * i / n))
    elif shape == "down":
        for i in range(n):
            bars.append(base * (1 - amp * i / n))
    elif shape == "crash":
        for i in range(n):
            if i < n - 3:
                bars.append(base * (1 + (0.0004 if i % 2 == 0 else -0.0004)))
            else:
                bars.append(base * (1 - amp * (i - (n - 3) + 1)))
    elif shape == "v_bounce":
        for i in range(n):
            if i < n - 6:
                bars.append(base * (1 - amp * (i / (n - 6)) * 0.6))
            elif i < n - 3:
                bottom = base * (1 - amp * 0.6)
                bars.append(bottom * (1 - amp * (i - (n - 6) + 1) / 3))
            else:
                bottom = base * (1 - amp * 0.6 - amp)
                bars.append(bottom * (1 + amp * (i - (n - 3) + 1) / 3))
    elif shape == "chop":
        for i in range(n):
            bars.append(base * (1 + amp * (0.5 if i % 2 == 0 else -0.5)))
    else:
        raise ValueError(f"未知价格形状: {shape}")
    return bars


def build_market_data(s: Scenario) -> Dict[str, Any]:
    """由场景构造 market_data (与 exchange/market_data.py 输出结构一致)。"""
    history = build_price_history(s.price_shape, s.shape_amp, s.price)
    # 保证最后一根收盘 = 当前价
    if history:
        scale = s.price / history[-1]
        history = [p * scale for p in history]
    hourly = [s.change_percent / 24.0] * 24
    return {
        "price": s.price,
        "change_percent": s.change_percent,
        "short_term_drop_percent": s.short_term_drop,
        "price_history": history,
        "hourly_changes": hourly,
        "technical": {
            "rsi": s.rsi,
            "atr_percent": s.atr_percent,
            "trend_direction": s.trend_direction,
            "trend_strength": s.trend_strength,
            "adx": s.adx,
            "bb_position": s.bb_position,
            "price_position": s.price_position,
            "macd_hist": s.macd_hist,
        },
    }


# ============================================================
# 结果
# ============================================================


@dataclass
class ScenarioResult:
    scenario: Scenario
    # 1. 市场环境
    regime: str = ""
    regime_confidence: float = 0.0
    # 2. 规则引擎
    rules_triggered: List[str] = field(default_factory=list)
    rule_sl: Optional[float] = None
    rule_pos_mult: Optional[float] = None
    # 3. 策略库
    strategy_signals: Dict[str, Tuple[str, float]] = field(default_factory=dict)
    selected_strategy: str = ""
    selected_signal: str = ""
    selected_confidence: float = 0.0
    # 4. AI 集成
    ai_original: Tuple[str, float] = ("", 0.0)
    ai_final: Tuple[str, float] = ("", 0.0)
    ai_adjustments: List[str] = field(default_factory=list)
    # 5. 门禁与决策
    gate: float = 0.5
    decision_action: str = ""
    decision_reason: str = ""
    decision_confidence: float = 0.0
    decision_strategy: str = ""
    # 6. 执行参数 (开仓时)
    sl_price: Optional[float] = None
    sl_distance: Optional[float] = None
    tp_price: Optional[float] = None
    tp_distance: Optional[float] = None
    suggested_position: Optional[float] = None
    # 7. 风险
    risk_level: str = ""
    risk_gate_can_open: bool = True
    risk_gate_reason: str = ""
    circuit_breaker: bool = False
    # 8. 学习记录
    learn_provider: str = ""
    learn_strategy: str = ""

    def sl_pct(self) -> str:
        return f"{self.sl_distance * 100:.2f}%" if self.sl_distance is not None else "-"

    def tp_pct(self) -> str:
        return f"{self.tp_distance * 100:.2f}%" if self.tp_distance is not None else "-"


# ============================================================
# 流水线 (镜像 adaptive_bot._adaptive_trading_cycle 的真实顺序)
# ============================================================


class Harness:
    """组件级流水线驱动器 (全部真实组件, AI 响应按场景注入)。

    每个场景使用全新组件实例 (等价于一次独立的 bot 观测):
    SustainedDeclineDetector 等组件持有实例状态 (周期高水位),
    跨场景共享会污染各独立市场快照的语义。
    """

    def __init__(self, config: Any, tmp_dir: str = "data_json_scenario"):
        self.config = config
        self.tmp_dir = tmp_dir
        self.decision_engine = DecisionEngine(config)
        self.tp_calculator = TakeProfitCalculator(config)

    def _new_components(self) -> Dict[str, Any]:
        return {
            "regime_detector": MarketRegimeDetector(),
            "rules_engine": AdaptiveRulesEngine(),
            "strategy_library": StrategyLibrary(),
            "strategy_manager": StrategyExecutionManager(),
            "integrator": AISignalIntegrator(),
            "risk_manager": RiskControlManager(RiskConfig()),
        }

    def run(self, s: Scenario) -> ScenarioResult:
        md = build_market_data(s)
        comps = self._new_components()
        result = ScenarioResult(
            scenario=s,
            ai_original=(s.ai_signal.upper(), s.ai_confidence),
        )

        # 1. 市场环境检测 (真实)
        perf = PerformanceMetrics(consecutive_losses=s.consecutive_losses)
        regime = comps["regime_detector"].detect(md)
        result.regime = regime.regime.value
        result.regime_confidence = regime.confidence

        # 2. 规则引擎 (真实)
        rule_result = comps["rules_engine"].evaluate_all(regime, perf)
        adjustments = rule_result.get("adjustments", {})
        result.rules_triggered = rule_result.get("triggered_rules", [])
        result.rule_sl = adjustments.get("stop_loss_percent")
        result.rule_pos_mult = adjustments.get("position_multiplier")

        # 3. 策略库信号 (真实)
        signals = comps["strategy_library"].get_all_signals(md)
        result.strategy_signals = {
            sig.strategy_type.value: (sig.signal.upper(), sig.confidence)
            for sig in signals
        }

        # 4. 策略选择 (真实)
        selected = comps["strategy_manager"].analyze_and_select(md, s.position)
        result.selected_strategy = str(getattr(selected, "strategy_type", selected))
        result.selected_signal = str(getattr(selected, "signal", "")).upper()
        result.selected_confidence = float(getattr(selected, "confidence", 0.5))

        # 5. AI 信号集成 (真实 integrator, AI 提供商响应按场景注入)
        ai_result = comps["integrator"].process(
            market_data=md,
            original_signal=s.ai_signal,
            original_confidence=s.ai_confidence,
        )
        result.ai_final = (
            str(ai_result.final_signal).upper(),
            float(ai_result.final_confidence),
        )
        result.ai_adjustments = list(ai_result.adjustments_made)
        # 与 AIClient.get_signal 相同的 market_data 写入
        md["ai_final_confidence"] = ai_result.final_confidence
        md["final_confidence"] = ai_result.final_confidence
        md["is_high_risk"] = ai_result.is_high_risk

        # 6. 规则门禁 (与 adaptive_bot._apply_rule_threshold_to_market_data 一致)
        ft = adjustments.get("fusion_threshold")
        if isinstance(ft, (int, float)):
            result.gate = min(
                max(float(ft), MIN_TRADE_CONFIDENCE_FLOOR), RULE_FUSION_THRESHOLD_MAX
            )
            md["min_trade_confidence"] = result.gate
        else:
            result.gate = float(
                getattr(getattr(self.config, "ai", None), "fusion_threshold", 0.5)
            )

        # 7. 风险状态 (真实) + 熔断早退 (与 bot 一致: 熔断中直接跳过后续)
        position = s.position or {}
        risk_state = comps["risk_manager"].assess_risk(md, position)
        result.risk_level = risk_state.risk_level.value
        result.risk_gate_can_open, result.risk_gate_reason = comps[
            "risk_manager"
        ].can_open_position(md, position)
        if risk_state.circuit_breaker_active:
            result.circuit_breaker = True
            result.decision_action = "skip"
            result.decision_reason = f"熔断触发: {risk_state.circuit_breaker_reason}"
            return result

        # 注入持仓状态 (与 bot 一致: market_data["has_position"]/"position_side"])
        has_position = bool(position.get("amount", 0) > 0)
        md["has_position"] = has_position
        md["position_side"] = str(position.get("side", "")) if position else ""

        # 8. 决策引擎 (真实)
        decision = self.decision_engine.make_decision(result.ai_final[0], selected, md)
        action = decision.get("action", "")
        reason = decision.get("reason", "")
        # 执行层检查 (与 bot._execute_trade 一致: 已有持仓时跳过开仓)
        if action == "open" and has_position:
            action = "skip"
            reason = f"已有持仓, 跳过开仓 (原决策: {reason})"
        result.decision_action = action
        result.decision_reason = reason
        result.decision_confidence = float(decision.get("confidence", 0.0))
        result.decision_strategy = str(decision.get("strategy", ""))

        # 9. 执行参数 (开仓场景: 真实风控参数 + 真实止盈计算)
        if result.decision_action in ("open", "sell") and not has_position:
            side = "buy" if result.decision_action == "open" else "sell"
            risk_params = comps["risk_manager"].calculate_trade_params(
                {
                    "side": side,
                    "price": s.price,
                    "entry_price": s.price,
                },
                md,
                risk_score=0.5,
                rule_adjustments=adjustments,
            )
            sl_price = risk_params.get("stop_loss_price")
            if sl_price:
                result.sl_price = float(sl_price)
                result.sl_distance = abs(s.price - sl_price) / s.price
            position_side = "long" if side == "buy" else "short"
            tp_price = self.tp_calculator.calculate(s.price, position_side, md)
            if tp_price and tp_price > 0:
                result.tp_price = float(tp_price)
                if position_side == "long":
                    result.tp_distance = (tp_price - s.price) / s.price
                else:
                    result.tp_distance = (s.price - tp_price) / s.price
            result.suggested_position = risk_params.get("suggested_position")
            # 复现生产 TP 保护 (adaptive_bot._enforce_take_profit_rr_floor):
            # C1: TP 距离 < SL×min_rr 时外扩; P2: 外扩目标受 k×ATR cap 约束
            if result.tp_distance is not None and result.sl_distance is not None:
                ratio = self.config.stop_loss.take_profit_min_rr_ratio
                if ratio > 0:
                    floor = result.sl_distance * ratio
                    atr_cap = (
                        self.config.stop_loss.take_profit_max_atr_multiplier
                        * s.atr_percent
                    )
                    target = min(floor, atr_cap)
                    if target > result.tp_distance:
                        result.tp_distance = target
                        if position_side == "long":
                            result.tp_price = s.price * (1 + target)
                        else:
                            result.tp_price = s.price * (1 - target)

        # 10. 学习记录字段 (与 adaptive_bot 开仓记录一致)
        result.learn_provider = s.provider
        result.learn_strategy = result.decision_strategy

        return result


# ============================================================
# 场景矩阵 (全波动谱)
# ============================================================

SCENARIOS: List[Scenario] = [
    # ================= A. 波动率谱 (无持仓, 多头倾向语境, AI BUY 75%)
    # 语境固定: 趋势向上 0.35 + RSI 45 + 区间 30% (低位), 隔离出波动率维度
    # (TrendRule 同时触发, 验证高优先级 VolatilityRule 覆盖其 SL/门禁/仓位) =================
    Scenario(
        name="A1-极低波动",
        group="A-波动率谱",
        description="ATR 0.05% (极端低波动/死水市) → SL clamp 下限 0.3%",
        atr_percent=0.0005,
        rsi=45.0,
        trend_direction="up",
        trend_strength=0.35,
        price_position=0.30,
        price_shape="up",
        ai_signal="buy",
        ai_confidence=0.75,
        expect={"decision_action": "open", "rule_sl": 0.003},
    ),
    Scenario(
        name="A2-低波动(实盘场景)",
        group="A-波动率谱",
        description="ATR 0.14% (2026-09-13 实盘水平) → SL 3×ATR=0.42%",
        atr_percent=0.0014,
        rsi=45.0,
        trend_direction="up",
        trend_strength=0.35,
        price_position=0.30,
        price_shape="up",
        ai_signal="buy",
        ai_confidence=0.75,
        expect={"decision_action": "open", "rule_sl": 0.0042},
    ),
    Scenario(
        name="A3-低波动上沿",
        group="A-波动率谱",
        description="ATR 0.19% (低波动带上沿, 3×ATR=0.57% 触顶 clamp 0.5%)",
        atr_percent=0.0019,
        rsi=45.0,
        trend_direction="up",
        trend_strength=0.35,
        price_position=0.30,
        price_shape="up",
        ai_signal="buy",
        ai_confidence=0.75,
        expect={"decision_action": "open", "rule_sl": 0.005},
    ),
    Scenario(
        name="A4-中等波动",
        group="A-波动率谱",
        description="ATR 0.30% (中等波动带) → SL 2.33×ATR=0.70%",
        atr_percent=0.003,
        rsi=45.0,
        trend_direction="up",
        trend_strength=0.35,
        price_position=0.30,
        price_shape="up",
        ai_signal="buy",
        ai_confidence=0.75,
        expect={"decision_action": "open", "rule_sl": 0.007},
    ),
    Scenario(
        name="A5-高波动",
        group="A-波动率谱",
        description="ATR 0.50% (高波动带) → SL 2×ATR=1.0%, 仓位 0.6x",
        atr_percent=0.005,
        rsi=45.0,
        trend_direction="up",
        trend_strength=0.35,
        price_position=0.30,
        price_shape="up",
        ai_signal="buy",
        ai_confidence=0.75,
        expect={"decision_action": "open", "rule_sl": 0.01, "rule_pos_mult": 0.7},
    ),
    Scenario(
        name="A6-极高波动",
        group="A-波动率谱",
        description="ATR 0.7% (极高波动带) → 超 ATR 上限门禁, 禁止开仓",
        atr_percent=0.007,
        rsi=45.0,
        trend_direction="up",
        trend_strength=0.35,
        price_position=0.30,
        price_shape="up",
        ai_signal="buy",
        ai_confidence=0.75,
        expect={
            "decision_action": "skip",
            "reason_contains": "高波动",
            "rule_pos_mult": 0.5,
        },
    ),
    Scenario(
        name="A7-极端波动",
        group="A-波动率谱",
        description="ATR 1.2% (极端波动) → ATR 门禁禁止开仓, 仓位 0.5x",
        atr_percent=0.012,
        rsi=45.0,
        trend_direction="up",
        trend_strength=0.35,
        price_position=0.30,
        price_shape="up",
        ai_signal="buy",
        ai_confidence=0.85,
        expect={
            "decision_action": "skip",
            "reason_contains": "高波动",
            "rule_pos_mult": 0.5,
        },
    ),
    Scenario(
        name="A8-极端波动门禁",
        group="A-波动率谱",
        description="ATR 0.8% + 信号过门禁 → ATR 上限门禁禁止开仓",
        atr_percent=0.008,
        rsi=45.0,
        trend_direction="up",
        trend_strength=0.35,
        price_position=0.30,
        price_shape="up",
        ai_signal="buy",
        ai_confidence=0.85,
        expect={"decision_action": "skip", "reason_contains": "高波动"},
    ),
    # ================= B. 趋势场景 (ATR 0.15%) =================
    Scenario(
        name="B1-强上升趋势",
        group="B-趋势",
        description="趋势向上 0.7 + RSI 62 + AI BUY 72% → 顺势开多",
        atr_percent=0.0015,
        rsi=62.0,
        trend_direction="up",
        trend_strength=0.7,
        adx=35.0,
        price_shape="up",
        ai_signal="buy",
        ai_confidence=0.72,
        expect={"decision_action": "open"},
    ),
    Scenario(
        name="B2-强下降趋势",
        group="B-趋势",
        description="趋势向下 0.7 + RSI 42 (非超卖) + AI SHORT 75% → 顺势开空",
        atr_percent=0.0015,
        rsi=42.0,
        trend_direction="down",
        trend_strength=0.7,
        adx=35.0,
        price_shape="down",
        ai_signal="short",
        ai_confidence=0.75,
        expect={"decision_action": "sell"},
    ),
    Scenario(
        name="B3-下降趋势AI-HOLD",
        group="B-趋势",
        description="趋势向下 0.7 + AI HOLD 60% → 不反向开多",
        atr_percent=0.0015,
        rsi=38.0,
        trend_direction="down",
        trend_strength=0.7,
        price_shape="down",
        ai_signal="hold",
        ai_confidence=0.60,
        expect={"no_long_open": True},
    ),
    Scenario(
        name="B4-震荡超卖",
        group="B-趋势",
        description="横盘 + RSI 25 超卖 + AI HOLD + 策略确认 → 超卖买入路径",
        atr_percent=0.0015,
        rsi=25.0,
        trend_direction="sideways",
        trend_strength=0.05,
        price_shape="chop",
        ai_signal="hold",
        ai_confidence=0.55,
        expect={},
    ),
    Scenario(
        name="B5-震荡超买做空",
        group="B-趋势",
        description="横盘 + RSI 79 超买 + 空R/R≥3 → 均值回归做空门禁",
        atr_percent=0.0015,
        rsi=79.0,
        trend_direction="sideways",
        trend_strength=0.05,
        price_position=0.85,
        price_shape="up",
        ai_signal="hold",
        ai_confidence=0.55,
        expect={},
    ),
    Scenario(
        name="B6-极端超买衰竭",
        group="B-趋势",
        description="RSI 83.5 + 趋势<0.12 + RR≥7 → 极端牛市衰竭做空",
        atr_percent=0.0015,
        rsi=83.5,
        trend_direction="sideways",
        trend_strength=0.10,
        price_position=0.95,
        price_shape="up",
        ai_signal="hold",
        ai_confidence=0.50,
        expect={},
    ),
    Scenario(
        name="B7-全HOLD(事故回归)",
        group="B-趋势",
        description="2026-09-13 05:17 事故场景: AI HOLD 56% + 无强策略 → skip",
        atr_percent=0.0014,
        rsi=50.0,
        trend_direction="neutral",
        trend_strength=0.02,
        price_shape="flat",
        ai_signal="hold",
        ai_confidence=0.56,
        expect={"decision_action": "skip"},
    ),
    Scenario(
        name="B8-下降趋势RSI超卖",
        group="B-趋势",
        description="下降趋势 + RSI 25 超卖 + AI SHORT → RSI超卖拦截做空",
        atr_percent=0.0015,
        rsi=25.0,
        trend_direction="down",
        trend_strength=0.6,
        price_shape="down",
        ai_signal="short",
        ai_confidence=0.80,
        expect={"no_short_open": True},
    ),
    # ================= C. 价格结构场景 (ATR 0.15%) =================
    Scenario(
        name="C1-阻力位附近买入",
        group="C-价格结构",
        description="价格位于区间 95% (近阻力) + BUY → 高位惩罚/拦截",
        atr_percent=0.0015,
        rsi=68.0,
        price_position=0.95,
        bb_position=0.95,
        price_shape="up",
        ai_signal="buy",
        ai_confidence=0.60,
        expect={},
    ),
    Scenario(
        name="C2-支撑位附近买入",
        group="C-价格结构",
        description="价格位于区间 8% (近支撑) + RSI 32 + BUY → 低位增强",
        atr_percent=0.0015,
        rsi=32.0,
        price_position=0.08,
        bb_position=0.05,
        price_shape="down",
        ai_signal="buy",
        ai_confidence=0.65,
        expect={},
    ),
    Scenario(
        name="C3-突破上行",
        group="C-价格结构",
        description="价格突破区间上沿 + 趋势向上 + BUY 75%",
        atr_percent=0.002,
        rsi=58.0,
        trend_direction="up",
        trend_strength=0.5,
        price_position=1.0,
        price_shape="up",
        ai_signal="buy",
        ai_confidence=0.75,
        expect={"decision_action": "open"},
    ),
    Scenario(
        name="C4-跌破支撑",
        group="C-价格结构",
        description="价格跌破区间下沿 + 趋势向下 + SHORT 70% → 开空",
        atr_percent=0.002,
        rsi=42.0,
        trend_direction="down",
        trend_strength=0.5,
        price_position=0.40,
        price_shape="down",
        ai_signal="short",
        ai_confidence=0.70,
        expect={"decision_action": "sell"},
    ),
    Scenario(
        name="C5-下跌结构买入",
        group="C-价格结构",
        description="bearish 结构 + BUY → 禁止做多",
        atr_percent=0.0015,
        rsi=50.0,
        trend_direction="down",
        trend_strength=0.4,
        price_shape="down",
        ai_signal="buy",
        ai_confidence=0.80,
        expect={"no_long_open": True},
    ),
    Scenario(
        name="C6-BTC高位风险",
        group="C-价格结构",
        description="price_position 0.98 (极高位) + BUY 52% → 高位风险拦截",
        atr_percent=0.0015,
        rsi=72.0,
        price_position=0.98,
        bb_position=0.99,
        price_shape="up",
        ai_signal="buy",
        ai_confidence=0.52,
        expect={"no_long_open": True},
    ),
    # ================= D. 崩盘/事件场景 =================
    Scenario(
        name="D1-闪崩",
        group="D-崩盘事件",
        description="15分钟 -3% 闪崩 + BUY → 持续下跌阻断买入",
        atr_percent=0.006,
        rsi=22.0,
        trend_direction="down",
        trend_strength=0.8,
        price_shape="crash",
        shape_amp=0.01,
        short_term_drop=-0.03,
        change_percent=-0.03,
        ai_signal="buy",
        ai_confidence=0.65,
        expect={"no_long_open": True},
    ),
    Scenario(
        name="D2-V型反弹",
        group="D-崩盘事件",
        description="暴跌后 V 型反弹 + crash_bounce 策略 + BUY → 反弹买入路径",
        atr_percent=0.004,
        rsi=48.0,
        trend_direction="up",
        trend_strength=0.3,
        price_shape="v_bounce",
        shape_amp=0.008,
        short_term_drop=-0.02,
        change_percent=-0.04,
        ai_signal="buy",
        ai_confidence=0.62,
        expect={},
    ),
    Scenario(
        name="D3-持续阴跌",
        group="D-崩盘事件",
        description="24h -1.8% 持续阴跌 + BUY → 下跌检测惩罚/阻断",
        atr_percent=0.0018,
        rsi=30.0,
        trend_direction="down",
        trend_strength=0.4,
        price_shape="down",
        shape_amp=0.018,
        short_term_drop=-0.008,
        change_percent=-0.018,
        ai_signal="buy",
        ai_confidence=0.60,
        expect={"no_long_open": True},
    ),
    Scenario(
        name="D4-严重下跌",
        group="D-崩盘事件",
        description="24h -5% 严重下跌 + BUY → 完全阻断买入",
        atr_percent=0.008,
        rsi=18.0,
        trend_direction="down",
        trend_strength=0.9,
        price_shape="down",
        shape_amp=0.05,
        short_term_drop=-0.04,
        change_percent=-0.05,
        ai_signal="buy",
        ai_confidence=0.70,
        expect={"no_long_open": True},
    ),
    # ================= E. 持仓状态场景 (ATR 0.15%) =================
    Scenario(
        name="E1-多头浮盈",
        group="E-持仓状态",
        description="持有 long (入场 76400, 现价 77000 +0.79%) → 追踪止损上移",
        atr_percent=0.0015,
        rsi=55.0,
        ai_signal="hold",
        ai_confidence=0.5,
        position={
            "amount": 0.01,
            "side": "long",
            "entry_price": 76400.0,
            "unrealized_pnl": 6.0,
        },
        expect={"no_new_open": True},
    ),
    Scenario(
        name="E2-多头浮亏未触发",
        group="E-持仓状态",
        description="持有 long (入场 77400, 现价 77000 -0.52%, 止损 76900 未触发) → 持有",
        atr_percent=0.0015,
        rsi=45.0,
        ai_signal="hold",
        ai_confidence=0.5,
        position={
            "amount": 0.01,
            "side": "long",
            "entry_price": 77400.0,
            "unrealized_pnl": -5.2,
        },
        expect={"no_new_open": True},
    ),
    Scenario(
        name="E3-多头共振卖出",
        group="E-持仓状态",
        description="持有 long + AI SELL 78% + 策略 SELL → 平仓",
        atr_percent=0.0015,
        rsi=70.0,
        trend_direction="down",
        trend_strength=0.3,
        price_shape="down",
        ai_signal="sell",
        ai_confidence=0.78,
        position={
            "amount": 0.01,
            "side": "long",
            "entry_price": 76400.0,
            "unrealized_pnl": 6.0,
        },
        expect={"decision_action": "close"},
    ),
    Scenario(
        name="E4-多头中再BUY",
        group="E-持仓状态",
        description="持有 long + AI BUY → 已有持仓, 跳过开仓",
        atr_percent=0.0015,
        rsi=58.0,
        trend_direction="up",
        trend_strength=0.5,
        price_shape="up",
        ai_signal="buy",
        ai_confidence=0.80,
        position={
            "amount": 0.01,
            "side": "long",
            "entry_price": 76400.0,
            "unrealized_pnl": 6.0,
        },
        expect={"no_new_open": True, "no_second_open_order": True},
    ),
    Scenario(
        name="E5-空头浮盈",
        group="E-持仓状态",
        description="持有 short (入场 77600, 现价 77000 盈利) → 持有+追踪",
        atr_percent=0.0015,
        rsi=40.0,
        trend_direction="down",
        trend_strength=0.4,
        price_shape="down",
        ai_signal="hold",
        ai_confidence=0.5,
        position={
            "amount": 0.01,
            "side": "short",
            "entry_price": 77600.0,
            "unrealized_pnl": 6.0,
        },
        expect={"no_new_open": True},
    ),
    Scenario(
        name="E6-空单平仓状态",
        group="E-持仓状态",
        description="short_to_close (空单触发平仓中) → 进入平仓流程",
        atr_percent=0.0015,
        rsi=45.0,
        ai_signal="hold",
        ai_confidence=0.5,
        position={
            "amount": 0.01,
            "side": "short_to_close",
            "entry_price": 77600.0,
            "unrealized_pnl": -2.0,
        },
        expect={"no_new_open": True},
    ),
    # ================= F. 风控场景 (ATR 0.15%) =================
    Scenario(
        name="F1-连亏3次",
        group="F-风控",
        description="连续亏损 3 次 + BUY 70% → 仓位 0.5x + 门禁 0.60",
        atr_percent=0.0015,
        rsi=55.0,
        trend_direction="up",
        trend_strength=0.4,
        price_shape="up",
        ai_signal="buy",
        ai_confidence=0.70,
        consecutive_losses=3,
        expect={"rule_pos_mult": 0.5, "gate": 0.60},
    ),
    Scenario(
        name="F2-连亏5次",
        group="F-风控",
        description="连续亏损 5 次 + BUY 70% → 仓位 0.2x + 门禁 0.70",
        atr_percent=0.0015,
        rsi=55.0,
        trend_direction="up",
        trend_strength=0.4,
        price_shape="up",
        ai_signal="buy",
        ai_confidence=0.70,
        consecutive_losses=5,
        expect={"rule_pos_mult": 0.2, "gate": 0.70},
    ),
    Scenario(
        name="F3-当日亏损回撤",
        group="F-风控",
        description="当日回撤 4% (接近熔断 3% 上限) + BUY → 风险等级抬升",
        atr_percent=0.0015,
        rsi=55.0,
        trend_direction="up",
        trend_strength=0.4,
        price_shape="up",
        ai_signal="buy",
        ai_confidence=0.70,
        daily_pnl_percent=-0.04,
        position={"position_percent": 0.0, "daily_pnl_percent": -0.04},
        expect={},
    ),
    Scenario(
        name="F4-低置信拦截",
        group="F-风控",
        description="横盘无技术共振 + BUY 48% → 被降级/惩罚后低于门禁, 拦截",
        atr_percent=0.0015,
        rsi=50.0,
        trend_direction="neutral",
        trend_strength=0.02,
        price_shape="flat",
        ai_signal="buy",
        ai_confidence=0.48,
        expect={"decision_action": "skip", "no_long_open": True},
    ),
    # ================= G. 信号集成流水线 (ATR 0.15%) =================
    Scenario(
        name="G1-明确HOLD不翻转",
        group="G-集成流水线",
        description="AI HOLD 56% + 技术买入条件 → 保持 HOLD (翻转守卫)",
        atr_percent=0.0015,
        rsi=52.0,
        trend_direction="up",
        trend_strength=0.3,
        price_shape="up",
        ai_signal="hold",
        ai_confidence=0.56,
        expect={"ai_final_signal": "HOLD"},
    ),
    Scenario(
        name="G2-模糊HOLD可翻转",
        group="G-集成流水线",
        description="AI HOLD 40% (模糊) + 技术买入条件 → 允许翻转 BUY",
        atr_percent=0.0015,
        rsi=52.0,
        trend_direction="up",
        trend_strength=0.3,
        price_shape="up",
        ai_signal="hold",
        ai_confidence=0.40,
        expect={"ai_final_signal": "BUY"},
    ),
    Scenario(
        name="G3-SELL不翻BUY",
        group="G-集成流水线",
        description="AI SELL 85% + 技术买入条件 → 保持 SELL",
        atr_percent=0.0015,
        rsi=30.0,
        trend_direction="down",
        trend_strength=0.5,
        price_shape="down",
        ai_signal="sell",
        ai_confidence=0.85,
        expect={"ai_final_signal": "SELL"},
    ),
    Scenario(
        name="G4-BUY超100归一化",
        group="G-集成流水线",
        description="AI BUY 置信度 75 (百分制误传) → 归一化 0.75",
        atr_percent=0.0015,
        rsi=58.0,
        trend_direction="up",
        trend_strength=0.4,
        price_shape="up",
        ai_signal="buy",
        ai_confidence=75.0,
        expect={"ai_final_conf_max": 1.0},
    ),
    Scenario(
        name="G5-阴跌中BUY降权",
        group="G-集成流水线",
        description="BUY 65% + 轻度持续下跌 → 置信度惩罚",
        atr_percent=0.0018,
        rsi=38.0,
        trend_direction="down",
        trend_strength=0.45,
        price_shape="down",
        shape_amp=0.012,
        short_term_drop=-0.012,
        change_percent=-0.015,
        ai_signal="buy",
        ai_confidence=0.65,
        expect={"ai_final_conf_max": 0.65},
    ),
]


def get_scenarios() -> List[Scenario]:
    """返回完整场景矩阵 (深拷贝, 防止测试间污染)。"""
    return [copy.deepcopy(s) for s in SCENARIOS]
