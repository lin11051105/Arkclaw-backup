---
name: monitoring-alerts
description: "数据监控与异常预警：日常巡检、异常归因、大盘趋势、数据 Gap、回传连续性、消耗进度、回本进度"
metadata:
  hermes:
    tags: [ua, monitoring, alerts, anomaly, pipeline]
    related_skills: [dap-ua]
---

# 数据监控与异常预警

## 能力说明

本 Skill 覆盖 7 项监控需求：

| 能力 | 需求 | 检查频率 | 告警级别 |
|------|------|---------|---------|
| 消耗进度监控 | 4.6 | 每 4 小时 | P1 |
| 账户余额监控 | 4.6 | 每 12 小时 | P0/P1 |
| 数据 Gap 预警 | 4.4 | 每 6 小时 | P1 |
| 回传连续性预警 | 4.5 | 每 6 小时 | P0/P1 |
| 日常投放数据监控 | 4.1 | 每日 | P1 |
| 数据异常归因分析 | 4.2 | 日常监控发现异常时 | P1 |
| 大盘趋势预警 | 4.3 | 每日 | P1/P2 |
| 回本进度预警 | 4.7 | 每日 | P1 |

所有数据查询通过 DAP 平台接口，`channel` 参数区分渠道。

## 触发条件

1. **Heartbeat 定时驱动**:
   - 消耗进度 → 读取 `heartbeat-state.json`，间隔 >= `thresholds.spend_progress.check_interval_hours`
   - 数据管线（Gap + 回传）→ 间隔 >= `thresholds.data_gap.check_interval_hours`
   - 账户余额 → 间隔 >= `thresholds.account_balance.check_interval_hours`
   - 日常监控 / 趋势预警 / 回本进度 → 每日一次

2. **手动触发**: 飞书指令 "检查消耗进度" / "检查回传" / "跑一次日常巡检" 等

3. **静默期规则**: 22:00-09:00 只执行管线和余额检查，跳过报告类推送。P0 无视静默期。
   - 时段配置：`thresholds.silent_period.start_hour`（默认 22）与 `thresholds.silent_period.end_hour`（默认 9）。
   - ⚠️ **实施待补**：当前 skill 代码尚未读取上述阈值做时间窗判定；推送时机由 cron 调度间接保证（详见 `docs/superpowers/plans/2026-04-07-skill-tests-plan2-p0-skills.md` 的 `resolve_alert_timing` 设计）。后续应把该函数落地到 `monitoring-alerts/scripts/`。

## 执行步骤

> **⚠️ 必须使用下方每节标注的 CLI 命令执行，不要自己拆解步骤或发明流程。**
> - **默认模式**: 不带 `--account-id` 参数，查询 .env 中的主力账户。这是标准流程，不是缺陷。
> - **指定账户**: 用户明确要求查某个账户时，传 `--account-id act_xxx`
> - **全账户巡检**: 仅当用户明确说"查所有账户"/"全量巡检"时，逐个账户调用 CLI。**未经用户要求不得自行遍历。**

### 一、消耗进度监控（需求 4.6，每 4 小时）

**输入**: `project_id`, `channel`（可选，默认全渠道）, `date`（默认当天）

**直接用 CLI**:
```bash
# 默认：查 .env 主力账户余额 + 消耗进度
python3 skills/monitoring-alerts/scripts/cli.py balance --project ROK

# 查指定账户
python3 skills/monitoring-alerts/scripts/cli.py balance --project ROK --account-id act_xxx

# 查所有 Active 账户汇总（用户问"所有账户余额能撑几天"时用这个）
python3 skills/monitoring-alerts/scripts/cli.py balance --project ROK --all
```
> - 默认模式：返回 `balance`（余额/状态）+ `spend_progress`（消耗进度）
> - `--all` 模式：遍历所有 Active 账户，返回每个账户的余额/日均消耗/覆盖天数 + 汇总
> - 消耗进度按 **日预算 × 当日时间比例** 计算预期消耗，与 Facebook 当日累计 spend 对比

**步骤**:

