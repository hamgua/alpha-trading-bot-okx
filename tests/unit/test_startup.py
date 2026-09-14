"""startup 模块单元测试。

覆盖 dream 2026-09-14-trading-loss-analysis 新增的纯函数：
- git_commit_short()：启动期取 git 短提交号，best-effort，绝不抛出。
- build_startup_info()：单行启动标识格式化，绝不抛出，含单行化消毒。

运行：.venv/bin/python -m pytest tests/unit/test_startup.py -v
"""

import re
import subprocess
from unittest.mock import MagicMock, call, patch

from alpha_trading_bot.startup import build_startup_info, git_commit_short


# ---------------------------------------------------------------------------
# git_commit_short
# ---------------------------------------------------------------------------
def test_git_commit_short_returns_string_never_raises() -> None:
    """任意情况下返回 str 且不抛异常；非 unknown 时形似短哈希。"""
    result = git_commit_short()
    assert isinstance(result, str)
    assert result == "unknown" or re.fullmatch(r"[0-9a-f]{4,40}", result)


def test_git_commit_short_matches_head_in_git_repo() -> None:
    """本项目为 git 仓库，返回值应与 `git rev-parse --short HEAD` 一致。"""
    proc = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    expected = proc.stdout.strip()
    if proc.returncode == 0 and expected:
        assert git_commit_short() == expected
    else:
        # 非 git 环境：应优雅降级为 unknown
        assert git_commit_short() == "unknown"


def test_git_commit_short_subprocess_exception_returns_unknown() -> None:
    """subprocess 抛异常（无 git / 权限拒绝）→ unknown，不抛出。"""
    with patch(
        "alpha_trading_bot.startup.subprocess.run", side_effect=OSError("git missing")
    ):
        assert git_commit_short() == "unknown"


def test_git_commit_short_timeout_expired_returns_unknown() -> None:
    """git 卡死触发 TimeoutExpired → unknown，不抛出。"""
    with patch(
        "alpha_trading_bot.startup.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["git"], timeout=5.0),
    ):
        assert git_commit_short() == "unknown"


def test_git_commit_short_nonzero_returncode_returns_unknown() -> None:
    """git 命令非 0 返回 → unknown（stdout 给非空值，隔离验证 returncode 优先）。"""
    proc = MagicMock()
    proc.returncode = 128
    proc.stdout = "abc1234"
    proc.stderr = "fatal: not a git repository"
    with patch("alpha_trading_bot.startup.subprocess.run", return_value=proc):
        assert git_commit_short() == "unknown"


def test_git_commit_short_empty_stdout_returns_unknown() -> None:
    """stdout 为空/仅空白 → unknown。"""
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = "   \n"
    with patch("alpha_trading_bot.startup.subprocess.run", return_value=proc):
        assert git_commit_short() == "unknown"


def test_git_commit_short_none_stdout_returns_unknown() -> None:
    """stdout 为 None（`or ""` 防御分支）→ unknown。"""
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = None
    with patch("alpha_trading_bot.startup.subprocess.run", return_value=proc):
        assert git_commit_short() == "unknown"


def test_git_commit_short_strips_whitespace() -> None:
    """正常输出应去除首尾空白。"""
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = "f4be915\n"
    with patch("alpha_trading_bot.startup.subprocess.run", return_value=proc):
        assert git_commit_short() == "f4be915"


def test_git_commit_short_forwards_timeout() -> None:
    """timeout 参数应透传给 subprocess.run（'不阻塞启动'的核心契约）。"""
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = "f4be915\n"
    with patch("alpha_trading_bot.startup.subprocess.run", return_value=proc) as mocked:
        git_commit_short(timeout=3.0)
        assert mocked.call_args == call(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3.0,
        )


# ---------------------------------------------------------------------------
# build_startup_info
# ---------------------------------------------------------------------------
def test_build_startup_info_full_fields_exact() -> None:
    """全字段：精确锁定单行格式契约。"""
    out = build_startup_info(
        version="4.0.0",
        commit="f4be915",
        mode="adaptive",
        test_mode=False,
        runtime="prod",
        symbol="BTC/USDT:USDT",
        leverage=10,
    )
    assert out == (
        "[启动] version=4.0.0 commit=f4be915 mode=adaptive "
        "test_mode=false runtime=prod symbol=BTC/USDT:USDT leverage=10"
    )


def test_build_startup_info_is_single_line() -> None:
    out = build_startup_info(version="4.0.0", commit="f4be915")
    assert "\n" not in out
    assert "\r" not in out


def test_build_startup_info_sanitizes_newline_injection() -> None:
    """日志注入防护：symbol 含换行时输出仍为单行（内容压到同一行）。"""
    out = build_startup_info(symbol="BTC/USDT:USDT\nFAKE - injected line")
    assert "\n" not in out
    assert "\r" not in out
    assert "FAKE" in out


def test_build_startup_info_commit_multiline_takes_first_token() -> None:
    """commit 含多行时仅取首个 token，保证单行。"""
    out = build_startup_info(commit="f4be915\nsecond_line")
    assert "commit=f4be915" in out
    assert "second_line" not in out


def test_build_startup_info_test_mode_variants() -> None:
    """test_mode: True→true / False→false / None→unknown。"""
    assert "test_mode=true" in build_startup_info(test_mode=True)
    assert "test_mode=false" in build_startup_info(test_mode=False)
    assert "test_mode=unknown" in build_startup_info(test_mode=None)


def test_build_startup_info_none_leverage_unknown() -> None:
    assert "leverage=unknown" in build_startup_info(leverage=None)


def test_build_startup_info_zero_leverage_kept() -> None:
    """leverage=0 应保留（`is not None` 语义，非真值判断）。"""
    assert "leverage=0" in build_startup_info(leverage=0)


def test_build_startup_info_empty_string_fallback() -> None:
    """字符串字段为空串 → unknown 兜底。"""
    out = build_startup_info(version="", commit="", mode="", runtime="", symbol="")
    assert "version=unknown" in out
    assert "commit=unknown" in out
    assert "mode=unknown" in out
    assert "runtime=unknown" in out
    assert "symbol=unknown" in out


def test_build_startup_info_all_defaults_never_raises() -> None:
    """全默认参数：不抛错，unknown 兜底。"""
    out = build_startup_info()
    assert "version=unknown" in out
    assert "commit=unknown" in out
    assert "test_mode=unknown" in out
    assert "leverage=unknown" in out


def test_build_startup_info_no_secret_field_names() -> None:
    """静态约束：输出不得包含机密字段名，防未来回归。"""
    out = build_startup_info(
        version="4.0.0",
        commit="f4be915",
        mode="adaptive",
        test_mode=False,
        runtime="prod",
        symbol="BTC/USDT:USDT",
        leverage=10,
    )
    lowered = out.lower()
    assert "api_key" not in lowered
    assert "password" not in lowered
    assert "okx_secret" not in lowered
