# Facebook 渠道适配器

## 依赖与环境

- **facebook-business SDK**（v25.0.1）
- **环境变量**（配置在 `workspace/.env`）：
  - `SOCIAL_FB_TOKEN` — Facebook Access Token
  - `META_AD_ACCOUNT_ID` — 广告账户 ID（act_xxx 格式）

## 代码结构

```
scripts/
├── common/               # 跨渠道公共模块
│   ├── app_config.py     # apps.json 解析（项目→promoted_object）
│   └── types.py          # 公共类型定义
├── facebook/             # Facebook 实现
│   ├── client.py         # MetaAdsClient（认证、错误处理、Rate Limit）
│   ├── config.py         # API 版本等配置
│   ├── params.py         # TypedDict 参数定义 + 默认值 + USD 转换
│   ├── campaign_manager.py  # Campaign/AdSet/Ad 创建、复制、查询
│   └── ad_manager.py     # 状态更新（暂停/恢复/批量）
└── cli.py                # 统一 CLI 入口
```

## CLI 命令参考

所有命令从项目根目录执行：

```bash
python workspace/skills/ads-channel/scripts/cli.py <command> [options]
```

### 命令列表

| 命令 | 对应意图 | 示例 |
|------|---------|------|
| `account-info` | account_info | `cli.py account-info` |
| `account-info --all` | list_accounts | `cli.py account-info --all --name ROK` |
| `list-campaigns` | list_campaigns | `cli.py list-campaigns --account-id act_xxx --limit 10` |
| `list-adsets` | list_adsets | `cli.py list-adsets --account-id act_xxx --campaign-id <id>` |
| `list-ads` | list_ads | `cli.py list-ads --account-id act_xxx --adset-id <id>` |
| `create-campaign` | create_campaign | `cli.py create-campaign --params '{"name":"ROK_US","daily_budget":500}'` |
| `create-adset` | create_adset | `cli.py create-adset --params '{"campaign_id":"<id>","name":"ROK_US","daily_budget":100,"countries":["US"],"os":"iOS","promoted_object":{"application_id":"<app_id>","object_store_url":"<url>"}}'` |
| `create-ad` | create_ad | `cli.py create-ad --params '{"adset_id":"<id>","name":"ROK_v1","creative_id":"<id>"}'` |
| `duplicate-adset` | — | `cli.py duplicate-adset --source-id <id> --target-campaign <id> --budget 100` |
| `update-status` | pause / resume | `cli.py update-status --entity-id <id> --type ad --status PAUSED` |
| `batch-update-status` | — | `cli.py batch-update-status --entity-ids <id1,id2> --type ad --status PAUSED` |
| `get-status` | — | `cli.py get-status --entity-id <id> --type campaign` |
| `resolve-app` | — | `cli.py resolve-app --project ROK --os iOS` |
| `list-apps` | — | `cli.py list-apps` |
| `get-insights` | get_insights | `cli.py get-insights --account-id act_xxx --date-start 2026-04-01 --date-end 2026-04-07` |
| `get-promoted-object` | — | `cli.py get-promoted-object --account-id act_xxx --limit 10` |

### CLI 输入模式

create 系列命令支持两种输入：

1. **JSON 模式**（推荐）：`--params '<JSON dict>'` — 传入完整参数字典，支持所有参数
2. **显式参数模式**（向后兼容）：`--name xxx --budget 100 --countries US,CA` — 逐个指定常用参数

`--params` 优先级高于显式参数。两种模式不可混用。

### promoted_object 解析

create-adset 需要 `promoted_object`（应用 ID + 商店链接），有三种方式提供：

1. **`--project ROK`** — 从 `config/apps.json` 自动解析（推荐）
2. **`--app-id <id> --store-url <url>`** — 手动指定（优先于 --project）
3. **JSON 模式直接传入** — `"promoted_object": {"application_id": "...", "object_store_url": "..."}`

如果 `apps.json` 中没有配置，先用 `cli.py get-promoted-object` 从账户中反查并补充配置。

## CLI 返回格式

所有命令输出 JSON 到 stdout。出错时输出 `{"error": "...", "code": N, "subcode": N}` 到 stderr 并 exit 1。

### account-info

```json
{
  "id": "act_123456",
  "name": "My Ad Account",
  "account_status": "Active",
  "currency": "USD",
  "balance": "$1234.56"
}
```

