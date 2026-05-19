---
name: campaign-builder
description: "广告搭建自动化：自然语言搭建 Campaign、新项目 SOP 校验、链路测试"
metadata:
  hermes:
    tags: [ua, campaign, ads, sop, naming]
    related_skills: [creative-lifecycle, ads-channel]
---

# 广告搭建自动化

## 能力说明

| 能力 | 需求 | 触发方式 |
|------|------|---------|
| 自然语言 → 自动搭建 Campaign | 3.1 | 手动（飞书指令） |
| 新项目投放前 SOP 自动化 | 3.2 | 手动（飞书指令） |
| 新产品链路测试自动化 | 3.3 | 手动（飞书指令） |

## 触发条件

1. **手动触发**: 飞书指令 "搭建广告"、"帮我搭一组美国 Broad 测试"、"检查 SOP"、"测试链路"
2. **注意**: 广告搭建的实际执行由 creative-lifecycle 的 `create-ads` CLI 完成。本 Skill 专注于交互式参数收集（LLM 意图解析 + 用户参数确认），确认后调 `create-ads`

## 执行步骤

### 一、自然语言 → 自动搭建 Campaign（需求 3.1）

**输入**: 自然语言描述（如 "美国+加拿大, iOS, Broad, CBO 500, 视频素材包A"）

**步骤**:

1. **LLM 意图解析**: 将自然语言映射为结构化参数:
   ```json
   {
     "project": "ROK",
     "countries": ["US", "CA"],
     "os": "iOS",
     "audience": "Broad",
     "budget": 500,
     "creative_id": "<ID>" 或 "file_url": "<URL>",
     "asset_type": "video"
   }
   ```
   如果参数不完整（缺少 channel 等必填项），通过飞书追问补全。

   **⚠️ 必问参数**：用户通常只提供项目、地区、OS、预算。以下参数必须确认：

   | 参数 | 为什么必须问 | CLI 对应 |
   |------|-------------|---------|
   | audience（Broad/Interest/LAL/Retarget） | 直接影响 CPI | `--audience` |
   | creative（creative_id 或素材文件） | 决定投放内容 | `--creative-id` 或 `--file-url` |

   **⚠️ 查找现有 creative 必须用 CLI，禁止自己写 Python**：

   用 `list-ads`，每条 Ad 里有 `creative_id`，速度快：
   ```bash
   # 拉最近 20 条 Ad（全账户），从中找 creative_id
   python3 workspace/skills/ads-channel/scripts/cli.py list-ads \
     --account-id act_xxx --limit 20

   # 按 Campaign 过滤
   python3 workspace/skills/ads-channel/scripts/cli.py list-ads \
     --account-id act_xxx --campaign-id <id> --limit 20
   ```

   从结果中选择合适的 `creative_id` 传给 `create-ads --creative-id`。**不需要关心该 creative 是 iOS 还是 Android 的**——`create-ads` 内部会自动检测：
   - 匹配目标 OS → 直接使用
   - 不匹配 → 从该 creative 的媒体文件（video_id/image_hash）自动创建正确平台的新 Creative，结果中显示 `creative_replaced`
   - 无法提取媒体 → 报错，换一个 creative_id

   **高级参数**（出价策略、版位、年龄/性别定向等）用默认值先创建，创建后用 `ads-channel update-entity` 按需调整。不要为了等用户确认每个高级参数而阻塞创建流程。

   用户确认核心参数后即可执行。**绝不可跳过确认直接创建。**

2. **模板匹配**: 读取 `MEMORY.md` 中历史最优模板:
   - 按国家组合 + 受众类型匹配
   - 如有匹配 → 使用历史最优参数填充默认值
   - 如无匹配 → 使用标准模板

3. **参数校验**:
   - 命名规则: 按 `config/naming-rules.json` 生成 Campaign/AdSet/Ad 命名
   - 预算校验:
     - if `budget < $10` → 拒绝并提示最低预算要求
     - if `budget > $5000` → 推送飞书确认请求:"预算 $X 超过单次上限 $5000，是否确认？"，**等待人工确认后执行**
     - if `$10 <= budget <= $5000` → 通过
   - 出价: 在渠道允许范围内

