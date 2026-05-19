---
name: dap-ua
description: "DAP 数据访问统一层：基于全量自定义报表（按游戏路由 report_id）+ 素材报告 + 渠道 Insights 三大数据源，提供 UA 投放数据查询的完整入口"
metadata:
  hermes:
    tags: [ua, dap, data, query, reporting]
    related_skills: [dap]
---

# DAP 数据访问统一层

## 报表映射（唯一配置点）

新增游戏报表时，改两处配置 + 验证所有消费端：

**配置**：
1. 代码：`lib/fetchers.py` → `GAME_REPORT_MAP` 字典加一行
2. 文档：更新下方表格

**验证**：确认所有调用 `make_fetch_custom_report()` 的 CLI 都透传了 `game=` 参数。
已完成透传的文件（`--project` → `game=`）：
- `monitoring-alerts/scripts/cli.py` — `_make_fetchers` 提取 `args.project`
- `report-reconcile/scripts/cli.py` — 同上
- `report-reconcile/scripts/_fetchers.py` — 闭包内用 `project_id` 延迟构造
- `channel-summary/scripts/cli.py` — 从 `args.project` 提取
- `deep-analysis/scripts/cli.py` — 同上
- `creative-lifecycle/scripts/_fetchers.py` — `make_fetch_country_report(game=)`

⚠️ **新增 skill 时如果调了 `make_fetch_custom_report()`，必须传 `game=`，否则会静默查错报表。**

| 游戏 | report_id | 报表名 | 备注 |
|------|-----------|--------|------|
| **PTSLG**（默认） | 26888 | ptslg_all_info_wangyis | 15 基础表 + 6 分析表，含 ad_group/ad/runtime/traffic |
| ROK | 26608 | ua_agent_test_vincent | 9 基础表 + 3 分析表 |

- 不指定游戏时默认查 **PTSLG**（26888）
- 用户如需查其他游戏，需明确说游戏名（如"查 ROK 的日趋势"）
- 所有报表共享相同的 29 个指标列，计算逻辑通用
- report_id 为内部配置项，不在面向外部的消息中暴露

## 能力说明

本 Skill 是 UA 投放数据查询的业务层入口，定义数据全景、组合查询场景和工具选择策略。底层调用由官方 `dap` skill 处理。

**四大数据源**：

1. **全量自定义报表** `get_custom_report` — report_id 按游戏路由（见上方「报表映射」），覆盖全链路后端指标
2. **素材维度报告** `query_material_report` — 素材级前端广告指标（CTR/CVR/消耗/CPI/ROAS），**仅包含有投放消耗的素材**
3. **DAP 素材库** HTTP API — **全量素材库**（含已上传未投放的素材），支持按短名/尺寸/语种/区域搜索。查素材、找多版本、找特定比例版本必须用这个，不能用 `query_material_report`
4. **渠道侧 Insights** ads-channel `get_insights` — Campaign / AdSet / Ad 级前端指标

**⚠️ 关键区分：查素材用素材库，查效果用素材报告**：
- **查素材/找素材/搜素材/找多版本/找特定尺寸** → 必须用 **DAP 素材库 HTTP API**（数据源 3），它包含全量素材包括未投放的
- **查素材效果/消耗/CPI/ROI** → 用 **素材报告**（数据源 2），它只有投放过的素材
- `query_material_report` 查不到没投放过的素材。用它找素材会漏掉已上传但未投放的版本
- 聚合维度的后端指标（CPI、ROI、留存、LTV）→ 使用全量报表
- 实体级前端指标（Campaign/AdSet 的 CTR、CVR、CPM）→ 使用 ads-channel `get_insights`
- `channel` 参数区分渠道（Meta / TikTok / Google / CPE），不传时返回全渠道汇总

⚠️ **"前后端"术语辨析（设计报表/监控表时必读）**：
- **"前端"** = 广告平台侧数据（Meta/Google/TikTok 自归因）：Impressions、Clicks、CTR、CVR、CPM、CPC、Installs、CPI(USD)、Spend
- **"后端"** = DAP 归因后数据（全量报表）：安装数、CPI(RMB)、留存率、付费率、ROI、LTV、ARPPU
- **CTR / CVR / CPM 只有前端有，不存在"后端"版本** — DAP 不采集广告展示/点击数据，无法计算这些率值指标
- **CPI 和安装数前后端都有**，是前后端差异对照的核心（前端=平台自归因 USD，后端=DAP 归因 RMB）
- **ROI / 留存 / LTV / 付费率只有后端有** — 需要后安装行为数据，广告平台不提供（Meta 的 purchase ROAS 是近似值，不等于真实 ROI）
- 设计监控表/报表时，不要创建"后端CTR""后端CVR""后端CPM"列——这些指标不存在

## 调用方式

