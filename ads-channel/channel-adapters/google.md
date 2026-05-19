# Google Ads 渠道适配器

> **状态**: 🔜 骨架预留，待实现

## 概述

Google Ads 渠道适配器，通过 Google Ads API 实现。Google App Campaign 高度算法驱动，人工可控范围有限（预算、CPI 目标、素材包、投放地区），适配器需反映这些限制。

## 依赖

- **Google Ads API**：[待确认 SDK / REST]
- **环境变量**：`GOOGLE_ADS_DEVELOPER_TOKEN`, `GOOGLE_ADS_OAUTH_TOKEN`（待配置）
- **API 版本**：v17+

## 实体层级

```
Customer (客户 / 账户)
  └── Campaign (App Campaign)
       └── Ad Group（Google 自动管理，有限手动控制）
            └── Ad (App Ad，只设素材包）
```

**与 Facebook 的关键差异**：
- Google App Campaign **无 AdSet 概念**（Ad Group 由 Google 算法自动创建和优化）
- 人工只能控制：预算、CPI 目标出价、素材包（文本/图片/视频）、投放地区
- 定向由 Google 算法自动优化，无法手动设置受众

## 意图 → API 映射（预留）

| 统一意图 | Google Ads API | 状态 | 备注 |
|---------|---------------|------|------|
| list_accounts | ListAccessibleCustomers | 待实现 | |
| list_campaigns | GoogleAdsService.Search (campaign) | 待实现 | |
| list_adsets | GoogleAdsService.Search (ad_group) | 待实现 | 只读，Google 自动管理 |
| list_ads | GoogleAdsService.Search (ad_group_ad) | 待实现 | |
| get_insights | GoogleAdsService.Search (metrics) | 待实现 | GAQL 查询语言 |
| create_campaign | CampaignService.MutateCampaigns | 待实现 | App Campaign 专用参数 |
| create_adset | **不支持** | — | Google App Campaign 无手动 AdSet |
| create_ad | AdGroupAdService.MutateAdGroupAds | 待实现 | 仅设素材包 |
| pause_entity | CampaignService.MutateCampaigns (status) | 待实现 | |
| resume_entity | CampaignService.MutateCampaigns (status) | 待实现 | |
| update_budget | CampaignBudgetService.MutateCampaignBudgets | 待实现 | |
| upload_creative | AssetService.MutateAssets | 待实现 | 图片/视频/文本 asset |

## Google 特异性

1. **无 AdSet 创建**：`create_adset` 意图在 Google 渠道应返回 `NOT_SUPPORTED` 错误，并说明 Google App Campaign 无手动 AdSet
2. **GAQL 查询**：Insights 查询使用 Google Ads Query Language（GAQL），非 REST 参数
3. **预算对象独立**：预算是独立资源（CampaignBudget），需先创建预算再关联 Campaign
4. **出价策略有限**：App Campaign 仅支持 target CPI / target CPA / maximize conversions
5. **素材包模式**：Ad 是素材包（多个文本 + 多个图片 + 多个视频），Google 自动组合
6. **金额单位**：API 使用 micros（1元 = 1,000,000 micros）
7. **状态值**：`ENABLED` / `PAUSED` / `REMOVED`

## 实现步骤（待执行）

1. 确认 Google Ads API 认证方式（OAuth2 + Developer Token）
2. 实现 GAQL 查询构建器
3. 实现 Campaign 创建（App Campaign 专用参数）
4. 处理预算独立对象的创建和关联
5. 实现素材包模式的 Ad 创建
6. 处理 `create_adset` 的 NOT_SUPPORTED 响应
7. 处理金额单位差异（micros ↔ 元）
8. 测试全流程
