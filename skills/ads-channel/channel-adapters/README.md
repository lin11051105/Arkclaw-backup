# 渠道适配器开发指南

## 如何新增渠道

1. 在 `channel-adapters/` 目录下创建 `{channel-name}.md`
2. 按照下面的模板填写渠道适配器内容
3. 在 `SKILL.md` 的"支持渠道"章节添加新渠道
4. 在 `SKILL.md` 的"渠道路由"流程图中添加新分支

## 适配器模板

每个适配器文件必须包含以下章节：

```
# {Channel} 渠道适配器

## 概述
（渠道简介、API 框架、认证方式）

## 依赖
（SDK / HTTP client、环境变量、API 版本）

## 实体层级
（该渠道的广告实体层级结构，与 Facebook 的差异）

## 意图 → API 映射
（12 个标准意图的 API 调用方式，不支持的标注 NOT_SUPPORTED）

## {Channel} 特异性
（金额单位、状态值映射、Rate Limit、特殊行为）
```

## 必须处理的跨渠道差异

| 差异点 | 说明 |
|--------|------|
| 金额单位 | Facebook=分, TikTok=元, Google=micros → 统一层用 USD 元 |
| 状态值 | Facebook=ACTIVE/PAUSED, TikTok=ENABLE/DISABLE, Google=ENABLED/PAUSED |
| 实体层级 | Google App Campaign 无 AdSet 手动创建 |
| 素材绑定 | Facebook=独立 Creative, TikTok=Ad 内嵌, Google=素材包 |
| Rate Limit | 各渠道限流机制不同，适配器内部处理 |

## 标准意图列表

适配器必须为以下 12 个意图提供映射（或标注 NOT_SUPPORTED）：

1. `list_accounts`
2. `list_campaigns`
3. `list_adsets`
4. `list_ads`
5. `get_insights`
6. `create_campaign`
7. `create_adset`
8. `create_ad`
9. `pause_entity`
10. `resume_entity`
11. `update_budget`
12. `upload_creative`
