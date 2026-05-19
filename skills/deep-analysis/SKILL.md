---
name: deep-analysis
description: "深度数据分析与策略建议：多维对比、渠道归因、A/B 分析、预算分配"
metadata:
  hermes:
    tags: [ua, analysis, attribution, budget, strategy]
    related_skills: [dap-ua]
---

# 深度数据分析与策略建议

## 能力说明

| 能力 | 需求 | 触发方式 | 技术层级 |
|------|------|---------|---------|
| 深度数据对比分析 | 5.1 | 手动 | L4 |
| 渠道成长深度归因 | 5.2 | 手动 | L4 |
| Campaign 变量 A/B 分析 | 5.3 | 手动 | L3 |
| 预算分配建议 | 5.4 | cron 月度 + 手动 | L3 |

## 触发条件

1. **手动触发**: 飞书指令 "分析 US 区 CPI 上涨原因"、"对比 Campaign A 和 B"、"建议下月预算分配"
2. **定时触发（cron）**: 预算分配建议每月生成
3. **被 monitoring-alerts 触发**: 异常归因后需要深入分析时

## 执行步骤

> **⚠️ 必须使用下方每节标注的 CLI 命令执行，不要自己拆解步骤或发明流程。** CLI 命令已封装完整逻辑，直接运行即可。

### 一、深度数据对比分析（需求 5.1）

**输入**: `project_id`, `channel`, `period_a`/`period_b`（对比时段）, `dimensions[]`（分析维度: Pub/版位/国家/素材）

**步骤**:

1. 通过 DAP 拉取两个时段的多维度指标:
   - 查询时段 A 的素材维度投放数据，指定项目名、渠道和日期范围
   - 查询时段 B 的素材维度投放数据，指定项目名、渠道和日期范围
   - 查询多维归因数据，按 Pub/版位/素材等维度拆分

2. 按维度分解指标变动的贡献度:
   ```
   对每个维度值:
     contribution = (dim_value_period_b - dim_value_period_a) / total_delta × 100%
   ```

3. 定位主要贡献来源: 哪些 Pub/版位/素材贡献了最大变动

4. LLM 生成分析报告:
   - 输入: 贡献度分解数据 + 历史记忆中的类似分析
   - 输出: 归因结论 + 策略建议

5. 推送飞书:
   ```
   📈 深度对比分析 — 项目XX, Meta 渠道
   时段: 本周 vs 上周

   CPI 变化: $2.0 → $2.5（+25%）
   
   贡献度分解:
   | 维度 | 变化 | 贡献度 |
   | Pub A | CPI +40% | 贡献 60% |
   | 版位 Feed | CPI +15% | 贡献 25% |
   | 素材 XX | CPI +30% | 贡献 15% |
   
   归因: Pub A 的竞争加剧导致 CPM 上升...
   建议: 1. 减少 Pub A 占比 2. 增加新版位测试
   ```

6. 沉淀策略结论到 MEMORY.md

### 二、渠道成长深度归因（需求 5.2）

**输入**: `project_id`, `channel`, `date_range`

**步骤**:

1. 通过 DAP 按层级拉取数据: 国家 → 版位 → Pub → 素材
2. 逐层计算增量贡献和质量指标:
   ```
   第一层: 哪个国家贡献了最多增量/最大下降
   第二层: 该国家下哪个版位是关键
   第三层: 该版位下哪些 Pub 变化最大
   第四层: 这些 Pub 下的素材效果如何
   ```
3. 定位增长卡点:
   - 流量问题: CPM 上升 / 竞争加剧
   - 素材问题: CTR 下降 / 素材疲劳
   - 转化链路问题: CVR 下降 / 落地页问题
4. LLM 生成增长卡点分析和修复优先级
5. 推送飞书报告
6. 沉淀到 MEMORY.md

### 三、Campaign 变量 A/B 分析（需求 5.3）

**输入**: `campaign_ids[]`, `variable`（audience/bid_strategy/optimization_goal/creative_pack）, `date_range`