4. **参数确认**（执行前必须展示并等待用户确认）:

   ```
   📋 即将执行 create-ads，参数确认：

   | 参数              | 值                      | 来源         |
   |-------------------|------------------------|-------------|
   | name              | ROK_US_en_video_v1     | 命名规则生成  |
   | creative_id       | <ID> 或 --file-url     | 用户指定     |
   | campaign_budget   | $500 (USD, CBO)        | 用户指定     |
   | adset_budget      | N/A                    | CBO 模式不设  |
   | countries         | US                     | 用户指定     |
   | os                | iOS                    | 用户指定     |
   | audience          | Broad                  | 用户确认     |
   | project           | ROK                    | 用户指定     |
   | objective         | OUTCOME_APP_PROMOTION  | 默认值       |
   | optimization_goal | APP_INSTALLS           | 默认值       |
   | billing_event     | IMPRESSIONS            | 默认值       |
   | bid_strategy      | N/A（账户默认）          | 默认值       |

   确认无误后执行。如需调整，请指出。
   ```

   **预算规则**:
   - **默认 CBO**：预算传 `--budget`（Campaign 层），`campaign_budget` 填值，`adset_budget` 写 N/A
   - **ABO 模式**：用户明确要求 AdSet 级预算时，传 `--adset-budget`，`adset_budget` 填值，`campaign_budget` 写 N/A
   - **两个预算字段必须都列出**（空的写 N/A），让用户清楚看到预算位置

   **表格规则**：
   - 选填参数若使用默认值，来源列写"默认值"；用户显式指定时写"用户指定"
   - 不需要列出不支持的字段

   **其他规则**:
   - 参数对应 `create-ads` CLI 的实际参数，不要列 CLI 不支持的字段
   - **等待用户明确确认后才执行**
   - 高级参数（出价策略、版位等）通过 `create-ads` 的对应 flag 直接传入，**不需要**创建后再用 `ads-channel update-entity` 修改

5. **执行创建**（用户确认后）:

   调用 creative-lifecycle 的 `create-ads` CLI（详见 creative-lifecycle SKILL.md "create-ads 两种模式"）：

   **必填参数**：
   ```bash
   python3 workspace/skills/creative-lifecycle/scripts/cli.py create-ads \
     --creative-id <ID> 或 --file-url <URL> --asset-type <video|image> \
     --name <素材名称> \
     --budget <USD> 或 --adset-budget <USD> \
     --countries <US,JP> --audience <Broad> --os <iOS|Android> --project <ROK>
   ```

   ⚠️ **`--name` 命名规则（必须遵守）**：
   - 格式：`{project}_{region}_{language}_{type}_{version}`，例如 `ROK_US_en_video_v1`
   - `--name` 的值同时作为 **Campaign 名称**（未传 `--campaign-name` 时）
   - 命名不合规会被校验拦截，请用 `naming generate` 或 `naming validate` 预检

   **Campaign 选填参数**（有默认值，按需传）：
   - `--campaign-name <名称>`  — 覆盖 Campaign 名称（不传则使用 `--name` 的值）
   - `--objective <目标>`      — 广告目标，默认 `OUTCOME_APP_PROMOTION`
   - `--campaign-status <状态>` — 初始状态，默认 `PAUSED`

   **AdSet 选填参数**（有默认值，按需传）：
   - `--optimization-goal <目标>` — 优化目标，默认 `APP_INSTALLS`
   - `--billing-event <事件>`    — 计费事件，默认 `IMPRESSIONS`
   - `--bid-strategy <策略>`     — 出价策略：`LOWEST_COST_WITHOUT_CAP` / `LOWEST_COST_WITH_BID_CAP` / `COST_CAP`
   - `--bid-amount <USD>`        — 出价上限（`COST_CAP` 时使用）
   - `--adset-status <状态>`     — 初始状态，默认 `PAUSED`

   用户如需指定出价策略（如 COST_CAP $5），直接在命令中加 `--bid-strategy COST_CAP --bid-amount 5`，无需事后再调。

   - Creative 平台自动适配、任一步骤失败自动中止
   - **不要手动拆成三步分别调 ads-channel CLI**

6. **Campaign 默认创建为暂停状态**（PAUSED），需确认后启动

7. **推送飞书**（必须包含以下所有内容，不可省略）:
   - 结构概览：Campaign/AdSet/Ad ID + 参数摘要
   - `campaign_url` — **必须贴出**，格式：`查看广告：{campaign_url}`
   - 报告附件：若有 `*_file_key`，说明"报告已发至群聊，点击附件下载"
8. **记录 memory**: 操作参数 + 结果

### 二、新项目投放前 SOP 自动化（需求 3.2）

**输入**: `project_id`, `channels[]`, `regions[]`, `objective`

**步骤**:

1. 根据输入变量加载匹配的 SOP 模板:
   ```
   读取 config/sop-templates/default.json
   （未来可按 channel/region/objective 分模板）
   ```

2. 逐项执行自动检查:
   - `auto_check == true` 的项目 → 自动验证
   - `auto_check == false` 的项目 → 标记为"待人工确认"

