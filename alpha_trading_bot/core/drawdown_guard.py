"""回撤停机总闸（P1，2026-10-04 双向交易 spec）

- 权益相对持久化高水位回撤 ≥ threshold（默认 30%）→ 禁止一切新开仓；
  已持仓继续由止损管理，不受影响。
- 高水位持久化到 data/trading_state/drawdown_baseline.json（进程重启不重置，
  避免"亏损后重启重置基准"漏洞）。
- 恢复仅手动：RISK_RESUME=1 + 重启（自动恢复 = 让失效策略继续亏）。
- equity <= 0（get_balance API 失败返回 0.0）视为无效读取，跳过本轮检查。
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .state_persistence import resolve_state_data_dir

logger = logging.getLogger(__name__)

BASELINE_FILENAME = "drawdown_baseline.json"


@dataclass
class DrawdownStatus:
    """单轮回撤检查结果"""

    halted: bool  # True = 禁止新开仓
    drawdown: float  # 当前回撤（相对高水位，0-1）
    high_water: float  # 当前高水位
    just_tripped: bool  # 本轮刚触发停机
    skipped: bool  # equity<=0，本轮检查被跳过


class DrawdownGuard:
    """30% 回撤停机总闸（纯本地状态，无网络 IO）。"""

    # 类型声明置于类级：由 _load() 统一初始化（mypy 成员收窄会误判启动分支不可达）
    _high_water: float
    _halted_since: Optional[float]

    def __init__(
        self,
        threshold: float = 0.30,
        resume: bool = False,
        data_dir: Optional[Path] = None,
    ) -> None:
        self._threshold = threshold
        self._file = resolve_state_data_dir(data_dir) / BASELINE_FILENAME
        self._load()
        if resume:
            if self._halted_since is not None:
                logger.warning(
                    "[风控总闸] RISK_RESUME=1 手动恢复，清除停机状态"
                    "（高水位 %.2f 保留）",
                    self._high_water,
                )
                self._halted_since = None
        elif self._halted_since is not None:
            logger.warning(
                "[风控总闸] 从上次运行恢复停机状态（触发于 %s），"
                "新开仓继续禁止；恢复需 RISK_RESUME=1 + 重启",
                time.strftime("%Y-%m-%d %H:%M", time.localtime(self._halted_since)),
            )

    def check(self, equity: float) -> DrawdownStatus:
        """用最新权益检查回撤状态（每个交易周期调用一次）。"""
        if equity <= 0:
            # API 失败时 get_balance 返回 0.0：不更新状态，避免误停机
            return DrawdownStatus(
                halted=self._halted_since is not None,
                drawdown=0.0,
                high_water=self._high_water,
                just_tripped=False,
                skipped=True,
            )
        if self._high_water <= 0:
            self._high_water = equity
        else:
            self._high_water = max(self._high_water, equity)
        drawdown = (self._high_water - equity) / self._high_water
        just_tripped = False
        if self._halted_since is None and drawdown >= self._threshold:
            self._halted_since = time.time()
            just_tripped = True
            logger.warning(
                "[风控总闸] OPEN: 回撤 %.1f%% ≥ 阈值 %.0f%%，禁止新开仓"
                "（高水位 %.2f → 当前权益 %.2f）；恢复需 RISK_RESUME=1 + 重启",
                drawdown * 100,
                self._threshold * 100,
                self._high_water,
                equity,
            )
        self._save()
        return DrawdownStatus(
            halted=self._halted_since is not None,
            drawdown=drawdown,
            high_water=self._high_water,
            just_tripped=just_tripped,
            skipped=False,
        )

    # ---- 持久化 ----

    def _load(self) -> None:
        # 先落干净默认值：文件缺失时不依赖异常分支
        self._high_water = 0.0
        self._halted_since = None
        try:
            if self._file.exists():
                raw = self._file.read_text(encoding="utf-8")
                data = json.loads(raw)
                self._high_water = float(data.get("high_water", 0.0))
                halted = data.get("halted_since")
                self._halted_since = float(halted) if halted else None
        except (ValueError, OSError, json.JSONDecodeError) as e:
            # 文件损坏/半写：以干净状态启动（Review Focus #2）
            logger.warning("[风控总闸] 基准文件读取失败，以干净高水位启动: %s", e)
            self._high_water = 0.0
            self._halted_since = None

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._file.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "high_water": self._high_water,
                        "halted_since": self._halted_since,
                        "updated_at": time.time(),
                    }
                ),
                encoding="utf-8",
            )
            os.replace(tmp, self._file)  # 原子替换，避免半写
        except OSError as e:
            logger.warning("[风控总闸] 基准文件写入失败（不影响本轮判定）: %s", e)
