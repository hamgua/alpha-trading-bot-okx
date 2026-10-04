"""回撤停机总闸测试（P1，spec: RISK_DRAWDOWN_HALT=0.30 + 手动恢复）"""

import pytest

from alpha_trading_bot.core.drawdown_guard import DrawdownGuard


def test_fresh_high_water_not_halted(tmp_path) -> None:
    g = DrawdownGuard(threshold=0.30, data_dir=tmp_path)
    s = g.check(1000.0)
    assert not s.halted and s.high_water == 1000.0
    assert s.drawdown == 0.0 and not s.just_tripped and not s.skipped


def test_trip_at_exact_threshold(tmp_path) -> None:
    g = DrawdownGuard(threshold=0.30, data_dir=tmp_path)
    g.check(1000.0)
    s = g.check(700.0)  # (1000-700)/1000 = 30% → 触发（≥ 语义）
    assert s.halted and s.just_tripped
    assert s.drawdown == pytest.approx(0.30)


def test_no_trip_below_threshold(tmp_path) -> None:
    g = DrawdownGuard(threshold=0.30, data_dir=tmp_path)
    g.check(1000.0)
    s = g.check(750.0)  # 25% → 不触发
    assert not s.halted and not s.just_tripped


def test_high_water_monotonic(tmp_path) -> None:
    g = DrawdownGuard(threshold=0.30, data_dir=tmp_path)
    g.check(1000.0)
    g.check(1100.0)  # 高水位上移
    s = g.check(700.0)  # (1100-700)/1100 ≈ 36.4%
    assert s.halted and s.high_water == 1100.0


def test_persistence_across_restart_keeps_halt(tmp_path) -> None:
    g1 = DrawdownGuard(threshold=0.30, data_dir=tmp_path)
    g1.check(1000.0)
    g1.check(700.0)  # trip
    g2 = DrawdownGuard(threshold=0.30, data_dir=tmp_path)  # 模拟重启
    s = g2.check(690.0)
    assert s.halted and not s.just_tripped and s.high_water == 1000.0


def test_manual_resume_clears_halt_keeps_high_water(tmp_path) -> None:
    g1 = DrawdownGuard(threshold=0.30, data_dir=tmp_path)
    g1.check(1000.0)
    g1.check(700.0)  # trip
    g2 = DrawdownGuard(threshold=0.30, resume=True, data_dir=tmp_path)
    s = g2.check(900.0)  # 权益已恢复到 10% 回撤（阈值内）
    assert not s.halted and not s.just_tripped
    assert s.high_water == 1000.0  # 高水位保留
    assert s.drawdown == 0.10


def test_resume_retrips_when_drawdown_persists(tmp_path) -> None:
    """手动恢复只清除停机闩，不覆盖实测风险：回撤仍 ≥ 阈值时立即再跳闸（断路器语义）。"""
    g1 = DrawdownGuard(threshold=0.30, data_dir=tmp_path)
    g1.check(1000.0)
    g1.check(700.0)  # trip
    g2 = DrawdownGuard(threshold=0.30, resume=True, data_dir=tmp_path)
    s = g2.check(700.0)  # 权益未恢复
    assert s.halted and s.just_tripped
    assert s.high_water == 1000.0


def test_invalid_equity_skipped_no_false_trip(tmp_path) -> None:
    # Review Focus #1: get_balance API 失败返回 0.0，不得误触发停机
    g = DrawdownGuard(threshold=0.30, data_dir=tmp_path)
    s = g.check(0.0)
    assert s.skipped and not s.halted and not s.just_tripped
    s2 = g.check(1000.0)  # 恢复后正常
    assert not s2.skipped and s2.high_water == 1000.0


def test_corrupted_baseline_file(tmp_path) -> None:
    # Review Focus #2: 文件损坏/半写 → 干净启动，不抛异常、不误停机
    (tmp_path / "drawdown_baseline.json").write_text("{not json", encoding="utf-8")
    g = DrawdownGuard(threshold=0.30, data_dir=tmp_path)
    s = g.check(1000.0)
    assert not s.halted and s.high_water == 1000.0


def test_wrong_shape_baseline_json_starts_clean(tmp_path) -> None:
    """Review Fix 1/5: 合法 JSON 但形状错误（顶层非 dict / 值类型错）也不得抛异常。"""
    for i, content in enumerate(["[1, 2, 3]", '{"high_water": []}']):
        case_dir = tmp_path / f"case{i}"
        case_dir.mkdir()
        (case_dir / "drawdown_baseline.json").write_text(content, encoding="utf-8")
        g = DrawdownGuard(threshold=0.30, data_dir=case_dir)
        s = g.check(1000.0)
        assert not s.halted and s.high_water == 1000.0, f"content={content!r}"


def test_snapshot_preserves_latch_without_equity_read(tmp_path) -> None:
    """Fix Round 1/5: snapshot() 不刷新权益/高水位，仅镜像当前 latch 状态。"""
    g = DrawdownGuard(threshold=0.30, data_dir=tmp_path)
    g.check(1000.0)
    s = g.snapshot()
    assert s.skipped and not s.halted and not s.just_tripped
    g.check(700.0)  # trip → latch 落盘
    s = g.snapshot()
    assert s.skipped and s.halted and not s.just_tripped
    assert s.high_water == 1000.0
    assert s.drawdown == 0.0