工具调用格式、参数规范、结果格式化规则见官方 `dap` skill（通过 `atlas-skillhub add dap` 安装）。本 skill 聚焦于数据全景和业务组合场景。

## 能力清单

### 一、全量报表数据（按游戏路由）

report_id 按游戏路由，具体映射见文档顶部「报表映射」章节。

#### 子表总览

| Table 键名 | 维度 | 约行数 | 用途 |
|------------|------|--------|------|
| `day` | 日期 | 动态 | 分日趋势、日报、同环比 |
| `retained` | 日期 | 动态 | 留存曲线 D2-D15, D30 |
| `roi` | 日期 | 动态 | ROI 曲线 D1-D15, D30，回本进度 |
| `ltv` | 日期 | 动态 | LTV 曲线 D1-D15, D30 |
| `media_src` | 渠道 | ~276 | 渠道效果对比 |
| `country` | 国家 | ~246 | 国家效果、预算分配 |
| `campaign` | 广告计划 | ~29000 | Campaign 效果、衰退检测 |
| `store` | OS | 3 | iOS / Android 对比 |
| `ua` | 优化师 | ~100 | 优化师产出 |
| `ua_group` | 小组 | ~3 | 团队汇总 |
| `country_level` | 梯度 | 4 | T0-T3 梯度分析 |
| `plate` | 地区 | ~23 | 大区分析 |

#### 标准指标列（29 列）

9 张维度表（day / media_src / country / campaign / store / ua / ua_group / country_level / plate）共享 1 个维度列 + 28 个指标列 = 29 列。维度列名因表而异（如 day 表为"日期"、media_src 表为"渠道"等），28 个指标列如下：

**消耗**：
- 消耗数(RMB)

**安装**：
- 安装数
- 安装成本(RMB) — 即 CPI

**创号**：
- 当日创号数
- 当日安装创号率
- 当日创号成本(RMB)

**创角**：
- 当日创角账号数
- 当日创号创角率
- 当日创角成本(RMB)

**留存**：
- 创号次留率 — D2 留存
- 创号7留率 — D7 留存
- 创号30留率 — D30 留存
- 创号次留成本(RMB)

**付费率**：
- 首日新付费率 — D1 付费占比
- 7日新付费率 — D7 累计付费占比
- 新付费率 — 全量付费占比

**ARPPU / ARPU**：
- 首日新ARPPU(RMB)
- 首日新ARPU(RMB)
- 7日新ARPPU(RMB)
- 新ARPPU(RMB)

**付费成本**：
- 首日新付费成本(RMB)
- 7日新付费成本(RMB)
- 新付费成本(RMB)

**ROI**：
- Actual_ROI
- ROI_最新
- ROI_1
- ROI_3
- ROI_7

#### 分析表特殊列

**retained 表**（留存曲线）：
- 日期、创号数、创号7留/次留（D7留存÷D2留存比值）
- 2日、3日、4日、5日、6日、7日、8日、9日、10日、11日、12日、13日、14日、15日 — 逐日留存率
- 30日 — D30 留存率

**roi 表**（ROI 曲线）：
- 日期、消耗数、创号数、创号成本、最新实收
- ROI_最新、ROI_24h
- ROI_1 ~ ROI_15（逐日）
- ROI_30

**ltv 表**（LTV 曲线）：
- 与 roi 表结构相同，但 ROI 指标替换为 LTV 值（每创号用户平均收入）
- 日期、消耗数、创号数、创号成本、最新实收
- LTV_最新、LTV_24h
- LTV_1 ~ LTV_15（逐日）
- LTV_30

#### get_custom_report 工具参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `report_id` | 是 | 报表 ID，按游戏路由（见「报表映射」章节） |
| `table` | 是 | 子表键名（day / retained / roi / ltv / media_src / country / campaign / store / ua / ua_group / country_level / plate） |
| `start_date` | 否 | 开始日期，格式 YYYY-MM-DD |
| `end_date` | 否 | 结束日期，格式 YYYY-MM-DD |
| `tz` | 否 | 时区（8 = UTC+8，0 = UTC+0） |
| `platform` | 否 | 平台筛选（iOS / Android） |
| `region` | 否 | 市场/地区筛选 |
| `ad_team` | 否 | 投放团队筛选 |
| `include_organic` | 否 | 是否包含自然量 |
| `campaign` | 否 | 广告计划名称筛选。⚠️ **必须传 campaign 名称字符串**（如 `"PTSLG_AND_VO_BAU_WW_Agent_20260423-CJF"`），**不能传 campaign ID**（如 `120245924849420100`），传 ID 会静默返回 `data: null` 而非报错。先从 `table=campaign` 查出名称再用于交叉筛选 |
| `page_size` | 否 | 每页返回行数，默认 20。country/campaign/media_src 等大表需调大（如 100） |

