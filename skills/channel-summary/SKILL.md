---
name: channel-summary
description: "渠道数据汇总与 CPE 点位达成率总览"
metadata:
  hermes:
    tags: [ua, reporting, channel, cpe, summary]
    related_skills: [dap-ua]
---

# 渠道数据汇总与 CPE 达成率

## 能力说明

| 能力 | 需求 | 触发方式 |
|------|------|---------|
| CPE 渠道点位达成率总览 | 5.5 | 定时（cron）+ 手动 |
| 渠道汇总 | 5.6 | 定时（cron）+ 手动 |

所有数据通过 DAP 平台接口查询，`channel` 参数区分渠道。

## 触发条件

1. **定时触发（cron）**: 每日/每周自动生成渠道汇总
2. **手动触发（飞书指令）**: "查看渠道汇总"、"CPE 达成率"
3. **被 report-reconcile 调用**: 作为日报/周报/月报的子模块

## 执行步骤

> **⚠️ 必须使用下方每节标注的 CLI 命令执行，不要自己拆解步骤或发明流程。** CLI 命令已封装完整逻辑，直接运行即可。

### 一、CPE 渠道点位达成率总览（需求 5.5）

**输入**: `project_id`, `date_start`, `date_end`, `channel`（可选，默认全部 CPE 渠道）

**直接用 CLI**:
```bash
python3 workspace/skills/channel-summary/scripts/cli.py cpe --project ROK --month 2026-04
```

**步骤**:

1. 读取 `config/thresholds.json` 中 `cpe.achievement_rate_alert_pct` 参数
2. 查询 CPE 渠道各点位的投放数据（达成量），按项目和日期范围
3. 获取约定量数据（来源 [待确认]: 合同系统 / 手工录入 / DAP 配置）
4. 计算达成率:
   ```
   achievement_rate = actual_achieved / contracted_quantity
   ```
5. 判定（引用规则引擎 T15）:
   - if `achievement_rate < thresholds.cpe.achievement_rate_alert_pct` → P1 告警
6. 输出报表:
   ```
   📊 CPE 达成率总览 — 项目XX（<start> ~ <end>）

   | 渠道 | 点位 | 约定量 | 实际达成 | 达成率 | 消耗 | 状态 |
   |------|------|--------|---------|--------|------|------|
   | 渠道A | 点位1 | 1000 | 850 | 85% | $500 | ✅ |
   | 渠道B | 点位2 | 2000 | 1200 | 60% | $800 | ⚠️低于70% |
   ```
7. 写入 `memory/YYYY-MM-DD.md`

### 二、渠道汇总（需求 5.6）

**输入**: `project_id`（可选，默认全部）, `date_start`, `date_end`, `group_by`（逗号分隔维度组合）

**`--group-by` 维度说明**:

| 维度 | DAP 表 | 说明 |
|------|--------|------|
| `channel` | media_src | 按渠道（默认） |
| `country` | country | 按国家 |

每张 DAP 表只有一个维度列 + 29 个指标列，不支持跨表维度组合。

**直接用 CLI**:
```bash
# 渠道维度（默认）
python3 workspace/skills/channel-summary/scripts/cli.py channel --date-start 2026-04-06 --date-end 2026-04-12
# 国家维度（加 --top-n 避免输出过大）
python3 workspace/skills/channel-summary/scripts/cli.py channel --date-start 2026-04-06 --date-end 2026-04-12 --group-by country --top-n 20
```

**步骤**:

1. 按指定维度查询核心投放指标（Spend、Installs、CPI、ROI、CTR、CVR），汇总各维度结果

2. 计算汇总指标: Spend, Installs, CPI, ROI, CTR, CVR

3. 维度组合由 `--group-by` 参数决定，支持任意单维度或同表多维度组合

