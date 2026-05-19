# Plan DSL 速查参考

> 供 plan-dsl-generator Skill 生成 DSL 时使用。完整协议见 `docs/ua_dsl_protocol/`。

---

## 1. DSL 顶层结构

```json
{
  "dsl_version": 1,
  "plan": {
    "type": "<15种枚举之一>",
    "name": "<40字内>",
    "description": "<可选>",
    "source": "<来源>",
    "reason": "<B类指令必填>",
    "trigger": { ... },
    "risk_level": "<low|medium|high|critical>",
    "auto_approve": false,
    "dry_run": false,
    "timeout_seconds": 600,
    "params": { ... },
    "nodes": [ ... ]
  }
}
```

**`plan.type` 枚举（15种）**

| type | 用途 |
|------|------|
| `alert` | 预警推送（无写操作） |
| `creative_decay` | 素材衰退关停 |
| `campaign_decay` | Campaign/AdSet 衰退处理 |
| `creative_scale` | 优质素材扩量 |
| `creative_inventory` | 素材库存盘点 |
| `campaign_launch` | 搭建 Campaign |
| `sop_check` | 新项目 SOP 校验 |
| `link_test` | 链路测试 |
| `optimization` | 自动优化（预算调整等） |
| `report` | 日/周/月报 |
| `reconciliation` | 月度对账 |
| `analysis` | 深度分析/归因 |
| `creative_ab_test` | 素材 AB 测试 |
| `dco_pipeline` | DCO 管线 |
| `custom` | 动态图（无模板） |

**`source` 枚举**：`system:monitor` / `agent:local` / `agent:builtin` / `user:<uid>`

**`risk_level` 推断规则**：
- `low`：只读查询、只告警、暂停操作
- `medium`：降预算、打标签、写生命周期
- `high`：创建 Campaign/AdSet/Ad、扩量到新账户
- `critical`：跨账户大额预算操作

**`auto_approve` 推断规则**：
- `risk_level = low` 且 `source = system:monitor` → `true`
- `risk_level >= medium` 或 `source = agent:local` → `false`
- 没有 `template_id` 的动态图 → 强制 `false`

---

## 2. trigger 字段

```json
// A类监控：定时触发
{
  "kind": "schedule",
  "schedule": "0 10 * * *",
  "scope": {
    "entity_type": "creative",
    "selector": "status = 'active' AND online_days >= 7",
    "batch_size": 100
  }
}

// B类指令：API触发（用户发指令）
{ "kind": "api" }

// D类管线：被父Plan的sub_plan节点创建
{ "kind": "sub_plan", "parent_node_id": "n_1" }
```

**`entity_type` 枚举**：`creative` / `ad` / `adset` / `campaign` / `account` / `project`

**selector 语法**（SQL WHERE子集，字段省略 `$entity.` 前缀）：
- 比较：`=` `!=` `<` `<=` `>` `>=`
- 逻辑：`AND` `OR` `NOT`
- 集合：`IN ('a','b')` / `NOT IN (...)`
- 模糊：`LIKE 'hero_%'`
- 标签：`tags CONTAINS 'paused_decay'` / `tags NOT CONTAINS 'xxx'`
- 空值：`IS NULL` / `IS NOT NULL`
- **不支持函数调用和算术**

**scope 使用规则**：
- scope **仅用于** A 类监控中需要逐实体巡检的场景（如：遍历所有 active 素材检查衰退）
- B 类指令（api 触发）**不使用** scope——实体由 `$params` 指定
- C 类报表（schedule 触发但无实体遍历）**不使用** scope——项目级汇总查询，在 nodes 中通过 query action 直接拉数据
- A 类监控中的项目级查询（如素材库存盘点、数据 Gap 监控）也**不使用** scope——它们查的是项目聚合指标，不需要逐实体迭代

---

## 3. params 声明

```json
"params": {
  "lookback_days": {
    "type": "integer",
    "required": false,
    "default": 14,
    "min": 7,
    "max": 30,
    "description": "回看天数"
  },
  "creative_id": {
    "type": "string",
    "required": true,
    "description": "目标素材ID"
  },
  "target_accounts": {
    "type": "array",
    "required": true,
    "items": { "type": "string" },
    "description": "目标账户ID列表"
  }
}
```