返回：`query_summary`（实际生效查询条件）+ `tables`（完整数据表）

#### 分页注意事项

media_src / country / campaign / ua / plate 等维度表默认仅返回前 20 行，按消耗降序排列。第一行通常是汇总行（Summary）。如需全量数据，使用 `page_size` 参数调大。campaign 表行数可达 ~29000，查询时建议配合日期范围缩小结果集。

### 二、素材维度投放报告

**工具**: `query_material_report`

查询素材级前端广告指标，适用于素材表现分析、设计师产出评估、创意效果对比。

#### 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `game` | 是 | 游戏名/别名/ID |
| `channel` | 是 | 投放渠道（Facebook / Google / TikTok 等） |
| `start_date` | 否 | 开始日期，默认近 7 天 |
| `end_date` | 否 | 结束日期 |
| `metrics` | 否 | 指定返回指标 |
| `sort_by` | 否 | 排序字段 |
| `sort_dir` | 否 | 排序方向 |
| `account` | 否 | 广告账户 |
| `campaign` | 否 | 广告系列 |
| `ad_group_id` | 否 | 广告组 ID |
| `ad_id` | 否 | 广告 ID |
| `filter_material` | 否 | 素材名模糊搜索（匹配素材全名中包含该子串的素材）。⚠️ **关键坑**：不匹配时**不报错、不返回空**，而是**静默忽略过滤条件**，返回全量数据，仅在 `warnings` 数组中提示"未找到匹配项，过滤条件已忽略"。**必须检查 warnings**，否则会误判为"查到了" |
| `material_type` | 否 | 素材类型 |
| `author` | 否 | 作者（设计师） |
| `producer` | 否 | 制作人 |
| `master` | 否 | 主创 |
| `first_cost_start` | 否 | 首消耗开始日期 |
| `first_cost_end` | 否 | 首消耗结束日期 |
| `session_id` | 否 | 会话 ID（多轮查询续接） |
| `message` | 否 | 自然语言补充描述 |

返回两张表：

**汇总表**（查询范围内的聚合数据）：

| 列 | 说明 |
|---|---|
| 消耗 | USD |
| 展示 | 绝对数 |
| 点击 | 绝对数 |
| 安装 | 绝对数 |
| CTR | 百分比 |
| CVR | 百分比 |
| CPI | USD |

**素材列表**（逐素材明细，按消耗降序）：

| 列 | 说明 |
|---|---|
| 名称 | 素材全名 |
| ID | 素材 ID |
| 消耗 | USD |
| 展示 | 绝对数 |
| 安装 | 绝对数 |
| 类型 | 视频/图片等 |
| CTR / CVR / CPI / ROAS | 效果指标 |
| 首消耗 | 首次产生消耗的日期 |
| 预览 | 素材预览链接 |

> **注意**：素材列表中**不含** campaign / ad_group / ad 列。`campaign` 等参数仅作输入筛选，返回结果不体现归属关系。

#### 典型场景

- **素材效果排名**：按消耗或 ROAS 排序，找到头部/尾部素材
- **设计师产出评估**：传 `author` 参数筛选特定设计师的素材表现
- **渠道素材对比**：同一时间段分别查 Facebook / Google / TikTok 渠道
- **Campaign 素材表现**：传 `campaign` 参数下钻到具体计划的素材
- **素材衰退检测**：对比不同时间段的 CTR/CVR 变化趋势
- **按短名查素材**：传 `filter_material` 参数（模糊匹配素材全名），按已知短名逐条查找素材的预览 URL 和投放数据。⚠️ **必须检查返回的 `warnings` 数组**——未匹配时 DAP 静默忽略过滤条件返回全量数据，不检查 warnings 会误判为查到了
- **Campaign 级前端指标**：传 `campaign` 参数筛选特定 Campaign，读取汇总表获得该 Campaign 聚合后的展示/点击/CTR/CVR/CPI（适合对少量异常 Campaign 下钻，不适合全量扫描）

#### 全量报表 vs 素材报告的区别

| 维度 | 全量报表（见「报表映射」） | 素材报告（query_material_report） |
|------|------------------------|--------------------------------|
| 粒度 | Campaign 级 | 素材级 |
| 指标类型 | 后安装指标（创号/留存/付费/ROI/LTV） | 广告前端指标（展示/点击/CTR/CVR/消耗/ROAS） |
| 维度拆分 | 日期/渠道/国家/Campaign/OS/优化师/小组/梯度/地区 | 素材/设计师/制作人/账户/Campaign/广告组 |
| 关系 | 互补，不可替代 | 互补，不可替代 |

### 三、报表库检索

**工具**: `list_custom_reports`

搜索 DAP 报表库，查找报表 ID。

