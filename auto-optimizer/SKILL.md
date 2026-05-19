---
name: auto-optimizer
description: "Campaign/AdSet 级自动优化：衰退判定、预算自动缩减、预算转移"
metadata:
  hermes:
    tags: [ua, optimization, budget, decay, campaign]
    related_skills: [dap-ua, ads-channel]
---

# Campaign/AdSet 自动优化

## 能力说明

| 能力 | 需求 | 触发方式 |
|------|------|---------|
| Campaign/AdSet 衰退判定与预算自动调整 | 3.4 | Heartbeat 每日 + 手动 |

与 creative-lifecycle 的素材级关停（需求 1.4）互补：
- creative-lifecycle: 操作粒度在素材/Ad 层
- auto-optimizer: 操作粒度在 Campaign/AdSet 层

## 触发条件

1. **Heartbeat 每日**: 在日常监控之后执行
2. **手动触发**: 飞书指令 "优化 Campaign XXX"、"检查广告组衰退"
3. **被 monitoring-alerts 触发**: 监控发现 Campaign 级异常后可触发本 Skill

## 执行步骤

> **⚠️ 必须使用下方每节标注的 CLI 命令执行，不要自己拆解步骤或发明流程。** CLI 命令已封装完整逻辑，直接运行即可。

### 一、Campaign/AdSet 衰退判定与自动优化

**输入**: 在跑的 Campaign/AdSet 列表（自动从 DAP 获取）

**步骤**:

1. **拉取效果数据**: 查询所有活跃 Campaign/AdSet 的近 7 天投放数据，指定项目名、渠道和日期范围，包含 Campaign/AdSet 级数据。

2. **Campaign 衰退判定**（引用规则引擎 B02）:
   读取 `config/thresholds.json` 中 `campaign_decay` 参数:
   ```
   if 连续 thresholds.campaign_decay.consecutive_days 天:
       cpi > target_cpi * thresholds.campaign_decay.cpi_above_target_pct
   then → 降预算 30% + P1 告警
   ```

   连续天数判定方式（一期 LLM 判定）:
   - 拉取 Campaign 近 7 天每日 CPI 数据
   - 逐日检查 CPI 是否 > target_cpi * 1.25
   - 统计连续满足条件的天数
   - if 连续天数 >= 3 → 触发衰退

3. **AdSet 衰退判定**（引用规则引擎 B03）:
   读取 `config/thresholds.json` 中 `adset_decay` 参数:
   ```
   if 连续 thresholds.adset_decay.consecutive_days 天:
       cpi > target_cpi * thresholds.adset_decay.cpi_above_target_pct
       AND roi < target_roi * thresholds.adset_decay.roi_below_target_pct
   then → 降预算 30% + P1 告警
   ```

4. **高风险消耗检测**（引用规则引擎 C04）:
   读取 `config/thresholds.json` 中 `high_risk_spend` 参数:
   ```
   if daily_spend > thresholds.high_risk_spend.daily_spend_threshold
      AND roi < target_roi * thresholds.high_risk_spend.roi_below_target_pct
   then → P1 告警 + 推送确认请求
   ```

5. **执行预算调整**（按决策分级）:

   **自动执行（降预算 <= 30%）**:
   调整 Campaign/AdSet 的预算，指定项目 ID、渠道、实体类型、实体 ID、预算类型和新预算金额。

   **需人工确认**:
   - 降预算 > 30%
   - 暂停日耗 > $500 的 Campaign
   → 推送建议到飞书，等待确认后执行

6. **预算转移**:
   - if 同 Campaign 下存在高 ROI 的 AdSet → 将缩减的预算转移过去
   - if 无合适转移目标 → 预算直接缩减

7. **推送飞书**: 调整通知，包含:
   ```
   ⚙️ 自动优化 — 项目XX

   Campaign "YY"（日耗 $300）→ 降预算 30%（$300 → $210）
   原因: 连续 3 天 CPI=$5.2/$5.5/$5.8（目标 $4.0 × 125% = $5.0）
   
   AdSet "ZZ"（日耗 $150）→ 降预算 30%（$150 → $105）
   原因: 连续 3 天 CPI 超标 + ROI < 目标 80%
   
   ⚠️ 需确认:
   Campaign "WW"（日耗 $800, ROI=65%）→ 建议暂停
   ```

8. **记录 memory**:
   ```
   [自动优化] Campaign "YY" 降预算 30%（$300→$210），触发: 连续3天 CPI>目标125%
   [自动优化] AdSet "ZZ" 降预算 30%（$150→$105），触发: CPI超标+ROI<80%
   [待确认] Campaign "WW"（$800/天, ROI=65%）建议暂停
   ```

## 输入/输出

### 输入参数

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `project_id` | string | 项目 ID | 必填 |
| `channel` | string | 渠道 | 全渠道 |
| `campaign_id` | string | 指定 Campaign（手动触发时） | 全部活跃 Campaign |

### 输出

| 场景 | 告警级别 | 内容 |
|------|---------|------|
| 自动降预算 | P1 通知 | 调前/调后预算 + 触发原因 |
| 高风险消耗 | P1 确认请求 | 建议操作 + 等待确认 |

## 判定规则