**type 枚举**：`string` / `integer` / `number` / `boolean` / `array` / `object`

---

## 4. 变量系统（6种前缀）

| 前缀 | 来源 | 生命周期 | 示例 |
|------|------|---------|------|
| `$params` | API 调用时传入 | 整个 Plan | `$params.lookback_days` |
| `$config` | 项目级配置（thresholds.json） | 整个 Plan | `$config.target_roi` |
| `$ctx` | 前序节点的输出 | 节点执行完后可用 | `$ctx.fetch.rows` |
| `$entity` | 监控 Runner 注入的当前实体 | 当前 Plan | `$entity.cpi_14d` |
| `$item` | foreach 当前遍历元素 | foreach 迭代内 | `$item.id` |
| `$index` | foreach 当前索引（0-based） | foreach 迭代内 | `$index` |

**路径访问**：`$ctx.fetch.rows[0].cpi`，负索引 `$ctx.fetch.rows[-1]` 取最后一项，越界返回 `null`。

**常用 `$config` 字段**：

| 字段 | 含义 |
|------|------|
| `$config.target_cpi` | 目标 CPI |
| `$config.target_roi` | 目标 ROI |
| `$config.target_roas` | 目标 ROAS |
| `$config.target_retention_d7` | 目标 D7 留存 |
| `$config.cost_cap_daily` | 单账户日预算上限 |
| `$config.alert_recipients` | 告警接收群 |
| `$config.creative_decay.consecutive_days` | 衰退判定连续天数 |
| `$config.creative_decay.roi_below_target_pct` | ROI 低于目标的比例（如 0.92） |
| `$config.creative_decay.cpi_above_target_pct` | CPI 高于目标的比例（如 1.15） |
| `$config.campaign_decay.consecutive_days` | Campaign 衰退连续天数 |
| `$config.scale_candidate.volume.*` | 扩量候选阈值 |
| `$config.winner_creative.*` | 爆款素材阈值 |
| `$config.creative_inventory.safety_line` | 素材库存安全线 |
| `$config.daily_monitoring.spend_spike_pct` | 消耗异常波动阈值 |
| `$config.account_balance.warning_days` | 余额预警天数 |
| `$config.spend_progress.deviation_alert_pct` | 消耗进度偏差告警阈值 |
| `$config.roi_progress.deviation_alert_pct` | ROI 进度偏差告警阈值 |
| `$config.creative_inventory.winner_min_count` | 爆款素材最少数量 |
| `$config.compliance.high_risk_threshold` | 合规高风险阈值 |
| `$config.data_gap.install_gap_pct` | 安装数据 Gap 告警阈值 |
| `$config.postback.interrupt_minutes` | 回传中断判定分钟数 |
| `$config.trend_detection.window` | 趋势检测窗口天数 |
| `$config.trend_detection.consecutive_days` | 趋势确认连续天数 |
| `$config.a_b_side.ctr_top_pct` | A面 CTR 阈值百分位 |
| `$config.a_b_side.retention_d7_min` | B面 D7 留存最低标准 |
| `$config.cpe.achievement_rate_alert_pct` | CPE 达成率告警阈值 |
| `$config.budget_adjustment.auto_max_reduction_pct` | 自动降预算最大幅度 |

---

## 5. 表达式与内置函数

**操作符**（优先级从低到高）：`OR` → `AND` → `NOT` → 比较（`==` `!=` `<` `>` `<=` `>=`）→ `IN/NOT IN` → `+` `-` → `*` `/` `%`

**注意**：字符串拼接必须用 `concat(a, b)`，禁止用 `+`。

**时序函数**（A类监控核心）：

| 函数 | 说明 |
|------|------|
| `consecutive_below(series, threshold)` | 从末尾起连续低于阈值的天数 |
| `consecutive_above(series, threshold)` | 从末尾起连续高于阈值的天数 |
| `consecutive_decline(series)` | 从末尾起连续环比下降天数 |
| `trend_decline(series, window, consecutive)` | 移动均值连续 N 天下降 → boolean |
| `trend_increase(series, window, consecutive)` | 移动均值连续 N 天上升 → boolean |
| `rolling_avg(series, window)` | 滚动均值 → array |

