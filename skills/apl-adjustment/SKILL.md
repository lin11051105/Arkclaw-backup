---
name: apl-adjustment
description: |
  Applovin Axon Campaign Management API 操作工具。

  当用户需要执行 Applovin 广告调整操作时使用，包括：Campaign 管理、素材组管理、预算调整、目标修改、国家定向等。

  配套 Skill：applovin-analytics（数据分析和建议生成）

  ⚠️ 重要：所有调整操作需要用户确认后执行。
metadata:
  version: 1.0.0
---

# APL Adjustment - Applovin 广告调整

Applovin Axon Campaign Management API 操作工具

**职责**：执行广告调整操作（Campaign/素材组/预算管理）
**配套 Skill**：`applovin-analytics`（数据分析和建议生成）

## ⚠️ 重要业务规则

### ROAS 定义（Campaign Management API）
> **当用户提到 "ROAS" 时，永远指代 IAP ROAS，即 `CHK_ROAS`**

用户只投放 IAP ROAS 产品，不使用 AD_ROAS 或 BLD_ROAS。

**注意**：Reporting API 中的 ROAS 是 Total ROAS（IAP + Ad），与 Campaign Management API 不同。

### 目标类型映射
| 用户说的 | API 使用的 |
|---------|-----------|
| ROAS / IAP ROAS | `CHK_ROAS` |
| CPI | `CPI` |
| CPE | `CPE` |
| CPP | `CPP` |

### Campaign 查询规则
> **当用户查询 Campaign 时，永远查询所有 Campaigns（分页获取全部），不是只返回前 100 个**

API 默认每页返回 100 个，需要分页获取直到获取完所有 Campaigns。

### Asset 查询规则（强制性）
> **⚠️ 当用户要求查询素材时，必须遍历所有分页，不能只查前 20 页！**

**错误做法（严禁）**：
- ❌ 只查询前 20 页（2000 个素材）
- ❌ 不显示查询进度
- ❌ 假设素材在前几页

**正确做法**：
- ✅ 遍历所有分页直到返回空结果
- ✅ 显示进度（每页显示已获取数量）
- ✅ Account 300004 有 4820+ 个素材，需要遍历约 49 页
- ✅ 预计耗时约 50 秒，提前告知用户

**代码模板**：
```python
all_assets = []
page = 1
while True:
    assets = manager.list_assets(page=page, size=100)
    if not assets:
        break
    all_assets.extend(assets)
    print(f"  第 {page} 页: {len(assets)} 个素材")
    if len(assets) < 100:
        break
    page += 1
    if page > 100:  # 安全限制
        break
print(f"总计: {len(all_assets)} 个素材")
```

**这是与用户的明确约定，必须遵守！**

### Creative Set 查询规则
> **当用户查询 Campaign 的素材组时，使用 `list_creative_sets` 全量获取再过滤，不是 `get_creative_sets_by_campaign_id`**

原因：`get_creative_sets_by_campaign_id` 端点可能返回不完整数据。
正确做法：
1. 分页获取所有素材组（可能多达 2000+ 个）
2. 按 `campaign_id` 过滤
3. **按 `creative_set_id` 去重**（API 可能返回重复数据）

### Creative Set 命名规则
> **当需要填入素材组名称时，必须按以下格式要求，并检查用户输入是否正确**

#### 标准命名格式
**格式**: `{语言}_{视频短名}_{试玩短名}_{商店页名}`

**示例**: `EN_被砸死的崽_保护美女过桥_PA_CPP`

#### 字段提取规则

| 资源类型 | 短名提取规则 | 示例 |
|---------|-------------|------|
| **视频短名** | 从**视频文件名**第4个 `_` 到第5个 `_` 之间的字段提取 | `WGAME_V_EN_AI_**被砸死的崽**_初版_...` → `被砸死的崽` |
| **试玩短名** | 从**试玩文件名**（HTML）第3个 `_` 到第4个 `_` 之间的字段提取 | `W3_PA_Applovin_**保护美女过桥**_20260513.html` → `保护美女过桥` |