| 参数 | 必填 | 说明 |
|------|------|------|
| `game` | 是 | 游戏名/别名/ID |
| `report_name` | 否 | 报表名称（模糊搜索） |
| `channel` | 否 | 渠道筛选 |

**已知报表**：见文档顶部「报表映射」章节。

### 四、标签与分类管理

#### add_marketing_tag — 新增推广标签

| 参数 | 必填 | 说明 |
|------|------|------|
| `game` | 是 | 游戏名 |
| `name` | 是 | 标签名称 |
| `region` | 是 | 市场（中国 / 国际 / 台湾 / 日本 / 韩国） |

#### add_material_class — 新增素材大类

| 参数 | 必填 | 说明 |
|------|------|------|
| `game` | 是 | 游戏名 |
| `name` | 是 | 大类名称 |

### 五、素材落盘统计

**工具**: `query_material_summary`

按设计师和日期范围统计素材落盘（产出）数据，适用于团队产能评估、个人产出考核。

#### 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `authors` | 是 | 设计师姓名（逗号分隔，如 `"宋玥玥,井三,Dora"`) |
| `start_date` | 是 | 开始日期 YYYY-MM-DD |
| `end_date` | 是 | 结束日期 YYYY-MM-DD |
| `game` | 否 | game_id 或项目简称（如 `10064` 或 `SAMO`），不传时返回所有项目 |

#### 返回

三张表：

| 表名 | 内容 |
|------|------|
| `summary` | 项目 × 素材大类交叉统计 |
| `author_summary` | 各设计师产出数量 |
| `details` | 素材明细列表 |

#### 典型场景

- **周产量统计**：传 `start_date`/`end_date` 为本周，`authors` 传团队全员
- **个人产出考核**：传单个 `authors`，按月汇总
- **项目维度产能**：传 `game` 参数筛选特定项目的落盘情况

### 六、DAP 素材库搜索（HTTP API）

**⚠️ 查素材/找素材/搜素材/找多版本/找特定尺寸 → 必须用这个接口，不能用 `query_material_report`。**

`query_material_report` 只返回有投放消耗的素材。DAP 素材库包含全量素材（含已上传未投放的），是唯一能找到"有 4:5 版本但从没投放过"的数据源。

#### 接口

`POST https://dap.lilithgame.com/dapper/api/material/v2/list/materials`

认证：`Authorization: Basic {DAP_API_TOKEN}`（环境变量 `DAP_API_TOKEN`）

#### 调用方式

Python 脚本调用（推荐）：

```python
# 方式 1: 直接用 DapHttpClient
import sys
sys.path.insert(0, "/root/workspace/ua_agent/workspace/skills")
from lib.dap_client import DapHttpClient

client = DapHttpClient()  # 自动读 DAP_API_TOKEN 环境变量

# 按短名搜素材（找所有尺寸版本）
results = client.search_materials(game_id=10091, keyword="宠物进化")
for r in results:
    print(f"id={r['id']} name={r['name']} size={r['width_height']}")

# 查单个素材详情
detail = client.get_material_detail(1148535)

# 方式 2: 用 _fetchers 工厂函数
from creative_lifecycle.scripts._fetchers import make_search_dap_materials, make_find_material_versions

search = make_search_dap_materials()
results = search(game_id=10091, keyword="宠物进化", region_id="2", material_type="video")

find_versions = make_find_material_versions()
versions = find_versions(game_id=10091, short_name="宠物进化")
```

或直接用 curl：

```bash
curl -s -X POST "https://dap.lilithgame.com/dapper/api/material/v2/list/materials" \
  -H "Content-Type: application/json" \
  -H "Authorization: Basic $DAP_API_TOKEN" \
  -d '{"game_id": 10091, "keyword": "宠物进化", "page": 1, "page_size": 50}'
```

#### 请求参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `game_id` | 是 | 项目 ID（ROK=10043, PTSLG=10091, PGAME=10064, AFKA=10046, IGAME=10076） |
| `keyword` | 否 | 短名/素材名模糊搜索 |
| `material_ids` | 否 | 素材 ID 列表精确查询，如 `[123, 456]` |
| `type` | 否 | 素材类型: video / image / image_set / trial_play |
| `status` | 否 | 启停状态: 0=暂停, 1=启用 |
| `review_status` | 否 | 审核状态: "3"=已通过 |
| `region_id` | 否 | 区域: "1"=国内, "2"=海外 |
| `language` | 否 | 语系: en / cn / ja / ko 等 |
| `ratio` | 否 | 宽高比例 |
| `marketing_tag_ids` | 否 | 推广标签 ID 列表 |
| `order` | 否 | 排序字段（默认 upload_datetime） |
| `sort` | 否 | 排序方向: desc / asc |
| `page` | 否 | 页码（默认 1） |
| `page_size` | 否 | 每页条数（默认 20） |