| 规则引擎编号 | 规则名称 | 类别 | 对应条件 |
|-------------|---------|------|---------|
| B02 | Campaign 衰退降预算 | B-时序 | 连续 3 天 CPI > 目标 125% |
| B03 | AdSet 衰退降预算 | B-时序 | 连续 3 天 CPI > 目标 125% 且 ROI < 目标 80% |
| C04 | 高风险消耗预警 | C-复合 | 日耗 > $500 且 ROI < 目标 80% |

## 安全规则

1. **预算调整上限**: 单次降预算不超过 `thresholds.budget_adjustment.auto_max_reduction_pct`（30%），超过需人工确认
2. **只暂停不删除**: 永远不删除 Campaign/AdSet
3. **日耗 >$500 的实体**: 暂停或大幅降预算必须经人工确认
4. **指标冲突时保 ROI**: 量和效率冲突时优先保护回本
5. **先记录再行动**: 每次操作前记录预期结果到 memory
6. **可回溯**: 所有调整记录可追溯，支持后续策略复盘
7. **iOS 72h SKAN 保护期（关键）**: SKAN 回传有 ~72h 延迟，刚启动的 iOS Campaign 不能基于"未到账"指标做暂停/降预算判断。必须使用 `decide_budget_action` 在 ROI 决策前加保护期闸，详见下文"iOS 安全规则"

## iOS 安全规则（SKAN 72h 保护期）

**为什么需要保护期**：SKAN（StoreKit Ad Network）的转化回传有约 72 小时的延迟（Apple 对 postback 做随机分桶 + 隐私窗口）。一条 iOS Campaign 启动后的前 72h 内，DAP 看到的 install/revenue 都是不完整的 —— 此时基于 ROI 做"暂停"或"降预算"会误杀本来正常的 Campaign。

**实现方式**：所有 iOS 行动决策必须经 `decide_budget_action` 函数。该函数在 ROI 分级判定前加一道保护期闸：

```python
from workspace.skills.auto_optimizer.scripts.budget_adjuster import decide_budget_action

result = decide_budget_action(
    campaign_id="C001",
    os="ios",                       # "ios" | "android"，默认 "android"
    launch_date="2026-04-06",       # ISO YYYY-MM-DD，Campaign 启动日
    today="2026-04-07",             # ISO YYYY-MM-DD，当前日
    actual_roi=0.10,                # 当前 Actual_ROI（OS-aware，调用方负责）
    target_roi=2.5,                 # 目标 ROI（通过 get_os_target 取得）
    daily_spend=300.0,              # 当前日耗 USD
    config=cfg,                     # 含 thresholds.budget_adjustment.min_age_hours_ios
)
```

**保护期判定**：

- 若 `os == "ios"` 且同时提供 `launch_date` 和 `today` 且 `(today - launch_date) < min_age_hours_ios` → 直接返回 `action="skip"`，跳过本次调整
- `min_age_hours_ios` 默认 `72`，从 `thresholds.budget_adjustment.min_age_hours_ios` 读取
- 保护期外（或 `os == "android"`）按 ROI 比例分级决策

**ROI 分级决策（保护期外）**：

| 条件 | action |
|------|--------|
| `actual_roi < 0.5 * target_roi` | `pause`（停掉） |
| `0.5 * target_roi <= actual_roi < target_roi` | `reduce`（降预算） |
| `target_roi <= actual_roi < 1.5 * target_roi` | `maintain`（维持） |
| `actual_roi >= 1.5 * target_roi` | `scale`（扩量候选） |

**返回字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `campaign_id` | str | 回显 |
| `action` | str | `"skip"` / `"pause"` / `"reduce"` / `"maintain"` / `"scale"` |
| `reason` | str | 决策理由（保护期会包含 "grace period" + 具体时长） |
| `os` | str | 回显（默认 `"android"`） |

**配置项**（`workspace/config/thresholds.json`）：

```json
{
  "budget_adjustment": {
    "auto_max_reduction_pct": 0.30,
    "min_age_hours_ios": 72
  }
}
```

**与 `compute_adjustment` 的关系**：`compute_adjustment(current_budget, reduction_pct, *, max_auto_reduction_pct, ...)` 是预算金额计算函数（只算降多少美元），不做行动决策；`decide_budget_action` 才是行动决策入口（pause/reduce/maintain/scale），二者并存。

**典型工作流（iOS Campaign 评估）**：

1. `decide_budget_action(...)` → `action`
2. 若 `action == "skip"` → 推 P2"iOS Campaign 处于 SKAN 保护期，本次跳过"，记录 memory
3. 若 `action == "reduce"` → 调 `compute_adjustment` 算具体降幅 → 推 P1 + 等确认（或自动执行）
4. 若 `action == "pause"` → `daily_spend > $500` 须等确认；否则按红线 1-3 执行

## 辅助脚本

所有衰退检测和高风险判定由 `scripts/` 下的 Python 脚本完成。Agent通过 CLI 调用脚本，读取输出 JSON，然后执行操作或推飞书告警。

**CLI 入口**: `python workspace/skills/auto-optimizer/scripts/cli.py <子命令> [参数]`

| 子命令 | 用途 | CLI 示例 |
|--------|------|---------|
| `decay` | Campaign/AdSet 衰退检测 | `cli.py decay --project ROK --days 7` |
| `high-risk` | 高风险消耗预警 | `cli.py high-risk --project ROK` |

CLI 自动加载 config（apps.json + thresholds.json）、构建 ads-channel insights 回调、执行脚本、JSON 输出到 stdout。
