---
name: competitive-intel
description: "竞品情报与渠道热点：竞品头部素材追踪、渠道创意热点抓取"
metadata:
  hermes:
    tags: [ua, competitive, intelligence, creative, trends]
    related_skills: [dap-ua]
---

# 竞品情报与渠道热点

## 能力说明

| 能力 | 需求 | 触发方式 | 技术层级 |
|------|------|---------|---------|
| 司内 & 竞品头部素材追踪 | 2.5 | cron 每周 + 手动 | L4 |
| 渠道热点抓取 | 2.6 | cron 每周 2-3 次 + Heartbeat + 手动 | L2 |

## 触发条件

1. **定时触发（cron）**:
   - 竞品追踪: 每周三 14:00 (`0 14 * * 3`)
   - 热点抓取: 每周一/三/五 10:00
2. **Heartbeat**: 热点监控可在空闲时触发
3. **手动触发**: 飞书指令 "查看竞品动态"、"最近有什么热点"

## 执行步骤

### 一、司内 & 竞品头部素材追踪（需求 2.5）

**输入**: `competitors[]`（竞品应用列表）, `category`（品类）, `regions[]`（关注地区）, `date_range`（默认近 7 天）

**步骤**:

1. **通过爬虫脚本抓取竞品投放数据**:
   ```bash
   bash workspace/scripts/crawler-competitor.sh \
     --competitors "<app1>,<app2>" \
     --category "<SLG>" \
     --regions "<US>,<JP>" \
     --date-range "7d"
   ```
   注: 爬虫脚本需要 [待开发]，负责从 AppGrowing 等三方平台抓取数据
   
   期望输出: JSON 格式的竞品素材列表
   ```json
   [
     {
       "app": "竞品A",
       "creative_id": "xxx",
       "type": "video",
       "first_seen": "2026-04-01",
       "estimated_impressions": 500000,
       "duration_days": 7,
       "regions": ["US", "CA"],
       "platform": "Facebook"
     }
   ]
   ```

2. **筛选新上榜的头部素材**: 按消耗量/展示量/投放天数排序，取 Top 20

3. **通过 DAP 查询司内同品类头部素材**: 通过 DAP 查询司内同品类头部素材投放数据，指定项目名、全渠道、日期范围（近 7 天），按消耗降序排列取 Top 20

4. **LLM 分析素材趋势变化**:
   - 输入: 竞品头部素材列表 + 司内头部素材 + 上周报告（来自 memory）
   - 分析:
     - 新上榜素材的类型、文案套路、视觉风格
     - 与上周对比的变化点
     - 竞品策略变动信号（如突然增加某类素材投放量）
   - 输出: 趋势分析 + 可借鉴方向建议

5. **推送飞书**: 竞品追踪周报，包含:
   - 新上榜素材列表（附截图/链接 if available）
   - 素材类型和风格分布变化
   - 竞品策略变动分析
   - 可借鉴方向建议
   - 注明"追热点不偏品"的边界提醒

6. **沉淀到 MEMORY.md**: 有长期价值的趋势（如"本月 SLG 品类普遍增加短视频投放"）

### 二、渠道热点抓取（需求 2.6）

**输入**: `channels[]`（关注渠道）, `category`（品类）, `regions[]`（关注地区）

**步骤**:

1. **通过爬虫脚本抓取渠道热点数据**:
   ```bash
   bash workspace/scripts/crawler-trending.sh \
     --channels "tiktok,facebook" \
     --category "<SLG>" \
     --regions "<US>,<JP>"
   ```
   注: 爬虫脚本需要 [待开发]
   
   数据源:
   - TikTok Creative Center: 热门音频、热门话题、上升趋势素材
   - FB Ad Library: 高曝光新素材
   
   期望输出:
   ```json
   [
     {
       "source": "TikTok Creative Center",
       "type": "audio",
       "name": "热门音频名",
       "trend_score": 95,
       "growth_7d": "+200%",
       "related_category": ["gaming", "entertainment"]
     }
   ]
   ```

2. **筛选近一周快速攀升的创意热点**: 按 trend_score 和 growth_7d 排序

3. **LLM 做热点归因和品牌匹配度评估**:
   - 输入: 热点列表 + 品类信息 + 品牌调性
   - 分析:
     - 该热点是否适合本品类（匹配度评分 1-10）
     - 时效性窗口预估（1 周 / 2 周 / 1 月）
     - 素材应用建议（如何将热点融入素材）
   - 输出: 热点提醒

4. **推送飞书**: 热点提醒（仅推送匹配度 >= 6 的热点）:
   ```
   🔥 渠道热点提醒

   1. [TikTok] 热门音频"XXX"
      趋势: 7 日增长 +200%
      品牌匹配度: 8/10
      时效窗口: ~2 周
      应用建议: 可用于 SLG 品类的战斗节奏类素材

   2. [Facebook] 叙事模板"YYY"
      ...
   
   ⚠️ 提醒: 追热点需保持品牌调性，避免过度跟风
   ```

5. **写入 `memory/YYYY-MM-DD.md`**
6. **有价值的热点规律沉淀到 MEMORY.md**

## 输入/输出

### 输入参数

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `competitors[]` | string[] | 竞品应用列表 | 项目配置中的默认列表 |
| `category` | string | 品类 | 项目默认品类 |
| `channels[]` | string[] | 关注渠道 | TikTok, Facebook |
| `regions[]` | string[] | 关注地区 | 项目默认地区 |
| `date_range` | string | 追踪时段 | 近 7 天 |

### 输出

| 场景 | 推送方式 | 频率 |
|------|---------|------|
| 竞品追踪周报 | 飞书文档 | 每周 |
| 热点提醒 | 飞书消息 | 每周 2-3 次 |

## 安全规则

1. 爬虫行为需**遵守三方平台的使用条款和频率限制**
2. 竞品数据**仅用于内部分析**，不得外泄
3. 热点建议需注明**"追热点不偏品"**的边界提醒
4. 爬虫脚本执行失败时静默处理，不影响其他 Skill 运行

## 待开发依赖

| 组件 | 说明 | 状态 |
|------|------|------|
| `scripts/crawler-competitor.sh` | 竞品投放数据爬虫 | [待开发] |
| `scripts/crawler-trending.sh` | 渠道热点数据爬虫 | [待开发] |
| AppGrowing 账号权限 | 竞品数据源 | [待确认 P07] |
| TikTok Creative Center 访问 | 热点数据源 | [待确认 P08] |
