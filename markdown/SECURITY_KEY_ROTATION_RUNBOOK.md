# 密钥轮换与泄漏处置流程（Gemini）

## 适用范围

- `GEMINI_API_KEY`
- `GOOGLE_API_KEY`
- 其他 AI Provider 密钥（可复用同流程）

## 触发条件

1. gitleaks/pre-commit/CI 检测到疑似泄漏
2. 云厂商告警提示密钥异常调用
3. 人工审计确认密钥出现在日志、工单、截图或代码仓库

## 应急处置（P0）

1. **立即冻结/吊销** 泄漏 key
2. 生成新 key（最小权限 + 来源限制）
3. 在密钥管理系统更新 `GOOGLE_API_KEY`（优先）
4. 重启机器人实例并验证健康检查
5. 检查过去 24h 调用与账单异常

## 配置回滚（保障交易连续性）

若 Gemini 恢复不及时，执行：

```bash
AI_MODE=single
AI_DEFAULT_PROVIDER=deepseek
```

或在融合模式移除 Gemini：

```bash
AI_MODE=fusion
AI_FUSION_PROVIDERS=deepseek,kimi
AI_FUSION_WEIGHTS=deepseek:0.5,kimi:0.5
```

## 审计记录模板

- 事件编号：
- 发现时间（UTC+8）：
- 泄漏来源：
- 影响范围：
- 旧 key 吊销时间：
- 新 key 生效时间：
- 回滚是否执行：
- 复盘结论与预防动作：

## 长期治理

1. 轮换周期：30~60 天
2. 强制启用 pre-commit + CI 密钥扫描
3. 禁止在日志中输出完整响应体/密钥字段
4. 发布前执行依赖漏洞扫描与 SBOM 校验
