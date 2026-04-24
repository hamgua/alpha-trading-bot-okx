## Context

当前仓库已具备 Gemini 基础接入能力（provider 注册、single/fusion 调用、基础测试），但在工程化落地层面仍存在跨模块缺口：

1. **Gemini 接入治理不完整**：功能可用，但灰度发布、回滚演练、配置一致性和文档一致性缺少统一约束。
2. **Harness Engineering 维度不闭环**：已存在 CI 与部分安全门禁，但发布可重复性、可观测性、回滚自动化、变更资产可追溯性不足。
3. **安全整改缺乏执行闭环**：审计已识别高风险（如密钥暴露、实盘隔离风险），但缺少统一的分级、时限、复验和留痕机制。

该变更涉及 `ai/`、`config/`、`core/`、`tests/`、CI 与 OpenSpec 规范，属于跨模块治理类变更。

## Goals / Non-Goals

**Goals:**
- 在不破坏现有交易主链路的前提下，完成 Gemini 集成能力的工程化加固（可灰度、可回滚、可验证）。
- 将 Harness Engineering 要求转化为可执行门禁与验收标准，覆盖测试、质量、安全、发布与回滚、可观测、文档变更管理。
- 建立安全审计整改闭环，确保高危风险可被及时阻断与复验。

**Non-Goals:**
- 不引入新的交易策略逻辑或收益优化算法。
- 不进行大规模架构重写（如整体替换 AI 调用框架）。
- 不在本次变更中实现完整 SIEM/SOC 平台，仅定义项目级可落地基线。

## Decisions

### Decision 1: 采用“最小改动优先”的 Gemini 加固策略

**Decision**
- 保持现有 `ai/providers.py` + `ai/client.py` 的统一 OpenAI-compatible 调用契约，不新增 Gemini 专属调用分支。
- 通过配置治理、测试覆盖和回滚演练提升稳定性，而非重构 provider 架构。

**Rationale**
- 现有仓库已具备 Gemini 主路径能力，从零重做会放大回归风险。
- 最小改动策略更符合交易系统稳定性优先原则。

**Alternatives considered**
- 方案A：新增 Gemini 独立 provider 类与调用器（放弃，复杂度与收益不匹配）。
- 方案B：沿用统一调用契约并加强门禁（采用）。

### Decision 2: 将实盘安全闸门前置到配置与执行层

**Decision**
- 在配置层明确并固化实盘前置条件，执行层增加显式防护（未满足实盘条件时拒绝下单）。
- 将“误实盘”纳入高危安全项并绑定验收门槛。

**Executable gate conditions（MUST 全部满足）**
- `TEST_MODE=false`
- 显式实盘确认开关为真（CLI `--real-trading` 或等效环境变量）
- 交易所凭据完整且通过配置校验
- 运行环境标识为允许实盘的受控环境（非默认开发环境）
- 下单入口安全闸门检查通过并写入审计日志

**Rationale**
- 审计显示误实盘风险属于交易安全高危，必须在执行路径前置拦截。

**Alternatives considered**
- 方案A：仅靠文档提醒（放弃，无法形成技术阻断）。
- 方案B：配置+执行双闸门（采用）。

### Decision 3: 建立分级安全整改闭环（P0/P1/P2 + SLA）

**Decision**
- 将审计结果标准化为 P0/P1/P2 分级，绑定整改时限、复验命令和审计记录模板。
- 将密钥泄露、依赖漏洞、供应链与配置风险纳入同一治理面板。

**Rationale**
- 当前审计有发现但缺少闭环流程，难以持续治理。

**Alternatives considered**
- 方案A：一次性人工修复（放弃，不可持续）。
- 方案B：制度化分级与复验（采用）。

### Decision 4: 以 Harness 工程规范构建“发布-回滚-可观测”闭环

**Decision**
- 将 Gemini 发布采用 shadow → 小流量 → 全量的分阶段流程，并要求配置级快速回滚可演练。
- 补齐结构化日志、关键指标、告警阈值与发布审计记录。
- 将供应链 provenance 验证设为发布阻断项（失败即阻断）。
- 明确仅非 P0 风险允许“告警期过渡”，并配置到期后自动切换为阻断。

**Rationale**
- AI provider 稳定性波动较大，灰度与回滚是生产必备能力。

**Alternatives considered**
- 方案A：一次性全量切换（放弃，风险不可控）。
- 方案B：分阶段发布+可回滚（采用）。

## Risks / Trade-offs

- **[Risk] 门禁增强导致短期交付速度下降** → **Mitigation**：仅对非 P0 项分阶段启用（先告警后阻断）；P0 与 provenance 自首日阻断。
- **[Risk] 实盘闸门改造可能影响现有自动化流程** → **Mitigation**：增加兼容开关并提供迁移窗口，先在测试环境回归。
- **[Risk] 安全扫描规则过严引发噪声** → **Mitigation**：建立扫描白名单与路径范围治理，保留规则评审机制。
- **[Risk] 可观测性改造增加运行开销** → **Mitigation**：指标采样与日志级别分层控制，避免高频全量埋点。

## Migration Plan

1. **Phase P0（安全与阻断）**
   - 落地密钥轮换与实盘防误触闸门。
   - 完成高危项修复并在 CI 中引入阻断检查。
2. **Phase P1（Gemini 工程化与质量门禁）**
   - 完成 Gemini 灰度/回滚流程、回归测试补齐、文档一致性修正。
   - 提升质量门禁覆盖（测试、类型、安全、依赖）。
3. **Phase P2（可观测与持续治理）**
   - 增加结构化日志/指标/告警与变更审计看板。
   - 建立周期性安全复审机制。

**Rollback strategy**
- Gemini 异常时通过配置快速回滚到稳定 provider 组合（`AI_DEFAULT_PROVIDER` / `AI_FUSION_PROVIDERS`）。
- 门禁策略异常时可回退到上一版本 pipeline 配置，但保留关键安全阻断（密钥泄露检测不可关闭）。

## Open Questions

- 观测基线选择 Prometheus 还是维持轻量日志+定时聚合方案？

## Resolved Baseline Policies

- 配置单一事实源（SoT）：`config/models.py` 作为权威配置模型，`ai/config_manager.py` 仅作为兼容适配层并逐步收敛。
- provenance 策略：发布阶段强制阻断（验证失败不得发布）。
- 风险门禁策略：P0（密钥泄露、误实盘、鉴权失效）首日阻断；仅非 P0 可设短期告警窗口并定义到期切换时间。
- 可观测验收阈值（首版）：
  - Gemini 请求成功率 ≥ 99%（24h 滑窗）
  - Gemini fallback 率 ≤ 5%（24h 滑窗）
  - 误实盘闸门误触发率 = 0（生产）
