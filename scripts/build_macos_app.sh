#!/bin/bash
# macOS 应用打包脚本
# 处理 .git 目录权限问题

set -e

echo "=== FastAgentFactory macOS 打包 ==="
echo ""

# 1. 临时移动 .git 目录
GIT_BACKUP_DIR="/tmp/fastagent_git_backup_$$"
mkdir -p "$GIT_BACKUP_DIR"

echo "1. 临时备份 .git 目录..."
if [ -d ".agentfactory/mcp/web_search/.git" ]; then
    mv .agentfactory/mcp/web_search/.git "$GIT_BACKUP_DIR/"
    echo "  ✓ 已备份 .agentfactory/mcp/web_search/.git"
fi

# 2. 执行打包
echo ""
echo "2. 开始打包..."
cd src-tauri
if cargo tauri build; then
    echo "  ✓ 打包成功"
    BUILD_SUCCESS=true
else
    echo "  ✗ 打包失败"
    BUILD_SUCCESS=false
fi
cd ..

# 3. 恢复 .git 目录
echo ""
echo "3. 恢复 .git 目录..."
if [ -d "$GIT_BACKUP_DIR/.git" ]; then
    mv "$GIT_BACKUP_DIR/.git" .agentfactory/mcp/web_search/
    echo "  ✓ 已恢复 .agentfactory/mcp/web_search/.git"
fi
rm -rf "$GIT_BACKUP_DIR"

# 4. 报告结果
echo ""
if [ "$BUILD_SUCCESS" = true ]; then
    echo "=== 打包完成 ==="
    echo ""
    echo "应用路径:"
    ls -lh src-tauri/target/release/bundle/macos/*.app 2>/dev/null || true
    echo ""
    echo "DMG 路径:"
    ls -lh src-tauri/target/release/bundle/dmg/*.dmg 2>/dev/null || true
    exit 0
else
    echo "=== 打包失败 ==="
    exit 1
fi
