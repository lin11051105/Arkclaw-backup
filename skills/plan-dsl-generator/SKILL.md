---
name: plan-dsl-generator
description: "自然语言 → Plan DSL：将用户意图分解为原子 DSL 元素并组装成合法 Plan DSL JSON"
metadata:
  hermes:
    tags: [ua, plan, dsl, generator]
---

# Plan DSL 生成器

## 能力说明

接收用户的自然语言业务需求，将其**分解为原子 DSL 元素**（plan type / action 名 / 表达式 / 节点类型），再按协议规则**组装成**合法的 Plan DSL JSON，最终 POST 提交到 Plan 引擎。

覆盖 32 条业务需求对应的全部场景，包括：
- A 类监控：素材衰退关停、Campaign 衰退、库存预警、消耗监控等（定时自动执行）
- B 类指令：Campaign 搭建、素材扩量、SOP 校验、链路测试、深度分析等（用户手动触发）
- C 类报表：日报、周报、月报、对账（定时生成推送）
- D 类管线：AI 素材测试、AB 测试（多阶段长流程）

**协议参考**：执行本 Skill 前，读取 `workspace/skills/plan-dsl-generator/dsl-reference.md` 作为 DSL 生成的完整参考。

---

## 触发条件

用户飞书消息中出现以下意图时触发：

- "帮我设置一个监控 / 告警 / 预警"
- "帮我搭 / 创建 / 新建一个 Campaign / 广告"
- "帮我扩量 / 复制到其他账户"
- "帮我生成 / 拉一下日报 / 周报 / 月报"
- "帮我跑一个 AB 测 / 素材测试"
- "帮我做一个分析 / 归因"
- "帮我检查 / 验证 SOP / 链路"
- 以及其他明确包含"自动执行"意图的指令

---

## 执行步骤

### Step 1：意图分解（Decompose）

从用户输入中逐一提取以下每个问题的答案，每个答案对应 DSL 中的一个或多个原子元素。

**① 任务性质 → plan.type + 执行模式**

| 用户说的关键词 | plan.type | 执行模式 |
|-------------|-----------|---------|
| 素材衰退/关停/暂停不达标素材 | `creative_decay` | A 监控 |
| Campaign/AdSet 衰退/降预算 | `campaign_decay` 或 `optimization` | A 监控 |
| 素材可用量/库存/爆款数量 | `creative_inventory` | A 监控 |
| 日常投放监控/消耗异常/余额不足/回传中断/数据Gap/ROI进度 | `alert` | A 监控 |
| 搭 Campaign/新建广告 | `campaign_launch` | B 指令 |
| 素材扩量/复制到其他账户 | `creative_scale` | B 指令 |
| SOP 检查/投放前校验 | `sop_check` | B 指令 |
| 链路测试/事件回传验证 | `link_test` | B 指令 |
| 素材合规检查 | `analysis` | B 指令 |
| 起量共性/爆款元素/地区偏好/A面B面分析/归因/对比 | `analysis` | B 指令 |
| 竞品追踪 | `analysis` | B 指令 |
| 预算分配建议 | `analysis` | B 指令 |
| 日报/周报/月报/数据报表 | `report` | C 报表 |
| 月度对账/结算单 | `reconciliation` | C 报表 |
| AI素材测试/AB测试管线 | `creative_ab_test` | D 管线 |

**② 触发方式 → trigger.kind**

| 信号 | trigger.kind |
|------|-------------|
| "每天/每周/定时/自动监控/自动执行" | `schedule` |
| "帮我现在/立刻/马上" 或 无时间词 | `api` |
| 被其他流程调用（管线中间步骤） | `sub_plan` |

**③ 操作实体 → trigger.scope.entity_type**（仅 schedule 触发时）

| 用户说的 | entity_type |
|---------|------------|
| 素材/视频/图片/creative | `creative` |
| Campaign/广告活动 | `campaign` |
| AdSet/广告组 | `adset` |
| 账户/account | `account` |
| 项目/产品/整体 | `project` |