> ⚠️ **重要**：视频短名和试玩短名分别来自**不同的文件**（视频文件和试玩HTML文件），不是从同一个文件名提取！

#### 创建素材组时的确认流程

**步骤1：获取视频信息**
- 询问用户视频文件名或ID
- 从视频文件名提取**视频短名**（第4-5个 `_` 之间）

**步骤2：获取试玩信息** ⚠️ **必须单独询问**
- 询问用户使用哪个试玩（HTML文件）
- 从试玩文件名提取**试玩短名**（第3-4个 `_` 之间）
- **禁止**从视频文件名猜测试玩短名

**步骤3：获取商店页名**
- 询问用户商店页名（如 PA_CPP）

**步骤4：组合名称**
- 格式：`{语言}_{视频短名}_{试玩短名}_{商店页名}`

#### 特殊情况处理

| 情况 | 处理方式 |
|------|---------|
| **1视频 + 1试玩** | 分别询问视频和试玩，然后自动提取短名 |
| **多个视频** | ⚠️ 必须和创建人确认：视频短名修改为什么 |
| **多个试玩** | ⚠️ 必须和创建人确认：试玩短名修改为什么 |
| **多个视频 + 多个试玩** | ⚠️ 必须和创建人确认：两个短名都需确认 |
| **仅有试玩** | 使用试玩的完整名字作为素材组名 |

#### 检查清单
- [ ] 语言字段是否正确（一般是 EN）
- [ ] 视频短名是否从第4-5个 `_` 间提取
- [ ] 试玩短名是否从第3-4个 `_` 间提取
- [ ] 商店页名是否正确（如 PA_CPP）
- [ ] 多个资源时是否已和创建人确认

#### 重要注意事项

> **⚠️ 文件名中的日期 ≠ 上传日期**
>
> 视频文件名中的时间（如 `260509`）是**视频制作完成的日期**，不是上传到 Applovin 的日期。
>
> **正确的上传时间字段**：
> - ✅ 使用 `upload_time` 字段（不是 `created_at`）
> - 格式: ISO 8601，如 `2026-05-13T03:46:25`
> - `created_at` 字段 unreliable（可能返回 null）

### Creative Set 创建技术规范

> **⚠️ 创建 Creative Set 时必须遵守以下技术规范，否则 API 会返回 400 错误**

#### 1. Asset Type 映射

| Asset 实际类型 | API 要求的 type 字段 |
|---------------|---------------------|
| 视频 (VID_LONG_P) | `"VID_LONG_P"` |
| HTML 试玩 | `"HOSTED_HTML"` ⚠️ **不是 "HTML"** |

#### 2. 必需的请求字段

创建 Creative Set 时必须包含以下字段：

```json
{
  "name": "RU_视频短名_试玩短名_PA",
  "campaign_id": "2021008",  // String 类型
  "assets": [
    {"id": "42502138", "type": "VID_LONG_P"},
    {"id": "30628057", "type": "HOSTED_HTML"}
  ],
  "status": "LIVE",  // 或 "PAUSED"
  "type": "APP",
  "version": "V2"  // ⚠️ 必需！
}
```

**注意**：`version: "V2"` 是必需字段，缺少会导致 `100001` 错误。

#### 3. Asset 状态检查

> **⚠️ 创建前必须检查所有 Asset 的状态，REJECTED 的 Asset 不能使用**

错误示例：
```
CAMPAIGN_MANAGEMENT_API_VALIDATION_ERROR. 
Invalid asset ids: [42152824(asset status: rejected)]
```

**正确做法**：
1. 获取 Asset 列表
2. 筛选 `status == "ACTIVE"` 的 Asset
3. 如果用户指定的 Asset 是 REJECTED，必须告知用户并请求替换

#### 4. Asset 组合规则

> **⚠️ Creative Set 必须包含视频 + 试玩，不能只包含视频**

支持的组合：
- ✅ 视频 + 试玩 (VID_LONG_P + HOSTED_HTML)
- ❌ 仅视频 (会报错: "asset combination is not supported")
- ❌ 仅试玩 (会报错)

#### 5. 字段类型要求