#### 返回字段

| 字段 | 说明 |
|------|------|
| `id` | DAP 素材主键 ID（= 报告中的素材 ID） |
| `name` | 素材短名（如"宠物进化"） |
| `material_name` | 完整命名（如"PTSLG_V_CN_KOL_宠物进化_初版_...") |
| `type` | video / image / image_set |
| `width_height` | 尺寸（如"1080*1920"、"1280*720"） |
| `language` | 语系 |
| `regions` | 区域（中国/国际） |
| `status` / `status_str` | 启停状态 |
| `download_url` | CDN 下载地址 |
| `thumbnail_url` | 封面图 |
| `author_name` | 设计师 |
| `marketing_tag` | 推广标签 |
| `created_at` | 入库日期 |

#### 典型场景

- **找素材的 4:5 版本**：传 `keyword=短名` 搜出所有版本，按 `width_height` 筛选 1080*1350 或类似 4:5 尺寸
- **找特定项目海外视频素材**：`game_id=10091, region_id="2", type="video"`
- **按 ID 精确查**：`material_ids=[1148535, 1147863]`
- **找同一短名的多版本**：`keyword=宠物进化` → 返回所有尺寸版本（1280*720, 720*1280, 1080*1920 等）
- **替换广告素材**：先从广告中提取当前素材短名 → 用 keyword 搜 DAP 素材库找目标尺寸版本 → 用新素材 ID 替换

### 七、数据查询场景映射

#### 单一查询映射

| 数据需求 | 工具 + 参数 | 关键返回字段 |
|---------|------------|-------------|
| 分日趋势 | `get_custom_report` table=day | 消耗、安装数、CPI、ROI、留存率 |
| 留存曲线 | `get_custom_report` table=retained | D2~D15、D30 留存率 |
| ROI 回本进度 | `get_custom_report` table=roi | ROI_最新、ROI_1~ROI_15、ROI_30、最新实收 |
| LTV 曲线 | `get_custom_report` table=ltv | LTV_1~LTV_15、LTV_30 |
| 渠道效果对比 | `get_custom_report` table=media_src | 各渠道消耗、CPI、ROI、留存 |
| 国家分析 | `get_custom_report` table=country | 各国消耗、安装、CPI、ROI |
| Campaign 排名 | `get_custom_report` table=campaign | Campaign 消耗、CPI、ROI、留存 |
| OS 拆分 | `get_custom_report` table=store | iOS/Android 消耗、CPI、ROI |
| 优化师产出 | `get_custom_report` table=ua | 优化师消耗、安装、CPI、ROI |
| 团队汇总 | `get_custom_report` table=ua_group | 小组消耗、安装、ROI |
| 国家梯度 | `get_custom_report` table=country_level | T0~T3 消耗、CPI、ROI |
| 大区分析 | `get_custom_report` table=plate | 大区消耗、CPI、ROI |
| 安装数据（按渠道/国家/OS） | `get_custom_report` 对应 table | 安装数、安装成本 |
| 收入数据 | `get_custom_report` table=roi | 最新实收 |
| 素材级 CTR/CVR | `query_material_report` | CTR、CVR、消耗、ROAS |
| 设计师评估 | `query_material_report` author=xxx | 设计师维度素材表现 |
| **查素材/找素材** | **DAP 素材库 HTTP** keyword=短名 | id、name、width_height、download_url |
| **找 4:5/16:9 版本** | **DAP 素材库 HTTP** keyword=短名 | 按 width_height 筛选目标尺寸 |
| **按 ID 查素材详情** | **DAP 素材库 HTTP** material_ids=[id] | 全量素材信息 |
| **找海外视频素材** | **DAP 素材库 HTTP** region_id="2" type="video" | 全量未投放素材也能查到 |
| Campaign 级 CTR/CVR/CPM | ads-channel `get_insights` | spend、impressions、clicks、ctr、cvr、cpm |
| 广告频次 | ads-channel `get_insights` fields=frequency | frequency |
| 版位效果分析 | ads-channel `get_insights` breakdowns=publisher_platform | 按版位拆分的 CTR、CPA |
| 报表 ID 查找 | `list_custom_reports` game=xxx | report_id |
| 标签/分类管理 | `add_marketing_tag` / `add_material_class` | status |
| 设计师落盘统计 | `query_material_summary` authors=xxx | summary、author_summary、details |
| 项目素材产量 | `query_material_summary` game=xxx | 项目 × 大类交叉统计 |

#### 素材×账号交叉分析（DAP 无法直接实现）

DAP 素材报告的 `filter_account` 参数模糊匹配常失败，`attributes="account"` 也不改变返回结构。**素材在不同广告账号下的表现对比只能通过 ads-channel 实现**：

**步骤**：