**步骤**:

1. 通过 DAP 拉取指定 Campaign 的效果数据
2. 按变量维度隔离效果差异（控制其他变量）:
   ```
   例: 对比 Broad vs 兴趣定向
   - Campaign A: Broad, CBO $500, US
   - Campaign B: 兴趣定向, CBO $500, US
   → 变量: audience, 控制变量: budget, country
   ```
3. 计算各变量水平的指标差异（CPI, ROI, CTR, CVR）
4. LLM 评估统计显著性和总结最优策略
5. 推送飞书 A/B 分析报告
6. 可复用的投放模板沉淀到 MEMORY.md

### 四、预算分配建议（需求 5.4）

**输入**: `project_ids[]`（可选），`total_budget`, `roi_target`, `date_range`

**步骤**:

1. 通过 DAP 拉取各渠道/项目的历史 ROI 曲线和 LTV 数据:
   - 拉取 ROI 自定义报表数据，指定报表 ID 和日期范围（近 30 天）
   - 查询 LTV 数据，获取各渠道按安装日期归因的累计价值曲线

2. 计算各渠道/项目的边际 ROI:
   ```
   marginal_roi = Δ revenue / Δ spend（每增加 $100 预算的 ROI 变化）
   计算粒度: 渠道级
   回溯窗口: 近 30 天
   ```

3. 约束优化:
   ```
   目标: maximize total_revenue
   约束1: total_spend <= total_budget
   约束2: overall_roi >= roi_target
   方法: 按边际 ROI 从高到低分配预算
   ```

4. LLM 生成三层配比建议:
   - 保底盘（~60%）: 历史证明稳定 ROI 达标的渠道/项目
   - 增长盘（~25%）: 边际 ROI 高、有增长空间的渠道/项目
   - 试验盘（~15%）: 新渠道/新地区/新策略测试预算

5. 推送飞书预算分配建议报告
6. 注明: **预算调整需人工确认后执行**

## 输入/输出

### 输入参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `project_id` | string | 项目 ID |
| `channel` | string | 渠道 |
| `period_a`/`period_b` | string | 对比时段 |
| `dimensions[]` | string[] | 分析维度 |
| `campaign_ids[]` | string[] | A/B 对比的 Campaign |
| `variable` | string | A/B 分析变量 |
| `total_budget` | number | 总预算 |
| `roi_target` | number | 回本目标 |

### 输出

| 场景 | 推送方式 | 内容 |
|------|---------|------|
| 对比分析 | 飞书报告 | 贡献度分解 + 归因 + 建议 |
| 渠道归因 | 飞书报告 | 逐层拆解 + 卡点定位 |
| A/B 分析 | 飞书报告 | 变量对比 + 最优策略 |
| 预算建议 | 飞书报告 | 三层配比 + 边际 ROI |

## 安全规则

1. 分析结果仅为建议，**预算调整需人工确认后执行**
2. 报告需注明**数据来源、时段和计算口径**
3. 策略建议需**附带数据佐证**，不做无依据推荐
4. 不直接执行任何预算调整操作

## 辅助脚本

贡献度分解和边际 ROI 计算由 `scripts/` 下的 Python 脚本完成。Agent通过 CLI 调用脚本，读取输出 JSON，然后生成飞书报告。

**CLI 入口**: `python workspace/skills/deep-analysis/scripts/cli.py <子命令> [参数]`

| 子命令 | 用途 | CLI 示例 |
|--------|------|---------|
| `contribution` | 多维贡献度分解 | `cli.py contribution --project ROK --period-a-start 2026-04-01 --period-a-end 2026-04-07 --period-b-start 2026-04-08 --period-b-end 2026-04-14` |
| `budget` | 边际 ROI & 预算分配建议 | `cli.py budget --project ROK --total-budget 10000 --roi-target 2.5` |

CLI 自动加载 config（apps.json + thresholds.json）、构建 DAP 回调、执行脚本、JSON 输出到 stdout。
