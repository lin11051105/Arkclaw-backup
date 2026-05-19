---
name: sentiment-daily-report
description: "Pgame 广告舆情日报 — 每日北京时间 18:00 拉取 Facebook 广告评论，分类后按 PRD 5 模块生成日报并推送飞书（含素材舆情群转发+点评）"
metadata:
  openclaw:
    emoji: "📰"
    user-invocable: true
    requires:
      tools: ["claude", "ads-channel.facebook.MetaAdsClient", "lib.feishu.FeishuClient"]
      env: ["SOCIAL_FB_TOKEN", "META_AD_ACCOUNT_ID", "FEISHU_APP_ID", "FEISHU_APP_SECRET"]
      python: ["jinja2>=3.1", "jsonschema>=4.0"]
---

# sentiment-daily-report

## 能力说明

Pgame（Clash of Critters）广告舆情盯盘日报。

**仅支持 Pgame 项目**。其他游戏（ROK/PTSLG/AFK 等）不支持本 Skill，它们的舆情监控需求需另行开发。

功能：
- 滚动 24h 拉取 Facebook + Instagram 广告评论（昨日 18:00 ~ 今日 18:00，北京时间）
- 按 sentiment（积极/中性/负面）+ theme（细类）分类
- 输出 5 模块结构化报告（顺序严格对齐 PRD）：
  1. 24h 评论量级总览（总量 + 分语种）
  2. 24h 定性分析（含 2.4 重大舆情警报：A=单素材负面>10 / B=单条评论高传播≥20 / C=占位）
  3. 24h 素材评论明细（按负面数倒序 + 风险等级 red/yellow/green/star）
  4. 持续跟踪重点素材（进入/退出条件已实现，状态落 `workspace/memory/sentiment-tracking/pgame.json`）
  5. 建议动作清单（暂停/扩量/观察）
- 每日 18:00 创建飞书文档（完整报告）并在同一条消息中推送简报摘要 + 文档链接

## 触发条件

- **定时任务（主）**：每日北京时间 18:00（EDT 06:00）cron 触发，推送到日报/异常警报群
- **定时任务（转发）**：北京时间 18:15（EDT 06:15）转发到「pgame 广告素材舆情监控」群（chat_id: `oc_70193b6259b41a10e5351f25c9d1745f`），转发时需附带数据点评
- **飞书指令**：手动触发时 **必须传 `--chat-id`**，否则不会创建飞书文档
- **被其他 Skill 调用**：暂无

### 转发群点评要求

素材舆情群的受众对数据敏感，转发时必须在简报后附一句**简短数据点评**，帮助快速判断态势。点评风格：简洁、带数据、有结论。示例：
- "量不大但负面率偏高（62%），8条基数太小不用紧张，持续关注就好。"
- "今天评论量放大到45条，负面率降到18%，整体健康。"
- "3条素材触发 yellow 预警，负面集中在画质吐槽，建议创意组关注。"

转发消息格式（一条消息，不分多条）：
```
{brief}

💬 {数据点评}

📄 完整报告: {doc_url}
```

## 执行步骤

1. `python3 workspace/skills/sentiment-daily-report/scripts/cli.py --chat-id <当前群的chat_id> generate --product Pgame` 启动。**`--chat-id` 必传**，Hermes 手动触发时从当前对话上下文获取群 ID 并传入。
2. `comment_fetcher.fetch_comments()` 通过 `_load("ads-channel", "facebook", "client")` 取 `MetaAdsClient`，拉取 24h 广告评论
3. `sentiment_classifier.classify()` 走本地 `claude` CLI subprocess（JSONL 协议）打 sentiment+theme
4. `dap_material.batch_resolve_materials()` 从 FB ad name 提取 DAP ID，查 DAP API 获取素材短名和语种
5. `tracking_store.load("Pgame")` 读取 `workspace/memory/sentiment-tracking/pgame.json`
6. `report_generator.build_report()` 组装 5 模块（严格按 PRD 顺序）
7. `feishu_publisher.publish()` 创建飞书文档（不发消息），返回 `doc_url` + `brief`
8. **Hermes 负责发消息**：读取 stdout JSON 中的 `brief` 和 `doc_url`，组合为**一条消息**发到群里。格式：`{brief}\n\n📄 完整报告: {doc_url}`。**不要额外发第二条消息。**

