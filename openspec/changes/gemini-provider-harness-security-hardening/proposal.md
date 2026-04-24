## Why

当前项目已具备 Gemini 基础接入能力，但从工程化落地角度仍存在三类关键缺口：一是 Gemini 能力在配置一致性、回滚演练和文档对齐上仍需规范化；二是 Harness Engineering 关注的可验证性/可观测性/可回滚性尚未形成闭环；三是安全审计已暴露高风险项（如本地密钥暴露与实盘隔离风险）但缺乏统一整改方案。现在推进该变更可降低实盘与供应链风险，并提升后续迭代可控性。

## What Changes

- 基于现有代码与审计结果，建立 Gemini 提供商治理基线：统一配置入口、回滚策略、测试与文档一致性。
- 将 Harness Engineering 要求落地为可执行门禁：覆盖测试/质量/安全扫描/发布与回滚/可观测性/变更留痕。
- 针对安全审计高中风险项制定整改方案与优先级（P0/P1/P2），并纳入任务清单与验收标准。
- 明确“最小改动路径”：避免不必要重构，优先通过配置、门禁和局部代码修复实现风险收敛。

## Capabilities

### New Capabilities
- `security-audit-remediation`: 建立代码安全与漏洞审计整改闭环，要求风险分级、处置时限、复验机制与审计留痕。

### Modified Capabilities
- `gemini-provider-integration`: 强化 Gemini 在 single/fusion 场景下的配置一致性、回退行为验证、灰度与配置级回滚要求。
- `engineering-quality-gates`: 扩展并细化质量门禁，补齐发布可重复性、回滚自动化、可观测性与变更资产可追溯要求。

## Impact

- 受影响代码路径（预期）：
  - `alpha_trading_bot/ai/`（provider 配置、fallback 与调用契约）
  - `alpha_trading_bot/config/`（配置校验、TEST_MODE/环境隔离约束）
  - `alpha_trading_bot/core/`（下单路径安全闸门与日志）
  - `tests/`（Gemini 与安全回归测试）
- 受影响工程资产：
  - `.github/workflows/`（门禁与发布/扫描流程）
  - `.pre-commit-config.yaml`（提交前安全拦截）
  - `README.md` 与运维文档（架构与回滚说明一致性）
  - `openspec/specs/*`（需求规范与任务可追踪化）
- 外部依赖影响：可能新增或启用安全/观测工具链（如依赖审计、指标导出）但保持与当前 Python 技术栈兼容。
