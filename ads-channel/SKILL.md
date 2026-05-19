---
name: ads-channel
description: "广告渠道操作抽象层：跨渠道广告创建、暂停、预算调整、参数更新、素材上传、数据查询"
metadata:
  hermes:
    tags: [ua, ads, campaign, facebook, budget, creative]
    related_skills: [dap-ua, campaign-builder, auto-optimizer, creative-lifecycle]
---

# 广告渠道操作抽象层

**与 dap-ua 的分工**：dap-ua 负责数据查询（只读），ads-channel 负责广告操作（写操作 + 实体查询）。

**支持渠道**：✅ Facebook/Meta | 🔜 TikTok（待实现）| 🔜 Google（待实现）

## CLI 命令

所有命令从项目根目录执行：
```bash
python3 workspace/skills/ads-channel/scripts/cli.py <command> [options]
```

### 查询类（自动执行）

| 命令 | 说明 | 示例 |
|------|------|------|
| `account-info` | 当前账户信息（余额/状态） | `account-info` |
| `account-info --all` | 列出 token 下所有账户 | `account-info --all --name ROK` |
| `list-campaigns` | Campaign 列表 | `list-campaigns --account-id act_xxx --limit 20` |
| `list-adsets` | AdSet 列表 | `list-adsets --campaign-id 123` |
| `list-ads` | Ad 列表（含 creative_id）**查 creative_id 首选此命令** | `list-ads --account-id act_xxx --limit 20` |
| `get-insights` | Insights 数据 | `get-insights --date-start 2026-04-01 --date-end 2026-04-15 --level campaign` |
| `get-status` | **查看实体完整信息的标准命令**。`--type campaign` 一次返回 Campaign + 全部 AdSet + 全部 Ad + Creative 完整层级，结果含 `campaign_url`（Ads Manager 直链）**必须贴给用户**，无需再拼 list-adsets/list-ads；`--type adset` 返回 AdSet 全字段；`--type ad` 返回 Ad + Creative 详情。详细 schema 见 `channel-adapters/facebook.md#get-status` | `get-status --entity-id 123 --type campaign` |
| `resolve-app` | 解析 apps.json | `resolve-app --project ROK --os iOS` |
| `list-apps` | 列出所有项目 | `list-apps` |
| `get-promoted-object` | 反查推广对象 | `get-promoted-object --limit 20` |

### 创建类（默认 PAUSED，不产生消耗）

> **为已有 Campaign 添加 AdSet / 为已有 AdSet 添加 Ad → 用 `update-entity`**（见下方修改/扩展类），系统根据 `--type` 和 `--params` 自动判断创建 vs 更新，自动处理 promoted_object 解析和跨 OS creative 适配。

| 命令 | 说明 | 示例 |
|------|------|------|
| `create-campaign` | 创建新 Campaign（无已有 Campaign 时使用） | `create-campaign --account-id act_xxx --name ROK_US_test --budget 500` |
| `duplicate-adset` | 复制 AdSet 到目标 Campaign | `duplicate-adset --account-id act_xxx --source-id 456 --target-campaign 123 --name "NewName" --budget 100` |

**`duplicate-adset` 注意事项（2026-05 修复）**：
- `--name` 可选，指定新 adset 名称（默认: 源名称_dup）
- **CBO campaign 自动跳过 budget**：源 adset 无 daily_budget 时不传预算（由 campaign 层控制），避免 Meta 报"预算过低"
- **直接透传源 targeting**：不再拆解/重组 targeting（旧逻辑丢失 `user_os`、`user_device`、`flexible_spec`、`targeting_automation` 等字段导致 OS mismatch 报错），整体透传确保完整
- **自动透传 `regional_regulated_categories`**：如源 adset 含合规声明（如 `SINGAPORE_UNIVERSAL`），自动复制到新 adset
- ⚠️ `duplicate-adset` 只复制 adset 定向参数，**不复制 ad**，需手动创建

### 修改/扩展类（按决策分级执行）

| 命令 | 说明 | 示例 |
|------|------|------|
| `update-entity` | **统一入口**：更新参数 / 创建子实体（自动判断） | 见下方详细说明 |
| `batch-update` | 批量更新 | `batch-update --entity-ids 123,456 --type adset --params '{"status":"PAUSED"}'` |

### 批量替换广告素材（Ad Creative 换视频）