**统计函数**：

| 函数 | 说明 |
|------|------|
| `percentile(values, pct)` | 百分位数，pct 为 0-100 |
| `avg(values)` | 均值 |
| `sum(values)` | 求和 |
| `min(values)` / `max(values)` | 最小/最大值 |
| `count(values)` | 数组长度 |
| `stddev(values)` | 标准差 |

**日期函数**：

| 函数 | 说明 | 示例 |
|------|------|------|
| `today()` | 当前日期 YYYY-MM-DD | `today()` |
| `now()` | 当前时间戳 ISO8601 | `now()` |
| `days_since(ts)` | 距今整天数 | `days_since($entity.created_at)` |
| `date_offset(date, offset)` | 日期偏移 | `date_offset(today(), '-14d')` |
| `days_between(ts_a, ts_b)` | b - a 的整天数 | — |

**通用函数**：

| 函数 | 说明 |
|------|------|
| `extract_field(arr, 'field')` | 从对象数组提取字段值数组，`consecutive_*` 的必要前置 |
| `concat(a, b, ...)` | 字符串拼接，所有类型自动转 string |
| `coalesce(a, b, ...)` | 返回第一个非 null 参数 |
| `contains(arr, x)` | 数组包含检查 → boolean |
| `len(x)` | 数组或字符串长度 |
| `abs(x)` | 绝对值 |

**不存在的函数（禁止使用）**：
- ~~`if(cond, a, b)`~~：DSL 无三元函数，条件分支用 condition 节点
- ~~`hours_between()`~~：只有 `days_between(ts_a, ts_b)` 和 `days_since(ts)`
- ~~`round()`~~：无取整函数

**`count()` vs `len()`**：`count(values)` 等价于 `len(values)`，推荐统一使用 `len()`。

**`date_offset` 合法偏移格式**：`-Nd`（天）/ `-Nw`（周）/ `-Nm`（月），N 为正整数。示例：`'-14d'`、`'-1w'`、`'-1m'`。不支持 `'first_day_of_month'` 等文字格式。

**算术运算**：`+` `-` `*` `/` `%` 均为合法操作符，可在表达式中直接使用（如 `$config.target_roi * 0.92`）。字符串拼接必须用 `concat()`，不能用 `+`。

---

## 6. 节点类型（7种）

### 6.1 action 节点

```json
{
  "type": "action",
  "id": "fetch",
  "action": "<action名>",
  "input": {
    "key": "value或表达式"
  },
  "idempotency_key": "concat('pause:', $entity.id, ':', today())",
  "on_error": "fail",
  "timeout_seconds": 60
}
```

- `input` 的所有 string value 都会被表达式求值器处理
- 传字面字符串用 `{ "literal": "..." }` 包装
- 涉资写操作（create_* / update_budget）**必须**提供 `idempotency_key`
- `on_error`：`fail`（默认）/ `skip` / `continue`

### 6.2 condition 节点

```json
{
  "type": "condition",
  "id": "check",
  "if": "consecutive_below(extract_field($ctx.fetch.rows, 'roi'), $config.target_roi * 0.92) >= 3",
  "then": [ ... ],
  "else_if": [
    { "if": "...", "then": [ ... ] }
  ],
  "else": [ ... ]
}
```

- `else_if` 按顺序短路求值，第一个命中后不再继续
- `then` 为空数组合法（仅记录触发）

### 6.3 yield 节点

```json
// 飞书审批
{
  "type": "yield", "yield": "approval",
  "template": "campaign_launch",
  "timeout_seconds": 86400, "on_timeout": "reject",
  "summary": { "key": "$params.xxx" }
}

// 定时等待
{ "type": "yield", "yield": "timer", "duration": "7d" }

// 外部信号
{ "type": "yield", "yield": "signal", "signal_key": "approved", "timeout_seconds": 3600 }
```

- `on_timeout`：`fail` / `reject` / `continue`
- 审批被拒时 Plan 置 `rejected`，不继续执行

