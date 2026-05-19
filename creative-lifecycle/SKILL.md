---
name: creative-lifecycle
description: "素材全生命周期管理：上传搭建、扩量判定、衰退关停、爆款盘点、库存统计、素材汇总"
metadata:
  hermes:
    tags: [ua, creative, lifecycle, upload, decay, scale]
    related_skills: [dap-ua, ads-channel]
---

# 素材全生命周期管理

## 能力说明

本 Skill 覆盖素材从入库到关停的完整生命周期：

| 能力 | 需求 | 触发方式 | 流程文件 |
|------|------|---------|---------|
| 新素材上传 & 广告搭建测试 | 1.1 | 手动（飞书指令） | [flows/upload.md](flows/upload.md) |
| 吸量/付费素材扩量上新 | 1.2 | Heartbeat（24h 后评估）+ 手动 | [flows/scale.md](flows/scale.md) |
| 素材健康评估（衰退 + 爆款 + 库存） | 1.4 / 1.6 | Heartbeat（每日）+ 手动 | [flows/creative-health.md](flows/creative-health.md) |
| 素材数据汇总 | 1.7 | 手动 + 定时 | [flows/material-summary.md](flows/material-summary.md) |

数据源分三层优先级：
1. **DAP Skill**（`call_dap` CLI）— 效果数据（消耗/CPI/ROI/安装），通过 `query_material_report` 和 `get_custom_report` 获取
2. **DAP HTTP API**（`lib/dap_client.py`）— 素材元数据（短名/语种/尺寸/多版本），工厂函数在 `_fetchers.py`：`make_search_dap_materials`、`make_find_material_versions`、`make_resolve_fb_names` 等
3. **FB SDK**（最低优先级）— 仅用于广告 CRUD 和评论拉取，不参与素材查找

## 项目选择与账户匹配

**项目选择**:
- **Heartbeat 定时**: 使用 `config/apps.json` 中配置的默认项目（当前默认 ROK）
- **手动触发**: 用户可指定项目（如"检测 PTSLG 的衰退"）；未指定时用默认项目

**账户匹配链路**:
1. 使用 `account-info --all --name <项目名>` 获取 token 下所有名称含项目名的 ad account
2. 对每个匹配的 account，使用 `--account-id <act_id>` 扫描该账户下所有活跃 Ad
3. 汇总所有匹配账户的结果

示例: `account-info --all --name ROK` → `act_972606124573616`, `act_2137002803718589` → 逐账户扫描

## 触发条件与流程路由

| 用户意图（自然语言） | 路由到 | mode |
|---------------------|--------|------|
| "上传素材"、"搭建测试" | [upload.md](flows/upload.md) | — |
| "扩量 XX 素材"、"哪些能扩量" | [scale.md](flows/scale.md) | — |
| "检测衰退"、"哪些在跌"、"素材表现差" | [creative-health.md](flows/creative-health.md) | decay |
| "爆款报告"、"盘点爆款"、"哪些素材好" | [creative-health.md](flows/creative-health.md) | winner |
| "素材健康"、"库存盘点"、"整体看看" | [creative-health.md](flows/creative-health.md) | all |
| "汇总素材数据"、"素材报告" | [material-summary.md](flows/material-summary.md) | — |

**Heartbeat 定时驱动**（每日，由 `memory/heartbeat-state.json` 跟踪上次执行时间）:
- 项目选择: 按 `config/apps.json` 中的项目列表，逐个项目串行执行
- 账户匹配: 每个项目执行前先 `account-info --all --name <项目名>` 获取关联账户
- 执行顺序: 素材健康评估（mode=all） → 扩量评估
- 素材效果评估: 上传 24h 后首次评估（由上传时记录的时间戳判断）

**被其他 Skill 调用**: creative-ai-test 完成分类后调用本 Skill 搭建测试

## 输入/输出

