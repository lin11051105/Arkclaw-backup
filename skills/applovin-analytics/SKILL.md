---
name: applovin-analytics
description: |
  Applovin Reporting API 数据查询和分析工具。

  当用户需要查询 Applovin 投放数据、分析 Campaign/素材组效果、生成调整建议时使用。

  配套 Skill：apl-adjustment（执行调整操作）

  功能包括：
  - Campaign 级别数据查询
  - 素材组级别数据查询
  - 分国家/渠道数据分析
  - 低 ROAS 素材识别
  - 生成暂停/调整建议
metadata:
  version: 1.0.0
---

# Applovin Analytics - 数据分析

Applovin Reporting API 数据查询和分析工具

**职责**：查询投放数据、分析效果、生成调整建议
**配套 Skill**：`apl-adjustment`（执行调整操作）

## 功能

### 1. Reporting API 客户端
- 通用查询接口
- 自动切换 report_type（advertiser/publisher）
- 支持 JSON/CSV 格式

### 2. 数据查询
- ✅ Campaign 级别数据
- ✅ 素材组级别数据
- ✅ 分国家数据
- ✅ 分渠道数据
- ✅ 自定义列组合

> **⚠️ 重要：所有数据都是 Cohort 数据，不是 Real-time 数据**
>
> - Cohort 数据：按安装日期聚合，反映用户生命周期价值
> - Real-time 数据：按事件日期聚合，反映实时发生的事件
> - **代码默认设置 `day_column=day`，确保返回 Cohort 数据**
> - 分析 ROAS/CPP/留存 等指标时必须使用 Cohort 数据
> - 如需 Real-time 数据，需显式设置 `day_column=None`

### 百分比数据处理
> **Reporting API 返回的百分比是原始数值（如 110.12 表示 110.12%）**
>
> - 代码自动将百分比除以 100 转换为小数（如 1.1012）
> - 涉及字段：ctr, conversion_rate, roas_x, iap_roas_x, ad_roas_x 等
> - 显示时格式化为百分比（如 110.12%）

### 3. 数据分析
- ✅ ROAS 分析（低 ROAS 识别）
- ✅ CPI 分析（高 CPI 识别）
- ✅ IR 分析（低 IR 识别）
- ✅ CPP 分析（高 CPP 识别）
- ✅ **整体出价分析**（基于 budget/spend/potential）
- ✅ 自定义指标分析

### 4. 生成调整建议
> **仅在用户询问时才生成建议，否则只执行数据查询和分析**

支持的建议类型：
- 暂停 Campaign
- 暂停素材组
- 排除国家
- 调整预算
- **调整出价**（整体出价分析）
  - 出价偏低（花超比例 >160%）
  - 出价略低（花超比例 130%~160%）
  - 出价偏高（实际花费比例 ≤75%）

## 调用流程

### 数据查询/分析
```
用户请求 → analytics skill 查询数据 → 展示分析结果
```

### 生成建议（用户询问时）
```
用户请求 → analytics skill 查询数据 → 分析 → 生成建议 → 用户确认
→ analytics skill 调用 apl-adjustment → 用户确认 → 执行操作
```

## 重要规则

### Report Type 自动切换
> **当使用 `report_type=advertiser` 查不到数据时，自动尝试 `report_type=publisher`**

### ROAS 定义
> **当用户提到 "ROAS" 时，永远指 Total ROAS（即 `roas_x`），不是 IAP ROAS 或 Ad ROAS**

- **Total ROAS** = (IAP Revenue + Ad Revenue) / Cost
- **D0/D1/D7** 等表示天数，需要询问用户具体指哪一天
- 默认查询 D7 ROAS（`roas_7d`）

### 返回格式选择
> **默认使用 `json` 格式**

- **JSON**（默认）：适合飞书对话框展示，易于解析和格式化
- **CSV**：适合下载和 Excel 分析，需要时显式指定

## 整体出价分析功能 (Campaign Bid Analysis - Overall)

### 功能说明
基于 Campaign 的 budget、spend 和 potential（来自邮件）数据，分析出价是否合理。