**④ 筛选条件 → trigger.scope.selector**（仅 schedule 触发时）

从用户描述的前置条件中提取，转成 selector 语法。常见对应：

| 用户描述 | selector 片段 |
|---------|--------------|
| 在投/投放中/active 的 | `status = 'active'` |
| 上线 N 天以上 | `online_days >= N` |
| 日耗超过 X 的 | `daily_spend > X` |
| 还没暂停的/没被处理的 | `tags NOT CONTAINS '<处理标签>'` |

**⑤ 需要拉什么数据 → query action 节点**

| 数据需求 | action |
|---------|--------|
| 素材分日 CTR/CPI/ROI 时序 | `query_creative_performance`（group_by: ["date"]） |
| Campaign/AdSet 分日效果 | `query_attribution`（dimensions: ["campaign"] 或 ["adset"]） |
| 安装数 | `query_installs` |
| 收入/LTV | `query_revenue` 或 `query_ltv` |
| 账户余额 | `query_account_balance` |
| 消耗进度 | `query_spend_progress` |
| 回传状态 | `query_postback_status` |
| 素材库存 | `query_creative_inventory` |
| 素材疲劳度/衰退决策 | `query_creative_fatigue`（含 fatigue_score/decision） |
| 素材列表 | `query_creative_assets` |
| 合规结果 | `query_compliance_result` |
| AI 标签 | `query_ai_tags` |
| 短名汇总 | `query_shortname_summary` |
| 报表数据（日/周/月） | `compose_report_data` |
| ROI 进度 | `query_roi_progress` |
| CPE 达成率 | `query_cpe_achievement` |

**⑥ 判定条件 → condition 节点的 if 表达式**

从用户描述的触发条件中提取，转成表达式。常见对应：

| 用户描述 | 表达式模式 |
|---------|----------|
| 连续 N 天 ROI 低于目标 X% | `consecutive_below(extract_field($ctx.fetch.rows,'roi'), $config.target_roi * 0.XX) >= N` |
| 连续 N 天 CPI 高于目标 X% | `consecutive_above(extract_field($ctx.fetch.rows,'cpi'), $config.target_cpi * 1.XX) >= N` |
| ROI/CPI 持续下滑 | `trend_decline(extract_field($ctx.fetch.rows,'roi'), 3, 3)` |
| 消耗进度偏差超过 X% | `abs($ctx.fetch.rows[0].progress_pct - $ctx.fetch.rows[0].expected_progress_pct) > $config.spend_progress.deviation_alert_pct` |
| 余额不足 N 天 | `$ctx.fetch.accounts[0].coverage_days < $config.account_balance.warning_days` |
| 指标超过同期 P80 | `$entity.ctr > percentile($ctx.fetch_cohort.cohort_ctr, 80)` |
| 库存低于安全线 | `$ctx.fetch.below_safety_line == true` |

**注意**：具体阈值数字**不从用户输入读取，全部引用 `$config.*`**。

**action 输入类型规范**：当 action 期望 `asset_ids`（ID 字符串数组）时，不能直接传 `$ctx.xxx.items`（对象数组），必须用 `extract_field($ctx.xxx.items, 'id')` 提取 ID 列表。

**⑦ 满足条件后的操作 → then 分支的 action 节点**

| 用户说的操作 | action |
|------------|--------|
| 暂停/关停素材/Campaign/AdSet | `update_entity_status`（status: "pause"） |
| 恢复/重新投放 | `update_entity_status`（status: "resume"） |
| 降预算/减少预算 | `update_budget` |
| 通知/告警/推送 | `notify` |
| 扩量/复制到其他账户 | `create_campaign` + `create_adset` + `create_ad`（foreach） |
| 打标/标记 | `tag_entity` |
| 记录 | `write_lifecycle_action` |
| 提交合规检测 | `submit_compliance_check` |
| 提交 AI 打标 | `submit_ai_tagging` |
| SOP 检查 | `run_sop_checklist` |
| 链路测试 | `run_link_test` |
| LLM 分析/解读/归因建议 | agent 节点（task 按场景选择） |
| 渲染报表 | `render_report` |
| 生成结算单 | `render_settlement` |