**yield 类型选用规则**：
- `approval`：涉资写操作前的人工审批（create_* / 扩量 / 大额预算调整）、对账结算单确认
- `timer`：固定时长等待，用于 AB 测试等需要跑满周期的场景（如 `"7d"`）
- `signal`：等待外部异步任务完成（AI 打标 / 合规检测 / 链路测试），任务完成后由回调触发继续执行

**禁止**：用 `yield:timer` 替代 `yield:signal` 等待异步任务——定时等待无法响应任务提前完成或超时失败。

### 6.4 foreach 节点

```json
{
  "type": "foreach",
  "id": "build_adsets",
  "items": "$ctx.struct.adsets",
  "do": [ ... ],
  "parallel": false,
  "max_concurrency": 10,
  "continue_on_error": false
}
```

- `$item` 是当前元素，`$index` 是当前下标（0-based）
- `$ctx.<foreach_id>.results[i].<child_node_id>` 访问第 i 次迭代中子节点的输出
- `$ctx.<foreach_id>.count` 是实际迭代次数

### 6.5 parallel 节点

```json
{
  "type": "parallel",
  "id": "fetch_multi",
  "wait": "all",
  "branches": [
    [ { "type": "action", "id": "fetch_a", ... } ],
    [ { "type": "action", "id": "fetch_b", ... } ]
  ]
}
```

- `wait`：`all`（默认）/ `any` / `race`
- 每个 branch 是一个节点数组（即使只有一个节点也必须用 `[...]` 包裹）
- parallel 完成后（`wait: "all"` 时），各分支子节点的输出通过 `$ctx.<子节点id>` 直接访问（子节点 id 全局唯一）
- **禁止**跨分支引用：同一个 parallel 内的分支 A 不能引用分支 B 的 `$ctx` 输出（并行执行，顺序不确定）
- 若后续节点依赖某个 parallel 分支的输出，该节点必须放在 parallel **之后**，不能放在 parallel 内部的其他分支中

### 6.6 agent 节点

```json
{
  "type": "agent",
  "id": "diagnose",
  "task": "anomaly_diagnosis",
  "input": { "timeseries": "$ctx.fetch.rows" },
  "optional": true,
  "timeout_seconds": 300
}
```

- `task` 枚举：`trend_attribution` / `report_narrative` / `creative_brief` / `strategy_advice` / `anomaly_diagnosis` / `material_insight`
- 输出到 `$ctx.<id>`：`.conclusion` / `.recommendations` / `.narrative` / `.confidence`
- `optional: true` 时 Agent 失败/超时不阻塞主流程

### 6.7 sub_plan 节点

```json
{
  "type": "sub_plan",
  "id": "build_test",
  "template_id": "tpl_campaign_launch_v1",
  "data": {
    "creative_id": "$params.creative_id",
    "account_id": "$params.test_account_id"
  },
  "wait": true
}
```

- `template_id` 和 `inline` 二选一
- 输出到 `$ctx.<id>`：`.sub_plan_id` / `.status` / `.result`

---

## 7. Action Registry（核心清单）

### 7.1 DAP 数据查询

