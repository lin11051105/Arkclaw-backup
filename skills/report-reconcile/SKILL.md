---
name: report-reconcile
description: "报表自动生成与月度财务对账：日报/周报/月报产出、月度渠道账单比对与结算单"
metadata:
  hermes:
    tags: [ua, reporting, reconciliation, finance, settlement]
    related_skills: [dap-ua, ads-channel]
---

# 报表自动生成与月度对账

## 能力说明

| 能力 | 需求 | 触发方式 |
|------|------|---------|
| 日报/周报/月报自动生成 | 6.1 | cron 定时 + 手动 |
| 月度对账 & 结算单 | 6.2 | cron 每月 1 日 + 手动 |

## 触发条件

1. **cron 定时触发**:
   - 日报: 每日 10:00 (`0 10 * * *`)
   - 周报: 每周一 10:00 (`0 10 * * 1`)
   - 月报: 每月 1 日 14:00 (`0 14 1 * *`)
   - 月度对账: 每月 1 日 14:00（与月报同时）
2. **手动触发**: 飞书指令 "生成昨日日报"、"生成上周周报"、"生成月度对账"

## 执行步骤

> **⚠️ 必须使用下方每节标注的 CLI 命令执行，不要自己拆解步骤或发明流程。** CLI 命令已封装完整逻辑，直接运行即可。

### 一、日报/周报/月报自动生成（需求 6.1）

**输入**: `type`（daily/weekly/monthly）, `project_id`（可选）, `channel`（可选）, `date_range`（可选）

**直接用 CLI**:
```bash
python3 workspace/skills/report-reconcile/scripts/cli.py --chat-id <oc_xxx> report --project ROK --type daily --date 2026-04-13
```

**步骤**:

1. **确定日期范围**:
   - daily: 昨天
   - weekly: 上周一至上周日
   - monthly: 上月 1 日至上月末

2. **拉取预配置报表**:
   搜索可用的自定义报表，指定项目名和报表名称关键词
   拉取自定义报表数据，指定报表 ID、日期范围和时区

3. **补充获取额外维度数据**:
   - 安装数据（按渠道/国家/OS 拆分）
   - 收入数据（按安装日期归因）
   - 渠道汇总: 调用 channel-summary Skill

4. **计算指标**:
   - 核心指标: Spend, Installs, CPI, ROI, CTR
   - 环比变化: 日环比（日报）/ 周环比（周报）/ 月环比（月报）
   - 偏移归因: 对比安装日期归因 vs 消耗日期归因的差异

5. **自动标注异常波动**:
   - 计算各指标与 7d/30d 基线的偏离
   - 偏离 > 阈值的项目高亮标注（参考 `thresholds.json` 中 `daily_monitoring` 参数）

6. **填充报表模板**:
   - 日报: `templates/daily-report.md`
   - 周报: `templates/weekly-report.md`
   - 月报: `templates/monthly-report.md`

7. **推送飞书**: P2 级别消息
8. **写入 `memory/YYYY-MM-DD.md`**: `[报表] 日报/周报/月报已生成并推送`

### 二、月度对账 & 结算单（需求 6.2）

**输入**: `month`（YYYY-MM）, `project_id`, `channel`（可选）

**直接用 CLI**:
```bash
python3 workspace/skills/report-reconcile/scripts/cli.py --chat-id <oc_xxx> reconcile --project ROK --month 2026-03
```

**步骤**:

1. **拉取渠道侧消耗数据**（通过 Facebook Insights API）:
   CLI 内部调用 `fetch_insights(start, end, "campaign", time_increment=1)`，获取全状态 Campaign 级逐日 spend。
   返回: `date_start`, `campaign_name`, `spend`（USD）
   > 注意: 当前使用 Insights 归因口径，非账单扣款口径。两者在归因窗口、退款、Coupon 上可能存在差异。Billing API 就绪后可切换。

2. **拉取 DAP 内部消耗明细**:
   CLI 内部调用 `fetch_custom_report("campaign", start, end)`，获取 DAP 侧 Campaign 级消耗数据。
   返回: `日期`, `campaign`, `消耗数`（RMB）

3. **统一口径比对**:
   - 按日期 + 渠道 + Campaign 维度逐条匹配
   - 计算每条记录的差异金额

4. **标记差异项**:
   - 差异率超 5% 的条目 → 标记为"待核查"
   - 差异率 ≤ 5% → 标记为"可接受"
   - 未匹配的条目 → 标记为"未匹配"（注明来源 fb_only 或 dap_only）
   > Coupon / 返点分类依赖渠道账单接口，当前版本暂不区分，统一标"待核查"。

5. **生成结算单草稿**: 加载 `templates/settlement.md`，填充渠道汇总、差异明细、Coupon/返点段。无模板时使用内联 Markdown fallback。