**⑧ 是否需要人工审批 → yield:approval**

满足以下任一条件，则在写操作之前插入 `yield:approval` 节点：
- 操作类型是"创建"（create_campaign / create_adset / create_ad）
- 操作类型是"扩量到新账户"
- risk_level 推断为 high 或 critical
- 用户未明确说"自动执行"

**⑨ 是否需要遍历 → foreach / parallel 节点**

| 信号 | 节点 |
|------|------|
| "每个素材/对每个Campaign" 或 items 是数组 | `foreach` |
| "同时/并行拉多个渠道/多个维度" | `parallel` |
| "每个素材分别测试，测完再..." | `foreach`（顺序） |
| "同时拉 Meta 和 TikTok 数据" | `parallel` |

**foreach 在 parallel 中的结构规则**：
- parallel 的 `branches` 数组中，每个分支必须是节点数组 `[...]`
- 即使分支只包含一个 foreach 节点，也必须写为 `[{ foreach }]`，不能省略外层数组
- **禁止**：parallel 内跨分支引用 `$ctx`（分支并行执行，引用另一分支的输出会读到 null）

**⑩ 是否需要 LLM 分析 → agent 节点**

| 用户说 | agent task |
|-------|-----------|
| 分析原因/归因/为什么 | `trend_attribution` 或 `anomaly_diagnosis` |
| 报表解读/总结/摘要 | `report_narrative` |
| 素材建议/创意方向 | `creative_brief` 或 `material_insight` |
| 策略建议/下一步怎么做 | `strategy_advice` |

---

### Step 2：识别缺口（Gap Check）

**只有以下 4 个意图无法推断时才追问用户，其他意图不追问：**

| 意图 | 追问条件 | 追问示例 |
|------|---------|---------|
| **触发方式** | 无法从语气判断是"持续监控"还是"现在执行一次" | "这个需求是设置成定时自动监控，还是你现在手动触发一次？" |
| **监控实体类型** | schedule 触发，但"素材""Campaign""账户"级别不明确 | "是监控素材级别的数据，还是 Campaign 级别的？" |
| **plan.type** | 自然语言对应 2 种以上可能的 type | "你说的'分析素材表现'，是要分析起量共性规律、地区偏好、还是爆款元素拓展方向？" |
| **核心操作** | 条件成立后该做什么完全无法推断 | "检测到异常后，是自动暂停、降预算，还是只发告警给你确认？" |

**以下意图不追问，直接处理：**

| 意图 | 处理方式 |
|------|---------|
| 判定阈值（ROI低多少算衰退） | 引用 `$config.*`，不追问 |
| 定时几点运行 | 默认 `"0 10 * * *"`（每天上午10点） |
| 回看天数等数值参数 | 在 params 段声明 `default`（默认14天） |
| risk_level | 按操作类型推断（创建/花钱=high，暂停=low，只读=low） |
| auto_approve | 按 risk_level 推断（high → false，low+monitor → true） |
| notify severity | 按操作重要性推断（暂停=P1，报表=P2，异常=P0/P1） |
| B类指令的 account_id / project_id 等 | 声明为 `$params.xxx`，不阻断 DSL 生成 |
| 爆款/winner 素材定位 | 使用 `query_creative_assets(tag=winner)` 或 `$entity.is_winner == true` 自动发现，不要求用户手动列举 |

---

### Step 3：组装 DSL（Assemble）

按以下顺序填充 JSON：

**① 填 Meta**

