## ADDED Requirements

### Requirement: CI SHALL 作为阻断式质量门禁
项目 CI MUST 将测试、类型检查、格式检查与静态检查设为阻断条件，禁止在主分支合并前以非阻断方式跳过失败项。

#### Scenario: 质量检查失败阻断合并
- **WHEN** 任一质量任务（pytest/mypy/flake8/black）失败
- **THEN** CI MUST 失败并阻断合并，且输出可定位失败原因

### Requirement: 系统 SHALL 建立安全扫描范围与噪声治理基线
安全审计流程 MUST 仅扫描受控源码与配置路径，并明确排除第三方依赖缓存与临时目录，避免误报淹没真实风险。

#### Scenario: 安全扫描聚焦源码
- **WHEN** 触发代码安全与漏洞扫描
- **THEN** 扫描范围 MUST 包含 `alpha_trading_bot/` 与关键配置文件，并排除 `venv/`、`.mypy_cache/`、`.opencode/` 等噪声路径

#### Scenario: 扫描结果可分级治理
- **WHEN** 扫描输出风险结果
- **THEN** 结果 MUST 按严重度分级（P0/P1/P2）并附带整改建议与处理时限

### Requirement: 系统 SHALL 强制密钥与凭据治理
系统 MUST 将密钥管理纳入开发与发布流程，包含提交前泄漏检测、历史泄漏轮换、以及环境变量规范化。

#### Scenario: 提交阶段拦截密钥泄漏
- **WHEN** 开发者提交包含疑似凭据的变更
- **THEN** pre-commit/CI MUST 拦截并提示修复，不得进入主分支

#### Scenario: 历史泄漏触发轮换
- **WHEN** 审计确认存在已暴露密钥
- **THEN** 团队 MUST 执行轮换并记录处置结果

### Requirement: 流水线 SHALL 支持 SBOM 与策略治理
项目发布流水线 MUST 具备 SBOM 生成/导入与策略执行能力，确保依赖组件满足组织安全与合规要求。

#### Scenario: SBOM 策略执行
- **WHEN** 构建或部署流程执行 SBOM Policy Enforcement
- **THEN** 对不符合 allow/deny 策略的组件 MUST 报告违规，并按策略阻断或告警

### Requirement: 流水线 SHALL 支持供应链签名与来源验证
项目流水线 MUST 提供制品签名与来源证明（provenance）验证能力，确保下游仅消费可信构建产物。

#### Scenario: 生成并校验来源证明
- **WHEN** 制品构建完成并进入发布路径
- **THEN** 系统 MUST 生成/保存可验证 provenance，并在后续阶段执行验证与策略检查

### Requirement: 变更 SHALL 具备可回滚发布策略
涉及 provider 或安全门禁策略的变更 MUST 以分阶段发布执行，支持配置级回滚并保留审计轨迹。

#### Scenario: 分阶段发布与回滚
- **WHEN** Gemini 或门禁策略在灰度阶段触发异常
- **THEN** 系统 MUST 通过配置开关快速回滚到上一个稳定状态，并记录回滚事件
