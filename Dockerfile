# 修复依赖问题的Dockerfile
FROM hamgua/alpha-trading-bot-okx:base_alpine-v1.5.2

# 设置时区
ENV TZ=Asia/Shanghai

# 创建非root用户提高安全性
RUN mkdir -p /app/logs /app/data_json /app/data

# 设置工作目录
WORKDIR /app

# 复制项目文件
COPY  . .

# 设置Python路径
ENV PYTHONPATH=/app

# 健康检查 - 验证程序可以启动
#HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
#     CMD python -c "from alpha_trading_bot import create_bot; print('✅ 模块导入成功')" || exit 1

# 使用exec形式确保信号传递
ENTRYPOINT ["python", "main.py"]

# docker 构建业务镜像命令
# docker buildx build --platform linux/amd64 --no-cache -t hamgua/alpha-trading-bot-okx:v3.0.9 -f Dockerfile ./
# docker push hamgua/alpha-trading-bot-okx:v3.0.9