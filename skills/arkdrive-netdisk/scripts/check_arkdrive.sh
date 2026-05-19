#!/bin/bash

ARKDRIVE_MOUNT_PATH="/root/.openclaw/workspace/arkdrive_uploads"

# Check if the mount point directory exists
if [ ! -d "$ARKDRIVE_MOUNT_PATH" ]; then
    echo "ArkDrive 未启用"
    echo "目录 $ARKDRIVE_MOUNT_PATH 不存在。"
    echo ""
    echo "请："
    echo "1. 如果还未购买 ArkDrive 网盘，请联系企业管理员购买"
    echo "2. 如果已经购买了 ArkDrive 网盘，请您自己在 ArkClaw 网页端为此实例启用"
    exit 0
fi

# Check if it's mounted with a FUSE file system
# We use mount command and grep for FUSE types (fuse., fuse.fsx, etc.)
if mount | grep -q " on $ARKDRIVE_MOUNT_PATH type fuse"; then
    # Get the file system type
    fs_type=$(mount | grep " on $ARKDRIVE_MOUNT_PATH type fuse" | awk '{print $5}')
    echo "ArkDrive 已启用并已挂载"
    echo "挂载路径: $ARKDRIVE_MOUNT_PATH"
    echo "文件系统类型: $fs_type"
    exit 0
fi

# If we reach here, directory exists but is not mounted
echo "ArkDrive 未启用"
echo "目录 $ARKDRIVE_MOUNT_PATH 存在，但未挂载 FUSE 文件系统。"
echo ""
echo "请："
echo "1. 如果还未购买 ArkDrive 网盘，请联系企业管理员购买"
echo "2. 如果已经购买了 ArkDrive 网盘，请您自己在 ArkClaw 网页端为此实例启用"
exit 0
