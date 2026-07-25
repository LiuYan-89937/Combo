#!/bin/bash
# 测试打包后的应用是否正常工作

set -e

APP_PATH="$1"
if [ -z "$APP_PATH" ]; then
    echo "用法: $0 <FastAgentFactory.app 路径>"
    exit 1
fi

if [ ! -d "$APP_PATH" ]; then
    echo "错误: 应用路径不存在: $APP_PATH"
    exit 1
fi

echo "=== 测试打包后的应用 ==="
echo "应用路径: $APP_PATH"
echo ""

# 1. 检查应用结构
echo "1. 检查应用结构..."
if [ -d "$APP_PATH/Contents/Resources/python" ]; then
    echo "✓ Python 运行时存在"
else
    echo "✗ Python 运行时缺失"
    exit 1
fi

if [ -d "$APP_PATH/Contents/Resources/web_frontend" ]; then
    echo "✓ web_frontend 存在"
else
    echo "✗ web_frontend 缺失"
    exit 1
fi

if [ -d "$APP_PATH/Contents/Resources/.agentfactory" ]; then
    echo "✓ .agentfactory 存在"
else
    echo "✗ .agentfactory 缺失"
    exit 1
fi

# 2. 检查 Python 可执行文件
echo ""
echo "2. 检查 Python 可执行文件..."
PYTHON_BIN="$APP_PATH/Contents/Resources/python/bin/python3"
if [ -x "$PYTHON_BIN" ]; then
    echo "✓ Python 可执行"
    PYTHON_VERSION=$("$PYTHON_BIN" --version)
    echo "  版本: $PYTHON_VERSION"
else
    echo "✗ Python 不可执行"
    exit 1
fi

# 3. 检查 Python 依赖
echo ""
echo "3. 检查 Python 依赖..."
SITE_PACKAGES="$APP_PATH/Contents/Resources/python/lib/python3.11/site-packages"
REQUIRED_PACKAGES=("fastapi" "uvicorn" "langchain" "langgraph" "pydantic")

for pkg in "${REQUIRED_PACKAGES[@]}"; do
    if [ -d "$SITE_PACKAGES/$pkg" ]; then
        echo "✓ $pkg"
    else
        echo "✗ $pkg 缺失"
        exit 1
    fi
done

# 4. 检查应用大小
echo ""
echo "4. 应用大小..."
APP_SIZE=$(du -sh "$APP_PATH" | cut -f1)
echo "  总大小: $APP_SIZE"

# 5. 检查符号链接（应该没有）
echo ""
echo "5. 检查符号链接..."
SYMLINK_COUNT=$(find "$APP_PATH/Contents/Resources/python" -type l 2>/dev/null | wc -l)
if [ "$SYMLINK_COUNT" -eq 0 ]; then
    echo "✓ 没有符号链接"
else
    echo "⚠ 发现 $SYMLINK_COUNT 个符号链接"
fi

echo ""
echo "=== 所有检查通过 ==="