### 分析规则

**1. 花超比例 (Potential / Budget)**
| 比例范围 | 备注 |
|---------|------|
| >160% | 出价偏低，需要调整 |
| 130%~160% | 出价略低，需要关注 |
| <130% | 出价正常，无需调整 |

**2. 实际花费比例 (Spend / Budget)**
| 比例范围 | 备注 |
|---------|------|
| ≤75% | 出价偏高，需要调整 |
| >75% | 出价正常 |

**3. 数据来源**
- **Budget**: 从 Campaign Management API 获取
- **Spend**: 从 Reporting API 获取
- **Potential**: 从邮件 "Lilith / AppLovin Campaign Spend Potential" 获取

### 使用方法

```bash
# CLI 命令
python3 cli.py bid-analysis \
  --campaign-id 1817245 \
  --start 2026-05-11 \
  --end 2026-05-17 \
  --potential-file potential_data.json
```

### potential 数据格式

```json
{
  "2026-05-11": {"potential": 4800, "note": ""},
  "2026-05-12": {"potential": 4500, "note": ""},
  "2026-05-13": {"potential": 3500, "note": ""},
  "2026-05-14": {"potential": 3800, "note": ""},
  "2026-05-15": {"potential": 2500, "note": ""},
  "2026-05-16": {"potential": 4000, "note": ""},
  "2026-05-17": {"potential": 3900, "note": ""}
}
```

如果某日期没有 potential 数据，则自动使用 budget 值，并备注"当日没有potential"。

### Python API

```python
from applovin_analytics import ApplovinAnalytics

analytics = ApplovinAnalytics.from_env()

# 加载 potential 数据
potential_data = {
    '2026-05-11': {'potential': 4800, 'note': ''},
    '2026-05-12': {'potential': 4500, 'note': ''},
    # ...
}

result = analytics.analyze_campaign_bid_overall(
    campaign_id='1817245',
    start_date='2026-05-11',
    end_date='2026-05-17',
    potential_data=potential_data
)

# 结果包含
# - daily_analysis: 每日分析数据
# - summary: 汇总数据（含结论）
```

### 输出示例

```
====================================================================================================
Campaign: 1817245
Analysis Period: 2026-05-11 to 2026-05-17
Daily Budget: $3,000
====================================================================================================

日期            Budget    Potential    花超比例       Spend    实际花费比例 备注
------------------------------------------------------------------------------------------------------------
2026-05-11      $3,000      $4,800      160.0%   $4,094.28        136.5% 出价略低，需要关注 | 出价正常
2026-05-12      $3,000      $4,500      150.0%   $3,920.06        130.7% 出价略低，需要关注 | 出价正常
2026-05-13      $3,000      $3,500      116.7%   $3,228.96        107.6% 出价正常，无需调整 | 出价正常
2026-05-14      $3,000      $3,800      126.7%   $3,465.93        115.5% 出价正常，无需调整 | 出价正常
2026-05-15      $3,000      $2,500       83.3%   $1,694.67         56.5% 出价正常，无需调整 | 出价偏高，需要调整
2026-05-16      $3,000      $4,000      133.3%   $3,472.53        115.8% 出价略低，需要关注 | 出价正常
2026-05-17      $3,000      $3,900      130.0%   $3,507.95        116.9% 出价略低，需要关注 | 出价正常
------------------------------------------------------------------------------------------------------------
汇总（平均值）         $3,000      $3,857      128.6%   $3,340.63        111.4% 出价正常，无需调整 | 出价正常

====================================================================================================
结论（基于汇总数据）：
  - 平均花超比例: 128.6%
  - 平均实际花费比例: 111.4%
  - 结论: 出价正常，无需调整 | 出价正常
====================================================================================================
```

---

## 素材分析功能 (Creative Set Analysis)

### 功能说明
4步分类法自动分析素材组表现，生成调整建议。

### 分析流程

**Step 1**: 筛选低于 Campaign D28 ROAS 的素材组

