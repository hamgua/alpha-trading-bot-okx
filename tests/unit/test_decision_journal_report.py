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


def test_load_journal_tolerates_broken_file_and_non_dict_lines(
    tmp_path, capsys
) -> None:
    """文件级坏 UTF-8（半写多字节）+ 非对象 JSON 行跳过不抛，好行仍可读。"""
    # 坏文件：合法行 + 半写多字节字符（\xe4\xb8 是不完整的 3 字节序列）
    (tmp_path / "decision_journal-2026-10-01.jsonl").write_bytes(
        json.dumps(_cycle("2026-10-01 09:00:00", 99.0, "BUY")).encode("utf-8")
        + b'\n{"type": "cycle", "final": "\xe4\xb8'
    )
    # 好文件：合法 cycle 行 + 合法 JSON 但非对象（数组）行
    (tmp_path / "decision_journal-2026-10-02.jsonl").write_text(
        json.dumps(_cycle("2026-10-02 09:00:00", 100.0, "HOLD"))
        + "\n[1, 2, 3]\n",
        encoding="utf-8",
    )
    cycles, outcomes = load_journal(tmp_path)  # 不抛
    assert [c["ts"] for c in cycles] == ["2026-10-02 09:00:00"]
    assert outcomes == {}
    assert "[warn]" in capsys.readouterr().err