4. 输出报表:
   ```
   📊 渠道汇总 — 全项目（<start> ~ <end>）

   | 渠道 | 消耗 | 安装 | CPI | ROI | CTR | CVR |
   |------|------|------|-----|-----|-----|-----|
   | Meta | $10K | 5000 | $2.0 | 120% | 3.5% | 8% |
   | TikTok | $8K | 4500 | $1.8 | 115% | 4.0% | 7% |
   | Google | $5K | 3000 | $1.7 | 110% | N/A | N/A |
   | CPE | $3K | 1000 | $3.0 | 90% | N/A | N/A |
   | **合计** | **$26K** | **13500** | **$1.93** | **113%** | - | - |
   ```

5. 推送飞书 / 返回给调用方（如 report-reconcile Skill）
6. 写入 `memory/YYYY-MM-DD.md`

### 三、iOS / Android OS 拆分（SKAN 真值路径）

> 自 2026-05-08 起，`channel` 子命令支持 `--os` 标志，按 OS 分别走不同归因源：

| `--os` | iOS 数据源 | Android 数据源 | 适用场景 |
|--------|-----------|---------------|---------|
| `android` | — | DAP `media_src` 表（概率归因） | Android 单端复盘、与 report-reconcile 对账 |
| `ios` | `hive.da_bi_dw.v_tb_skan_report_day_v2`（SKAN 真值） | — | iOS 单端复盘、SKAN 校准 |
| `both` *(默认)* | SKAN 视图 | DAP 表 | 跨端汇总（消耗加权 CPI/ROI 由 `lib.os_aggregator.combine` 计算） |

**关键约束**:

- `--os ios` 或 `--os both` 必须同时传 `--game-id`（SKAN 视图按 `game_id` 过滤；映射见 `apps.json` 各项目的 `skan.game_id`）。
- iOS 路径仅支持 `--group-by channel`，因为 SKAN 视图维度为 `(third_dt, game_id, spreader_name)`，不含 `country`/`media_src`。传 `country` 会触发 `ValueError`。
- **72h SKAN 回传缓冲**：SKAN postback 最多延迟 72 小时回传，iOS 当日数据要等 3 天后才接近完整。Cron 调度时 `date_end <= today-3`，否则 SKAN 行数据会偏低；CLI 不强行阻塞，但 `--os ios|both` 且 `date_end > today-3` 时输出会附 `warning` 字段。
- ROI 公式差异：SKAN 路径用 `revenue / (1 - sk_conversion_null/sk_install) / cost`（按 null fraction gross-up 后再除消耗），DAP 路径直接使用 `首日付费ROI`。

**CLI 示例**:

```bash
# 默认（both，SKAN+DAP 合并；ROK game_id=10043）
python3 workspace/skills/channel-summary/scripts/cli.py channel \
    --date-start 2026-04-06 --date-end 2026-04-12 \
    --os both --game-id 10043

# 仅 iOS（SKAN 真值）
python3 workspace/skills/channel-summary/scripts/cli.py channel \
    --date-start 2026-04-06 --date-end 2026-04-12 \
    --os ios --game-id 10043

# 仅 Android（DAP 概率归因，不需 --game-id）
python3 workspace/skills/channel-summary/scripts/cli.py channel \
    --date-start 2026-04-06 --date-end 2026-04-12 \
    --os android
```

**输出结构（JSON）**:

```jsonc
{
  "os": "both",
  "group_by": "channel",
  "totals": {
    "spend": 26000.0, "installs": 13500, "revenue": 29380.0,
    "cpi": 1.93, "roi": 1.13,
    "by_os": {
      "ios":     {"spend": 8000.0,  "installs": 3500,  "revenue": 9100.0,  "cpi": 2.29, "roi": 1.14},
      "android": {"spend": 18000.0, "installs": 10000, "revenue": 20280.0, "cpi": 1.80, "roi": 1.13}
    }
  },
  "ios_rows":     [/* SKAN rows: spreader_name, spend, installs, revenue, cpi, roi */],
  "android_rows": [/* DAP rows: media_src, spend, installs, revenue, cpi, roi, ctr, cvr */],
  "rows": [/* 合并后用于兼容旧消费者；优先使用 ios_rows / android_rows */],
  "markdown": "## iOS（SKAN 真值）\n... \n## Android（DAP 概率归因）\n..."
}
```

