#!/bin/bash
# ArkClaw Workspace Backup Script
# 自动备份到 GitHub

set -e

echo "=== ArkClaw Backup Script ==="
echo "Started at: $(date)"

# 设置 GitHub Token（从文件读取）
TOKEN_FILE="$HOME/.github_token"
if [ -f "$TOKEN_FILE" ]; then
    export GITHUB_TOKEN=$(cat "$TOKEN_FILE")
else
    echo "Error: Token file not found at $TOKEN_FILE"
    exit 1
fi

if [ -z "$GITHUB_TOKEN" ]; then
    echo "Error: GITHUB_TOKEN is empty"
    exit 1
fi

# 配置 Git 使用 Token
cd /root/.openclaw/workspace

# 设置远程 URL 包含 Token
REMOTE_URL="https://lin11051105:${GITHUB_TOKEN}@github.com/lin11051105/Arkclaw-backup.git"
git remote set-url origin "$REMOTE_URL"

# 添加所有更改
echo "Adding changes..."
git add -A

# 检查是否有更改需要提交
if git diff --cached --quiet; then
    echo "No changes to commit"
else
    # 提交更改
    echo "Committing changes..."
    git commit -m "Auto backup: $(date '+%Y-%m-%d %H:%M:%S')"
fi

# 推送到 GitHub
echo "Pushing to GitHub..."
git push origin master

echo "Backup completed at: $(date)"