1. 用 ads-channel `account-info --all` 获取全部账号，筛选有消耗的活跃账号
2. 逐账号调用 `get-insights --level ad --time-increment 7`（或自定义天数），获取 Ad 级数据
3. 从 `ad_name` 字段提取素材 ID：正则 `_(\d{5,8})(?:\.\w+)?$`（素材 ID 嵌在广告名称末尾）
4. 将提取的素材 ID 与 DAP `query_material_report` 返回的素材数据 JOIN，得到素材×账号交叉表
5. 异常检测：
   - 爆款表现差：账号 CPI > 素材均值 × 2（受众饱和/高竞争区/iOS 结构性高成本）
   - 非爆款表现好：账号 CPI < 素材均值 × 0.4 且安装≥20（小账号红利/地区适配/素材-受众匹配）

**限制**：
- 仅 Meta 渠道可用（ads-channel Facebook 适配器已实现，TikTok/Google 待实现）
- 当前 Token 仅覆盖 ROK 和 AFK 的 Meta 账号，其他游戏需 DAP 新接口
- 账号数量多时需串行调用（每次间隔 2-5 秒避免限流），不要用 execute_code 批量调用
- **大账号超时**: 超过 1000 条 ad 的账号（如 Cyberklick_iOS）单次 get-insights 会超时，需按 3 天日期窗口分段查询（如 04-07~04-09、04-10~04-13），每段 timeout=180s，最后 merge JSON 数组

**典型发现**：
- 高消耗账号（如 cheetah-01）的爆款素材 CPI 系统性偏高 3-5 倍 → 受众饱和 + VO 出价策略
- 小账号（如 pltvCE-cheetah-04）非爆款素材 CPI 低至均值 10% → 受众新鲜 + pLTV 优化精准
- 地区账号（如 SINO-JP）某些素材 CPI 极低 → 素材主题与地区偏好高度匹配
- iOS 账号（如 CyberKlick-iOS）CPI 结构性偏高 → ATT 影响 + iOS 用户获取成本高

#### 组合查询示例

**1. 日报生成**
- 步骤 1：`get_custom_report` table=day，取当日 + 前一日数据，计算环比
- 步骤 2：`get_custom_report` table=media_src，取各渠道当日汇总
- 步骤 3：`get_custom_report` table=country，取 TOP 国家数据
- 组合输出：消耗/安装/CPI 同环比 + 渠道拆分 + 国家 TOP N

**2. ROI 回本检查**
- 步骤 1：`get_custom_report` table=roi，取指定日期的 ROI 曲线
- 步骤 2：读取 `config/thresholds.json` 中的回本目标阈值
- 步骤 3：逐日对比 ROI_N vs 目标值，标记未达标日期
- 输出：回本进度表 + 未达标告警

**3. 渠道健康度分析**
- 步骤 1：`get_custom_report` table=media_src，取当日各渠道汇总
- 步骤 2：`get_custom_report` table=day，取最近 7 天分日趋势
- 步骤 3：计算各渠道 7 日趋势（消耗/CPI/ROI 走势），识别异常渠道
- 输出：渠道健康度评分 + 异常渠道预警

**4. 素材效果分析**
- 步骤 1：`query_material_report`，取素材级 CTR/CVR/消耗/ROAS
- 步骤 2：`get_custom_report` table=campaign，取 Campaign 级后端指标
- 步骤 3：通过 Campaign 名称关联素材与后端效果，综合评估素材价值
- 输出：素材排名（前端指标 + 关联后端 ROI）

**5. Campaign 异常下钻（后端 → 前端指标）**
- 步骤 1：`get_custom_report` table=campaign，找到 CPI 异常偏高或 ROI 异常偏低的 Campaign
- 步骤 2：对异常 Campaign 调用 ads-channel `get_insights`，传 `entity_type=campaign`、`entity_id=<ID>`、`fields=["spend","impressions","clicks","ctr","cvr","cpm"]`，批量获取前端指标
- 步骤 3：判断异常原因是前端（CTR/CVR 下降）还是后端（留存/付费下降），给出针对性建议
- 输出：异常 Campaign 列表 + 前后端指标对比 + 归因分析

**6. 素材×账号交叉分析（全游戏巡检）**
- 步骤 1：`query_material_report` 分别查每个游戏每个渠道的素材数据，获取素材 ID 列表和 CPI/ROAS
- 步骤 2：ads-channel `account-info --all` 获取全部 Meta 账号，按 status=Active 筛选
- 步骤 3：逐账号 `get-insights --level ad --time-increment 7`，串行执行（sleep 2-5s 避免限流）
- 步骤 4：从 ad_name 提取素材 ID（正则 `_(\d{5,8})(?:\.\w+)?$`），按素材 ID 与步骤 1 JOIN
- 步骤 5：计算每个素材在各账号的 CPI，与素材整体均值对比，输出异常点
- 输出：爆款素材效果差的账号 + 非爆款素材效果好的账号 + 原因分析