3. 汇总检查结果:
   ```
   ✅ 已通过 (N 项):
   - 广告账户状态: Active
   - 事件映射: install/purchase 已配置
   ...

   ⏳ 待人工确认 (M 项):
   - MMP 归因配置
   - 预算计划
   - KPI 目标
   ...

   ❌ 未通过 (K 项):
   - 素材包准备: 仅 1 条可用素材（要求 >= 3）
     → 建议: 上传更多素材
   ```

4. 推送飞书: SOP 清单（含每项状态 + 未通过项的修复建议）
5. 记录 memory

### 三、新产品链路测试自动化（需求 3.3）

**输入**: `project_id`, `channel`, `events[]`（默认 install, purchase, register）

**步骤**:

1. **触发测试事件**:
   - 通过 ads-channel 调用渠道的测试模式/沙盒接口发送模拟安装事件
   - 如渠道无沙盒接口，则查询最近 1 小时内的真实回传数据作为验证依据
   - 记录触发时间戳

2. **等待回传到达**（超时时间: 5 分钟，轮询间隔: 30 秒）:
   - 每 30 秒查询一次 DAP 回传状态接口，检查是否收到对应事件
   - 超时未收到 → 标记为"回传未到达"

3. 验证回传到达:
   - 事件是否到达
   - 参数字段完整性（必填字段是否齐全，参考 `thresholds.json` 中 `postback.required_fields`）
   - 归因路径是否正确

4. 判定:
   - 所有事件回传到达且字段完整 → 链路正常
   - 任一事件未到达或字段缺失 → 链路异常，**阻断投放**

5. 推送飞书:
   - 链路正常: P2 "链路测试通过"
   - 链路异常: P0 "链路断点报告" — 包含断点位置、缺失字段、修复建议、阻断投放标记

6. 记录 memory

### 四、OS-aware 预算合规校验（SKAN iOS / Android 分流，需求 8.x）

**目的**：单条新建广告的"目标 CPI / 目标 ROI / 日预算"合规校验。iOS 与 Android 的目标值不同（SKAN iOS 因 72h 回传延迟 + 可见安装比例较低，CPI 通常更高），必须按 OS 分流取目标。

**适用场景**：在执行 `create-ads` 前，先用本检查项验证当前传入的 `daily_budget` 与 SOP 中配置的 `target_cpi` / `target_roi` 是否匹配；不匹配时给出明确的 issue 列表供人工/Agent 决策。

**Python API**：

```python
from workspace.skills.campaign_builder.scripts.sop_checker import check_budget_sop

result = check_budget_sop(
    project_id="ROK",
    proposed_daily_budget=1000.0,   # USD
    config=apps_config,             # workspace/config/apps.json 的内容
    os="ios",                       # "ios" | "android"，默认 "android"
)
```

**目标值解析（关键行为）**：通过 `lib.fetchers.get_os_target(app, os=os, field=...)` 解析，查找顺序：

1. `app["facebook"][f"{os}_target_cpi"]`（OS 专属键，如 `ios_target_cpi=14.0`）
2. `app["facebook"]["target_cpi"]`（旧版统一键，回退兜底）
3. `default=0.0`（最后兜底）

`target_roi` 同理。**`daily_budget` 不做 OS 拆分**——这是单条上限，与 OS 无关。

**返回字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `project_id` | str | 回显输入 |
| `os` | str | 回显输入（默认 `"android"`） |
| `effective_target_cpi` | float | 解析后的目标 CPI（OS 专属优先） |
| `effective_target_roi` | float | 解析后的目标 ROI |
| `proposed_daily_budget` | float | 回显输入 |
| `issues` | list[dict] | issue 列表，每项 `{"code", "severity", "detail"}` |

**Issue 代码**：

| code | 触发条件 | severity |
|------|---------|---------|
| `budget_below_min` | `proposed_daily_budget < $10` | P1 |
| `budget_above_cap` | `proposed_daily_budget > $5000` | P1 |

**异常**：`project_id` 不在 `config["apps"]` 中 → `ValueError`（不静默 fallback 到默认值）。

**配置示例（`apps.json` 片段）**：

```json
{
  "apps": {
    "ROK": {
      "facebook": {
        "daily_budget": 1000,
        "target_cpi": 12.0,
        "ios_target_cpi": 14.0,
        "android_target_cpi": 11.0,
        "target_roi": 2.0,
        "ios_target_roi": 2.5,
        "android_target_roi": 1.8
      }
    }
  }
}
```

上述配置下：

- `os="ios"` → `effective_target_cpi=14.0`, `effective_target_roi=2.5`
- `os="android"` → `effective_target_cpi=11.0`, `effective_target_roi=1.8`
- 若仅有 `target_cpi=12.0`（无 OS 专属键）→ 任何 OS 都回退到 `12.0`