| Action | 稳定性 | 关键 input | 关键 output |
|--------|--------|-----------|------------|
| `query_creative_performance` | 🟡 | `project_id` `asset_id` `date_start` `date_end` `group_by` | `.rows`（含 cpi/roi/ctr/cvr/spend） |
| `query_attribution` | 🟡 | `date_start` `date_end` `group_by`(O, default channel) `os`(O, both/ios/android) `top_n`(O) | `.rows` `.baseline` |
| `query_installs` | 🟡 | `project_id` `date_start` `date_end` `channel`(O) | `.rows`（含 installs） |
| `query_revenue` | 🟡 | `project_id` `date_start` `date_end` | `.rows`（含 revenue/arpu） |
| `query_ltv` | 🟡 | `project_id` `install_date_start` `install_date_end` `ltv_days` | `.rows`（含 ltv_d1/d7/d30） |
| `query_retention` | 🟡 | `project_id` `install_date_start` `install_date_end` `retention_days` | `.rows` |
| `query_account_balance` | 🟡 | `project_id` `channel`(O) | `.accounts`（含 balance/coverage_days） |
| `query_spend_progress` | 🟡 | `project_id` `channel`(O) | `.rows`（含 progress_pct/expected_progress_pct） |
| `query_creative_assets` | 🟡 | `project_id` `status`(O) `tag`(O) | `.items` `.total` |
| `query_creative_inventory` | 🟡 | `project_id` `channel`(O) | `.usable_count` `.winner_count` `.below_safety_line` |
| `query_creative_fatigue` | 🟡 | `project_id` `channel`(O) | `.items`（含 fatigue_score/decision） |
| `query_shortname_summary` | 🟡 | `project_id` `date_start` `date_end` `short_name`(O) | `.rows`（含 short_name/cpi/roi） |
| `query_postback_status` | 🟡 | `project_id` `channel`(O) | `status`（healthy/delayed/broken）`last_postback_at` |
| `query_compliance_result` | 🟡 | `asset_id` 或 `task_id` | `risk_level` `score` `violations` |
| `query_ai_tags` | 🟡 | `asset_id` 或 `asset_ids` | `tags` `primary_style` `hook_type` |
| `query_cpe_achievement` | 🟡 | `project_id` `date_start` `date_end` | `.rows`（含 agreed_volume/achievement_rate） |
| `query_roi_progress` | ✅ | `project_id` `channel` `date` `month`(O) | `actual_roi_mtd` `target_roi_by_day` `roi_trend_14d` |
| `query_material_report` | ✅ | `game` `channel` `start_date` `end_date` | `.tables` |
| `get_custom_report` | ✅ | `report_id` `start_date`(O) `end_date`(O) | `.tables` |

### 7.2 写操作

| Action | 稳定性 | 幂等 | 关键 input | 关键 output |
|--------|--------|------|-----------|------------|
| `update_entity_status` | 🟡 | ✅ | `project_id` `channel` `entity_type` `entity_id` `status`(pause/resume) | `previous_status` `new_status` |
| `update_budget` | 🟡 | ❌ | `project_id` `channel` `entity_type` `entity_id` `budget_type` `new_budget` | `previous_budget` `new_budget` |
| `create_campaign` | 🟡 | ❌ | `project_id` `channel` `account_id` `name` `objective` `budget_type` `budget` | `campaign_id` |
| `create_adset` | 🟡 | ❌ | `project_id` `channel` `campaign_id` `name` `targeting` `bid_strategy` | `adset_id` |
| `create_ad` | 🟡 | ❌ | `project_id` `channel` `adset_id` `name` `asset_ids` | `ad_id` |
| `write_lifecycle_action` | 🟡 | ❌ | `project_id` `asset_ids` `action`(approve/pause/resume/archive) `source` `reason` | `success_ids` |
| `submit_compliance_check` | 🟡 | ❌ | `asset_id` `project_id` `channel_targets` | `task_id` `status` |
| `submit_ai_tagging` | 🟡 | ❌ | `asset_id` `project_id` | `task_id` |

### 7.3 Engine 内部（稳定，直接可用）