1. 读取 `config/thresholds.json` 中 `spend_progress` 参数
2. 拉取 Facebook Campaign 级 Insights 当日 spend；读取 `apps.json` 中 `daily_budget`
3. 计算 `expected_spend_by_progress = daily_budget × time_progress_pct`（0~1，按当日时钟）
4. `deviation = |today_spend - expected_spend_by_progress| / max(expected_spend_by_progress, ε)`
5. 若 `deviation > deviation_alert_pct` → P1；否则 `summary` 为「进度正常」
6. 告警则推送飞书消息（模板: `templates/feishu-alerts/p1-spend-progress.md`）
7. 写入 `memory/YYYY-MM-DD.md`: `[消耗进度] 项目X 偏差Z% — 已告警/正常`

**回传连续性**:
```bash
python3 skills/monitoring-alerts/scripts/cli.py postback-continuity --project ROK --end-date 2026-04-16 --days 3
```
> 对区间内每一天拉 DAP `get_custom_report`（`table=day`）；若某日安装与收入均为 0 → `alerts` 中带 P0。详见 `gap_checker.check_postback_continuity`。

### 二、账户余额监控（需求 4.6，每 12 小时）

**输入**: `project_id`, `account_id`（可选，默认用 .env 中的默认账户）

**数据获取方式**:

```bash
# 查单个账户余额（默认账户）
python3 skills/ads-channel/scripts/cli.py account-info

# 查指定账户余额
python3 skills/ads-channel/scripts/cli.py account-info --account-id act_2243882512769338
```

返回字段：`id`、`name`、`account_status`、`currency`、`balance`（格式 "$123.45"）、`balance_raw`（float, USD）

**所有金额单位均为 USD，无需额外转换。**

**步骤**:

1. 读取 `config/thresholds.json` 中 `account_balance` 参数
2. 调用 ads-channel `account-info` 获取账户余额（`balance_raw` 字段，单位 USD）
3. 调用 ads-channel `get-insights --level campaign --date-start <7天前> --date-end <昨天>` 获取近 7 天消耗，计算日均消耗
4. 计算余额覆盖天数:
   ```
   balance_days = balance_raw / daily_avg_spend_7d
   ```
5. 判定:
   - if `balance_days < thresholds.account_balance.critical_days` → P0 紧急告警（模板: `p0-balance-critical.md`）
   - if `balance_days < thresholds.account_balance.warning_days` → P1 告警（模板: `p1-balance-warning.md`）
6. P0 告警无视静默期，直接推送并 @项目负责人
7. **报告中必须注明账户 ID 和账户名**（单账户查询，需明确是哪个账户的余额）
8. 写入 `memory/YYYY-MM-DD.md`

**注意**：余额是单个广告账户的，不是整个 BM 的。一个项目可能有多个账户（如 ROK 有 25 个），每次查询只返回一个账户的余额。如需检查多个账户，需逐个传入 `account_id`。

### 三、数据 Gap 预警（需求 4.4，每 6 小时）

**输入**: `project_id`, `date`（默认昨天）

**直接用 CLI**:
```bash
python3 skills/monitoring-alerts/scripts/cli.py data-gap --project ROK --date 2026-04-13
```

CLI 内部逻辑（Agent 不需要手动执行这些步骤，了解即可）:

1. **Facebook 侧数据**: 自动获取 token 下所有 Active 广告账户，逐个调 ads-channel `get-insights --level campaign` 并汇总 installs 和 revenue（全账户合计）
2. **DAP 侧数据**: 调用 DAP `get_custom_report(table="media_src")`，取 Facebook 渠道行的安装数（全账户汇总）
3. 计算 Gap（两侧口径对齐到 Facebook 渠道全账户）:
   ```
   install_gap = |fb_installs - dap_installs| / max(fb_installs, dap_installs, 1)
   ```
4. 判定:
   - if `install_gap > thresholds.data_gap.install_gap_pct` → P1 告警
   - if `fb_installs > 0 and dap_installs == 0` → P0 管线中断