**与 `check_sop` 的关系**：`check_sop(template, check_results)` 仍然存在（模板驱动的 SOP checklist），不受影响。`check_budget_sop` 是新增的预算合规专用函数，二者并存。

**预算合规阈值来源**：`check_budget_sop` 读取 `thresholds.budget_sop.min_daily_usd` 与 `thresholds.budget_sop.max_daily_usd`（位于 `workspace/config/thresholds.json`），缺失时回退到模块默认 `min=50.0 / max=2000.0`（参见 `scripts/sop_checker.py`）。

## 输入/输出

### 输入参数

| 参数 | 类型 | 说明 |
|------|------|------|
| 自然语言描述 | string | 搭建广告时的自然语言指令 |
| `project_id` | string | 项目 ID |
| `channel` | string | 渠道 |
| `channels[]` | string[] | SOP 检查的渠道列表 |
| `regions[]` | string[] | 目标地区 |
| `events[]` | string[] | 链路测试的事件列表 |

### 输出

| 场景 | 推送方式 | 内容 |
|------|---------|------|
| 搭建完成 | 飞书通知 | 结构概览 + 参数摘要 |
| SOP 清单 | 飞书通知 | 每项状态 + 修复建议 |
| 链路正常 | 飞书 P2 | "链路测试通过" |
| 链路异常 | 飞书 P0 | 断点报告 + 阻断投放 |

## 已知坑 & Pitfalls

### 1. 跨账户 Creative 报错（error_subcode 1815696）

`create-ads` CLI 默认使用 `META_AD_ACCOUNT_ID` 环境变量指定的账户。如果 `--creative-id` 指向的 creative 属于**另一个广告账户**，Meta API 会报：

> "创意属于另一广告账户"（error_subcode 1815696）

**解决**：在调用前覆盖环境变量，指向 creative 所属的账户：
```bash
META_AD_ACCOUNT_ID=<creative所属账户的纯数字ID> python3 workspace/skills/creative-lifecycle/scripts/cli.py create-ads ...
```

**预防**：查找 creative 时用 `list-ads --account-id act_xxx`，记住它属于哪个账户。创建广告时用同一个账户。

### 2. 双端搭建必须在命名中区分 OS

同一素材分 iOS / Android 两组搭建时，如果 `--name` 相同（如 `ROK_JP_ja_video_v1`），两个 Campaign、AdSet、Ad 会**完全同名**，在 Ads Manager 中无法区分。

**必须做**：用 `--campaign-name` 加 OS 后缀区分：
- iOS 组：`--campaign-name ROK_JP_ja_video_v1_iOS`
- Android 组：`--campaign-name ROK_JP_ja_video_v1_Android`

### 3. ABO 模式必须有 bid_strategy

使用 `--adset-budget`（ABO 模式）时，Meta API 要求 Campaign 必须设置 `bid_strategy`，否则报 error_subcode 4834005（"无法在未设置竞价策略的情况下使用广告组预算共享"）。

`campaign_manager.py` 已修复（2026-05-08）：ABO + `is_adset_budget_sharing_enabled=true` 时自动补 `LOWEST_COST_WITHOUT_CAP`。如果再遇到此报错，检查 `campaign_manager.py` 第 47-53 行的逻辑。

## 安全规则

1. **不能花钱**: 新创建的 Campaign 默认暂停状态，需人工确认后启动
2. **预算上限**: 单次创建总预算不超过 $5000
3. **命名规范**: 必须通过命名规则校验
4. **链路断点阻断**: 链路测试发现断点时必须阻断投放，不可跳过
5. **先记录再行动**: 所有创建操作前先记录到 memory

## 辅助脚本

命名规则校验和 SOP 清单校验由 `scripts/` 下的 Python 脚本完成。Agent通过 CLI 调用脚本，读取输出 JSON，然后推飞书报告。

**CLI 入口**: `python workspace/skills/campaign-builder/scripts/cli.py <子命令> [参数]`

| 子命令 | 用途 | CLI 示例 |
|--------|------|---------|
| `naming generate` | 生成标准命名 | `cli.py naming generate --fields '{"project":"ROK","region":"US","language":"en","type":"video","version":"v1"}'` |
| `naming validate` | 校验命名是否合规 | `cli.py naming validate --name "ROK_US_en_video_v1"` |
| `naming parse` | 解析命名为字段字典 | `cli.py naming parse --name "ROK_US_en_video_v1"` |
| `sop` | SOP 清单校验 | `cli.py sop --check-results '{"account_status":{"passed":true,"detail":"active"}}'` |

CLI 自动加载 config（naming-rules.json + sop-templates/default.json）、执行脚本、JSON 输出到 stdout。素材命名的生成、校验、解析统一使用 `lib/naming.py`，不要自行解析 naming-rules.json。