| Action | 用途 | 关键 input | 关键 output |
|--------|------|-----------|------------|
| `tag_entity` | 给实体打标签 | `project_id` `entity_type` `entity_id` `tags` | `affected_count` |
| `notify` | 飞书消息推送 | `severity`(P0/P1/P2) `template`(O) `message` `data` `recipients`(O) | `message_id` |
| `audit_log` | 显式写审计记录 | `action` `entity_id` `detail` | `audit_id` |
| `fail_plan` | 立即结束 Plan，状态 failed | `reason`(O) | — |
| `complete_plan` | 立即结束 Plan，状态 completed | `summary`(O) | — |
| `compose_report_data` | 报表数据编排（内部并行调多个 query） | `project_id` `report_type`(daily/weekly/monthly) `date_start` `date_end` | `current` `baseline` `anomalies` |
| `render_report` | Jinja2 模板渲染 | `template`(daily-report/weekly-report/monthly-report/settlement) `data` | `content` `format` |
| `compute_test_structure` | 由测试模板+素材推导 adsets 结构 | `project_id` `asset_ids` `channel` `country` `budget` | `adsets` `total_daily_budget` |
| `compute_account_pool` | 由地区/产品推导扩量目标账户池 | `project_id` `channel` `country` `exclude_account_ids`(O) | `target_accounts` |
| `compute_attribution` | 多维贡献度分解 | `project_id` `date_start` `date_end` `dimensions` `metric`(O) | `factors` |
| `compute_anomaly_attribution` | 异常归因（逐层下钻） | `project_id` `date_start` `date_end` `dimensions` | `layers` `root_cause` |
| `compute_growth_attribution` | 增长卡点归因 | `project_id` `channel` `current_period` `baseline_period` `dimensions` | `layers` `priority_fixes` |
| `compute_a_b_factors` | A面/B面元素归因 | `project_id` `date_start` `date_end` `a_side_filter` `b_side_filter` | `a_factors` `b_factors` |
| `compute_period_diff` | 周期对比贡献度 | `project_id` `period_a_start` `period_a_end` `period_b_start` `period_b_end` `dimensions` | `contribution` |
| `compute_winner_pattern` | 爆款元素与指标正相关挖掘 | `project_id` `date_start` `date_end` `min_samples`(O) | `factors` |
| `compute_region_preference` | 地区/语言/版位偏好排序 | `project_id` `date_start` `date_end` `dimensions`(country/language/placement) | `preferences` |
| `compute_metric_baseline` | 7/30天加权基线 | `project_id` `metric` `window_7d_data` `window_30d_data` | `baseline` |
| `compute_billing_diff` | 渠道账单 vs 内部消耗差异 | `project_id` `channels` `month` `diff_threshold_pct` | `has_difference` `diff_items` |
| `check_budget_feasibility` | 余额+历史消耗判断预算可行性 | `current_budget` `reduction_pct` `max_auto_reduction_pct` `daily_spend`(O) `high_spend_threshold`(O) | `feasible` `adjusted_budget` `requires_approval` |
| `run_sop_checklist` | 跑 SOP 模板 | `template`(dict) `check_results`(dict, 调用方预先采集的检查项原始结果) | `passed_count` `failed_items` `manual_items` |
| `run_link_test` | 链路测试（事件→回传→归因） | `project_id` `channel` `events` | `passed` `failed_steps` |
| `aggregate_metrics` | 日常监控：拉 30 天 insights → 算 7d/30d 基线 → 检测 spend/CPI/CTR/CVR 异常 | `project_id` `date`(YYYY-MM-DD) `os`(O, android/ios) | `status` `metrics` `alerts` |
| `compute_group_by_field` | 按字段分组，输出每组的 ids | `items` `group_field` | `groups` |
| `compute_install_gap` | DAP vs 前端安装数 Gap | `project_id` `date_start` `date_end` `channel`(O) | `install_gap_pct` `revenue_gap_pct` |
| `render_settlement` | 结算单渲染 | `project_id` `month` `billing_diff` | `file_url` `total_amount` |
| `parse_creative_naming` | 素材命名解析 | `asset_name` | `short_name` `parsed_fields` `is_valid` |

---

## 8. $entity 常用字段

### entity_type = creative

| 字段 | 类型 | 说明 |
|------|------|------|
| `$entity.id` | string | 素材 ID（asset_id） |
| `$entity.name` | string | 素材全名 |
| `$entity.short_name` | string | 素材短名 |
| `$entity.project_id` | string | 所属项目 |
| `$entity.channel` | string | 渠道 |
| `$entity.status` | enum | active/ready/paused/archived |
| `$entity.online_days` | int | 上线天数（engine 派生） |
| `$entity.created_at` | string | 创建时间 ISO8601 |
| `$entity.cpi_14d` | array\<number\> | 近 14 天 CPI 时序（按天） |
| `$entity.roi_14d` | array\<number\> | 近 14 天 ROI 时序 |
| `$entity.ctr_14d` | array\<number\> | 近 14 天 CTR 时序 |
| `$entity.daily_spend` | number | 最新日消耗 |
| `$entity.tags` | array\<string\> | 实体标签（tag_entity 写入） |
| `$entity.is_winner` | bool | 是否爆款（engine 按阈值实时算） |
| `$entity.compliance_status` | enum | safe/medium_risk/high_risk/unknown |