```json
{
  "dsl_version": 1,
  "plan": {
    "type": "<Step1①的结论>",
    "name": "<简洁描述，40字内>",
    "source": "<schedule触发→system:monitor，用户触发→agent:local>",
    "reason": "<B类/D类必填，A类/C类可不填>",
    "trigger": "<Step1②③④的结论>",
    "risk_level": "<按Step1⑧推断>",
    "auto_approve": "<按risk_level推断>"
  }
}
```

**② 填 Params**

只声明"调用方需要在运行时传入的参数"。以下情况需要声明：
- B 类指令中用户指定的具体对象（creative_id / account_id / campaign.name 等）
- 可选的配置参数（lookback_days / duration / budget_ratio 等，加 default）
- A 类监控中允许覆盖默认值的参数（如 lookback_days）

阈值参数**不放 params**，走 `$config.*`。

**③ 填 Nodes（按执行模式套对应骨架）**

**A 类监控骨架：**
```
1. action（id="fetch"）：query 类 action，拉时序或聚合数据
2. condition（id="check"）：
     if: 时序函数 + $config 阈值
     then:
       a. write action（update_entity_status 或 update_budget）+ idempotency_key
       b. tag_entity（打"已处理"标签，与 selector 的 NOT CONTAINS 配合防重复）
       c. write_lifecycle_action（审计）
       d. notify（severity 按严重程度）
```

**B 类指令骨架：**
```
1. [compute action]：推导结构/校验参数（如 compute_test_structure）
2. yield: approval（risk_level >= medium 时）
     template: 对应审批模板
     summary: 关键参数摘要
3. write action（主操作）+ idempotency_key
4. [foreach → write action]：批量创建时
5. notify(P2)：完成通知
```

**C 类报表骨架：**
```
1. action（id="fetch"）：compose_report_data 或多个 query action
2. action（id="render"）：render_report
3. [agent（optional=true）]：report_narrative（LLM 解读）
4. notify(P2)：data.report_body="$ctx.render.content"
```

**D 类管线骨架：**
```
1. sub_plan：tpl_campaign_launch_v1（搭测试 Campaign）
2. yield: timer：duration="$params.duration"
3. foreach（items="$params.asset_ids"，parallel=true）：
     a. query action（id="perf"）：测量结果
     b. condition：
          then（达标）：tag_entity(winner) + notify(P1)
          else_if（一般通过）：tag_entity(ab_passed)
          else（未通过）：update_entity_status(pause) + write_lifecycle_action(archive)
```

**④ 关键规则检查（组装时逐项确认）**

- 所有 `create_*` / `update_budget` 节点都带 `idempotency_key`
- `update_entity_status` 也带 `idempotency_key`（格式：`concat('<动作>:', $entity.id, ':', today())`）
- A 类监控的 selector 加防重复标签过滤（`tags NOT CONTAINS 'xxx'`），then 末尾打对应标签
- 阈值全部引用 `$config.*`，不写具体数字
- `$ctx.<node_id>` 引用的 node_id 必须在当前节点前面已出现
- B 类指令的 `auto_approve` 必须为 `false`
- **Action 名合法性**：所有 action 必须在 `dsl-reference.md` Section 7 Registry 中存在；若场景需要尚未定义的 action，在 DSL 中标注 `"_draft": true` 并在说明中注明 🔴，不能假装它已存在
- **Agent task 合法性**：agent 节点的 `task` 字段只能是以下 6 个枚举之一：`trend_attribution` / `report_narrative` / `creative_brief` / `strategy_advice` / `anomaly_diagnosis` / `material_insight`，禁止自创 task 名
- **表达式函数合法性**：condition 的 `if` 和 action 的 `input` 表达式中，只能使用 `dsl-reference.md` Section 5 列出的内置函数和操作符，不能自创函数
- **yield 类型选择**：等待外部异步任务（AI 打标 / 合规检测 / 链路测试）完成 → `yield:signal`；固定时长等待（AB 测试跑满 N 天）→ `yield:timer`；涉资操作前审批 → `yield:approval`
- **trigger.scope 适用性**：scope 仅用于 A 类监控逐实体巡检；B 类指令、C 类报表、项目级查询的 A 类监控不使用 scope
- **notify severity 规范**：B 类分析指令结果 → P2（信息级报告）；A 类监控告警 → P1；管线中断 / 账户封禁 / 回传断裂 → P0
- **foreach 在 parallel 中的结构**：parallel 的 branches 中，每个分支必须包裹在 `[...]` 数组中，即使只有一个节点