### 输入参数汇总

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `project_id` | string | 项目 ID | 必填 |
| `channel` | string | 渠道 | 全渠道 |
| `mode` | string | 健康评估模式（all/decay/winner） | all |
| `asset_ids[]` | string[] | 素材 ID 列表（手动指定时） | 自动获取 |
| `countries[]` | string[] | 国家列表（上传搭建用） | 必填（上传时） |
| `audience` | string | 受众类型（Broad/兴趣/重定向） | Broad |
| `budget` | number | Campaign 日预算（USD，CBO 模式，默认） | 与 `adset_budget` 二选一 |
| `adset_budget` | number | AdSet 日预算（USD，ABO 模式） | 与 `budget` 二选一 |
| `date_start` / `date_end` | string | 日期范围（短名汇总用） | 近 7 天 |

### 输出格式

| 场景 | 推送方式 | 内容 |
|------|---------|------|
| 上传完成 | 飞书通知 | Campaign/AdSet/Ad ID + 参数摘要 + `campaign_url`（Ads Manager 直链） |
| 扩量通知 | 飞书通知 | 素材列表 + 判定类型 + 目标账户 |
| 衰退检测 | 飞书 P1 告警 | 衰退/观察/跳过分类 + 逐日 CPI/ROI + conclusion + 附件下载（`decay_report_file_key`） |
| 爆款+库存 | 飞书 P2 消息 | 可用量/爆款量 + 爆款明细 + conclusion + 附件下载（`winner_report_file_key`） |
| 素材汇总 | 飞书消息 | 创意级效果报告表格 + 附件下载（`summary_report_file_key`） |
| 扩量候选 | 飞书消息 | 扩量候选列表 + 附件下载（`scale_report_file_key`） |
| 短名汇总 | 飞书消息 | 附件 JSON + 正文用 `feishu_summary`（无 `\|` 表格）；完整表在附件 `markdown` |
| 爆款+库存（分地区） | 飞书 / JSON | `winner_report.inventory_by_region` 与 `inventory_by_region_feishu`（地区维度，见下方说明） |

**分地区表现**（`--mode winner` 或 `--mode all` 时自动执行）：从 DAP `get_custom_report(table="country")` 拉取各国消耗/安装/CPI/ROI，按爆款阈值判定各国是否达标。输出字段：`inventory_by_region`（JSON，含 region/spend/installs/cpi/roi/is_hot）、`inventory_by_region_feishu`（飞书列表）。

**CLI 输出字段说明 — Hermes 回复时必须包含以下信息，无需等用户追问**：

| 字段 | 含义 | Hermes 必须做什么 |
|------|------|-----------------|
| `*_file_key` | 报告已上传飞书并自动发送至群聊 | 在飞书消息中告知用户"报告已发至群聊，点击附件即可下载" |
| `*_upload_error` | 上传/发送失败时有此字段（`*_file_key` 此时为本地路径） | 告知用户上传失败原因，并给出本地路径 |
| `campaign_url` | 广告 Ads Manager 直链 | **必须在飞书消息中贴出此 URL**，格式：`查看广告：{campaign_url}` |

⚠️ **campaign_url 不可省略**：每次广告创建成功后，必须在回复中贴出 `campaign_url`，否则用户无法在 Ads Manager 中查看广告。

## 判定规则

| 规则引擎编号 | 规则名称 | 流程文件 |
|-------------|---------|---------|
| C01 | 吸量素材扩量候选 | [scale.md](flows/scale.md) |
| C02 | 付费素材扩量候选 | [scale.md](flows/scale.md) |
| B01 | 素材衰退自动关停 | [creative-health.md](flows/creative-health.md) decay 分支 |
| C03 | 爆款素材判定 | [creative-health.md](flows/creative-health.md) winner 分支 |
| T07 | 可用素材库存不足 | [creative-health.md](flows/creative-health.md) winner 分支 |
| T08 | 爆款素材不足 | [creative-health.md](flows/creative-health.md) winner 分支 |

## 辅助脚本

所有规则计算和报告生成由 `scripts/` 下的 Python 脚本完成。

🚫 **禁止手动拉 DAP/Insights 数据再用 execute_code 处理** — 原始数据行数多，灌入上下文会导致 ReadTimeout。必须通过 CLI 调用，数据处理在本地 Python 完成，你只需读取 CLI 输出的汇总 JSON。

Agent 通过 CLI 调用脚本，读取输出 JSON，然后推飞书、等用户确认。

