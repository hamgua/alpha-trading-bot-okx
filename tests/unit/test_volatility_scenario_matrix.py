"""全场景波动矩阵测试

覆盖所有虚拟币交易波动情况: 波动率谱 (死水→极端)、趋势 (强升/强降/震荡)、
价格结构 (阻力/支撑/突破/破位)、崩盘事件 (闪崩/V型/阴跌/严重下跌)、
持仓状态 (浮盈/浮亏/平仓/再买入)、风控 (连亏/回撤/低置信)、
信号集成流水线 (翻转守卫/归一化/下跌惩罚)。

全部通过真实组件流水线 (volatility_scenario_harness) 驱动,
仅 AI 提供商响应按场景注入。
"""

import pytest

from alpha_trading_bot.config.models import Config

from .volatility_scenario_harness import (
    Harness,
    Scenario,
    get_scenarios,
)

SCENARIOS = get_scenarios()
SCENARIO_IDS = [s.name for s in SCENARIOS]


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    cfg = Config()
    return Harness(cfg, tmp_dir=str(tmp_path_factory.mktemp("scenario")))


def _check_invariants(result) -> None:
    """所有场景必须满足的全局业务不变量。"""
    # 1. 置信度门禁永远不低于抛硬币下限
    assert result.gate >= 0.50, f"{result.scenario.name}: 门禁 {result.gate} < 0.50"

    # 2. 开仓时止损距离必须在安全范围 (0.3% ~ 1.5%)
    if result.decision_action in ("open", "sell") and result.sl_distance is not None:
        assert (
            0.0025 <= result.sl_distance <= 0.016
        ), f"{result.scenario.name}: 止损距离 {result.sl_distance:.4f} 超出安全范围"

    # 3. 开仓时止盈距离不得低于 R/R 下限 (受 4×ATR cap 约束, 容差 5%)
    # 复现 _enforce_take_profit_rr_floor: final_tp ≥ min(SL×min_rr, k×ATR)
    if (
        result.sl_distance is not None
        and result.tp_distance is not None
        and result.scenario.position is None
        and result.decision_action in ("open", "sell")
    ):
        floor = min(result.sl_distance * 1.0, 4.0 * result.scenario.atr_percent)
        assert result.tp_distance >= floor * 0.95, (
            f"{result.scenario.name}: 止盈 {result.tp_distance:.4f} < "
            f"R/R下限 {floor:.4f} (C1 保护未生效)"
        )

    # 4. AI 最终置信度必须在 [0, 1]
    assert (
        0.0 <= result.ai_final[1] <= 1.0
    ), f"{result.scenario.name}: AI 置信度越界 {result.ai_final[1]}"