6. 告警则推送飞书消息（模板: `templates/feishu-alerts/p1-data-gap.md`）
7. 写入 `memory/YYYY-MM-DD.md`

### 四、回传连续性预警（需求 4.5，每 6 小时）

**输入**: `project_id`, `channel`, `event_name`（默认检查 install + purchase）

**直接用 CLI**:
```bash
python3 skills/monitoring-alerts/scripts/cli.py postback-continuity --project ROK --end-date 2026-04-16 --days 3
```
> 独立子命令，对区间内每天检查 DAP 安装/收入是否均为 0。`data-gap` 检查单日 Gap，`postback-continuity` 检查多日连续性。

**步骤**:

1. 读取 `config/thresholds.json` 中 `postback` 参数
2. 查询回传链路状态，获取各渠道事件的最后回传时间、近 1 小时回传量、缺失字段和状态
3. 判定:
   - if `status == "broken"` 或 `距 last_postback_at > thresholds.postback.interrupt_minutes 分钟` → P0 管线中断告警
   - if `missing_fields` 非空 → P1 回传字段缺失告警
4. P0 告警使用模板 `p0-pipeline-interrupt.md`，**无视静默期**直接推送并 @项目负责人
5. P1 告警使用模板 `p1-postback-fields.md`
6. 查询 DAP 各数据表的同步状态（最后更新时间、行数变化、是否延迟）
7. if 任一数据表 `status == "stale"` → P1 告警
8. 写入 `memory/YYYY-MM-DD.md`

### 五、日常投放数据监控（需求 4.1，每日）

**输入**: `project_id`, `channel`（可选）, `country`（可选）

**直接用 CLI**:
```bash
python3 skills/monitoring-alerts/scripts/cli.py daily --project ROK --date 2026-04-13
```

**步骤**:

1. 读取 `config/thresholds.json` 中 `daily_monitoring` 参数
2. 查询素材维度投放数据（近 7 天）和 Campaign 级效果数据（按项目、渠道和日期范围）
3. 计算基线:
   ```
   baseline = 7d_avg * thresholds.daily_monitoring.baseline_7d_weight
            + 30d_avg * thresholds.daily_monitoring.baseline_30d_weight
   ```
4. 逐指标判定异常（与基线对比）:
   - if `yesterday_spend > baseline_spend * (1 + thresholds.daily_monitoring.spend_spike_pct)` → 消耗突增
   - if `yesterday_spend < baseline_spend * (1 - thresholds.daily_monitoring.spend_drop_pct)` → 消耗突降
   - if `yesterday_cpi > baseline_cpi * (1 + thresholds.daily_monitoring.cpi_spike_pct)` → CPI 突增
   - if `yesterday_ctr < baseline_ctr * (1 - thresholds.daily_monitoring.ctr_drop_pct)` → CTR 突降
   - if `yesterday_cvr < baseline_cvr * (1 - thresholds.daily_monitoring.cvr_drop_pct)` → CVR 突降
5. 存在异常项 → 触发异常归因分析（见下方第六节）
6. 无异常 → 写入 `memory/YYYY-MM-DD.md`: `[日常巡检] 各指标正常`
7. 推送监控报告到飞书（模板: `p1-daily-anomaly.md`），列出所有异常项

### 六、数据异常归因分析（需求 4.2，日常监控发现重大异常时触发）

**前提**: 第五节日常监控发现指标异常

> **无独立 CLI 命令**: 本节是 Agent 级分析流程（LLM 逐层下钻归因），不由单一脚本完成。Agent 根据 `daily` 命令的异常输出，逐步调用 DAP 查询进行下钻分析。

**步骤**:

1. 确定异常指标和偏离幅度
2. 逐层下钻获取数据:
   - **第一层 OS**: 按 iOS / Android 拆分，定位异常集中在哪个 OS
   - **第二层 渠道**: 按 channel 拆分（Meta / TikTok / Google）
   - **第三层 Campaign**: 查看异常渠道下各 Campaign 的贡献度
   - **第四层 指标拆解**: CPM → CTR → CVR → CPI 链路中哪个环节恶化
   - **第五层 版位/素材**: 通过 DAP 归因接口按 Pub/placement/creative 拆分
   
   逐层查询归因数据，按指定维度（OS → 渠道 → Campaign → 版位 → 素材）下钻分析