当需要批量替换 Ad 中的视频（如换尺寸版本），流程如下：

**步骤**：
1. 从 DAP `get_material_detail(dap_id)` 获取 `download_url`（字段名是 `download_url`，不是 `video_url`）
2. 用 `upload_video_from_url(client, file_url=url, name=name)` 上传到 FB → 获得 `video_id`
3. 读取旧 Ad 的 `AdCreative.object_story_spec` → 提取 `message`, `title`, `image_hash`, `image_url`, `instagram_user_id`
4. 创建新 AdCreative，**必须带 `image_hash`**（或 `image_url`），否则 API 报错 1443226（"你的广告缺少视频缩略图"）
5. `Ad.api_update(params={"creative": {"creative_id": new_id}})` 更新广告

**关键坑点**：
- ⚠️ **视频缩略图必填**：`create_ad_creative` 的 `video_data` 中必须指定 `image_hash` 或 `image_url`，否则返回 400 (error_subcode=1443226)。最简单的做法是复用旧 creative 的 `image_hash`
- ⚠️ **DAP detail 的视频字段**：视频下载链接在 `download_url` 字段，`video_url` 和 `preview_url` 通常为空
- ⚠️ **DAP GET 请求不能带 Content-Type**：`get_material_detail` 是 GET 请求，带 `Content-Type: application/json` 会导致 DAP 返回 400（已在 `dap_client.py` 中修复）

**Facebook 主文案长度**：primary text（message）超过约 125 字符会被折叠显示 "...展开/See more"。安全阈值建议控制在 100 字符以内，最多 2-3 句话。

```python
# 批量替换示例骨架
from facebook.creative_manager import upload_video_from_url
from facebook_business.adobjects.adcreative import AdCreative
from facebook_business.adobjects.ad import Ad

# 1. Upload new video
result = upload_video_from_url(fb_client, file_url=dap_download_url, name=material_name)
new_video_id = result["video_id"]

# 2. Read old creative (preserve message/title/thumbnail)
old_creative = AdCreative(old_creative_id)
old_creative.api_get(fields=[AdCreative.Field.object_story_spec])
spec = old_creative["object_story_spec"]
vd = spec["video_data"]

# 3. Create new creative with old thumbnail + new video
video_data = {
    "video_id": new_video_id,
    "call_to_action": vd["call_to_action"],
    "message": new_message,  # keep or shorten
    "title": vd["title"],
    "image_hash": vd["image_hash"],  # REQUIRED — reuse old thumbnail
}
new_creative = fb_client.account.create_ad_creative(params={
    "name": f"{vd['title']} replaced",
    "object_story_spec": {"page_id": spec["page_id"], "video_data": video_data},
})

# 4. Update ad
Ad(ad_id).api_update(params={"creative": {"creative_id": new_creative["id"]}})
```

### 缩略图更新（直接 API，CLI 不支持）

CLI 不支持缩略图更新，需直接调用 Meta Graph API。

**流程**：

1. **获取视频可选缩略图列表**：
   ```
   GET /{video_id}/thumbnails → data[].{id, uri, width, height, is_preferred}
   ```
   每个视频通常有 ~20 个自动生成的缩略图。

2. **选择最佳缩略图**：
   - 下载缩略图到本地（`/tmp/` 目录）
   - 用 Pillow 拼成带序号的 montage（`Image.new` + `paste` + `ImageDraw.text`）
   - 用 Vision AI 分析选择最佳：构图清晰、色彩鲜明、动作感强、小尺寸可读
   - ⚠️ ImageMagick `montage` 命令在环境中不可用，必须用 Pillow

3. **更新 Ad creative 的缩略图**：
   ```python
   # 获取 Ad 的 object_story_spec
   # GET /{ad_id}?fields=creative{object_story_spec}

   # ⚠️ 关键：必须删除 image_hash，只保留 image_url
   video_data.pop('image_hash', None)
   video_data['image_url'] = thumb_uri  # 从 thumbnails API 获取的 uri

   # POST /{ad_id}  creative={"object_story_spec": updated_oss}
   ```

   **坑点**：如果同时传 `image_url` 和 `image_hash`，API 报错"只应该在 video_data 字段内指定 image_url 和 image_hash 中的一个"。

4. **批量更新**：同一 video_id 的多条 Ad（跨 AdSet）共享同一缩略图选择。按 video_id 分组，逐条更新 Ad。