---

### Step 4：校验 DSL

生成 DSL JSON 后，**必须**将其通过校验脚本检查：

```bash
echo '<生成的 DSL JSON>' | python workspace/skills/plan-dsl-generator/scripts/validate_dsl.py
```

校验脚本会自动完成：
1. **JSON 格式修复**：补全缺失的 `}` `]`、移除尾部逗号、从 markdown 代码块提取等
2. **DSL 语义校验**：检查 plan.type / action 名 / agent task / yield 类型 / parallel 分支结构是否合法

**处理校验结果**：
- `valid: true` + `repaired: false` → 直接使用
- `valid: true` + `repaired: true` → 使用修复后的 `dsl` 字段输出，告知用户已自动修复
- `valid: false` → 根据 `errors` 列表修正 DSL 后重新校验，直到通过

---

### Step 5：展示 DSL

向用户说明关键决策，然后给出**校验通过后**的 DSL：

```
根据你的描述，我理解为：
- 任务类型：<plan.type 及一句话说明>
- 触发方式：<schedule/api + 频率>
- 执行逻辑：<1-2句核心节点链路描述>
- 审批要求：<是否需要人审>

生成的 Plan DSL：

[DSL JSON]
```

---

### Step 6：提交 Plan 引擎

展示 DSL 后，将其 POST 到 Plan 引擎进行执行验证。

**提交命令**：

```bash
curl -s -X POST http://172.24.176.1:8000/api/v1/plans \
  -H "Content-Type: application/json" \
  -d '{"dsl": <校验通过的 DSL JSON>}'
```

**如果 DSL 包含 `$params` 参数（B 类指令）**，需要在请求中补充 `params_override`，将用户提供的具体参数值传入：

```bash
curl -s -X POST http://172.24.176.1:8000/api/v1/plans \
  -H "Content-Type: application/json" \
  -d '{"dsl": <DSL JSON>, "params_override": {<用户提供的参数键值对>}}'
```

**解读引擎响应**：

| 返回字段 | 含义 | 处理方式 |
|---------|------|---------|
| `state: "completed"` | 执行成功 | 告知用户"Plan 已通过引擎验证并模拟执行成功"，摘要展示关键 `ctx` 输出 |
| `state: "paused"` | 执行到 yield 节点暂停 | 告知用户"Plan 已暂停，等待审批/信号"，展示 `yield_info` 中的 `yield_type` 和 `summary` |
| `state: "invalid"` | DSL 校验不通过 | 展示 `validation_errors` 列表，根据错误修正 DSL 后重新提交 |
| `state: "failed"` | 执行过程出错 | 展示 audit_log 中最后一条 `status=failed` 的错误信息，分析原因并修正 |
| `validation_warnings` | 非阻塞警告 | 列出警告供用户参考，不阻断 |

**向用户反馈时的格式**：

```
引擎验证结果：<completed / paused / invalid / failed>

[如果 completed]
✅ Plan 模拟执行成功，共执行 N 个节点。
关键输出：<从 ctx 中提取 1-3 个关键结果摘要>

[如果 paused]
⏸️ Plan 执行到审批节点暂停，等待 <approval/signal>。
Plan ID: <plan_id>
审批摘要：<yield_info.summary>
可通过 POST /api/v1/plans/<plan_id>/approve 继续执行。

[如果 invalid]
❌ DSL 校验未通过：
<逐条列出 validation_errors>
→ 正在修正后重新提交...

[如果 failed]
❌ 执行失败：<错误原因>
→ 正在分析并修正...
```