| 字段 | 类型 | 说明 |
|-----|------|------|
| `campaign_id` | String | Campaign ID 必须是字符串 |
| `assets[].id` | String | Asset ID 必须是字符串 |
| `creative_set_id` (更新时) | String | 更新素材组时 ID 必须是字符串 |

### Creative Set 批量创建流程

#### 步骤1：确认视频和试玩列表
- 获取用户指定的视频列表
- 获取用户指定的试玩列表
- **检查所有 Asset 状态为 ACTIVE**

#### 步骤2：确认 Creative Set 配置
询问用户确认：
- [ ] Creative Set 命名格式
- [ ] 初始状态 (LIVE/PAUSED)
- [ ] 语言设置
- [ ] 国家定向

#### 步骤3：执行创建
- 逐个创建 Creative Set
- 每个请求包含 `version: "V2"`
- Asset type 使用 `"VID_LONG_P"` 和 `"HOSTED_HTML"`
- 添加延迟避免频率限制（建议 0.5s）

#### 步骤4：验证结果
- 列出 Campaign 的所有 Creative Set
- 确认数量和名称正确
- 确认状态正确

### 素材替换规则

> **⚠️ 严禁擅自替换用户指定的素材**

如果创建时发现素材不可用（REJECTED 或不存在）：
1. **立即停止创建**
2. **告知用户具体问题**
3. **请求用户确认替换方案**
4. **获得明确确认后才能继续**

**错误做法**（严禁）：
- ❌ 自动用其他素材替换
- ❌ 跳过不可用的素材继续创建
- ❌ 不告知用户擅自修改配置

**正确做法**：
- ✅ 告知用户 "Asset 42152824 状态为 REJECTED，不可用"
- ✅ 询问 "是否替换为其他素材？请指定替换素材"
- ✅ 等待用户明确回复后再继续

#### 可选参数询问（创建前必须询问）

在创建素材组前，必须询问用户以下可选参数：

| 参数 | 说明 | 默认值 | 是否必须询问 |
|------|------|--------|-------------|
| `countries` | 投放国家（ISO 3166-1 alpha-2 代码列表） | 全部国家 | ✅ 必须询问 |
| `languages` | 语言列表 | 全部语言 | ✅ 必须询问 |
| `status` | 初始状态 | LIVE | ✅ 必须询问 |

**询问示例：**
```
即将创建素材组，请确认以下可选参数：
1. 投放国家（默认全部）：如 US,JP,DE
2. 语言（默认全部）：如 ENGLISH,JAPANESE
3. 初始状态（默认 LIVE）：LIVE 或 PAUSED
```

### Creative Set 更新规则
> **更新素材组时，`id` 必须是 String 类型，且 `assets` 字段是必需的**

正确做法：
1. 先获取素材组完整信息（`get_creative_set`）
2. 修改需要的字段（如 `status`）
3. 保留原有 `assets` 字段（必需）
4. 提交更新请求

示例：
```python
# 获取现有素材组
cs = manager.get_creative_set('1005239518')

# 更新状态（保留 assets）
payload = {
    'id': '1005239518',  # String 类型
    'status': 'PAUSED',
    'type': 'APP',
    'campaign_id': cs['campaign_id'],
    'name': cs['name'],
    'assets': cs['assets']  # 必需！
}
```

## 官方 API 文档

**地址**: https://support.axon.ai/zh/growth/promoting-your-apps/api/axon-campaign-management-api

**遇到问题时**：
1. 访问官方文档核查字段类型和要求
2. 注意 `id` 字段的类型（Campaign 是 Long，Creative Set 是 String）
3. 查看 "创建" / "更新" 列确定必需字段

## ⚠️ 安全规则

**所有修改操作执行前必须获得用户确认！**

- ✅ **确认**: 回复 "可以" / "确认" / "yes" / "ok"
- ❌ **取消**: 其他回复或 5 分钟超时

## 完整功能列表

### Campaign 管理
- ✅ `campaign list` - 列出 Campaigns
- ✅ `campaign get` - 获取 Campaign 详情
- ✅ `campaign create` - 创建 Campaign
- ✅ `campaign pause` - 暂停 Campaign
- ✅ `campaign resume` - 恢复 Campaign