## 输入/输出

### 输入参数

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `project_id` | string | 项目 ID | 全部项目 |
| `channel` | string | 渠道 | 全渠道 |
| `date_start` / `date_end` | string | 日期范围 | 近 7 天 |
| `group_by` | string | 聚合维度: channel 或 country | channel |

### 输出格式

| 场景 | 推送方式 | 内容 |
|------|---------|------|
| CPE 达成率 | 飞书消息 | 点位达成率表格 + 低达成率标记 |
| 渠道汇总 | 飞书消息 | 渠道级指标表格 |
| 作为子模块 | 返回结构化数据 | 供 report-reconcile 使用 |

## 判定规则

| 规则引擎编号 | 规则名称 | 对应章节 |
|-------------|---------|---------|
| T15 | CPE 达成率低于 70% | 一 |

## 安全规则

1. 纯数据查询和汇总，**不执行任何修改操作**
2. 财务相关数据（消耗、费用）不得泄露到非授权渠道
3. CPE 约定量等合同信息属于商务敏感数据，仅推送到授权群

## 辅助脚本

所有汇总计算由 `scripts/` 下的 Python 脚本完成。

🚫 **禁止手动拉 DAP 数据再用 execute_code 处理** — 国家维度有 200+ 行原始数据，灌入上下文会导致 ReadTimeout。必须通过 CLI 调用，数据聚合在本地 Python 完成，你只需读取 CLI 输出的汇总 JSON。

Agent 通过 CLI 调用脚本，读取输出 JSON，然后推飞书或生成汇总。

**CLI 入口**: `python workspace/skills/channel-summary/scripts/cli.py <子命令> [参数]`

| 子命令 | 用途 | CLI 示例 |
|--------|------|---------|
| `channel` | 渠道汇总（维度: channel 或 country） | `cli.py channel --date-start 2026-04-06 --date-end 2026-04-12 --group-by country --top-n 20` |
| `cpe` | CPE 渠道点位达成率总览 | `cli.py cpe --project ROK --month 2026-04 --account-ids act_xxx,act_yyy` |

⚠️ **国家维度务必加 `--top-n`**：含 country 的维度可能返回 200+ 国家，输出过大会导致超时。建议 `--top-n 20`（按消耗排序取前 20，totals 仍为全量汇总）。

示例：
```bash
cli.py channel --date-start 2026-04-06 --date-end 2026-04-12 --group-by country --top-n 20
```

CLI 自动加载 config（apps.json + thresholds.json）、构建 DAP/ads-channel 回调、执行脚本、JSON 输出到 stdout。

### cpe 多项目查询流程

**`cpe` 命令每次只查一个 `--project`，多项目需分别调用。** 一个项目可能对应多个 Facebook 广告账户，必须全部传入才能得到正确的汇总数据。

**标准流程**：
```bash
# Step 1：按项目名查出关联的所有广告账户
account-info --all --name ROK   # → act_xxx, act_yyy
account-info --all --name AFK   # → act_zzz
account-info --all --name IGAME # → act_aaa

# Step 2：逐项目查询（--account-ids 传入所有关联账户，逗号分隔）
cpe --project ROK   --month 2026-04 --account-ids act_xxx,act_yyy
cpe --project AFK   --month 2026-04 --account-ids act_zzz
cpe --project IGAME --month 2026-04 --account-ids act_aaa
```

`--account-ids` 不传时使用环境变量 `META_AD_ACCOUNT_ID`（单账户场景）。多账户时 fetcher 内部循环查询后自动合并 rows，`_extract_action_value` 对所有 rows 求和，无重复计数。
