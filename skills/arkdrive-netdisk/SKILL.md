---
name: "arkdrive-netdisk"
description: 检测并管理挂载在 /root/.openclaw/workspace/arkdrive_uploads 的 ArkDrive 网盘。当需要将文件保存到 ArkDrive 网盘持久化存储或检查 ArkDrive 网盘是否启用并挂载时使用此技能。
metadata:
  version: "1.0.3"
  openclaw:
    emoji: "☁️"
    requires: { "bins": ["mount", "grep"] }
---

# ArkDrive 网盘 技能

此技能帮助你检测和使用挂载在工作区内的 ArkDrive 网盘。

## 什么是 ArkDrive

ArkDrive 是 ArkClaw 提供的专用网盘服务。启用后，它会在 `/root/.openclaw/workspace/arkdrive_uploads` 挂载一个 FUSE 文件系统，为你的文件提供持久化存储。

## 何时使用

当用户要求执行以下操作时使用此技能：
- "检查 ArkDrive 是否可用"
- "检查网盘是否可用"
- "把这个文件保存到 ArkDrive"
- "将文件存储到网盘"
- "检查网盘是否已启用"
- "把目录备份到网盘"

## 检测逻辑

ArkDrive 通过检查 `/root/.openclaw/workspace/arkdrive_uploads` 是否挂载了 FUSE 文件系统来检测。

**重要提示：**
- 目录 `/root/.openclaw/workspace/arkdrive_uploads` 可能存在但**未挂载**——这只是一个空的本地目录，应视为 ArkDrive**未启用**
- 只有当该路径挂载了 FUSE 文件系统时，ArkDrive 才被视为活跃状态
- 如果未挂载，用户需要联系管理员购买 ArkDrive 或在 ArkClaw 实例网页端启用

## 指令

### 1. 检查 ArkDrive 状态

运行此脚本检查 ArkDrive 是否已启用并挂载：

```bash
scripts/check_arkdrive.sh
```

**已挂载时的输出示例：**
```text
ArkDrive 已启用并已挂载
挂载路径: /root/.openclaw/workspace/arkdrive_uploads
文件系统类型: fuse
```

**未挂载时的输出示例：**
```text
ArkDrive 未启用
目录 /root/.openclaw/workspace/arkdrive_uploads 存在，但未挂载 FUSE 文件系统。

请：
1. 如果还未购买 ArkDrive 网盘，请联系企业管理员购买
2. 如果已经购买了 ArkDrive 网盘，请您自己在 ArkClaw 网页端为此实例启用
```

### 2. 保存文件到 ArkDrive

确认 ArkDrive 已挂载后，你可以直接将文件保存到 `/root/.openclaw/workspace/arkdrive_uploads`。

**复制文件：**
```bash
cp source_file.txt /root/.openclaw/workspace/arkdrive_uploads/
```

**直接写入 ArkDrive：**
```bash
echo "内容" > /root/.openclaw/workspace/arkdrive_uploads/output.txt
```

**创建目录：**
```bash
mkdir -p /root/.openclaw/workspace/arkdrive_uploads/my_folder
```

### 3. 反馈

向用户反馈文件存储位置时，报告 ArkDrive 内的路径：

**反馈示例：**
> "文件已成功保存到 ArkDrive。
> **路径：** my_folder/source_file.txt"

### 4. 如果 ArkDrive 未启用该怎么办

如果脚本报告 ArkDrive 未启用，你**必须**：
1. 告知用户 ArkDrive 不可用
2. 说明：
   - 如果还未购买 ArkDrive 网盘，需要联系企业管理员先购买
   - 如果已经购买了 ArkDrive 网盘，需要用户自行在 ArkClaw 网页端为此实例启用

## 特殊文件说明

ArkDrive 网盘根目录下有一个默认的状态记录文件：`._arkdrive_lock`

**关于此文件的重要说明：**
- 这是一个空的状态记录文件，用于 ArkDrive 内部使用
- **禁止对外暴露**此文件，在列出网盘内容时应过滤掉此文件
- **禁止修改或删除**此文件，这可能导致 ArkDrive 功能异常
- 在向用户展示文件列表、统计文件数量或提供文件相关反馈时，应完全忽略此文件