### 复制 Campaign（含 AdSet + Ad）到新定向

当需要复制整个 Campaign 结构但修改定向（如 WW排除 → 正向定向），CLI 的 `duplicate-adset` 不复制 Ad，需要手动三步走：

**步骤**：
1. 创建空壳 Campaign（`create-campaign`）
2. 用 SDK 创建 AdSet（CLI `create-adset` 不支持 `bid_constraints` 等高级参数）
3. 用 SDK 批量创建 Ad（CLI `create-ad` 会用默认账户，需显式指定 `account_id`）

**⚠️ 正向定向国家的 Meta API 坑点（实测 2026-05）**：

- **TH（泰国）要求 age_min ≥ 20**：错误码 1870249「所选定位选项无法用于青少年受众」。含 TH 时必须 `age_min: 20`。WW 排除模式不受此限制，改正向定向才会触发
- **SG（新加坡）需要合规声明**：错误码 3858550。要么传 `compliance_section: SINGAPORE_UNIVERSAL`，要么从国家列表去掉 SG
- **RU（俄罗斯）被平台限制**：创建直接报错，从国家列表去掉
- **app_install_state 与年龄限制冲突**：即使不传 age，含 TH 时 `app_install_state` 也会触发 1870249。去掉该字段或确保 age_min ≥ 20
- **VO 出价必须带 bid_constraints**：`optimization_goal: VALUE` 必须同时传 `bid_constraints: {roas_average_floor: N}`，N = 出价值 × 100（如 0.15 → 15）。不传则报错 2490487
- **CLI create-adset 不支持 bid_constraints**：CLI 会丢掉该参数，直接用 SDK
- **CLI create-ad 用默认账户**：Ad 会创建到 `META_AD_ACCOUNT_ID`（.env 中的默认账户），需用 SDK 显式传 `account_id`

**SDK 创建 AdSet 示例**（含 VO 出价 + 正向定向）：
```python
from facebook.client import MetaAdsClient
client = MetaAdsClient(account_id='act_xxx')

result = client.account.create_ad_set(params={
    'campaign_id': '<campaign_id>',
    'name': 'XXX_VO_Top40_9x16',
    'targeting': {
        'age_min': 20,  # TH 要求
        'age_max': 65,
        'device_platforms': ['mobile'],
        'geo_locations': {
            'countries': ['US', 'DE', 'KR', ...],  # 去掉 SG/RU
            'location_types': ['home', 'recent']
        },
        'targeting_automation': {'advantage_audience': 1},
        'user_os': ['Android']
    },
    'optimization_goal': 'VALUE',
    'billing_event': 'IMPRESSIONS',
    'destination_type': 'APP',
    'promoted_object': {
        'application_id': '<app_id>',
        'custom_event_type': 'PURCHASE',
        'object_store_url': '<store_url>'
    },
    'bid_constraints': {'roas_average_floor': 15},  # 0.15 × 100
    'status': 'PAUSED'
})
```

**SDK 批量创建 Ad**：
```python
# ⚠️ 先从原 AdSet 实时读取 Ad 的 creative_id
from facebook_business.adobjects.adset import AdSet
adset = AdSet('<original_adset_id>')
adset['account_id'] = 'act_xxx'
ads = adset.get_ads(fields=['id', 'name', 'creative', 'status'])
for ad in ads:
    real_creative_id = ad['creative']['id']  # 用实时值，不要用缓存的 ID

# 创建 Ad
result = client.account.create_ad(params={
    'adset_id': '<new_adset_id>',
    'name': '<ad_name>',
    'creative': {'creative_id': '<creative_id>'},
    'status': 'PAUSED'
})
# 部分 creative_id 可能已失效（返回 1487015 "广告创意无效"），跳过即可
```

⚠️ **creative_id 必须从 Ad 对象实时读取**：不要依赖之前缓存或记录的 creative_id。Meta 后台可能重建 creative（ID 变化），只有从 `ad['creative']['id']` 实时获取的才可靠。

### CBO 切换（Campaign 级预算 ↔ AdSet 级预算）

从 AdSet 级预算切到 CBO：直接对 Campaign 设置 `daily_budget`，AdSet 预算自动清除。
```python
# POST /{campaign_id}  data={daily_budget: 50000}  # cents
```
无需手动清除 AdSet 预算（设 0 会报错"预算过低"）。