3. 计算各层级对整体变化的贡献度:
   ```
   contribution_pct = (layer_delta * layer_weight) / total_delta * 100
   ```
4. 调用 LLM 进行归因分析:
   - 输入: 异常指标数据 + 各层贡献度 + 来自 `memory/` 的近期类似案例
   - 输出: 归因结论 + 建议操作
5. 推送 P1 异常归因报告到飞书，包含:
   - 异常指标及偏离幅度
   - 下钻路径和各层贡献度（表格展示）
   - LLM 归因结论
   - 建议操作（附风险等级标注）
6. 写入 `memory/YYYY-MM-DD.md`，如果是新型异常模式则同步写入 `MEMORY.md`

### 七、大盘趋势预警（需求 4.3，每日）

**输入**: `project_id`, `channel`, `os`

**直接用 CLI**:
```bash
python3 skills/monitoring-alerts/scripts/cli.py trend --project ROK
```

**步骤**:

1. 读取 `config/thresholds.json` 中 `trend_detection` 参数
2. 查询近 14 天投放趋势数据，包含 CPI、CPM、CTR、ROI 等核心指标
3. 运行趋势检测:
   - **CPM 系统性下滑**: 计算 `thresholds.trend_detection.moving_avg_window` 日移动均值，检查是否连续下降 >= `thresholds.trend_detection.consecutive_decline_days` 天
   - **素材批量疲劳**: 统计活跃素材中 CTR 连续下降的比例，if > `thresholds.trend_detection.batch_fatigue_pct` → P1 告警
   - **ROI 持续恶化**: 检查 ROI 是否连续 `thresholds.trend_detection.consecutive_decline_days` 天环比下降
4. 检测到趋势变化时:
   - 调用 LLM 进行趋势分析:
     - 输入: 趋势数据 + 同期对比 + 近期操作记录（来自 memory）
     - 输出: 趋势归因 + 策略建议（调预算/调目标/调素材策略）
   - 策略建议为**建议性质，需人工确认后执行**，本 Skill 不自动执行策略调整
   - 素材批量疲劳 → P1（模板: `p1-batch-fatigue.md`）
   - 其他趋势 → P2（模板: `p2-trend-warning.md`）
5. 写入 `memory/YYYY-MM-DD.md`

### 八、回本进度预警（需求 4.7，每日）

**输入**: `project_id`, `channel`

**直接用 CLI**:
```bash
# 查单日 ROI 进度（默认昨天）
python3 skills/monitoring-alerts/scripts/cli.py roi-progress --project ROK --channel Facebook

# 查本月回本进度（用户问"本月回本"时用这个）
python3 skills/monitoring-alerts/scripts/cli.py roi-progress --project ROK --month 2026-04

# 查指定日期范围
python3 skills/monitoring-alerts/scripts/cli.py roi-progress --project ROK --date 2026-04-01 --date-end 2026-04-19
```

**步骤**:

1. 读取 `config/thresholds.json` 中 `roi_progress` 参数
2. 查询 LTV 数据，获取各渠道按安装日期归因的 D1/D3/D7/D14/D30 累计价值
3. 计算实际回本进度:
   ```
   actual_roi = cumulative_revenue / cumulative_spend
   ```
4. 对比回本目标路径（从项目配置获取）:
   ```
   expected_roi = target_roi_curve[current_day]
   deviation = |actual_roi - expected_roi| / expected_roi
   ```
5. **ROI 趋势前向预测**:
   - 基于已有的 D1/D3/D7 LTV 数据，按历史 LTV 衰减曲线外推 D14/D30 预期值
   - 计算预测月底 ROI:
     ```
     predicted_roi_d30 = actual_ltv_d7 * (historical_d30_ltv / historical_d7_ltv) / cpi
     ```
   - if `predicted_roi_d30 < target_roi * 0.9` → 标记为"预测月底不达标"