### 预算管理
- ✅ `campaign budget global` - 修改全球预算
- ✅ `campaign budget country` - 修改国家级预算

### 目标管理
支持所有目标类型：
- ✅ `CPI` - Cost Per Install
- ✅ `CPE` - Cost Per Event
- ✅ `CPP` - Cost Per Purchase
- ✅ `AD_ROAS` - Ad ROAS (不使用)
- ✅ `BLD_ROAS` - Blended ROAS (不使用)
- ✅ `CHK_ROAS` - IAP ROAS **(默认，用户说 ROAS 时指此)**

### 竞价策略
- ✅ `target_goal_with_cpi_billing` - 目标 CPI 竞价
- ✅ `auto_bidding_with_cpm_billing` - 自动 CPM 竞价
- ✅ `maximize_results_with_cpm_billing` - 最大化结果 CPM 竞价

### 国家定向
- ✅ `campaign targeting list` - 列出目标国家
- ✅ `campaign targeting add` - 添加国家
- ✅ `campaign targeting remove` - 移除国家
- ✅ `campaign targeting set` - 设置国家（替换）
- ✅ 支持美国地区定向 (region_codes)

### 素材组管理
- ✅ `creative list` - 列出素材组
- ✅ `creative get` - 获取素材组详情
- ✅ `creative create` - 创建素材组
- ✅ `creative update` - 更新素材组
- ✅ `creative clone` - 克隆素材组
- ✅ `creative enable` - 启用素材组
- ✅ `creative disable` - 禁用素材组

### 资源管理
- ✅ `asset list` - 列出资源
- ✅ `asset upload` - 上传资源（支持 html, gif, jpg, png, mp4, mov）
- ✅ `asset upload-result` - 查询上传结果

## 认证

```bash
export APPLOVIN_API_KEY=your_api_key
export APPLOVIN_ACCOUNT_ID=your_account_id
```

## 使用示例

### Campaign 管理

```bash
# 列出 Campaigns
python3 cli_full.py campaign list

# 创建 Campaign
python3 cli_full.py campaign create \
  --name "My Campaign" \
  --platform android \
  --package-name com.example.app \
  --start-date 2024-01-01 \
  --end-date 2024-12-31 \
  --budget 1000

# 暂停 Campaign
python3 cli_full.py campaign pause --campaign-id 12345

# 恢复 Campaign
python3 cli_full.py campaign resume --campaign-id 12345
```

### 预算管理

```bash
# 修改全球预算
python3 cli_full.py campaign budget global \
  --campaign-id 12345 \
  --budget 2000

# 修改国家预算
python3 cli_full.py campaign budget country \
  --campaign-id 12345 \
  --country US \
  --budget 500
```

### 目标管理

```bash
# 设置 CPI 目标
python3 cli_full.py campaign goal set \
  --campaign-id 12345 \
  --goal-type CPI \
  --target-value 2.5

# 设置 IAP ROAS 目标
python3 cli_full.py campaign goal set \
  --campaign-id 12345 \
  --goal-type CHK_ROAS \
  --target-value 0.15
```

### 素材组管理

```bash
# 列出素材组
python3 cli_full.py creative list

# 获取素材组详情
python3 cli_full.py creative get --creative-set-id 67890

# 创建素材组
python3 cli_full.py creative create \
  --name "My Creative Set" \
  --campaign-id 12345 \
  --assets '[{"id": "asset1", "type": "VID_LONG_P"}]'

# 克隆
python3 cli_full.py creative clone \
  --creative-set-id 67890 \
  --target-campaign-id 54321

# 启用/禁用
python3 cli_full.py creative enable --creative-set-id 67890
python3 cli_full.py creative disable --creative-set-id 67890
```

### 资源管理

```bash
# 列出
python3 cli_full.py asset list
python3 cli_full.py asset list --type video

# 上传
python3 cli_full.py asset upload \
  --files /path/to/video1.mp4 /path/to/image1.png

# 查询上传结果
python3 cli_full.py asset upload-result --upload-id xxx
```

## 资源类型