account_status 可能值：Active, Disabled, Unsettled, Pending_Risk_Review, In_Grace_Period, Pending_Closure, Closed。

**`--all` 模式**（列出 token 下所有账户）:

```json
[
  {"id": "act_123456", "name": "Lilith-ROK-SINO-0时区-AI", "account_status": "Active", "currency": "USD", "balance": "$2100.36"}
]
```

`--name <keyword>` 按账户名称模糊过滤（不区分大小写）。

### list-campaigns

`--account-id <act_id>` 可选，指定查询的广告账户（默认用 `.env` 中的 `META_AD_ACCOUNT_ID`）。

```json
[
  {
    "id": "123456789",
    "name": "ROK_US_iOS_Broad_CBO500",
    "status": "ACTIVE",
    "daily_budget": 500.0,
    "objective": "OUTCOME_APP_PROMOTION"
  }
]
```

daily_budget 已转换为 USD（不是 cents）。

### list-adsets

`--account-id <act_id>` 可选，`--campaign-id <id>` 可选按 Campaign 过滤。

```json
[
  {
    "id": "123456789",
    "name": "ROK_US_iOS_Broad",
    "status": "ACTIVE",
    "daily_budget": 100.0,
    "campaign_id": "987654321",
    "optimization_goal": "APP_INSTALLS"
  }
]
```

daily_budget 已转换为 USD。

### list-ads

`--account-id <act_id>` 可选，`--adset-id <id>` 可选按 AdSet 过滤。

```json
[
  {
    "id": "123456789",
    "name": "ROK_US_v1",
    "status": "ACTIVE",
    "adset_id": "111222333",
    "creative_id": "444555666"
  }
]
```

### create-campaign

```json
{"campaign_id": "123456789", "status": "PAUSED"}
```

### create-adset

```json
{"adset_id": "123456789", "status": "PAUSED"}
```

### create-ad

```json
{"ad_id": "123456789", "status": "PAUSED"}
```

### duplicate-adset

返回格式同 create-adset：`{"adset_id": "<id>", "status": "PAUSED"}`

### update-status

```json
{"entity_id": "123456789", "entity_type": "campaign", "new_status": "PAUSED", "success": true}
```

### batch-update-status

```json
[
  {"entity_id": "111", "entity_type": "ad", "new_status": "PAUSED", "success": true},
  {"entity_id": "222", "entity_type": "ad", "new_status": "PAUSED", "success": false, "error": "..."}
]
```

单个失败不影响其他实体，逐条返回结果。

### get-status

- `--type campaign`：返回 `{ campaign: {...}, adsets: [ {..., ads: [...]} ], summary: {adset_count, ad_count}, campaign_url: "https://..." }`。**一次调用拿到 Campaign + 所有 AdSet + 所有 Ad + Creative 完整层级**，无需再调 list-adsets/list-ads。`campaign_url` 是 Ads Manager 直链，**必须贴给用户**。
- `--type adset`：返回 `{ ...adset字段..., ads: [...], adset_url: "https://..." }`。含 `countries`/`os` 解析后的值，含下属 Ads（与 campaign 层级逻辑共用）。
- `--type ad`：返回 `{ ...ad字段..., creative: {...}, ad_url: "https://..." }`。含 Creative 详情（`object_story_spec`, `thumbnail_url`）。

### resolve-app

```json
{"application_id": "151773865450393", "object_store_url": "https://apps.apple.com/app/id..."}
```

### list-apps

返回 `config/apps.json` 的完整内容（按项目→平台组织的 dict）。

### get-insights

`--account-id` 可选，`--date-start` / `--date-end` 必填，`--time-increment 1` 逐日（默认），`--level ad`（默认，可选 adset/campaign）。

```json
[
  {
    "ad_id": "123456789",
    "ad_name": "ROK_US_v1",
    "date": "2026-04-01",
    "spend": 100.0,
    "impressions": 50000,
    "clicks": 2500,
    "ctr": 5.0,
    "installs": 40,
    "cpi": 2.5
  }
]
```

`installs` 从 Facebook `actions` 中提取 `mobile_app_install` 计数。`cpi` = spend / installs，无安装时为 `null`。

### get-promoted-object

```json
[
  {
    "application_id": "151773865450393",
    "object_store_url": "https://apps.apple.com/app/id...",
    "adset_name": "ROK_US_iOS_Broad"
  }
]
```