**自动修正规则**：
- `state: "invalid"` 时，根据 `validation_errors` 逐条修正 DSL，重新从 Step 4（校验）开始，最多重试 2 次
- `state: "failed"` 时，检查 `audit_log` 中失败节点的 `error` 字段，修正表达式或 input 后重新提交，最多重试 1 次
- 重试仍失败则展示最终错误，不再自动修改

---

## 各场景意图识别速查

以下是 32 条需求的自然语言触发信号与对应 plan.type 的快速对照，供意图分类参考：

| 用户说的关键词 | plan.type | 模式 |
|-------------|-----------|------|
| 素材测试/上传新素材/搭测试广告 | `campaign_launch` | B |
| 优质素材/吸量素材/扩量/复制到更多账户 | `creative_scale` | B |
| AI分类/视觉分层/自动测试素材 | `creative_ab_test` | D |
| 素材衰退/ROI低/CPI高/自动暂停 | `creative_decay` | A |
| 素材合规/风险评分/违规检查 | `analysis`（合规） | B |
| 素材库存/可用素材多少/爆款数量 | `creative_inventory` | A |
| 素材短名/命名规则/按short_name汇总 | `report`（素材） | C |
| 起量素材共性/为什么起量/爆款元素 | `analysis`（起量） | B |
| 地区偏好/哪个地区喜欢什么风格 | `analysis`（偏好） | B |
| 爆款拓展/基于爆款生成新方向 | `analysis`（拓展） | B |
| A面B面/吸量付费分层分析 | `analysis`（A/B面） | B |
| 竞品追踪/竞品头部素材 | `analysis`（竞品） | B |
| 渠道热点/TikTok热榜/Meta趋势 | `alert`（热点） | A |
| 搭Campaign/新建广告投放 | `campaign_launch` | B |
| SOP检查/投放前自查/新项目上线 | `sop_check` | B |
| 链路测试/事件回传/归因链路 | `link_test` | B |
| Campaign衰退/AdSet效果下滑 | `campaign_decay` | A |
| 日常监控/消耗/CPI/ROI异常告警 | `alert` | A |
| 数据异常归因/为什么CPI高了 | `analysis`（归因） | B |
| 大盘趋势/整体效果/趋势预警 | `alert`（趋势） | A |
| 数据Gap/DAP和前端数据对不上 | `alert`（Gap） | A |
| 回传中断/postback异常 | `alert`（回传） | A |
| 消耗进度/账户余额不足 | `alert`（余额） | A |
| 回本进度/ROI目标达成 | `alert`（ROI进度） | A |
| 深度分析/多维对比/周期对比 | `analysis`（深度） | B |
| 渠道成长/增长卡点/为什么没起量 | `analysis`（成长） | B |
| Campaign变量测试/AB测变量 | `analysis`（变量） | B |
| 预算分配/怎么分预算/边际ROI | `analysis`（预算） | B |
| CPE达成率/CPE点位 | `report`（CPE） | C |
| 渠道汇总/各渠道数据汇总 | `report`（渠道） | C |
| 日报/周报/月报/数据报告 | `report` | C |
| 月度对账/渠道账单/结算单 | `reconciliation` | C |

---

## 安全规则

1. **不生成删除操作**：只用 `update_entity_status(status=pause)`，不生成删除实体的 DSL
2. **涉资操作必须有审批**：任何包含 `create_*` 节点的 DSL，`auto_approve` 必须为 `false` 且包含 `yield:approval`
3. **阈值不硬编码**：condition 节点的 if 表达式中，数值阈值必须引用 `$config.*`，拒绝将用户说的"ROI低于5%"直接写成 `< 0.05`
4. **不猜测参数值**：B 类指令中 account_id / project_id 等运行时参数，声明为 `$params` 而不是猜一个值填进去
5. **提交失败不重试**：4xx 错误直接告知用户，不自动修改 DSL 重试