6. **推送飞书**:
   - 结算单草稿
   - 差异项清单
   - Coupon / 返点明细
   - 状态: **待人工确认**

7. **写入 `memory/YYYY-MM-DD.md`**: `[对账] <month> 结算单已生成，差异项 N 条，待人工确认`

### 三、OS-aware 报表（SKAN iOS 真值路径，需求 8.x）

iOS 概率归因从 2026-05 起改用 SKAN 真值（DAP 概率口径仅作辅助参考）。Android 不变，继续走 DAP。报表层支持三种 OS 模式，互不影响：

| `os` 取值 | 行为 | 数据来源 |
|-----------|------|----------|
| `android`（默认） | 仅 DAP day 表，向后兼容旧调用 | `fetch_custom_report("day", ...)`（DAP 概率归因） |
| `ios` | 仅 SKAN view，强校验 `fetch_skan_by_game_day` + `game_id` | `hive.da_bi_dw.v_tb_skan_report_day_v2`（SKAN 真值，view 内已 null gross-up） |
| `both` | 双口径并行：DAP 行作为 Android 切片 + SKAN 行作为 iOS 切片，spend-weighted 合并 | DAP（Android）+ SKAN（iOS） |

**数据列映射**（SKAN view 列名为英文，与 DAP 中文列分开）：

| 指标 | DAP 行（Android） | SKAN 行（iOS） |
|------|-------------------|----------------|
| 消耗 | `消耗数` | `cost` |
| 安装 | `安装数` | `sk_install` |
| 收入 | `消耗数 × Actual_ROI`（按行派生） | `revenue`（view 内已 null gross-up） |
| ROI | `Actual_ROI` | `revenue / cost` |

**`generate_report` 新签名**（向后兼容，新参数全部 optional）：

```
generate_report(
    report_type, project_id, *,
    date_override=None, config,
    fetch_custom_report,                  # 既有
    fetch_channel_summary=None,           # 既有
    fetch_skan_by_game_day=None,          # NEW: fn(*, date_start, date_end) -> list[dict]
    game_id=None,                         # NEW: 数据仓库 game_id（如 ROK=10043）
    os="android",                         # NEW: "android" | "ios" | "both"
) -> dict
```

**约束**：当 `os ∈ {"ios", "both"}` 时，`fetch_skan_by_game_day` 与 `game_id` **二者皆必填**，否则抛 `ValueError`。`game_id` 来自 `apps.json` 的 `<project>.game_id`（顶层字段，由 T6 引入）。

**输出形状**：

- `os="android"`：`metrics` 仍是扁平 `{spend, installs, cpi, roi, ctr, *_dod, *_prev, ...}`，无 `by_os` key（向后兼容）。
- `os ∈ {"ios", "both"}`：`metrics` 顶层为 spend-weighted 合并值（CPI/ROI 不是简单平均），并新增 `by_os: {ios: {...}, android: {...}}` 子结构。`ctr` 在 SKAN 路径下为 0（SKAN 无展示/点击信号）。

**双口径表格渲染**：当 `metrics.by_os` 存在时，模板/CLI 输出层应同时展示总账、iOS 切片、Android 切片三行，并在备注中注明 iOS 数据源 `hive.da_bi_dw.v_tb_skan_report_day_v2`。

**SKAN 回传延迟保护**：SKAN 回传窗口 ≥ 72h，建议日报/周报的报表日期 ≥ 当日 -3 天；月度对账已经天然滞后一个月，不受影响。

**触发组合示例**（CLI 接入后）：

```bash
# Android 默认（旧行为）
python3 .../report-reconcile/scripts/cli.py --chat-id <oc_xxx> report --project ROK --type daily --date 2026-04-12

# iOS 单口径（SKAN 真值）
python3 .../report-reconcile/scripts/cli.py --chat-id <oc_xxx> report --project ROK --type daily --date 2026-04-12 --os ios

# 双口径（iOS 真值 + Android 概率归因，渲染 by_os 拆分）
python3 .../report-reconcile/scripts/cli.py --chat-id <oc_xxx> report --project ROK --type daily --date 2026-04-12 --os both
```

> 📌 `_fetchers.py` 已经从 `lib.fetchers` 重导出 `make_fetch_skan_by_game_day(game_id: int)`，CLI 在传入 `--os ios|both` 时按 `apps.json[project].game_id` 注入闭包；与 `make_fetch_custom_report(game=project_id)` 并行存在，互不冲突。

## 输入/输出

### 输入参数

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `type` | string | 报表类型（daily/weekly/monthly） | 必填 |
| `project_id` | string | 项目 ID | 全部项目 |
| `channel` | string | 渠道 | 全渠道 |
| `date_range` | string | 日期范围 | 根据 type 自动计算 |
| `month` | string | 对账月份（YYYY-MM） | 上月 |