**CLI 入口**: `python workspace/skills/creative-lifecycle/scripts/cli.py [--chat-id <oc_xxx>] <子命令> [参数]`

⚠️ **`--chat-id` 是顶层参数，必须放在子命令之前**。

| 子命令 | 用途 | CLI 示例 |
|--------|------|---------|
| `creative-health` | 衰退+爆款+库存评估 | `cli.py --chat-id <oc_xxx> creative-health --project ROK --date 2026-04-10 --mode all` |
| `scale-candidates` | 扩量候选评估 | `cli.py --chat-id <oc_xxx> scale-candidates --project ROK --date 2026-04-10` |
| `upload-creative` | 纯素材上传（命名校验+上传→creative_id） | `cli.py upload-creative --name "ROK_US_en_video_v1" --file-url <URL或本地路径> --asset-type video --os iOS --project ROK` |
| `create-ads` | 广告搭建（两种模式，自动适配 Creative 平台） | 见下方两种模式 |
| `summary` | 素材数据汇总 | `cli.py --chat-id <oc_xxx> summary --project ROK --date-start 2026-04-03 --date-end 2026-04-10` |
| `short-name` | 素材短名规则数据汇总 | `cli.py --chat-id <oc_xxx> short-name --project ROK --date-start 2026-04-03 --date-end 2026-04-10` |

CLI 自动加载 config（apps.json + thresholds.json + naming-rules.json）、构建 DAP/ads-channel 回调、执行脚本、JSON 输出到 stdout。素材命名解析统一使用 `lib/naming.py`（校验、字段提取、短名解析），所有 naming-rules 相关逻辑不要自行实现。

**⚠️ `--chat-id` 必须传（对话场景）**：
- 从 system prompt `Source` 行读取群名或 oc_xxx，直接传给 `--chat-id`（FeishuClient 自动解析群名）
- 传了则 CLI 自动上传并发文件到该群；**不传则只上传，文件不发送**
- 定时任务（cron）不传，报告只入库不发群

### create-ads 两种素材模式

**`--creative-id` 和 `--file-url` 二选一。** 直接调 `create-ads` 即可，不要手动拆步骤。

**模式 A：传 `--creative-id`**（已有 creative）
```bash
cli.py create-ads --creative-id <ID> --name ROK_US_en_video_v1 \
  --budget 50 --countries US --audience Broad --os Android --project ROK
```
自动检查 creative 的 store URL 是否与 `--os` 匹配：
- **匹配**：直接使用该 `creative_id`
- **不匹配（OS 跨平台）**：从原 creative 的 `object_story_spec` 提取 `video_id`（视频）或 `image_hash`（图片），用目标 OS 的 store URL 自动创建新 AdCreative，透明切换，结果中会带 `creative_replaced` 字段说明替换详情
- **既无 video_id 也无 image_hash**：报错中止，需用户重新选择素材

这意味着：**你只需传 `list-ads` 里找到的任意 `creative_id`，OS 不匹配时系统会自动用同一素材新建正确平台的 creative，无需手动找 video_id。**

**模式 B：传 `--file-url`**（从零上传素材）
```bash
cli.py create-ads --file-url <URL或本地路径> --asset-type video --name ROK_US_en_video_v1 \
  --budget 50 --countries US --audience Broad --os Android --project ROK
```
一步完成：命名校验 → 上传素材 → 创建 AdCreative（自动绑定目标 OS 的 store URL）→ 搭建 Campaign/AdSet/Ad。

### 预算模式（CBO vs ABO）

**`--budget` 和 `--adset-budget` 二选一。** 默认传 `--budget`（Campaign 维度，CBO）。

| 参数 | 预算位置 | Facebook 模式 | 说明 |
|------|---------|--------------|------|
| `--budget <USD>` | Campaign | **CBO**（默认） | Campaign 统一控制预算，AdSet 不设预算 |
| `--adset-budget <USD>` | AdSet | **ABO** | 每个 AdSet 独立控制预算，Campaign 不设预算 |

