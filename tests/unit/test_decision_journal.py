"""DecisionJournal 测试（P1 决策日志）"""

import json
from datetime import datetime, timedelta
from pathlib import Path

from alpha_trading_bot.core.decision_journal import DecisionJournal

TS_FMT = "%Y-%m-%d %H:%M:%S"


def _read(journal_dir: Path, day: str) -> list:
    f = journal_dir / f"decision_journal-{day}.jsonl"
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l]


def test_disabled_writes_nothing(tmp_path) -> None:
    j = DecisionJournal(enabled=False, data_dir=tmp_path)
    j.record_cycle({"price": 1.0})
    assert list(tmp_path.glob("decision_journal-*.jsonl")) == []


def test_record_cycle_appends_jsonl(tmp_path) -> None:
    j = DecisionJournal(enabled=True, data_dir=tmp_path)
    j.record_cycle({"price": 84000.0, "final": "HOLD"})
    lines = _read(tmp_path, datetime.now().strftime("%Y-%m-%d"))
    assert len(lines) == 1
    assert lines[0]["type"] == "cycle"
    assert lines[0]["price"] == 84000.0
    assert "ts" in lines[0]


def test_backfill_4h_window(tmp_path) -> None:
    j = DecisionJournal(enabled=True, data_dir=tmp_path)
    now = datetime.now()
    old_ts = (now - timedelta(hours=4)).strftime(TS_FMT)
    # 直接写一条旧 cycle 记录（模拟 4 小时前的周期）
    day = (now - timedelta(hours=4)).strftime("%Y-%m-%d")
    with open(tmp_path / f"decision_journal-{day}.jsonl", "a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {"type": "cycle", "ts": old_ts, "price": 84000.0, "final": "BUY"}
            )
            + "\n"
        )
    n = j.backfill(now, 86000.0)
    assert n == 1
    # outcome 行落在当前天文件
    outcomes = [
        l for l in _read(tmp_path, now.strftime("%Y-%m-%d")) if l["type"] == "outcome"
    ]
    assert len(outcomes) == 1
    assert outcomes[0]["forward_return_4h"] == round((86000.0 - 84000.0) / 84000.0, 8)
    assert outcomes[0]["direction_correct_4h"] is True  # BUY 且正收益


def test_backfill_hold_direction_none(tmp_path) -> None:
    j = DecisionJournal(enabled=True, data_dir=tmp_path)
    now = datetime.now()
    old_ts = (now - timedelta(hours=4)).strftime(TS_FMT)
    day = (now - timedelta(hours=4)).strftime("%Y-%m-%d")
    with open(tmp_path / f"decision_journal-{day}.jsonl", "a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {"type": "cycle", "ts": old_ts, "price": 84000.0, "final": "HOLD"}
            )
            + "\n"
        )
    j.backfill(now, 86000.0)
    outcomes = [
        l for l in _read(tmp_path, now.strftime("%Y-%m-%d")) if l["type"] == "outcome"
    ]
    assert outcomes[0]["direction_correct_4h"] is None


def test_backfill_across_day_boundary(tmp_path) -> None:
    # Review Focus #4: 23:50 的 cycle 在次日 03:50 回填 T+4h
    now = datetime(2026, 10, 4, 3, 50, 0)
    j = DecisionJournal(enabled=True, data_dir=tmp_path)
    old = datetime(2026, 10, 3, 23, 50, 0)
    f = tmp_path / "decision_journal-2026-10-03.jsonl"
    f.write_text(
        json.dumps(
            {
                "type": "cycle",
                "ts": old.strftime(TS_FMT),
                "price": 84000.0,
                "final": "BUY",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    n = j.backfill(now, 84800.0)
    assert n == 1


def test_backfill_no_double_write(tmp_path) -> None:
    j = DecisionJournal(enabled=True, data_dir=tmp_path)
    now = datetime.now()
    old_ts = (now - timedelta(hours=4)).strftime(TS_FMT)
    day = (now - timedelta(hours=4)).strftime("%Y-%m-%d")
    with open(tmp_path / f"decision_journal-{day}.jsonl", "a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {"type": "cycle", "ts": old_ts, "price": 84000.0, "final": "BUY"}
            )
            + "\n"
        )
    j.backfill(now, 86000.0)
    # 第二次仍在同一 4h 窗口内（age=4h05m），去重集合防重复写
    j.backfill(now + timedelta(minutes=5), 86100.0)
    outcomes = [
        l
        for l in _read(tmp_path, (now + timedelta(minutes=5)).strftime("%Y-%m-%d"))
        if l["type"] == "outcome"
    ]
    assert len(outcomes) == 1  # 已有 outcome 的不重复写


def test_write_failure_does_not_raise(tmp_path) -> None:
    # Review Focus #3: 写失败吞异常 + WARNING，不抛出
    j = DecisionJournal(enabled=True, data_dir=tmp_path)
    import unittest.mock as mock

    with mock.patch("pathlib.Path.open", side_effect=OSError("disk full")):
        j.record_cycle({"price": 1.0})  # 不得抛异常
    j.backfill(datetime.now(), 1.0)  # 同样不得抛


def test_retention_prunes_old_files(tmp_path) -> None:
    j = DecisionJournal(enabled=True, data_dir=tmp_path)
    old_day = (datetime.now() - timedelta(days=91)).strftime("%Y-%m-%d")
    old = tmp_path / f"decision_journal-{old_day}.jsonl"
    old.write_text("{}\n", encoding="utf-8")
    DecisionJournal(enabled=True, data_dir=tmp_path)  # 重新 init 触发清理
    assert not old.exists()