#### update-entity 自动判断：更新 vs 创建

系统根据 `--type` 和 `--params` 内容自动判断操作类型，无需额外标记：

| 条件 | 行为 | entity-id 含义 |
|------|------|---------------|
| `--type adset` + params 含 `name` + (`--os`/`--project` 或 `countries`) | **创建 AdSet** | campaign_id（父实体） |
| `--type ad` + params 含顶层 `creative_id` | **创建 Ad** | adset_id（父实体） |
| 其余情况 | **更新** 已有实体参数 | 实体本身 ID |

**更新已有实体**（params 不含创建信号）：

```bash
# 暂停 Campaign
update-entity --entity-id 123 --type campaign --params '{"status": "PAUSED"}'
# 改 AdSet 预算
update-entity --entity-id 456 --type adset --params '{"daily_budget": 500}'
# 换素材（同 OS）— creative 嵌套 dict 格式
update-entity --entity-id 789 --type ad --params '{"creative": {"creative_id": "xxx"}}'
# 换素材（跨 OS 适配）— creative 嵌套 dict + --os/--project
update-entity --entity-id 789 --type ad --params '{"creative": {"creative_id": "xxx"}}' --os Android --project ROK
```

**创建 AdSet**（params 含 `name` + OS/countries）：

```bash
# entity-id = campaign_id，自动注入。--os + --project 自动解析 promoted_object
update-entity --entity-id <campaign_id> --type adset \
  --os Android --project ROK \
  --params '{"name": "ROK_Android_US", "daily_budget": 50, "countries": ["US"]}'
```

**创建 Ad**（params 含顶层 `creative_id`，非嵌套 `creative` dict）：

```bash
# entity-id = adset_id，自动注入。--os + --project 自动适配 creative 平台
update-entity --entity-id <adset_id> --type ad \
  --os Android --project ROK \
  --params '{"name": "ROK_Android_Ad", "creative_id": "<ios_creative_id>"}'
```

**典型场景：已有 iOS Campaign，为同一 Campaign 添加 Android 组**

```bash
# 1. 创建 Android AdSet（type=adset + name + --os → 创建模式）
update-entity --entity-id <campaign_id> --type adset \
  --os Android --project ROK \
  --params '{"name": "ROK_Android_US", "daily_budget": 50, "countries": ["US"]}'
# → {"adset_id": "xxx", "status": "PAUSED"}

# 2. 创建 Ad 并自动适配 creative（type=ad + creative_id → 创建模式）
update-entity --entity-id <adset_id> --type ad \
  --os Android --project ROK \
  --params '{"name": "ROK_Android_Ad", "creative_id": "<ios_creative_id>"}'
# → {"ad_id": "xxx", "status": "PAUSED"}
```

### 素材库查询（无 CLI，需 Python SDK）

CLI 不支持列出/搜索素材，需直接调用 facebook-business SDK：

```python
# AdVideos — 返回 id, title, created_time, source(CDN直链)
videos = client.account.get_ad_videos(
    fields=['id', 'title', 'created_time', 'source'],
    params={'limit': 25}
)

# AdImages — 返回 id, name, hash, url, created_time
images = client.account.get_ad_images(
    fields=['id', 'name', 'hash', 'url', 'created_time'],
    params={'limit': 25}
)
```

**限制**：
- 作用域是单个 ad account（act_xxx），不是 Business Suite 的跨账户 Media Library
- 要看全部素材需逐账户遍历
- AdVideo 按 title 精确查，AdImage 按 hash 查，无模糊搜索

### 认证架构

`workspace/.env` 中三个核心变量：

**SOCIAL_FB_TOKEN** — 系统用户 "ua-agent"(122103312098782378) 的 Access Token
- 认证凭证，所有 Graph API 调用依赖此 Token
- 45项权限，含 ads_management, business_creative_management 等
- 类型: System User Token（非个人账号）

**META_BUSINESS_ID** = 1589262821285499 — Business Portfolio "Lilith Games"
- 最顶层组织容器
- 通过它访问: Media Library、Creative Folders、下属 Ad Account 列表
- 注意: 684085081667854 是代理商(脸谱网中国区总代理)，素材库为空