**7. Campaign 衰退检测**
- 步骤 1：`get_custom_report` table=campaign，取 Campaign 维度数据
- 步骤 2：读取 `config/thresholds.json` 中的衰退判定阈值
- 步骤 3：对比各 Campaign 近 N 天 CPI/ROI 变化，标记衰退 Campaign
- 输出：衰退 Campaign 列表 + 建议操作（暂停/降预算）

**8. Campaign × Country 后端 ROI 分析**
- 步骤 1：`get_custom_report` table=campaign，获取目标 campaign 的**名称**（不是 ID）
- 步骤 2：`get_custom_report` table=day + `campaign=计划名`，拉分日趋势看 ROI_1 走向
- 步骤 3：`get_custom_report` table=country + `campaign=计划名` + `page_size=100`，拉聚合期 country 数据
- 步骤 4（可选）：逐天拉 country 表看核心国家 ROI_1 趋势（区分偶发波动 vs 持续恶化）
- 输出：campaign 级日趋势 + 国家分层（优质/及格/问题）+ 趋势方向 + 操作建议
- ⚠️ campaign 参数**必须传名称字符串**，传 ID 会静默返回空数据
- ⚠️ DAP 报表原始单位是 RMB，需按汇率换算为 USD（约 /7.2）

### 七、广告前端指标（渠道侧 Insights）

实体级前端指标（Campaign / AdSet / Ad 粒度的 spend / impressions / clicks / CTR / CVR / CPM / frequency 等）通过 `ads-channel` skill 的 `get_insights` 意图查询。指标详情、可拆分维度、调用方式见 `ads-channel` SKILL.md。

**与 DAP 数据源的选择**：

| 场景 | 用 ads-channel `get_insights` | 用 `query_material_report` |
|------|------|------|
| Campaign 级 CTR/CVR/CPM | ✅ 直接查，支持批量 | ⚠️ 需传 campaign 参数逐个筛选，不适合批量 |
| 素材级 CTR/CVR/ROAS | ❌ 不支持素材粒度 | ✅ 素材维度原生支持 |
| Frequency（频次） | ✅ 直接查 | ❌ 不支持 |
| 版位拆分 | ✅ breakdowns 支持 | ❌ 不支持 |
| 设计师/制作人维度 | ❌ 不支持 | ✅ 原生支持 |

### 八、已通过替代方案实现的能力

以下能力原计划依赖 DAP 新接口，但已通过 Facebook API + 现有 DAP 工具实现：

| 能力 | 替代方案 | 所属 Skill |
|------|---------|-----------|
| 账户余额查询 | ads-channel `account-info` (Facebook API) | monitoring-alerts |
| 消耗进度查询 | ads-channel `get-insights` 汇总当日消耗 vs apps.json `daily_budget` | monitoring-alerts |
| 数据 Gap 预警 | Facebook `get-insights` vs DAP `get_custom_report` 对比 | monitoring-alerts |
| 素材库存/爆款量 | DAP `query_material_report` + 阈值判定 | creative-lifecycle |
| 素材衰退检测 | DAP `query_material_report` 逐日对比 | creative-lifecycle |
| 短名聚合报表 | DAP `query_material_report` + 命名规则解析 | creative-lifecycle |

### 九、待 DAP 新接口的能力

以下能力确实需要 DAP 平台提供新接口，当前无替代方案：

| 能力 | 用途 | 阻塞的 Skill |
|------|------|-------------|
| Postback 回传实时状态 | 分钟级回传中断检测（当前用 T+1 Gap 近似） | monitoring-alerts |
| 素材列表查询（按标签/状态筛选） | 库存盘点中按标签/状态过滤 | creative-lifecycle |
| 素材命名解析（服务端） | 统一命名校验（当前用本地 naming-rules.json） | creative-lifecycle |
| 渠道账单导出 | 自动化月度对账（当前用 Facebook Insights 近似） | report-reconcile |
| 素材合规检测 | 上传前合规预检 | creative-compliance |
| AI 标签 | 素材分层、洞察分析 | creative-ai-test, creative-insight |

## 工具选择指引