def _check_expectations(result) -> None:
    """场景级期望断言。"""
    exp = result.scenario.expect
    name = result.scenario.name

    if "decision_action" in exp:
        assert result.decision_action == exp["decision_action"], (
            f"{name}: 期望 action={exp['decision_action']}, "
            f"实际={result.decision_action} (reason={result.decision_reason})"
        )

    if "reason_contains" in exp:
        assert exp["reason_contains"] in result.decision_reason, (
            f"{name}: 期望 reason 含 '{exp['reason_contains']}', "
            f"实际='{result.decision_reason}'"
        )

    if "rule_sl" in exp and result.rule_sl is not None:
        assert (
            abs(result.rule_sl - exp["rule_sl"]) < 1e-6
        ), f"{name}: 期望规则 SL={exp['rule_sl']}, 实际={result.rule_sl}"

    if "rule_sl_max" in exp and result.rule_sl is not None:
        assert (
            result.rule_sl <= exp["rule_sl_max"] + 1e-9
        ), f"{name}: 规则 SL={result.rule_sl} 超过上限 {exp['rule_sl_max']}"

    if "rule_pos_mult" in exp and result.rule_pos_mult is not None:
        assert (
            abs(result.rule_pos_mult - exp["rule_pos_mult"]) < 1e-9
        ), f"{name}: 期望仓位乘数={exp['rule_pos_mult']}, 实际={result.rule_pos_mult}"

    if "gate" in exp:
        assert (
            abs(result.gate - exp["gate"]) < 1e-9
        ), f"{name}: 期望门禁={exp['gate']}, 实际={result.gate}"

    if "ai_final_signal" in exp:
        assert (
            result.ai_final[0] == exp["ai_final_signal"]
        ), f"{name}: 期望 AI 终态={exp['ai_final_signal']}, 实际={result.ai_final[0]}"

    if "ai_final_conf_max" in exp:
        assert (
            result.ai_final[1] <= exp["ai_final_conf_max"] + 1e-9
        ), f"{name}: AI 终态置信度 {result.ai_final[1]} 超过上限 {exp['ai_final_conf_max']}"

    # 开仓方向约束
    has_position = result.scenario.position is not None
    if exp.get("no_long_open"):
        assert not (
            result.decision_action == "open"
        ), f"{name}: 禁止开多, 但实际 open (reason={result.decision_reason})"
    if exp.get("no_short_open"):
        assert not (
            result.decision_action == "sell" and not has_position
        ), f"{name}: 禁止开空, 但实际 sell"
    if exp.get("no_new_open"):
        assert (
            not has_position or result.decision_action != "open"
        ), f"{name}: 有持仓时不应再开仓"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=SCENARIO_IDS)
def test_scenario_business_handling(scenario: Scenario, harness: Harness):
    """每个波动场景: 全局不变量 + 场景级期望。"""
    result = harness.run(scenario)
    _check_invariants(result)
    _check_expectations(result)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=SCENARIO_IDS)
def test_scenario_learning_record(scenario: Scenario, harness: Harness):
    """开仓场景: 学习记录必须带真实 provider 与策略名 (R4 修复回归)。"""
    if scenario.position is not None:
        pytest.skip("持仓场景不新开仓")
    result = harness.run(scenario)
    if result.decision_action not in ("open", "sell"):
        pytest.skip("未开仓")
    assert result.learn_provider in (
        "qwen38",
        "fusion",
        "deepseek",
    ), f"{scenario.name}: 学习 provider 无效: {result.learn_provider}"
    assert (
        result.learn_provider != "unknown"
    ), f"{scenario.name}: 学习 provider 不能是 unknown (R4 回归)"


def test_scenarios_cover_volatility_spectrum():
    """矩阵完整性: 波动率谱必须覆盖 0.05% ~ 1.2% ATR 全谱。"""
    atrs = sorted(s.atr_percent for s in SCENARIOS)
    assert atrs[0] <= 0.0005, "缺少极低波动场景 (≤0.05%)"
    assert atrs[-1] >= 0.008, "缺少极端波动场景 (≥0.8%)"
    # 覆盖低/中/高/极高四个波动带
    assert any(s.atr_percent < 0.002 for s in SCENARIOS), "缺少低波动带 (<0.20%)"
    assert any(0.002 <= s.atr_percent <= 0.0035 for s in SCENARIOS), "缺少中等波动带"
    assert any(0.0035 < s.atr_percent <= 0.006 for s in SCENARIOS), "缺少高波动带"
    assert any(s.atr_percent > 0.006 for s in SCENARIOS), "缺少极高波动带"


def test_scenarios_cover_market_events():
    """矩阵完整性: 必须覆盖 闪崩/V型/阴跌/严重下跌 四类事件。"""
    shapes = {s.price_shape for s in SCENARIOS}
    for required in ("crash", "v_bounce", "down", "up", "flat", "chop"):
        assert required in shapes, f"缺少价格形状场景: {required}"


def test_position_scenarios_cover_sides():
    """矩阵完整性: 持仓状态必须覆盖 多头/空头/平仓中。"""
    sides = {(s.position or {}).get("side") for s in SCENARIOS if s.position}
    assert {"long", "short", "short_to_close"} <= sides, f"持仓方向覆盖不全: {sides}"