6. 判定:
   - if `deviation > thresholds.roi_progress.deviation_alert_pct` → P1 告警
   - if 步骤 5 预测月底不达标 → 在告警中附加预测结论
7. 推送飞书消息（模板: `p1-roi-progress.md`），包含:
   - 项目、渠道、当前回本进度、目标路径、偏差
   - ROI 趋势预测: 基于 D7 LTV 外推的 D30 预期值 + 达标概率
   - 风险等级: 偏差 10-20% 中风险 / >20% 高风险
8. 写入 `memory/YYYY-MM-DD.md`

### 九、iOS-aware 监控（SKAN 真值路径，需求 8.x）

**适用场景**: iOS 渠道受 ATT 限制，DAP 概率归因准确率不足以支撑日常监控。本 Skill 通过 `--os ios` 切换到 SKAN 真值路径（视图 `hive.da_bi_dw.v_tb_skan_report_day_v2`），Android 路径保持 DAP 不变。

**关键约束**:

1. **72h SKAN postback 延迟保护**: SKAN 回传最长延迟 72 小时。请求查询日期距今不足 3 天时，CLI 直接返回
   ```json
   {"skipped": true, "reason": "iOS SKAN postback delay 72h: query window too recent",
    "min_query_date": "<today-3>", "project_id": "...", "os": "ios"}
   ```
   **不发起 DW 查询**，避免基于半截数据触发误报。
2. **校准窗口预留 2 天 buffer**: 周/月校准查询区间应整体后移 2 天，由调用方在 `--date` / `--date-end` 上控制。
3. **Android 路径默认不变**: `--os` 默认值 `android`，所有现有 cron 行为向后兼容。

**支持的子命令**:

| 子命令 | iOS 行为 | Android 行为（默认）|
|--------|---------|------------------|
| `daily --os ios` | 走 SKAN 视图 (`make_fetch_skan_by_game_day`)；72h guard 生效；CTR/CVR 强制为 0（SKAN 无点展信号），`bl_ctr/bl_cvr > 0` 守卫自动抑制相关告警 | 走 DAP 概率归因 (`make_fetch_material_report`) |
| `daily --os both` | 输出 `{android: ..., ios: ...}` 双键结构；由 `lib.os_aggregator.combine` 按消耗加权聚合 | 同上 |
| `roi-progress --os ios` | `target_roi` 经 `get_os_target(app, os="ios", field="target_roi")` 解析（优先 `ios_target_roi`，回退 `target_roi`）；阈值块优先 `roi_progress_ios`（缺失回退 `roi_progress`） | 走 `roi_progress` 阈值块 + `target_roi` |

**SKAN 视图列映射**（`hive.da_bi_dw.v_tb_skan_report_day_v2`，Trino 通过 impyla 接入）:

| 视图列 | 监控指标 | 备注 |
|-------|---------|------|
| `cost` | `spend` | RMB |
| `sk_install` | `installs` | 已扣 `cv=null` 部分的真值 |
| `cpi` | `cpi` | 视图直接给出，不重算 |
| `skan_roi` | `roi` | 视图侧已做 null gross-up: `revenue / (1 - sk_conversion_null/sk_install) / cost` |
| `revenue` / `mmp_cv_revenue` | revenue 类指标 | 用于回本进度判定 |

**OS-aware 配置**:

1. **`apps.json[project]`**:
   - 顶层 `game_id`（int）— SKAN 路径用此映射查询参数（如 ROK=10043, PTSLG=10091, AFKA=10046, IGAME=10076, WGAME=10048, PGAME=10064）
   - `facebook.ios_target_cpi` / `ios_target_roi` — iOS 专用目标值
   - `facebook.android_target_cpi` / `android_target_roi` — Android 专用目标值
   - `facebook.target_cpi` / `target_roi` — legacy 字段，作为 OS 缺失时的 fallback