**META_AD_ACCOUNT_ID** = 2243882512769338 — 默认操作的广告账户
- create-* 等写操作使用此账户
- 读操作可通过 --account-id 指定其他账户
- 此 Business 下有 40+ 账户(ROK 25, AFK 17...)，这只是默认的一个

层级关系：
```
Token(ua-agent) ─授权→ Business Portfolio(META_BUSINESS_ID)
                          ├── Media Library
                          ├── Ad Account(META_AD_ACCOUNT_ID) ← 默认
                          ├── Ad Account B
                          └── ...
```

### Business Media Library（跨账户素材库）—— DAP 同步素材的真实存储

DAP 上传到 FB 的素材存储在 Business Media Library 的 Creative Folders 中。通过正确的 API 参数可以搜索定位素材并获取 `video_id`，用于创建广告。

**⚠️ 搜索 API 关键参数（2026-05 实测验证）**：

```
GET /{business_id}/creatives
参数:
  creative_folder_id: <文件夹ID>          # 必须，限定搜索范围
  filtering: [
    {"field":"name_or_content_filter","operator":"CONTAIN","value":"<加密素材名>"},
    {"field":"is_valid","operator":"EQUAL","value":true}
  ]
  fields: id,name,video_id,type           # video_id 可直接用于创建广告
```

**❌ 以下参数组合搜不到（踩坑记录）**：
- `filtering` 用 `name_or_id` 字段 → 全局搜部分素材搜不到（尤其多语言版本）
- 不传 `creative_folder_id` → 文件夹内素材可能被截断搜不到
- `folder_id` 替代 `creative_folder_id` → 行为不一致，部分场景失效
- `recursive=true` → v24.0 API 不支持（400 错误）

**文件夹 ID 获取方式**：
1. 从 DAP `get_material_detail(material_id)` 获取 `upload_fb_folder_path`（如 `日本/ja/万国觉醒/20260126-20260201/美宣自制/视频`）
2. 从 Business 根目录逐级导航：`GET /{business_id}/creative_folders` → `GET /{folder_id}/subfolders` → 按路径段名称匹配
3. ⚠️ `creative_folders` 根目录可能超 50 个，需设 `limit=200` 或翻页
4. ⚠️ 子文件夹也可能超 100 个（如 ROK EN 万国觉醒下 135+ 周文件夹），需翻页

**完整素材定位流程（DAP → FB video_id）**：
```
DAP get_material_detail(dap_id)
  → encrypted_material_name（加密命名）
  → upload_fb_folder_path（上传路径）
  ↓
逐级导航 FB creative_folders 拿到叶子文件夹 ID
  ↓
GET /{biz}/creatives?creative_folder_id=<叶子ID>&filtering=[name_or_content_filter=加密名]
  → id, name, video_id
  ↓
用 video_id 创建 AdCreative / Ad
```

**Business ID**: `1589262821285499`（Lilith Games）— DAP 素材的上传目标 Business

**Python SDK 一键解析（推荐）**：

`creative_manager.py` 内置 `resolve_video_ids()`，封装了完整的 DAP→文件夹导航→搜索流程：
```python
from facebook.client import MetaAdsClient
from facebook.creative_manager import resolve_video_ids

client = MetaAdsClient(account_id='act_xxx')
results = resolve_video_ids(client, [1096114, 1096108])
# → {1096114: {"video_id": "xxx", "fb_creative_id": "yyy", ...}, ...}
```

内部自带文件夹路径缓存（同项目/地区不重复导航）和请求间隔控制（0.3s）。

异常分级（均为可捕获异常，agent 可据此决策）：
- `MaterialNotUploaded` / `FolderNotFound` / `CreativeNotFound` — 业务错误，agent 可直接上报用户
- `RateLimitError`（来自 `client.graph_get`）— 自动重试 3 轮（30s/60s/120s）后仍失败，抛给 agent 决策（等待/降频/上报）

**注意**：高频遍历文件夹树会触发 Meta API rate limit（403），`client.graph_get()` 统一处理重试，超限后抛 `RateLimitError` 供 agent 介入。

**`client.py` 通用 HTTP 方法**（所有上层模块应通过这两个方法访问 Graph API，不要用裸 `requests`）：
- `client.graph_get(path, params)` — 单次请求，统一认证 + rate limit 重试
- `client.graph_paginate(path, params)` — 自动翻页获取全部结果

