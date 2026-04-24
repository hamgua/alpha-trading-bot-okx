#!/bin/bash
set -euo pipefail

# Gemini 配置级回滚辅助脚本（仅生成建议配置，不直接修改 .env）

MODE="${1:-single}"

echo "==================================="
echo "Gemini 回滚配置建议"
echo "==================================="

if [[ "$MODE" == "single" ]]; then
  cat <<'EOF'
AI_MODE=single
AI_DEFAULT_PROVIDER=deepseek
EOF
elif [[ "$MODE" == "fusion" ]]; then
  cat <<'EOF'
AI_MODE=fusion
AI_FUSION_PROVIDERS=deepseek,kimi
AI_FUSION_WEIGHTS=deepseek:0.5,kimi:0.5
EOF
else
  echo "用法: $0 [single|fusion]"
  exit 1
fi

echo ""
echo "说明:"
echo "1) 将上述配置写入受控环境变量或密钥系统"
echo "2) 重启服务后执行健康检查"
echo "3) 在 SECURITY_REMEDIATION_LEDGER.md 记录回滚事件"