| 类型 | 扩展名 | Content-Type |
|------|--------|--------------|
| HTML | .html | text/html |
| GIF | .gif | image/gif |
| JPEG | .jpg, .jpeg | image/jpeg |
| PNG | .png | image/png |
| MP4 | .mp4 | video/mp4 |
| MOV | .mov | video/quicktime |

## API 限制

- 频率：每 60 秒 1000 请求
- 上传：最多 40 个文件，总大小 ≤ 10GB，单个 ≤ 1GB

## 目标类型限制

| 类型 | 限制 |
|------|------|
| AD_ROAS | > 10% (0.1) |
| BLD_ROAS | > 5% (0.05) |
| CHK_ROAS | > 1% (0.01) |
| CPE | < $500 |
| CPI | < $200 |
| CPP | < $500 |

## 性能说明

### 资源查询
> **Account 300004 有 4748+ 个资源，完整遍历需要 ~50 秒**

**查询时显示进度**：
```
第 1 页: 100 个资源
第 2 页: 100 个资源
...
总计获取: 4748 个资源
```

**推荐做法**：
- 用户指定资源名称/ID → 直接查询
- 用户指定日期 → 遍历全部并显示进度
- 用户未指定 → 询问具体需求

---

## 新功能：APL 素材上传（从 DAP 同步到 Applovin）

### 功能说明

从 DAP 素材库查询符合条件的素材，自动同步到 Applovin。

**流程**：
1. 根据筛选条件从 DAP 查询素材（使用 data skill）
2. 从 Windows 同步文件夹复制素材到本地
3. 用户确认素材列表
4. 上传素材到 Applovin
5. 同步素材过审状态

### 使用方法

```bash
python3 scripts/upload_from_dap.py \
  --game-id 10048 \
  --type video \
  --language en \
  --ratio "1080*1920" \
  --material-class AI \
  --start-date 2026-05-11 \
  --end-date 2026-05-17
```

### 参数说明

| 参数 | 必填 | 说明 |
|-----|------|------|
| `--game-id` | ✅ | 项目 ID（Wgame=10048） |
| `--type` | ❌ | 素材类型（video/image/image_set/trial_play），默认 video |
| `--language` | ❌ | 语系（en/cn/ja/ko/ru） |
| `--ratio` | ❌ | 尺寸比例（如 1080*1920） |
| `--material-class` | ❌ | 素材大类（AI/3D/剪辑/KOL/本地化） |
| `--start-date` | ✅ | 开始日期（YYYY-MM-DD） |
| `--end-date` | ✅ | 结束日期（YYYY-MM-DD） |
| `--page-size` | ❌ | 每页查询数量，默认 1000 |
| `--local-dir` | ❌ | 本地临时目录，默认 /tmp/apl_upload |
| `--skip-confirm` | ❌ | 跳过用户确认（谨慎使用） |

### 使用示例

**示例 1：上传上周 Wgame 的英文 AI 视频素材（9:16）**
```bash
python3 scripts/upload_from_dap.py \
  --game-id 10048 \
  --type video \
  --language en \
  --ratio "1080*1920" \
  --material-class AI \
  --start-date 2026-05-11 \
  --end-date 2026-05-17
```

**示例 2：上传上周所有素材**
```bash
python3 scripts/upload_from_dap.py \
  --game-id 10048 \
  --start-date 2026-05-11 \
  --end-date 2026-05-17
```

**示例 3：上传俄语素材**
```bash
python3 scripts/upload_from_dap.py \
  --game-id 10048 \
  --language ru \
  --ratio "1080*1920" \
  --start-date 2026-05-11 \
  --end-date 2026-05-17
```

### 注意事项

1. **page_size=1000**：查询时使用 page_size=1000，确保不遗漏素材
2. **Windows 同步文件夹**：DAP 记录了素材的 Windows 同步文件夹地址，脚本会从此路径复制素材
3. **分批上传**：每批最多 40 个文件（Applovin API 限制）
4. **用户确认**：上传前会显示素材列表，需要用户确认
5. **过审状态同步**：上传完成后会自动查询并显示素材的过审状态