**Ad Account 级查询仍然可用**（已上架投放的素材）：
- `/{ad_account_id}/advideos` + `/adimages` — 广告 creative 实际引用的素材存储
- 适用于查找已在投放中的素材，但新上传未搭建的素材不在此
- 视频按 title 查，图片按 hash 查

**⚠️ 历史结论勘误（2026-04-27 → 2026-05-08）**：
旧结论称 Business Media Library "只是附属文件柜、不用于素材查询"——这仅适用于已在投放的素材的反查场景。对于 **DAP 新上传尚未搭建的素材**，Business Media Library 是唯一可查到 video_id 的路径。两个场景用不同路径：
- 新素材定位 video_id → Business Media Library `/{biz}/creatives`
- 已投放素材反查 → Ad Account 级 `/{act}/advideos`

### DAP 素材报告（按投放数据查）

`query_material_report`：
- `filter_material` 按素材名称模糊匹配（非 ID）
- 只能查有投放消耗的素材，返回预览 CDN 链接
- 注意检查 warnings（不匹配时静默忽略过滤条件）

### 素材上传（通过 creative-lifecycle CLI）

素材上传和 AdCreative 创建通过 `creative-lifecycle` skill 的 CLI 完成：
```bash
# 纯素材上传
python3 workspace/skills/creative-lifecycle/scripts/cli.py upload-creative --name ROK_US_en_video_v1 --file-url <URL> --asset-type video --os iOS --project ROK

# 搭建广告（自动处理 Creative 平台适配）
python3 workspace/skills/creative-lifecycle/scripts/cli.py create-ads --creative-id <ID> --name ROK_US_en_video_v1 --budget 50 --countries US --audience Broad --os Android --project ROK
```

## update-entity 参数参考

### 更新模式（默认）

| entity_type | 可修改字段 |
|-------------|-----------|
| campaign | `name`, `status`, `daily_budget`, `lifetime_budget`, `bid_strategy`, `spend_cap` |
| adset | `name`, `status`, `daily_budget`, `lifetime_budget`, `bid_amount`, `bid_strategy`, `optimization_goal` |
| ad | `name`, `status`, `creative`（格式: `{"creative_id": "xxx"}`） |

### 创建 AdSet 模式（type=adset + name + OS/countries）

--params 中可传：`name`(必填), `daily_budget`, `countries`(list), `bid_strategy`, `billing_event`, `optimization_goal`, `promoted_object`, `status`
- `--os` + `--project` 自动填充 `promoted_object` 和 `os`
- `campaign_id` 自动取 `--entity-id`

### 创建 Ad 模式（type=ad + 顶层 creative_id）

--params 中可传：`name`(必填), `creative_id`(必填), `status`
- `--os` + `--project` 自动跨 OS 适配 creative
- `adset_id` 自动取 `--entity-id`
- 区分：顶层 `"creative_id": "xxx"` 触发创建，嵌套 `"creative": {"creative_id": "xxx"}` 触发更新

金额字段（`daily_budget`, `lifetime_budget`, `spend_cap`, `bid_amount`）单位 USD，自动转 cents。

## get-insights 返回字段

固定返回：`ad_id`, `ad_name`, `campaign_id`, `campaign_name`, `date`, `spend`, `impressions`, `clicks`, `ctr`, `installs`, `cpi`, `revenue`, `actions`

参数：
- `--level`: campaign / adset / ad / account
- `--time-increment`: 1=逐日（默认），不传=聚合
- `--include-inactive`: 加上后不过滤状态（对账用）
- `--account-id`: 指定账户

## 决策分级

**自动执行**：所有只读、创建（默认 PAUSED）、暂停、降预算 ≤30%

**需确认**：恢复实体、升预算、降预算 >30%、暂停日耗 >$500 Campaign

**立即上报**：操作失败涉及消耗异常、账户封禁/政策违规

## 安全规则

1. 新建实体默认 PAUSED，不产生消耗
2. 只暂停不删除——ads-channel 不提供 delete 操作
3. 先记录再行动——操作前写 memory
4. 单次创建预算上限 $5,000
5. Token 通过环境变量注入，不暴露
6. 渠道未就绪时明确拒绝

## 渠道适配器

每个渠道的 API 映射、完整参数定义、渠道特异性见：
- Facebook: `channel-adapters/facebook.md`
- TikTok: `channel-adapters/tiktok.md`（待实现）
- Google: `channel-adapters/google.md`（待实现）
