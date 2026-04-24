## ADDED Requirements

### Requirement: 系统 SHALL 支持 Gemini 作为可配置 AI 提供商
系统 MUST 将 Gemini 纳入统一 provider 注册与配置校验体系，确保在 single 与 fusion 模式下均可被显式选择，并在配置缺失时提供可诊断错误。

#### Scenario: single 模式启用 Gemini
- **WHEN** 用户设置 `AI_MODE=single` 且 `AI_DEFAULT_PROVIDER=gemini`
- **THEN** 系统 MUST 使用 Gemini 发起信号请求，并产出标准化信号结构（signal + confidence）

#### Scenario: fusion 模式包含 Gemini
- **WHEN** 用户设置 `AI_MODE=fusion` 且 `AI_FUSION_PROVIDERS` 包含 `gemini`
- **THEN** 系统 MUST 将 Gemini 纳入并行调用与融合计算，不得因 provider 不识别而崩溃或静默跳过

### Requirement: 系统 SHALL 统一 provider 调用契约
系统 MUST 对所有 provider（含 Gemini）使用一致的输入输出与异常语义，包括超时、重试、错误分级和回退策略，避免策略实现间接口不兼容。

#### Scenario: 融合策略切换时保持调用兼容
- **WHEN** 运行时切换融合策略（如 weighted、majority、consensus、consensus_boosted）
- **THEN** 系统 MUST 维持统一调用签名与返回契约，不得出现仅部分策略可运行的兼容性错误

#### Scenario: provider 请求失败触发回退
- **WHEN** Gemini 调用超时、429 或 5xx 错误且满足回退条件
- **THEN** 系统 MUST 按配置的 fallback 顺序降级到可用 provider，并记录可追踪日志

### Requirement: 系统 SHALL 提供 Gemini 可回滚开关
系统 MUST 保持 provider 级别与模式级别的可回滚能力，确保 Gemini 接入异常时可通过配置快速恢复到既有稳定路径。

#### Scenario: 回滚默认 provider
- **WHEN** 生产环境判定 Gemini 不稳定并执行回滚
- **THEN** 仅通过配置切换 `AI_DEFAULT_PROVIDER` 或 `AI_FUSION_PROVIDERS` 即可恢复既有 provider 链路，无需代码变更

### Requirement: 系统 SHALL 提供 Gemini 最小回归验证
系统 MUST 提供覆盖配置校验、路由调用、融合参与、响应解析与回退行为的自动化最小回归测试，以防止后续变更破坏 Gemini 集成。

#### Scenario: provider 注册与配置校验测试通过
- **WHEN** CI 执行 Gemini 相关单元/集成测试
- **THEN** 必须验证 Gemini 在 provider 列表、环境变量读取与配置校验中的行为符合预期

#### Scenario: 融合路径回归测试通过
- **WHEN** CI 执行 fusion 场景测试并包含 Gemini
- **THEN** 必须验证融合输出稳定且错误路径可控（失败时有明确降级）
