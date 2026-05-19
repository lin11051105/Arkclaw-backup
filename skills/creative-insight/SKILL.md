---
name: creative-insight
description: "素材洞察分析：起量共性、跨地区偏好、爆款元素拓展、A面/B面分析"
metadata:
  hermes:
    tags: [ua, creative, insight, analysis, trends]
    related_skills: [dap-ua]
---

# 素材洞察分析

## 能力说明

| 能力 | 需求 | 触发方式 | 技术层级 |
|------|------|---------|---------|
| 起量素材共性分析 | 2.1 | cron 每周 + 手动 | L4 |
| 跨地区/语言/版位偏好分析 | 2.2 | cron 每周 + 手动 | L4 |
| 爆款核心元素 & 拓展建议 | 2.3 | cron 每周 + 手动 | L4 |
| A面/B面素材共性分析 | 2.4 | cron 每周 + 手动 | L4 |

## 触发条件

1. **定时触发（cron）**: 每周执行一次（如每周五 14:00）
2. **手动触发**: 飞书指令 "分析起量素材共性"、"看一下爆款元素"

## 执行步骤

### 一、起量素材共性分析（需求 2.1）

**输入**: `project_id`, `date_range`（默认近 2 周）, `channel`（可选）

**步骤**:

1. 筛选高消耗素材，按消耗降序查询投放数据，指定项目名、渠道、日期范围（近 14 天）、排序方式和数量上限
   从结果中筛选: 日耗 > $50 且 CPI < 目标值的素材

2. 查询素材的 AI 标签结果，获取标签列表、主要风格、钩子类型和 CTA 类型

3. 标签 × 效果交叉分析:
   ```
   对每个标签维度（题材/节奏/风格/元素）:
     计算各标签值的平均 CTR/CPI/ROI
     排序发现正相关（高 CTR/低 CPI）的标签组合
   ```

4. LLM 提炼共性规律:
   - 输入: 标签 × 效果数据 + 品类知识
   - 输出: 可复制的成功因子 + 创意生产建议

5. 推送飞书洞察报告
6. 沉淀素材规律到 MEMORY.md

### 二、跨地区/语言/版位偏好分析（需求 2.2）

**输入**: `project_id`, `date_range`, `dimensions`（region/language/placement）

**步骤**:

1. 按地区/语言/版位聚合素材效果数据
2. 查询各地区的素材标签分布
3. 交叉分析: 不同地区/版位的素材偏好差异
   ```
   例: US 地区偏好强冲突开场（CTR +30% vs 平均）
       JP 地区偏好角色展示（CTR +20% vs 平均）
   ```
4. LLM 生成偏好结论和新素材定向测试建议
5. 推送飞书报告
6. 沉淀到 MEMORY.md

### 三、爆款核心元素 & 拓展建议（需求 2.3）

**输入**: `project_id`, `date_range`, `top_n`（分析的爆款数量，默认 10）

**步骤**:

1. 筛选爆款素材（引用 `thresholds.json` 中 `winner_creative` 参数）:
   ```
   爆款 = thresholds.winner_creative.calculation_months 个月内
          累计消耗 >= thresholds.winner_creative[project][creative_type]
   同一短名不分渠道/尺寸/时长统一计算
   ```
2. 查询爆款素材的 AI 标签和结构化元素
3. 提取可复用元素（人物设定、冲突结构、利益点表达、镜头语言）
4. LLM 结合品类知识和竞品数据生成拓展方向
5. 推送飞书报告: 爆款素材列表 + 核心元素 + N 个拓展方向
6. 沉淀到 MEMORY.md

### 四、A面/B面素材共性分析（需求 2.4）

**输入**: `project_id`, `date_range`

**步骤**:

1. 拉取素材效果数据（CTR, ROI, 留存率）
2. 分类素材:
   - **A 面素材**: CTR 排名 Top 20%（拉新力强）
   - **B 面素材**: ROI/留存 排名 Top 20%（付费/留存好）
3. 分别分析两类素材的标签分布和共性元素:
   ```
   A 面共性: 强冲突开场、大字卖点、快节奏剪辑
   B 面共性: 玩法深度展示、角色养成、策略性叙事
   ```
4. LLM 对比分析: 交叉发现既拉新又付费的元素
5. 推送飞书 A/B 面分析报告:
   - A 面素材共性（高 CTR 的有效元素）
   - B 面素材共性（高 ROI/留存的有效元素）
   - 交叉发现
   - 策略建议（A 面负责拓量、B 面负责收口）
