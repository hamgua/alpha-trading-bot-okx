# -*- coding: utf-8 -*-
"""市场结构方向 24h/4h 一致性门槛测试 (Task 5)。

修复目标: 11-24 13:43 阴跌中 (24h -5%、HTF sideways) 1h 结构仍给出
direction=long → 逆势抄底。新门槛:
- long 建议需 change_percent > -3.0 (24h 未深跌)
- short 建议需 change_percent < +3.0 (24h 未深涨)
- change_percent == 0 (未传/未知) → 24h 门槛不启用 (零回归; 4h 门槛为既有 P1-4)
"""

from alpha_trading_bot.ai.market_structure import MarketStructureAnalyzer


def _analyzer_with_structure(structure: str) -> MarketStructureAnalyzer:
    """固定 1h 摆动点使结构判定可控 (被测对象是方向门槛, 非结构识别)。

    bullish: HH+HL; bearish: LH+LL。摆动点列表为 oldest-first,
    _determine_structure 比较 [-1] 与 [-2]。HTF 路径 (window=1) 返回空 →
    htf="unknown", 隔离 24h 门槛与既有 P1-4 的 4h 冲突守卫。
    """
    analyzer = MarketStructureAnalyzer()

    def _fake_swing_points(price_history, window=None):
        if window is not None:  # HTF 路径 → 数据不足 → "unknown"
            return [], []
        if structure == "bullish":
            return [100.0, 110.0], [90.0, 92.0]  # HH + HL
        return [110.0, 100.0], [92.0, 90.0]  # LH + LL

    analyzer._find_swing_points = _fake_swing_points
    return analyzer


# 1h 价格序列 (recent-first); 摆动点被 mock, 此序列仅满足长度/HTF 数据要求
HIST = [100.0 + i for i in range(48)][::-1]  # 48 根, 100→148


def test_baseline_bullish_fixture_gives_long() -> None:
    """前置: bullish 结构 + 良好 R/R → 默认 (change_percent=0) 给出 long。"""
    analyzer = _analyzer_with_structure("bullish")
    res = analyzer.analyze(HIST, current_price=95.0)
    assert res.structure == "bullish"
    assert res.suggested_direction == "long"


def test_long_direction_blocked_when_24h_declining() -> None:
    analyzer = _analyzer_with_structure("bullish")
    res = analyzer.analyze(HIST, current_price=95.0, change_percent=-5.0)
    assert res.suggested_direction != "long"
    assert res.suggested_direction == "none"
    assert "一致性门槛" in res.htf_note


def test_long_direction_allowed_when_24h_flat_or_up() -> None:
    analyzer = _analyzer_with_structure("bullish")
    res = analyzer.analyze(HIST, current_price=95.0, change_percent=-1.0)
    assert res.suggested_direction == "long"
    assert "一致性门槛" not in res.htf_note


def test_short_direction_blocked_when_24h_rising() -> None:
    analyzer = _analyzer_with_structure("bearish")
    res = analyzer.analyze(HIST, current_price=93.5, change_percent=4.0)
    assert res.suggested_direction != "short"
    assert res.suggested_direction == "none"
    assert "一致性门槛" in res.htf_note


def test_short_direction_allowed_when_24h_falling() -> None:
    analyzer = _analyzer_with_structure("bearish")
    res = analyzer.analyze(HIST, current_price=93.5, change_percent=-1.0)
    assert res.suggested_direction == "short"


def test_gate_off_when_change_percent_zero() -> None:
    """change_percent=0 (未传/未知) → 24h 门槛不启用, 行为与既有 P1-4 一致。"""
    analyzer = _analyzer_with_structure("bullish")
    res = analyzer.analyze(HIST, current_price=95.0)  # 默认 change_percent=0.0
    assert res.suggested_direction == "long"
    assert "一致性门槛" not in res.htf_note
