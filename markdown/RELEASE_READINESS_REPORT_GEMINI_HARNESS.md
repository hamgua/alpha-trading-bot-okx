# Gemini + Harness 工程化上线前评审报告

## 变更范围

- OpenSpec Change: `gemini-provider-harness-security-hardening`
- 目标：
  - 统一 Gemini provider 入口与回退契约
  - 建立 P0/P1/P2 安全整改闭环
  - 强化 CI 阻断门禁、发布可重复性与回滚机制
  - 落地观测指标与阈值（成功率/fallback/实盘闸门）

## 已落地条目

1. **实盘安全闸门**
   - 配置层新增：`TEST_MODE`, `REAL_TRADING_CONFIRMED`, `RUNTIME_ENVIRONMENT`
   - 执行层新增拒单：标准/自适应交易路径在前置条件不满足时拒绝下单并记录闸门指标

2. **Gemini 工程化治理**
   - 保持统一调用契约，补充运行时指标记录（Gemini 成功/失败、fallback 调用）
   - 新增 Gemini 回滚脚本：`scripts/rollback_gemini.sh`

3. **安全与漏洞整改**
   - 弱哈希替换：`md5` -> `sha256`
   - 本地持久化权限收敛：关键目录 700 / 文件 600
   - 新增整改台账：`markdown/SECURITY_REMEDIATION_LEDGER.md`

4. **Harness 门禁与交付治理**
   - CI 新增阻断测试：Gemini + 实盘闸门回归
   - 修复发布脚本 Dockerfile 引用，支持可重复构建
   - 调整 `.gitignore`，确保 `.github/`、`openspec/`、`tests/` 可纳入审查

5. **观测指标与阈值**
   - 新增观测模块：`alpha_trading_bot/utils/observability.py`
   - 新增 Gemini/Safety SLO 阈值检查接口

## 验收命令（执行记录由 CI 与本地验证补齐）

```bash
pytest tests/unit/test_gemini_integration.py tests/unit/test_live_trading_guard.py -q
pytest
mypy alpha_trading_bot/
flake8 alpha_trading_bot/ --max-line-length=88 --extend-ignore=E203,W503
pip-audit --progress-spinner=off --strict
```

## 发布与回滚建议

1. 发布分阶段：shadow -> 小流量 -> 全量
2. 回滚优先配置级：
   - `AI_MODE`
   - `AI_DEFAULT_PROVIDER`
   - `AI_FUSION_PROVIDERS`
3. 回滚后必须记录：触发原因、执行人、时间线、恢复结果

## 结论

本次变更已对齐 OpenSpec 目标方向，具备进入 `opsx-archive` 前的验证与审查基础。建议在完成全量验证命令并通过后执行归档。
