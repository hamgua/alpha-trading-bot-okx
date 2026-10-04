"""决策日志报表聚合函数测试（P1）"""

import json
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
from decision_journal_report import agg_by, load_journal  # noqa: E402

TS_FMT = "%Y-%m-%d %H:%M:%S"


def _write_day(dir_path: Path, day: str, records) -> None:
    # 追加写入（与 DecisionJournal._append 一致）；同一 day 多次调用累积
    with (dir_path / f"decision_journal-{day}.jsonl").open(
        "a", encoding="utf-8"
    ) as fh:
        fh.write("\n".join(json.dumps(r) for r in records) + "\n")


def _cycle(ts, price, final, **extra):
    r = {"type": "cycle", "ts": ts, "price": price, "final": final}
    r.update(extra)
    return r


def test_load_journal_joins_outcomes(tmp_path) -> None:
    _write_day(tmp_path, "2026-10-01", [
        _cycle("2026-10-01 10:00:00", 100.0, "BUY",
               jev={"choice": "buy", "confidence": 0.6}),
        {"type": "outcome", "ts": "2026-10-01 10:00:00",
         "forward_return_4h": 0.02, "direction_correct_4h": True},
    ])
    cycles, outcomes = load_journal(tmp_path)
    assert len(cycles) == 1 and len(outcomes) == 1
    assert cycles[0]["forward_return_4h"] == 0.02


def test_agg_by_jev_conf_buckets(tmp_path) -> None:
    _write_day(tmp_path, "2026-10-01", [
        _cycle(f"2026-10-01 10:{i:02d}:00", 100.0, "HOLD",
               jev={"choice": "buy", "confidence": c})
        for i, c in enumerate([0.5, 0.6, 0.8])
    ])
    _write_day(tmp_path, "2026-10-01", [
        {"type": "outcome", "ts": f"2026-10-01 10:{i:02d}:00",
         "forward_return_4h": v, "direction_correct_4h": v > 0.001}
        for i, v in enumerate([0.01, 0.02, -0.01])
    ])
    cycles, _ = load_journal(tmp_path)

    def key_fn(c):
        jev = c.get("jev") or {}
        conf = jev.get("confidence", 0.0)
        bucket = "<0.55" if conf < 0.55 else ("0.55-0.75" if conf < 0.75 else ">=0.75")
        return f"jev:{jev.get('choice', '?')}:{bucket}"

    rows = agg_by(cycles, key_fn)
    by_key = {r["key"]: r for r in rows}
    assert by_key["jev:buy:<0.55"]["count"] == 1
    assert by_key["jev:buy:0.55-0.75"]["count"] == 1
    assert by_key["jev:buy:>=0.75"]["count"] == 1
    assert by_key["jev:buy:0.55-0.75"]["avg_fwd_4h"] == 0.02
