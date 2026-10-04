"""决策日志（P1，2026-10-04 双向交易 spec）

每周期追加一行 JSONL（各层信号 + 价格），并在后续周期回填 T+4h/T+24h
前向收益（追加 outcome 行，按 ts join）。文件按日轮转，保留 90 天。
所有 IO 失败吞异常 + WARNING：决策日志故障永不中断交易周期。
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from .state_persistence import resolve_state_data_dir

logger = logging.getLogger(__name__)

FILE_PREFIX = "decision_journal-"
RETENTION_DAYS = 90
# 15 分钟周期的回填容错窗口（±10 分钟）
WINDOW_4H = (
    timedelta(hours=4) - timedelta(minutes=10),
    timedelta(hours=4) + timedelta(minutes=10),
)
WINDOW_24H = (
    timedelta(hours=24) - timedelta(minutes=10),
    timedelta(hours=24) + timedelta(minutes=10),
)

TS_FMT = "%Y-%m-%d %H:%M:%S"


class DecisionJournal:
    """JSONL 决策日志（追加式，单进程写入）。"""

    def __init__(self, enabled: bool, data_dir: Optional[Path] = None) -> None:
        self._enabled = enabled
        self._dir = resolve_state_data_dir(data_dir)
        if self._enabled:
            try:
                self._dir.mkdir(parents=True, exist_ok=True)
                self._prune_old_files()
            except OSError as e:
                logger.warning("[决策日志] 初始化目录失败，日志功能禁用: %s", e)
                self._enabled = False

    # ---- 写入 ----

    def record_cycle(self, entry: Dict[str, Any]) -> None:
        """追加一条 cycle 记录（ts 取当前时间）。"""
        if not self._enabled:
            return
        record = {"type": "cycle", "ts": datetime.now().strftime(TS_FMT)}
        record.update(entry)
        self._append(record, datetime.now())

    def backfill(self, current_ts: datetime, current_price: float) -> int:
        """回填 4h/24h 前向收益，返回本次回填的 outcome 行数。

        先汇总当天+前一天全部记录，done 集合跨文件去重（防跨天重复回填）。
        """
        if not self._enabled:
            return 0
        # ticker 拉取失败时 current_price 可能为 0/None/NaN，此时前向收益无意义，跳过回填
        if current_price is None or not current_price > 0:
            return 0
        days = {
            current_ts.strftime("%Y-%m-%d"),
            (current_ts - timedelta(days=1)).strftime("%Y-%m-%d"),
        }
        all_records: list = []
        for day in sorted(days):
            f = self._dir / f"{FILE_PREFIX}{day}.jsonl"
            if not f.exists():
                continue
            try:
                # 逐行容错：半写产生的坏字节降级为 U+FFFD，所在行 JSON 解析失败被跳过，好行保留
                lines = f.read_bytes().decode("utf-8", errors="replace").splitlines()
            except (OSError, UnicodeDecodeError) as e:
                logger.warning("[决策日志] 读取 %s 失败: %s", f.name, e)
                continue
            all_records.extend(self._parse(lines))
        done_4h = {
            r["ts"]
            for r in all_records
            if r.get("type") == "outcome" and r.get("forward_return_4h") is not None
        }
        done_24h = {
            r["ts"]
            for r in all_records
            if r.get("type") == "outcome" and r.get("forward_return_24h") is not None
        }
        written = 0
        for rec in all_records:
            if rec.get("type") != "cycle":
                continue
            try:
                entry_ts = datetime.strptime(rec["ts"], TS_FMT)
            except (KeyError, ValueError):
                continue
            age = current_ts - entry_ts
            for label, window, key, done in (
                ("4h", WINDOW_4H, "forward_return_4h", done_4h),
                ("24h", WINDOW_24H, "forward_return_24h", done_24h),
            ):
                if not (window[0] <= age <= window[1]) or rec["ts"] in done:
                    continue
                try:
                    base_price = float(rec.get("price", 0))
                except (TypeError, ValueError):
                    continue
                if base_price <= 0:
                    continue
                fwd = round((current_price - base_price) / base_price, 8)
                final_sig = str(rec.get("final", "")).strip().upper()
                if final_sig == "BUY":
                    correct: Optional[bool] = fwd > 0.001
                elif final_sig in ("SELL", "SHORT"):
                    correct = fwd < -0.001
                else:
                    correct = None
                outcome = {
                    "type": "outcome",
                    "ts": rec["ts"],
                    key: fwd,
                    f"direction_correct_{label}": correct,
                }
                self._append(outcome, current_ts)
                done.add(rec["ts"])
                written += 1
        return written

    # ---- 内部 ----

    @staticmethod
    def _parse(lines: list) -> list:
        out = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue  # 半写/损坏行跳过
            if isinstance(obj, dict):
                out.append(obj)  # 合法 JSON 但非对象（数组/标量）跳过
        return out

    def _append(self, record: Dict[str, Any], ts: datetime) -> None:
        try:
            f = self._dir / f"{FILE_PREFIX}{ts.strftime('%Y-%m-%d')}.jsonl"
            with f.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning("[决策日志] 写入失败（周期不受影响）: %s", e)

    def _prune_old_files(self) -> None:
        cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
        for f in self._dir.glob(f"{FILE_PREFIX}*.jsonl"):
            try:
                day = datetime.strptime(f.stem.replace(FILE_PREFIX, ""), "%Y-%m-%d")
            except ValueError:
                continue
            if day < cutoff:
                try:
                    f.unlink()
                except OSError as e:
                    logger.warning("[决策日志] 清理 %s 失败: %s", f.name, e)