### 输出格式

| 场景 | 模板 | 告警级别 |
|------|------|---------|
| 日报 | `templates/daily-report.md` | P2 |
| 周报 | `templates/weekly-report.md` | P2 |
| 月报 | `templates/monthly-report.md` | P2 |
| 结算单 | `templates/settlement.md` | P2（需人工确认） |

## Pitfalls

### Gateway OAuth Token 过期（cron 环境常见）

CLI 依赖 Atlas AI Gateway 的 OAuth token 访问 DAP。Token 有效期约 5–7 天（基于历史观察：2026-04-18、04-25、05-04 连续三次过期）。过期后所有依赖 DAP 的 cron 任务全部失败。CLI 报错包含 `idaas.lilith.com` 授权链接或 `端口 20265 已被占用`。

**诊断**：
```bash
atlas-skillhub gateway status
# 看 "valid": false 和 "expires_at" 字段
```

**cron 环境无法自动修复** — `gateway login` 需要浏览器交互式 OAuth。遇到此错误时：
1. 先清理残留端口占用：`lsof -ti:20265 | xargs kill -9 2>/dev/null; sleep 1`
2. 再次尝试 CLI（端口占用可能是上次失败残留，清理后可恢复）
3. 如果仍报 OAuth/idaas 错误 → token 确实过期，无法在 cron 中自动修复
4. 记录到 `memory/YYYY-MM-DD.md`
5. 通过 feishu.py 直接发送 **P0 告警**（DAP 不可用属于管线中断，按 AGENTS.md P0 级别处理），内容包含：
   - 失败的报告类型和日期范围
   - Token 过期时间（从 `atlas-skillhub gateway status` 的 `expires_at` 获取）
   - 恢复命令：`lsof -ti:20265 | xargs kill -9` + `atlas-skillhub gateway login`
   - 补跑命令：完整的 CLI 报告命令

**feishu.py 告警 fallback**（CLI 本身依赖 DAP 无法使用时）：
```bash
cd /root/workspace/ua_agent && python3 -c "
import sys; sys.path.insert(0, 'workspace/skills')
from lib.feishu import FeishuClient
client = FeishuClient(chat_id='<oc_xxx>')
client.send_text('<P0 告警内容>')
"
```
> feishu.py 不依赖 DAP，token 过期时仍可用于发送告警。

### 端口 20265 残留占用

DAP 回调监听使用本地端口 20265。如果上次 CLI 异常退出，端口可能残留占用。**每次 CLI 调用失败提示端口占用时先清理再重试**:
```bash
lsof -ti:20265 | xargs kill 2>/dev/null; sleep 1
```
清理后重试一次即可判断是端口残留还是 token 过期。

## 安全规则

1. 财务数据（消耗明细、账单、结算单）**不得泄露到非授权渠道**
2. 结算单为**草稿状态**，必须经人工确认后才能作为最终结算依据
3. 报表数据需**注明数据截止时间和数据来源**，避免误导决策
4. Coupon / 返点等特殊项需单独列明，不可混入常规消耗

## 辅助脚本

所有报表生成和对账逻辑由 `scripts/` 下的 Python 脚本完成。

🚫 **禁止手动拉 DAP/Insights 数据再用 execute_code 处理** — 原始数据行数多，灌入上下文会导致 ReadTimeout。必须通过 CLI 调用，数据处理在本地 Python 完成，你只需读取 CLI 输出的汇总 JSON。

Agent 通过 CLI 调用脚本，读取输出 JSON/Markdown，然后推飞书或生成文件。

**CLI 入口**: `python workspace/skills/report-reconcile/scripts/cli.py [--chat-id <oc_xxx>] <子命令> [参数]`

⚠️ **`--chat-id` 是顶层参数，必须放在子命令之前**。

| 子命令 | 用途 | CLI 示例 |
|--------|------|---------|
| `report` | 生成日报/周报/月报 | `cli.py --chat-id <oc_xxx> report --project ROK --type daily --date 2026-04-12` |
| `reconcile` | 月度对账 & 结算单 | `cli.py --chat-id <oc_xxx> reconcile --project ROK --month 2026-03 --exchange-rate 7.24` |

CLI 自动加载 config（apps.json + thresholds.json）、构建 DAP/ads-channel 回调、执行脚本、JSON 输出到 stdout。

**⚠️ `--chat-id` 必须传（对话场景）**：
- 从 system prompt `Source` 行读取群名或 oc_xxx，直接传给 `--chat-id`（FeishuClient 自动解析群名）
- `report` 子命令传了则自动上传并发文件到该群
- 定时任务（cron）不传，报告只入库不发群