从账户现有 AdSet 中反查，去重后返回。

## 实体层级

```
Ad Account (act_xxx)
  └── Campaign
       └── Ad Set
            └── Ad
                 └── Creative
```

## 创建参数

### create_campaign 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| name | str | **必填** | Campaign 名称 |
| objective | str | OUTCOME_APP_PROMOTION | 投放目标 |
| daily_budget | float | - | 日预算（USD，自动转 cents） |
| lifetime_budget | float | - | 总预算（USD，自动转 cents） |
| status | str | PAUSED | 创建状态 |
| bid_strategy | str | LOWEST_COST_WITHOUT_CAP | 出价策略 |
| special_ad_categories | list[str] | [] | 特殊广告类别（HOUSING 等） |
| spend_cap | float | - | 花费上限（USD，转 cents） |
| start_time | str | - | 开始时间（ISO 8601） |
| stop_time | str | - | 结束时间（ISO 8601） |
| is_skadnetwork_attribution | bool | - | SKAdNetwork 归因 |
| smart_promotion_type | str | - | Advantage+ 类型 |

未列出的参数作为额外字段直接透传给 SDK。

金额字段（daily_budget, lifetime_budget, spend_cap）传入 USD，脚本自动 ×100 转 cents。

### create_adset 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| name | str | **必填** | AdSet 名称 |
| campaign_id | str | **必填** | 所属 Campaign ID |
| daily_budget | float | - | 日预算（USD） |
| lifetime_budget | float | - | 总预算（USD） |
| status | str | PAUSED | 创建状态 |
| bid_strategy | str | LOWEST_COST_WITHOUT_CAP | 出价策略 |
| bid_amount | float | - | 出价金额（USD，转 cents） |
| bid_constraints | dict | - | 出价约束 |
| billing_event | str | IMPRESSIONS | 计费事件 |
| optimization_goal | str | APP_INSTALLS | 优化目标 |
| promoted_object | dict | - | `{application_id, object_store_url}` |
| attribution_spec | list[dict] | - | 归因窗口 |
| destination_type | str | - | 落地类型 (APP 等) |
| start_time | str | - | 开始时间 |
| end_time | str | - | 结束时间 |
| is_dynamic_creative | bool | - | 动态素材 |
| **Targeting** | | | |
| countries | list[str] | - | 国家列表 |
| os | str | - | iOS / Android |
| audience_type | str | Broad | Broad/Interest/Lookalike/Retarget（仅业务逻辑，不传 API） |
| publisher_platforms | list[str] | SDK 默认 | 版位（不传=全版位） |
| age_min | int | - | 最小年龄 |
| age_max | int | - | 最大年龄 |
| genders | list[int] | - | 性别 [1]=男 [2]=女 |
| locales | list[int] | - | 语言区域 |
| interests | list[dict] | - | 兴趣 `[{"id":"xx","name":"xx"}]` |
| custom_audiences | list[dict] | - | 自定义受众 `[{"id":"xx"}]` |
| excluded_custom_audiences | list[dict] | - | 排除受众 |
| app_install_state | str | - | INSTALLED/NOT_INSTALLED |

**受众类型映射**：
| 统一类型 | Facebook 参数 |
|---------|--------------|
| Broad | 不设 interests/custom_audiences |
| Interest | targeting.interests: [{id, name}] |
| Lookalike | targeting.custom_audiences: [{id}]（LAL audience） |
| Retarget | targeting.custom_audiences: [{id}]（Custom audience） |

### create_ad 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| name | str | **必填** | Ad 名称 |
| adset_id | str | **必填** | 所属 AdSet ID |
| creative_id | str | **必填** | Creative ID |
| status | str | PAUSED | 创建状态 |
| tracking_specs | list[dict] | - | 追踪规格 |
| conversion_domain | str | - | 转化域名 |

### pause / resume

```bash
cli.py update-status --entity-id <id> --type campaign --status PAUSED
cli.py update-status --entity-id <id> --type adset --status ACTIVE
cli.py batch-update-status --entity-ids <id1>,<id2> --type ad --status PAUSED
```

适用于 Campaign / AdSet / Ad。

### update_budget

目前未实现独立 CLI 命令。Facebook 不允许同时设置 daily_budget 和 lifetime_budget。

### upload_creative

已实现（`scripts/facebook/creative_manager.py`）。

