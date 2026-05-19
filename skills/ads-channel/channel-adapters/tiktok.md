# TikTok 渠道适配器

> **状态**: 🔜 骨架预留，待实现

## 概述

TikTok 渠道适配器，通过 TikTok Marketing API 实现。当前为骨架文件，定义渠道特异性和预期 API 映射，待接入时补充完整实现。

## 依赖

- **TikTok Marketing API**：[待确认 SDK / 直接 HTTP]
- **环境变量**：`TIKTOK_ACCESS_TOKEN`（待配置）
- **API 版本**：v1.3+

## 实体层级

```
Advertiser (广告主)
  └── Campaign
       └── Ad Group（对应 Facebook AdSet）
            └── Ad
```

**与 Facebook 的差异**：
- Facebook `AdSet` = TikTok `Ad Group`
- TikTok 无 `AdCreative` 独立对象，素材直接挂在 Ad 上

## 意图 → API 映射（预留）

| 统一意图 | TikTok API | 状态 |
|---------|-----------|------|
| list_accounts | GET /advertiser/info | 待实现 |
| list_campaigns | GET /campaign/get | 待实现 |
| list_adsets | GET /adgroup/get | 待实现 |
| list_ads | GET /ad/get | 待实现 |
| get_insights | GET /report/integrated/get | 待实现 |
| create_campaign | POST /campaign/create | 待实现 |
| create_adset | POST /adgroup/create | 待实现 |
| create_ad | POST /ad/create | 待实现 |
| pause_entity | POST /campaign/status/update 或 /adgroup/status/update 或 /ad/status/update | 待实现 |
| resume_entity | 同 pause_entity，status=ENABLE | 待实现 |
| update_budget | POST /campaign/update 或 /adgroup/update | 待实现 |
| upload_creative | POST /file/video/ad/upload 或 /file/image/ad/upload | 待实现 |

## TikTok 特异性

1. **状态值差异**：`ENABLE` / `DISABLE`（非 ACTIVE / PAUSED），需做映射
2. **Coupon / 赔付**：TikTok 有小额赔付（Coupon）机制，在账单中体现为负值消耗，月度对账时需特殊处理
3. **素材上传**：素材直接绑定在 Ad 上，无独立 Creative 对象
4. **AWEME 追踪**：TikTok 特有的素材追踪 ID
5. **金额单位**：API 接受元（非分），与 Facebook 不同
6. **Report API**：使用 integrated report，支持多维度交叉查询
7. **Rate Limit**：按 App 级别限流，10 QPS 默认上限

## 实现步骤（待执行）

1. 确认 TikTok Marketing API SDK / HTTP client 接入方式
2. 配置 Token 获取和刷新流程
3. 实现各意图的 API 映射
4. 处理状态值映射（ENABLE ↔ ACTIVE, DISABLE ↔ PAUSED）
5. 处理金额单位差异（TikTok 用元，统一层用元）
6. 实现 Coupon 赔付的账单特殊处理
7. 测试全流程