### entity_type = campaign

| 字段 | 类型 | 说明 |
|------|------|------|
| `$entity.id` | string | Campaign ID |
| `$entity.name` | string | Campaign 名称 |
| `$entity.project_id` | string | 所属项目 |
| `$entity.channel` | string | 渠道 |
| `$entity.status` | enum | active/paused/... |
| `$entity.daily_budget` | number | 日预算 |
| `$entity.daily_spend` | number | 最新日消耗 |
| `$entity.online_days` | int | 上线天数 |
| `$entity.cpi_14d` | array\<number\> | 近 14 天 CPI 时序 |
| `$entity.roi_14d` | array\<number\> | 近 14 天 ROI 时序 |
| `$entity.tags` | array\<string\> | 实体标签 |

---

## 9. 四种模式节点图骨架

### A 类：监控（schedule 触发）

```
trigger: schedule → scope(entity_type + selector)
  └─ [query action，id="fetch"]        # 拉该实体的时序数据
  └─ condition，id="check"
       if: consecutive_below(extract_field($ctx.fetch.rows, 'roi'), ...) >= N
       then:
         └─ [write action]             # update_entity_status / update_budget
         └─ tag_entity                 # 防重复触发
         └─ write_lifecycle_action     # 审计
         └─ notify(P1)
```

**关键约定**：
- selector 加 `tags NOT CONTAINS '<已处理标签>'` 防止重复触发
- 阈值全部引用 `$config.<module>.*`，不写数字
- write action 必须带 `idempotency_key`，格式 `concat('<动作>:', $entity.id, ':', today())`

### B 类：指令（api 触发）

```
trigger: api
params: { 运行时需要的参数 }
  └─ [validate / compute action]       # 参数校验或结构推导
  └─ yield: approval                   # risk_level >= medium 时必须
       template: "<审批模板>"
       summary: { 关键参数摘要 }
  └─ write action（主操作）
       idempotency_key: ...
  └─ [foreach → write action]          # 批量创建时
  └─ notify(P2)
```

### C 类：报表（schedule 触发，无 entity 遍历）

```
trigger: schedule（无 scope）
  └─ compose_report_data / query action，id="fetch"
  └─ render_report，id="render"
  └─ [agent: report_narrative，optional=true]
  └─ notify(P2)
       data.report_body: "$ctx.render.content"
       data.narrative: "$ctx.narrative.narrative"
```

### D 类：管线（sub_plan 触发，含长等待）

```
trigger: sub_plan
params: { asset_ids, test_account_id, duration, ... }
  └─ sub_plan: tpl_campaign_launch_v1  # 搭测试Campaign
  └─ yield: timer                      # 等测试周期
       duration: "$params.duration"
  └─ foreach: $params.asset_ids，parallel=true
       └─ query action，id="perf"
       └─ condition
            if: perf达标（CPI < target*0.8 AND ROI > target*1.2）
            then: tag_entity(winner) + notify(P1)
            else_if: 一般通过
            then: tag_entity(ab_passed)
            else: update_entity_status(pause) + write_lifecycle_action(archive)
```

---

## 10. 常见组合模式备忘

**时序判定标准写法**：
```json
"if": "consecutive_below(extract_field($ctx.fetch.rows, 'roi'), $config.target_roi * $config.creative_decay.roi_below_target_pct) >= $config.creative_decay.consecutive_days"
```

**idempotency_key 标准写法**：
```json
"idempotency_key": "concat('pause_decay:', $entity.id, ':', today())"
```

**日期范围标准写法**：
```json
"date_start": "date_offset(today(), concat('-', $params.lookback_days, 'd'))",
"date_end": "today()"
```

**防重复触发闭环**：
- selector 加 `tags NOT CONTAINS 'already_processed_tag'`
- then 分支末尾加 `tag_entity` 打同名标签

**notify 的 data 引用最新数据**：
```json
"data": {
  "cpi_recent": "$ctx.fetch.rows[-1].cpi",
  "roi_recent": "$ctx.fetch.rows[-1].roi"
}
```