```
需要什么数据？
│
├─ 聚合指标（CPI/ROI/留存/LTV/消耗/安装，按维度拆分）
│  ├─ 按日期 → get_custom_report table=day / retained / roi / ltv
│  ├─ 按渠道 → get_custom_report table=media_src
│  ├─ 按国家 → get_custom_report table=country
│  ├─ 按 Campaign → get_custom_report table=campaign
│  ├─ 按 OS → get_custom_report table=store
│  ├─ 按优化师 → get_custom_report table=ua
│  ├─ 按小组 → get_custom_report table=ua_group
│  ├─ 按梯度 → get_custom_report table=country_level
│  └─ 按大区 → get_custom_report table=plate
│
├─ 素材级指标（CTR/CVR/ROAS，按素材/设计师拆分）
│  └─ query_material_report
│
├─ 实体级前端指标（Campaign/AdSet/Ad 的 CTR/CVR/CPM/频次/版位）
│  └─ ads-channel get_insights（支持 fields 和 breakdowns 参数）
│
├─ 不知道报表 ID
│  └─ list_custom_reports 查找
│
├─ 素材落盘/产量统计（按设计师/项目/大类）
│  └─ query_material_summary
│
├─ 标签/分类管理
│  ├─ 推广标签 → add_marketing_tag
│  └─ 素材大类 → add_material_class
│
└─ 以上均不匹配
   ├─ 先用 list-tools 检查是否有新工具上线
   └─ 如无可用工具，记录数据缺口到 memory，通知用户该能力暂不可用
```

**关键判断规则**：

1. **后端 vs 前端**：CPI / ROI / 留存 / LTV 等后安装指标 → 全量报表；CTR / CVR / CPM 等广告前端指标 → 素材报告或 ads-channel `get_insights`
2. **素材级 vs 实体级**：按素材/设计师拆分 → 素材报告；按 Campaign / AdSet / Ad 粒度（含频次、版位）→ ads-channel `get_insights`
3. **交叉维度筛选**：全量报表子表可通过 `campaign` / `platform` / `region` / `ad_team` 参数交叉筛选。例如查 `table=country` + `campaign=计划名` 可得到 **campaign × country** 交叉数据（含 ROI_1 等后端指标）。⚠️ `campaign` 参数必须传名称字符串，不能传 ID
4. **必传日期范围**：所有查询都应传 start_date / end_date，避免默认范围导致数据量过大或不符合预期
5. **分页控制**：campaign / media_src / country 等大表默认仅返回 20 行，需要更多数据时调大 page_size

## 跨游戏素材批量查询模式

当需要一次性查询多个游戏的素材数据时（如"给我 ROK、SAMO、PTSLG 的爆款素材"），使用 `execute_code` 批量调用：

### 关键要点

1. **日期分段**：每段 ≤ 2 个月，避免 HTTP 500。推荐按双月分段（如 Jan-Feb、Mar-Apr）
2. **限流**：每次 DAP 调用间隔 ≥ 5 秒（`time.sleep(5)`）
3. **分页**：`page_size=50`，默认按消耗降序。Top 100（2 页）通常足以覆盖爆款
4. **游戏名映射**：ROK=万国觉醒、SAMO=万龙觉醒(10064)、PTSLG=帕萌战斗日记(10091)
5. **渠道**：分别查 Facebook 和 Google（TikTok 如需也可加）
6. **聚合逻辑**：同一素材跨时段/渠道需聚合——消耗和安装直接累加，ROAS 需按消耗加权（`sum(spend×ROAS) / total_spend`），CPI 用总消耗/总安装
7. **输出目录**：`os.makedirs("/tmp/hermes", exist_ok=True)` 确保目录存在
8. **爆款实用标准**：无配置化阈值时，用消耗门槛（如 ≥ $50K/季度）作为爆款筛选条件，比 CPI/ROAS 硬阈值更通用

### 返回数据解析

```python
outer = json.loads(r["output"])
inner = json.loads(outer["content"][0]["text"])
# inner["tables"][1] = 素材列表表（columns + data）
cols = [c["name"] for c in inner["tables"][1]["columns"]]
for row in inner["tables"][1]["data"]:
    record = dict(zip(cols, row))
    # record keys: "名称", "ID", "消耗", "展示", "安装", "类型", "CTR", "CVR", "CPI", "ROAS", "首消耗", "预览"
```

### 典型调用规模

- 3 游戏 × 2 渠道 × 2 时段 × 2 页 = 24 次调用，约 2~3 分钟（含 sleep）
- 每次返回约 50 条素材，去重后每游戏约 150~300 条唯一素材

## 结果呈现规范

DAP 工具返回结果的格式化规则见官方 `dap` skill。核心要点：

- `query_summary` 必须在表格前展示（get_custom_report）
- `tables` 完整透传，按 `columns[i].format` 格式化（`percent` → %，`cny` → ¥，`usd` → $）
- `truncated=true` 时注明总数和当前显示数
- `warnings` / `ambiguities` 非空时必须展示，不静默忽略

## 安全规则

1. 所有写操作（标签新增、分类新增）须遵守 `AGENTS.md` 中的决策分级
2. 不在日志或消息中暴露 API Key、Token
3. 数据查询结果中的财务敏感信息仅推送到授权渠道
4. report_id 为内部配置项（见「报表映射」），不在面向外部的消息中暴露
