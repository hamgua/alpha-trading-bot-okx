"""启动运行标识辅助（纯函数，无副作用）。

背景 (dream 2026-09-14-trading-loss-analysis):
    日志根因分析时发现无法从运行日志判断"实际加载的是哪个代码版本"
    （提交时间 ≠ 长驻进程加载时间，且各日日志均从周期中途开始、无版本标记）。
    本模块提供无副作用的启动标识生成逻辑，供入口在启动时记录，
    使后续日志可追溯代码版本。仅标准库实现，测试中可直接导入
    （不会像导入 ``main`` 那样在导入期触发 ``load_dotenv``）。
"""

from __future__ import annotations

import logging
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


def _clean(value: str) -> str:
    """单行化消毒：将回车/换行替换为空格并去首尾空白，防止日志换行注入。"""
    return value.replace("\r", " ").replace("\n", " ").strip()


def git_commit_short(timeout: float = 5.0) -> str:
    """返回当前 git 短提交号（best-effort，绝不抛出）。

    Args:
        timeout: 子进程超时（秒），避免在无 git / git 卡住时阻塞启动。

    Returns:
        git 短提交号；无 git / 命令非 0 返回 / 空输出 / 异常时返回 ``"unknown"``。

    Note:
        依赖进程工作目录为 git 仓库根（``subprocess`` 未指定 ``cwd``）；
        从仓库外启动将得到 ``"unknown"``（best-effort，可接受）。
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 - best-effort，任何失败都降级为 unknown
        logger.debug("获取 git commit 失败: %s: %s", type(exc).__name__, exc)
        return "unknown"
    if proc.returncode != 0:
        logger.debug(
            "git rev-parse 非 0 返回: %s, stderr=%s",
            proc.returncode,
            (proc.stderr or "").strip(),
        )
        return "unknown"
    commit = (proc.stdout or "").strip()
    return commit if commit else "unknown"


def build_startup_info(
    version: str = "unknown",
    commit: str = "unknown",
    mode: str = "unknown",
    test_mode: Optional[bool] = None,
    runtime: str = "unknown",
    symbol: str = "unknown",
    leverage: Optional[int] = None,
) -> str:
    """格式化为单行启动标识日志。

    纯函数：不抛错；字段为 ``None`` / 空串时以 ``unknown`` 兜底，确保启动期
    不因字段缺失而中断。字符串字段经单行化消毒，防止换行日志注入。

    Args:
        version: 包版本号（如 ``4.0.0``）。
        commit: git 短提交号（可为 ``unknown``）。
        mode: 运行模式（standard / adaptive）。
        test_mode: 是否测试模式（None 时输出 ``unknown``）。
        runtime: 运行环境（dev / test / staging / prod）。
        symbol: 交易对。
        leverage: 杠杆倍数。

    Returns:
        单行字符串，例如
        ``[启动] version=4.0.0 commit=abc1234 mode=adaptive test_mode=false ...``
    """
    if test_mode is None:
        test_mode_str = "unknown"
    elif test_mode:
        test_mode_str = "true"
    else:
        test_mode_str = "false"

    version_s = _clean(version) or "unknown"
    commit_clean = _clean(commit)
    # commit 额外取首个 token，确保单行（防 PATH 上 git 输出异常多行）
    commit_s = commit_clean.split()[0] if commit_clean else "unknown"
    mode_s = _clean(mode) or "unknown"
    runtime_s = _clean(runtime) or "unknown"
    symbol_s = _clean(symbol) or "unknown"

    return (
        f"[启动] version={version_s} "
        f"commit={commit_s} "
        f"mode={mode_s} "
        f"test_mode={test_mode_str} "
        f"runtime={runtime_s} "
        f"symbol={symbol_s} "
        f"leverage={leverage if leverage is not None else 'unknown'}"
    )
