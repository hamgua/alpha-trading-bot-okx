"""依赖元数据一致性测试。"""

import re
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _requirement_name(requirement: str) -> str:
    return re.split(r"[<>=!~;\[]", requirement, maxsplit=1)[0].strip().lower()


def _read_requirements() -> dict[str, str]:
    requirements: dict[str, str] = {}
    for line in (PROJECT_ROOT / "requirements.txt").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        requirements[_requirement_name(line)] = line
    return requirements


def test_ccxt_version_is_pinned_consistently() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())
    project_deps = {
        _requirement_name(dep): dep for dep in pyproject["project"]["dependencies"]
    }
    requirements = _read_requirements()

    assert project_deps["ccxt"] == "ccxt==4.5.56"
    assert requirements["ccxt"] == project_deps["ccxt"]