2. **`thresholds.json` 块**:
   - `daily_monitoring_ios.cpi_spike_pct` 通常 ≈ 0.50（吸收 SKAN postback 噪声，vs Android 0.30）
   - `roi_progress_ios.deviation_alert_pct` 通常 ≈ 0.15（vs Android 0.10）
   - 缺失时自动回退到 `daily_monitoring` / `roi_progress` legacy 块

**CLI 示例**（cwd 为 `workspace/`）:

```bash
# iOS 单日（必须 ≥ 3 天前；今天是 2026-05-08，最近可查 2026-05-04）
python3 skills/monitoring-alerts/scripts/cli.py daily --project ROK --os ios --date 2026-05-04

# iOS + Android 双侧聚合（用于"全盘"概览）
python3 skills/monitoring-alerts/scripts/cli.py daily --project ROK --os both --date 2026-05-04

# iOS 月度回本（区间结束日期需预留 2 天 buffer）
python3 skills/monitoring-alerts/scripts/cli.py roi-progress --project ROK --os ios --date 2026-04-01 --date-end 2026-04-29

# 72h guard 触发示例（查询日期 2026-05-07 距今不足 3 天 → 跳过）
python3 skills/monitoring-alerts/scripts/cli.py daily --project ROK --os ios --date 2026-05-07
# → {"skipped": true, "reason": "iOS SKAN postback delay 72h: query window too recent", ...}
```

**与规则引擎的关系**: iOS 路径的判定逻辑与 Android 一致（T01/T06/T10-T14 同套规则），仅切换数据源和阈值块。OS 专属阈值块缺失时无缝回退到 legacy 块，保证规则全集生效。

## 输入/输出

### 输入参数汇总

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `project_id` | string | 项目 ID | 必填 |
| `channel` | string | 渠道（Meta/TikTok/Google/CPE） | 全渠道 |
| `country` | string | 国家/地区 | 全部 |
| `date` | string | 检查日期 | 当天 |
| `event_name` | string | 事件名（回传检查用） | install,purchase |
| `check_type` | string | 手动触发时指定检查类型 | 全部到期项 |

### 输出格式

所有告警推送到飞书，格式使用 `templates/feishu-alerts/` 下的对应模板。

| 检查项 | 告警模板 | 告警级别 |
|--------|---------|---------|
| 管线中断 | `p0-pipeline-interrupt.md` | P0 |
| 余额紧急 | `p0-balance-critical.md` | P0 |
| 消耗进度偏差 | `p1-spend-progress.md` | P1 |
| 数据 Gap | `p1-data-gap.md` | P1 |
| 回传字段缺失 | `p1-postback-fields.md` | P1 |
| 日常异常 | `p1-daily-anomaly.md` | P1 |
| 余额不足 | `p1-balance-warning.md` | P1 |
| 回本进度偏差 | `p1-roi-progress.md` | P1 |
| 素材批量疲劳 | `p1-batch-fatigue.md` | P1 |
| 趋势变化 | `p2-trend-warning.md` | P2 |

## 判定规则

所有判定阈值引用 `config/thresholds.json`，不在本 Skill 中硬编码。规则分类对照:

| 规则引擎编号 | 规则名称 | 类别 | 本 Skill 对应章节 |
|-------------|---------|------|-----------------|
| T01 | 消耗进度偏差预警 | A-阈值比较 | 一 |
| T02 | 账户余额不足告警 | A-阈值比较 | 二 |
| T03 | 账户余额紧急告警 | A-阈值比较 | 二 |
| T04 | Install Gap 预警 | A-阈值比较 | 三 |
| T05 | Revenue Gap 预警 | A-阈值比较 | 三 |
| T06 | 回本进度偏差预警 | A-阈值比较 | 八 |
| T09 | 消耗进度过快预警 | A-阈值比较 | 一 |
| T10-T14 | 日常异常突变 | A-阈值比较 | 五 |
| B05 | ROI 持续恶化 | B-时序条件 | 七 |
| D01 | 回传链路中断 | D-管线健康 | 四 |
| D02 | DAP 数据同步延迟 | D-管线健康 | 四 |
| D03 | 回传字段缺失 | D-管线健康 | 四 |
| E01 | CPM 系统性下滑 | E-趋势检测 | 七 |
| E04 | 素材批量疲劳 | E-趋势检测 | 七 |