**功能**: 上传素材文件（视频/图片）到 Facebook 广告库 + 创建 AdCreative。

**函数**:
- `upload_video(client, *, file_path, name)` → `{"video_id", "name"}`
- `upload_video_from_url(client, *, file_url, name)` → `{"video_id", "name"}`
- `upload_image(client, *, file_path, name)` → `{"image_hash", "image_url", "name"}`
- `create_ad_creative_for_video(client, *, video_id, name, page_id, link_url, message)` → `{"creative_id", "name"}`
- `create_ad_creative_for_image(client, *, image_hash, name, page_id, link_url, message)` → `{"creative_id", "name"}`
- `upload_creative(client, *, asset_type, file_url, name, page_id, link_url)` → 统一入口，自动判断本地/远程、视频/图片

**调用方**: creative-lifecycle 的 `_fetchers.make_upload_creative_fn()` 封装了此模块。

## Facebook 特异性

1. **金额单位**：API 接受分（cents），脚本自动做元→分转换（×100）
2. **状态值**：`ACTIVE` / `PAUSED`（ads-channel 只使用这两个）
3. **Advantage+ Campaign**：新版 API 推荐使用 OUTCOME_APP_PROMOTION objective
4. **Rate Limit**：client.py 内置 Rate Limit 检测和重试，Agent无需额外处理

## Pitfalls（踩坑记录）

### Campaign 创建
- **`is_adset_budget_sharing_enabled` 必填**：不使用 CBO 时必须传 `is_adset_budget_sharing_enabled: False`，否则报 error_subcode 4834011。
- **ABO + `is_adset_budget_sharing_enabled=true` 时必须有 `bid_strategy`**：Meta 要求启用预算共享时必须指定竞价策略，否则报 error_subcode 4834005（"无法在未设置竞价策略的情况下使用广告组预算共享"）。`campaign_manager.py` 已修复：ABO 模式下自动填充 `LOWEST_COST_WITHOUT_CAP`。

### AdSet 创建 — VO (Value Optimization)
- **bid_strategy 必须用 `LOWEST_COST_WITH_MIN_ROAS`**，不能用 `LOWEST_COST_WITH_BID_CAP`（会报 error_subcode 1885324 "竞价策略不支持价值优化"）。
- **出价通过 `bid_constraints` 传，不是 `bid_amount`**：`bid_constraints: {"roas_average_floor": N}`，N 是 ROAS 底线值（如用户说 VO 出价 0.1 → 传 10）。不传会报 error_subcode 2490487。
- **不要传 `bid_amount`**，VO 模式下该字段无效。

### AdSet 创建 — WW 定向
- **必须有正向地区**：不能只设 `excluded_geo_locations` 而不设 `geo_locations`，否则报 error_subcode 1885364 "缺少目标受众地区"。
- **WW 正确写法**：`geo_locations: {"country_groups": ["worldwide"], "location_types": ["home", "recent"]}` + `excluded_geo_locations: {"countries": ["JP", "VN", ...]}`。
- **新加坡合规声明**：WW 包含 SG 会要求 `compliance_section` 提供 `SINGAPORE_UNIVERSAL` 声明（error_subcode 3858550），不想处理声明可将 SG 加入排除列表。

### AdSet 创建 — 版位
- **`facebook_positions` 中 `reels` 无效**（error_subcode 1815433），正确值为 `facebook_reels`。建议 VO campaign 不指定版位，使用自动版位（不传 `publisher_platforms`/`facebook_positions`/`instagram_positions`）。

### Creative 创建 — 视频缩略图
- **video creative 必须提供缩略图**：`create_ad_creative_for_video` 的 `video_data` 中必须传 `image_hash` 或 `image_url`，否则报 error_subcode 1443226 "你的广告缺少视频缩略图"。
- **获取自动生成缩略图**：上传视频后等待 5-10 秒，调用 `GET /{video_id}?fields=picture` 获取 Facebook 自动生成的缩略图 URL，作为 `image_url` 传入。
- **注意**：视频处理中时 `picture` 可能返回占位符 GIF（URL 含 `rsrc.php`），需轮询直到获得真实缩略图 URL（含 `scontent` 或 `fbcdn`）。
- **批量上传视频慢**：每个视频上传 + 等待缩略图约 15-30 秒，13 条素材约需 5 分钟，应使用 background process 或预期较长执行时间。