## 输入/输出

### 输入
- ENV: `SOCIAL_FB_TOKEN`, `META_AD_ACCOUNT_ID`, `FEISHU_APP_ID`, `FEISHU_APP_SECRET`
- CLI: `--product Pgame [--from-fixture] [--dry-run]`

### 输出
- 报告 JSON: `workspace/memory/sentiment-reports/YYYY-MM-DD-pgame.json`（schema: `schemas/report_schema.json`）
- 跟踪状态: `workspace/memory/sentiment-tracking/pgame.json`
- 飞书简报：群消息（文本 + 文件附件）

## 判定规则

阈值集中定义在 `workspace/config/thresholds.json` 的 `sentiment_daily_report` 节（**以 thresholds.json 为准**，下表仅作概览）：

| 参数 | 默认 | 触发 |
|------|-----:|------|
| `alert_negative_burst` | 10 | A: 单素材 24h 负面 > 10 → 警报 |
| `alert_high_engagement` | 20 | B: 单条评论 likes+replies ≥ 20 → 警报 |
| `near_threshold_ratio` | 0.85 | A 提前预警（接近阈值） |
| `risk_red_negative_count` | 10 | 负面 >10 条 → red |
| `risk_red_negative_rate` | 0.40 | 负面率 >40% → red |
| `risk_yellow_negative_count_min` | 5 | 负面 5-10 条 → yellow |
| `risk_yellow_negative_rate_min` | 0.20 | 负面率 20-40% → yellow |
| `risk_star_positive_rate` | 0.60 | 积极率 >60% AND 总数 ≥20 → star |
| `risk_star_min_total` | 20 | star 判定最低总量要求 |

风险等级遵循 PDF 规范四级体系：`red`（暂停）/ `yellow`（观察）/ `green`（正常）/ `star`（扩量）。

## 安全规则

- ⚙ **只暂停不删除**：建议清单只输出 pause / scale / observe，永远不输出 delete
- 🔒 **凭据隔离**：FB Token + 飞书凭据从 `.env` 读取，不写入日志/输出
- 📍 **写位置受限**：只写 `workspace/memory/sentiment-{tracking,reports}/` 目录
- ❌ **C 触发器占位**：`C_not_implemented` 是预留扩展点（TikTok/UAC 跨渠道病毒传播），默认不发出，避免假阳性
- ⏳ **前置依赖（ads-channel）**：`ads-channel.facebook.MetaAdsClient.fetch_ad_comments` 接口未就绪期间，本 Skill 仅支持 `--from-fixture` 模式跑通流水线；cron 触发条件（每日 18:00 自动 generate）必须等 ads-channel 接口落地、灰度跑通后才能打开，否则会卡在 `_build_report_live` 拉评论这一步
- ⚠ **降级感知**：`classify()` 失败时（claude CLI 超时 / 非零返回 / JSONDecodeError）会写 `report.meta.degradation_flag`；下游消费方读到 `is_degraded=true` 必须显式提示『含分类降级数据』，禁止沉默使用

## 验证关口

```bash
# 单元测试
python3 -m pytest tests/unit/test_sentiment_daily_report/ -v

# 静态检查
ruff check workspace/skills/sentiment-daily-report
mypy --strict workspace/skills/sentiment-daily-report

# 端到端冒烟（使用 fixture，不打 FB/飞书）
python3 workspace/skills/sentiment-daily-report/scripts/cli.py generate \
    --product Pgame --from-fixture --dry-run
```