## 安全规则

1. 本 Skill **只读取数据和发送告警**，不执行任何修改操作（不暂停、不调预算、不删除）
2. P0 告警**无视静默期**（22:00-09:00），直接推送并 @项目负责人
3. P1/P2 在静默期内攒到次日 09:00 汇总推送
4. 告警消息**不得包含** API Key、Token、密码等敏感信息
5. 每次检查结果（无论是否告警）都写入 `memory/YYYY-MM-DD.md`

## 辅助脚本

所有检查逻辑由 `scripts/` 下的 Python 脚本完成。

🚫 **禁止手动拉 DAP/Insights 数据再用 execute_code 处理** — 原始数据行数多，灌入上下文会导致 ReadTimeout。必须通过 CLI 调用，数据处理在本地 Python 完成，你只需读取 CLI 输出的汇总 JSON。

Agent 通过 CLI 调用脚本，读取输出 JSON，然后推飞书告警。

### 飞书告警推送方式

推送方式取决于运行场景：

- **Cron 定时任务**: 最终 response 由 Hermes 自动投递到目标群，**不需要手动调用 feishu.py 或 send_message**。直接把告警内容写在最终回复中即可。不要浪费工具调用去找推送方法。
- **交互式会话**: 如需主动推送文件或消息到飞书群，使用 `python3 skills/lib/feishu.py --chat-id <群名或oc_xxx> send-text --text "内容"` 或 `send-file --file /path/to/file`。注意 `--chat-id` 是顶层参数，必须在子命令之前。

**CLI 入口**: `python3 skills/monitoring-alerts/scripts/cli.py <子命令> [参数]`

> ⚠️ **路径注意**: cwd 是 `workspace/`，CLI 路径从 `skills/` 开始。不要加 `workspace/` 前缀，否则变成双重 `workspace/workspace/skills/...` 导致找不到文件。

> ⚠️ **Gateway Token 预检（必做）**: 所有 CLI 子命令都依赖 Atlas AI Gateway（DAP 调用）。**运行 CLI 之前，先执行 `atlas-skillhub gateway status` 检查 token 是否有效。** 如果 `"valid": false`，CLI 会挂起等待交互式浏览器登录（在 cron 中会超时 120s+ 然后返回空输出，浪费时间和 token）。
> - Token 缓存文件: `/root/.atlas-ai-gateway-oauth.json`，有效期约 5-7 天
> - Token 过期时的正确处理: **不要尝试运行 CLI**，直接报告 token 过期。Cron 场景下用 `session_search` 检查当天是否已有 P0 告警发出，避免重复推送
> - 恢复方法（需人工）: `lsof -ti:20265 | xargs kill -9 && atlas-skillhub gateway login`，然后在浏览器中完成 IDaaS OAuth 登录

| 子命令 | 用途 | CLI 示例 |
|--------|------|---------|
| `balance` | 账户余额 & 消耗进度预警 | `cli.py balance --project ROK`（单账户）或 `--all`（全账户汇总） |
| `data-gap` | 前端/DAP 数据 Gap 预警 | `cli.py data-gap --project ROK`（默认昨天，可 `--date 2026-04-12`） |
| `roi-progress` | 回本进度预警 | `cli.py roi-progress --project ROK`（默认昨天，可 `--month 2026-04` 查月度；加 `--os ios` 走 SKAN 真值，详见章节九）|
| `daily` | 日常投放监控（昨日 vs 7d/30d 基线） | `cli.py daily --project ROK`（默认昨天，可 `--date 2026-04-12`；加 `--os ios` 或 `--os both` 启用 SKAN 路径，详见章节九）|
| `trend` | 大盘趋势预警（CPM/ROI 趋势 + 素材批量疲劳） | `cli.py trend --project ROK --days 14` |

CLI 自动加载 config（apps.json + thresholds.json）、构建 DAP/ads-channel 回调、执行脚本、JSON 输出到 stdout。
