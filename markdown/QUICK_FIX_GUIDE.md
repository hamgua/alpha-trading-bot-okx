# 快速修复指南

## 🚨 依赖问题快速修复

### 问题：Docker 启动时报 `No module named 'dotenv'`

## 快速解决方案

### 方案1：使用修复后的配置（推荐）

1. **使用修复后的 docker-compose 文件**：
   ```bash
   docker-compose -f docker-compose.fixed.yml up -d
   ```

2. **查看日志确认修复**：
   ```bash
   docker-compose -f docker-compose.fixed.yml logs -f
   ```

### 方案2：构建新镜像

1. **一键构建脚本**：
   ```bash
   # 构建并推送镜像
   ./build_and_push.sh all

   # 使用新镜像
   docker-compose up -d
   ```

### 方案3：本地验证

1. **测试基础镜像**：
   ```bash
   docker run --rm hamgua/alpha-trading-bot-okx:v3.0.9 python -c "import dotenv; print('✅ Fixed')"
   ```

## 🐳 Docker 命令速查

### 查看容器状态
```bash
docker ps
docker-compose ps
```

### 查看日志
```bash
# 查看实时日志
docker-compose logs -f

# 查看最后100行日志
docker-compose logs --tail=100
```

### 重启服务
```bash
docker-compose restart
```

### 清理并重新启动
```bash
docker-compose down
docker-compose up -d
```

## 🔧 故障排查

### 1. 检查镜像依赖
```bash
# 进入容器检查
docker exec -it alpha-trading-bot-okx bash
python -c "import dotenv, ccxt, numpy; print('All OK')"
```

### 2. 检查环境变量
```bash
docker exec -it alpha-trading-bot-okx env | grep PYTHON
```

### 3. 检查文件权限
```bash
docker exec -it alpha-trading-bot-okx ls -la /app/
```

## 📋 验证清单

- [ ] 容器成功启动
- [ ] 日志无导入错误
- [ ] 健康检查通过
- [ ] 版本命令正常

## 🆘 紧急恢复

如果新镜像有问题，可以回退到本地运行：

```bash
# 停止Docker容器
docker-compose down

# 使用本地虚拟环境运行
./run.sh --help
```

## 📞 获取帮助

1. 查看详细日志：`docker-compose logs -f`
2. 检查构建文档：`DOCKER_DEPENDENCY_FIX.md`
3. 验证镜像：`docker run --rm <image> --version`

---

**注意**：修复后的镜像版本为 `v3.0.9`，基础镜像版本为 `base_alpine-v1.5.1`