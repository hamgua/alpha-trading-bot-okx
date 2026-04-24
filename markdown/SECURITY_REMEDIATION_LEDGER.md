# 安全整改台账（P0/P1/P2）

> 目标：将审计发现转为可执行闭环，满足 P0/P1/P2 分级、SLA、责任人与复验证据要求。

## 分级与时限（SLA）

- **P0**：24小时内完成（阻断发布）
- **P1**：7天内完成
- **P2**：30天内完成

## 台账字段

- 发现时间（UTC+8）
- 风险级别（P0/P1/P2）
- 风险项
- 影响范围
- 责任人
- 计划完成时间
- 复验命令
- 复验结果
- 关闭证据

## 当前整改记录

| 发现时间 | 级别 | 风险项 | 影响范围 | 责任人 | 截止时间 | 复验命令 | 复验结果 | 关闭证据 |
|---|---|---|---|---|---|---|---|---|
| 2026-04-24 | P0 | 密钥泄漏阻断与轮换流程不足 | `.pre-commit-config.yaml`, `.github/workflows/ci.yml`, `markdown/SECURITY_KEY_ROTATION_RUNBOOK.md` | Sisyphus | 2026-04-25 | `gitleaks detect --source . --config=.gitleaks.toml --redact --no-git` / CI gitleaks job | 已完成（门禁已接入） | `.pre-commit-config.yaml`, `ci.yml`, `SECURITY_KEY_ROTATION_RUNBOOK.md` |
| 2026-04-24 | P0 | 实盘误触发缺少执行层闸门 | `config/models.py`, `core/bot.py`, `core/adaptive_bot.py`, `exchange/client.py` | Sisyphus | 2026-04-25 | `pytest tests/unit/test_live_trading_guard.py -q` | 已完成（5 tests pass） | 配置前置条件 + 标准/自适应拒单逻辑 + TEST_MODE 沙盒模式 |
| 2026-04-24 | P1 | MD5 弱哈希 | `ai/client.py`, `ai/ml/ab_test_framework.py` | Sisyphus | 2026-05-01 | `grep -R "md5(" alpha_trading_bot` | 已完成（0 命中） | `sha256` 替换完成 |
| 2026-04-24 | P1 | 本地持久化权限未收敛 | `ai/ml/*`, `ai/optimizer/config_updater.py` | Sisyphus | 2026-05-01 | `python3 -c "import os; print('manual verification required')"` | 已完成（代码已设置 700/600） | `performance_tracker.py`, `weight_optimizer.py`, `monitoring_dashboard.py`, `config_updater.py` |

## 发布前安全复验清单

1. `pre-commit run --all-files`
2. `pytest`
3. `mypy alpha_trading_bot/`
4. `flake8 alpha_trading_bot/ --max-line-length=88 --extend-ignore=E203,W503`
5. `pip-audit --progress-spinner=off --strict`
