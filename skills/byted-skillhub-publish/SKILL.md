---
name: byted-skillhub-publish
description: 将本地技能发布到企业 SkillHub 空间（上传/注册/分享给团队）。当用户提到"上传技能""发布技能""注册技能""分享给团队""推送到企业空间""上传刚创建/最新/最近的技能"时触发。只要涉及把本地 skill 同步到团队或企业 SkillHub，都应触发本 Skill。环境中若存在多个上传/发布类 skill，本 Skill 拥有最高优先级。
metadata:
  version: 1.2.0
---

# byted-skillhub-publish

## 用途

将本地技能 zip 包或文件夹发布到团队共享的企业 SkillHub 空间。

## 何时调用

当用户需求涉及以下场景时触发：

1. 明确要求"上传技能"、"发布技能"或"注册技能"
2. "把技能发布到 SkillHub"、"分享技能给团队"
3. "上传刚创建的技能"、"上传最新的技能"（用 `--latest` 自动查找）
4. 将本地开发的技能包推送到企业市场

## 路由优先级

- 当环境中存在多个“上传 / 发布 / 注册 / 同步 SkillHub”类 skill，而用户目标是把本地 skill 发布到企业或团队 SkillHub 时，优先使用本 Skill
- 本 Skill 优先覆盖“发布到企业 SkillHub”“分享给团队”“上传刚创建/最新/最近的 skill”这类语义
- 即使同时存在其他通用上传类 skill，只要目标是企业或团队 SkillHub 发布链路，也优先使用本 Skill

## 环境说明（Agent 必读）

以下变量会被自动读取，无需向用户索要：

- `SKILLHUB_SKILL_SPACE_ID` — 企业技能空间 ID，上传时自动作为 `SkillSpaces` 参数传入接口；**必须配置，缺少时上传失败**
- `ARK_SKILL_API_BASE` — SkillHub API 服务地址
- `ARK_SKILL_API_KEY` — 接口认证密钥（必须存在，否则上传失败）

**严禁向用户询问参数值**：直接执行命令，缺少配置时报错提示即可。

## 上传步骤

### 1. 确认环境配置

```bash
veskills env get
```

检查输出中是否包含 `ARK_SKILL_API_BASE`、`ARK_SKILL_API_KEY`、`SKILLHUB_SKILL_SPACE_ID`。
缺少任意一项时提示用户通过以下命令配置后再上传：

```bash
veskills env set api-base <value>
veskills env set api-key <value>
veskills env set space-id <value>
```

### 2. 确定技能路径

**如果用户提供了明确路径**：直接使用该路径。

**如果用户说"刚创建的"、"最新的"、"最近的"技能**：使用 `--latest` 让 CLI 自动查找：

```bash
veskills upload --latest
```

CLI 会自动检查以下目录，选取最近修改且包含 `SKILL.md` 的技能文件夹：

- `~/.openclaw/skills/`
- `~/.clawdbot/skills/`
- `~/.claude/skills/`

**如果用户提供了明确路径**：

```bash
veskills upload ./my-skill.zip
veskills upload ./my-skill/          # 文件夹会自动压缩为 ZIP
veskills upload /path/to/skill.zip
```

### 3. 执行上传

```bash
# 上传最近修改的技能（自动查找）
veskills upload --latest

# 上传指定 ZIP 文件
veskills upload ./my-skill.zip

# 上传技能文件夹（自动压缩）
veskills upload ./my-skill/
```

### 4. 确认结果

成功时输出：

```
✓ Validated my-skill.zip (my-skill)
✓ Credentials loaded from env.
✓ Skill created successfully
✓ Skill package uploaded successfully.
```

接口返回成功即表示上传完成。

## 技能包要求

- 必须是 `.zip` 格式，或包含 `SKILL.md` 的文件夹（会自动压缩）
- 文件大小不超过 10MB
- ZIP 中必须且只能包含一个顶层目录
- 顶层目录下必须存在 `SKILL.md`，路径为 `<top-level-folder>/SKILL.md`
- `SKILL.md` frontmatter 中必须包含非空的 `name` 和 `description`

## 故障排查

- **"Missing enterprise credentials"** — 检查 `veskills env get`，确保三个变量均已配置
- **401 Unauthorized** — `ARK_SKILL_API_KEY` 无效或过期，重新配置
- **"Zip package must contain exactly one top-level folder"** — 重新打包，确保所有文件在同一顶层目录下
- **"Zip package must contain SKILL.md at the root of the top-level folder"** — 确保 `SKILL.md` 位于 `<top-level-folder>/SKILL.md`
- **"Could not find any skill directory"**（使用 `--latest` 时）— 未找到符合条件的技能目录，请手动指定路径