```bash
# CBO（默认）：预算在 Campaign 层
cli.py create-ads --creative-id <ID> --name ROK_US_en_video_v1 \
  --budget 50 --countries US --audience Broad --os iOS --project ROK

# ABO：预算在 AdSet 层
cli.py create-ads --creative-id <ID> --name ROK_US_en_video_v1 \
  --adset-budget 50 --countries US --audience Broad --os iOS --project ROK
```

### Campaign / AdSet 可选参数

`create-ads` 所有参数均为明确的 CLI flag，无 JSON blob。除必填参数外，下列选填参数可按需覆盖默认值：

**Campaign 选填参数**：

| Flag | 默认值 | 说明 |
|------|--------|------|
| `--campaign-name` | 与 `--name` 相同 | 覆盖 Campaign 名称；不传时自动使用 `--name` 的值（已通过命名规则校验） |
| `--objective` | `OUTCOME_APP_PROMOTION` | Campaign 广告目标 |
| `--campaign-status` | `PAUSED` | Campaign 初始状态（`PAUSED`/`ACTIVE`） |

**AdSet 选填参数**：

| Flag | 默认值 | 说明 |
|------|--------|------|
| `--optimization-goal` | `APP_INSTALLS` | AdSet 优化目标 |
| `--billing-event` | `IMPRESSIONS` | AdSet 计费事件 |
| `--bid-strategy` | 无（账户默认） | 出价策略：`LOWEST_COST_WITHOUT_CAP` / `LOWEST_COST_WITH_BID_CAP` / `COST_CAP` |
| `--bid-amount` | 无 | 出价上限 USD（`bid-strategy=COST_CAP` 时使用） |
| `--adset-status` | `PAUSED` | AdSet 初始状态（`PAUSED`/`ACTIVE`） |

```bash
# 示例：指定 COST_CAP 出价策略
cli.py create-ads --creative-id <ID> --name ROK_US_en_video_v1 \
  --budget 50 --countries US --audience Broad --os iOS --project ROK \
  --bid-strategy COST_CAP --bid-amount 5.0

# 示例：覆盖 Campaign 目标
cli.py create-ads --creative-id <ID> --name ROK_US_en_video_v1 \
  --budget 50 --countries US --audience Broad --os iOS --project ROK \
  --objective OUTCOME_SALES
```

**确认表格模板**（执行前必须向用户展示）：

```
| 参数             | 值              | 来源         |
|------------------|----------------|-------------|
| name             | ROK_US_en...   | 命名规则生成  |
| creative_id      | 123456         | 用户指定     |
| campaign_budget  | $50            | 用户指定 (CBO)|
| adset_budget     | N/A            | CBO 模式不设  |
| countries        | US             | 用户指定     |
| os               | iOS            | 用户指定     |
| audience         | Broad          | 用户确认     |
| project          | ROK            | 用户指定     |
| objective        | OUTCOME_APP... | 默认值       |
| optimization_goal| APP_INSTALLS   | 默认值       |
| bid_strategy     | N/A            | 账户默认     |
```

无论哪种模式，**两个预算字段都必须在确认表格中列出**（空的写 N/A）。选填参数若用了默认值，表格中注明"默认值"；若用户显式指定，注明"用户指定"。

**设计原则**:
- 脚本通过依赖注入接收回调函数，不直接调用外部 API
- CLI 中的 `_fetchers.py` 封装 DAP subprocess 调用和 ads-channel Python import
- 所有阈值从 `config/thresholds.json` 读取，脚本内零硬编码
- 输出为 JSON（stdout + 报告文件），Agent读取后决定如何推送和交互

## 安全规则

1. **只暂停不删除**: 所有关停操作只执行暂停，永远不删除素材/广告/广告组/Campaign
2. **扩量需分级**:
   - 同账户扩量: 可自动执行
   - 跨账户/跨地区扩量: 推送建议到飞书，等待人工确认
3. **先记录再行动**: 每次自动操作前先记录到 `memory/YYYY-MM-DD.md`
4. **预算上限控制**: 测试搭建的预算不得超过模板上限
5. **指标冲突时保 ROI**: 吸量和回本冲突时，优先保护 ROI
6. **Campaign 默认暂停**: 新创建的 Campaign 默认为暂停状态，需确认后启动