**Step 2**: 按消耗分类
- **A类**: 消耗 ≥ `起量消耗判定` 阈值
- **B类**: 消耗 < `起量消耗判定` 阈值

**Step 3**: A类细分
- **A1**: 近14天 + ROAS ≥ 0.5倍 Campaign ROAS → 继续观察
- **A2**: 近14天 + ROAS < 0.5倍 Campaign ROAS → 暂停投放
  - 特例: 近3天创建的标记为"新素材" → 继续观察
- **A3**: 早于14天 → 暂停投放
  - 特例: 近3天创建的标记为"新素材" → 继续观察

**Step 4**: B类细分
- **B1**: 近30天 → 继续观察
- **B2**: 早于30天 → 暂停投放

### 使用方法

```python
from applovin_analytics import ApplovinAnalytics
from datetime import datetime

analytics = ApplovinAnalytics.from_env()

# 素材组创建日期（从 Campaign Management API 获取）
set_dates = {
    'EN_素材组1_PA_CPP': '2026-05-01',
    'EN_素材组2_PA_CPP': '2026-04-15',
    # ...
}

# 执行素材分析
result = analytics.analyze_creative_sets(
    campaign_id='1817245',
    start_date='2026-05-07',
    end_date='2026-05-13',
    volume_threshold=1000,  # 起量消耗判定阈值（$1k）
    set_dates=set_dates,
    today=datetime(2026, 5, 14)
)

# 结果包含
# - campaign_roas_28d: Campaign D28 ROAS
# - a1/a2/a3/b1/b2: 分类后的素材组列表
# - summary: 暂停/观察统计
```

### 关键参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `volume_threshold` | 起量消耗判定阈值（A类/B类划分） | 1000 (= $1k) |
| `set_dates` | 素材组创建日期字典 | {'name': '2026-05-01'} |
| `today` | 分析日期 | datetime(2026, 5, 14) |

### 建议生成规则
> **仅在用户明确要求时生成建议**

- 日常查询 → 只返回数据
- 用户问"应该怎么做"/"有什么建议" → 生成建议

## 预定义列组合

| 列集合 | 包含列 |
|--------|--------|
| `basic` | campaign, campaign_id, cost, conversions, clicks, impressions |
| `roas` | basic + roas_7d, iap_roas_7d |
| `cpi` | basic + average_cpa |
| `ir` | basic + conversion_rate |
| `cpp` | basic + first_purchase, cpp_0d |
| `creative` | campaign, creative_set, cost, conversions |
| `country` | campaign, country, cost, conversions, roas_7d |
| `full` | 所有可用列 |

## CLI 使用

```bash
# 通用查询
python3 cli.py query --start 2024-01-01 --end 2024-01-07 --columns full

# Campaign 数据
python3 cli.py campaigns --start 2024-01-01 --end 2024-01-07 --platform ios

# 素材组数据
python3 cli.py creatives --start 2024-01-01 --end 2024-01-07 --campaign-id 12345

# 分国家数据
python3 cli.py countries --start 2024-01-01 --end 2024-01-07

# 分析（只分析，不生成建议）
python3 cli.py analyze --start 2024-01-01 --end 2024-01-07 --type roas

# 分析并生成建议
python3 cli.py analyze --start 2024-01-01 --end 2024-01-07 --type all --suggest

# 整体出价分析
python3 cli.py bid-analysis \
  --campaign-id 1817245 \
  --start 2026-05-11 \
  --end 2026-05-17 \
  --potential-file potential_data.json

# 素材组4步分析
python3 cli.py creative-analysis \
  --campaign-id 1817245 \
  --start 2026-05-11 \
  --end 2026-05-17 \
  --volume-threshold 1200
```

## 依赖

- `apl-adjustment` skill：用于执行调整操作
- Reporting API Key：用于查询数据

## API 文档

https://support.axon.ai/zh/growth/promoting-your-apps/api/axon-reporting-api

## 认证

```bash
export APPLOVIN_REPORT_KEY="your_report_key"
```

**注意**：Reporting API Key 与 Campaign Management API Key 不同！
