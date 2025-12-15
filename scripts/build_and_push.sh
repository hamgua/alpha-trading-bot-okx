#!/bin/bash
# Alpha Trading Bot Docker 镜像构建和推送脚本

set -e

echo "==================================="
echo "Alpha Trading Bot Docker 构建脚本"
echo "==================================="

# 配置
PLATFORM="linux/amd64"
BASE_IMAGE="hamgua/alpha-trading-bot-okx:base_alpine-v1.5.1"
APP_IMAGE="hamgua/alpha-trading-bot-okx:v3.0.9"

# 函数：构建基础镜像
build_base_image() {
    echo "构建基础镜像..."
    docker buildx build \
        --platform $PLATFORM \
        --no-cache \
        -t $BASE_IMAGE \
        -f Dockerfile_base.alpine.fixed \
        ./
}

# 函数：推送基础镜像
push_base_image() {
    echo "推送基础镜像..."
    docker push $BASE_IMAGE
}

# 函数：构建应用镜像
build_app_image() {
    echo "构建应用镜像..."
    docker buildx build \
        --platform $PLATFORM \
        --no-cache \
        -t $APP_IMAGE \
        -f Dockerfile.fixed \
        ./
}

# 函数：推送应用镜像
push_app_image() {
    echo "推送应用镜像..."
    docker push $APP_IMAGE
}

# 函数：测试镜像
test_image() {
    echo "测试应用镜像..."
    docker run --rm $APP_IMAGE --version
}

# 主函数
main() {
    # 检查 Docker 是否运行
    if ! docker info > /dev/null 2>&1; then
        echo "错误: Docker 未运行"
        exit 1
    fi

    # 检查参数
    if [[ "$1" == "build" ]]; then
        build_base_image
        build_app_image
    elif [[ "$1" == "push" ]]; then
        push_base_image
        push_app_image
    elif [[ "$1" == "all" ]]; then
        build_base_image
        push_base_image
        build_app_image
        push_app_image
        test_image
    elif [[ "$1" == "test" ]]; then
        test_image
    else
        echo "用法: $0 {build|push|all|test}"
        echo ""
        echo "  build  - 构建镜像"
        echo "  push   - 推送镜像到仓库"
        echo "  all    - 构建并推送镜像"
        echo "  test   - 测试应用镜像"
        echo ""
        echo "示例:"
        echo "  $0 build    # 只构建镜像"
        echo "  $0 all      # 完整流程：构建+推送+测试"
        exit 1
    fi

    echo ""
    echo "==================================="
    echo "操作完成！"
    echo "==================================="
}

# 运行主函数
main "$@"