6. 沉淀到 MEMORY.md

## 输入/输出

### 输入参数

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `project_id` | string | 项目 ID | 必填 |
| `channel` | string | 渠道 | 全渠道 |
| `date_range` | string | 分析时段 | 近 2 周 |
| `dimensions` | string | 聚合维度 | region |
| `top_n` | number | 爆款分析数量 | 10 |

### 输出

| 场景 | 推送方式 | 频率 |
|------|---------|------|
| 起量共性 | 飞书报告 | 每周 |
| 地区偏好 | 飞书报告 | 每周 |
| 爆款元素 | 飞书报告 | 每周 |
| A/B 面分析 | 飞书报告 | 每周 |

## 安全规则

1. 洞察仅为**建议参考**，创意方向最终由创意团队决策
2. AI 标签分析依赖模型质量，报告需注明**置信度**
3. 分析结论需**附带数据佐证**

### 五、素材×账号异常分析

**输入**: `project_id`, `date_range`

**目的**: 发现同一素材在不同广告账号下效果差异巨大的异常情况，定位受众饱和、地区适配、iOS 结构性问题等。

**步骤**:

1. 通过 DAP `query_material_report` 获取素材级数据（CPI/ROAS/安装）
2. 通过 ads-channel `account-info --all` 获取活跃 Meta 账号列表
3. 逐账号调用 ads-channel `get-insights --level ad`（串行，间隔 2-5 秒）
4. 从 `ad_name` 提取素材 ID（正则: `_(\d{5,8})(?:\.\w+)?$`）
5. JOIN 素材报告数据，计算每个素材在各账号的 CPI 与均值的比值
6. 异常检测:
   - **爆款效果差**: 账号 CPI > 素材均值 × 2 → 受众饱和/竞价环境/iOS/VO出价
   - **非爆款效果好**: 账号 CPI < 素材均值 × 0.4 且安装≥20 → 小账号红利/地区匹配
7. LLM 综合分析原因并给出素材×账号优化建议

**限制**: 仅 Meta 渠道可用，需 ads-channel Facebook 适配器。详见 dap-ua skill 的"素材×账号交叉分析"章节。

**实战经验（2026-04 ROK 分析积累）**:

1. **大账号查询超时**: 超过 1000 条 ad 的账号（如 Cyberklick_iOS 1900+ ads）需按 3 天日期窗口分段查询，每段设 180s timeout，最后 merge JSON 数组。不要一次拉全量。
2. **CPI 差异的根因多是 Campaign 策略，非素材质量**:
   - LTV 定向账号（LALltv50%、全项目ltv30%）天然 CPI 高 3-5x，但 ROAS 可能更高
   - pltv14multi 类低门槛 Campaign 让任何素材都能跑出 $1-2 CPI，容易产生"非爆款表现好"的假象
   - 判定素材效果差/好时，必须控制 Campaign 类型和地区变量，否则结论无意义
3. **分析框架**:
   - 爆款效果差：先看是不是 LTV 定向/iOS 结构性高成本/地区不匹配，再判定是否真差
   - 非爆款效果好：先排除 Android 低门槛 Campaign 和 VN 等低 CPI 地区的"天然优势"
   - 最终要比 ROAS 而非 CPI——CPI 高但 ROAS 也高说明用户质量好，不应优化掉
4. **老素材在越南等新兴市场疲劳周期更长**，可大胆回收历史素材测试

## 辅助脚本

起量筛选、爆款筛选、标签交叉分析和 A/B 面分类由 `scripts/` 下的 Python 脚本完成。Agent通过 CLI 调用脚本，读取输出 JSON，然后生成飞书洞察报告。

**CLI 入口**: `python workspace/skills/creative-insight/scripts/cli.py <子命令> [参数]`

| 子命令 | 用途 | CLI 示例 |
|--------|------|---------|
| `volume` | 起量素材筛选 | `cli.py volume --project ROK --start 2026-04-01 --end 2026-04-14` |
| `winners` | 爆款素材筛选 | `cli.py winners --project ROK --start 2026-04-01 --end 2026-04-14` |
| `tags` | 标签 × 效果交叉分析 | `cli.py tags --project ROK --start 2026-04-01 --end 2026-04-14 --metric ctr` |
| `ab-face` | A面/B面素材分类 | `cli.py ab-face --project ROK --start 2026-04-01 --end 2026-04-14` |

CLI 自动加载 config（apps.json + thresholds.json）、构建 DAP 回调、执行脚本、JSON 输出到 stdout。
