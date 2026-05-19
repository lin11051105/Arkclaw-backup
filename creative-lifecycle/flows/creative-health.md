# 三、素材健康评估 — 衰退检测 + 爆款盘点 + 库存统计（需求 1.4 / 1.6）

```yaml
flow: creative_health
trigger:
  heartbeat_daily: mode = "all"
  manual:
    - intent: "衰退相关（检测衰退、哪些在跌、素材表现差）"
      mode: decay
    - intent: "爆款相关（爆款报告、盘点爆款、哪些素材好）"
      mode: winner
    - intent: "综合评估（素材健康、库存盘点、整体看看）"
      mode: all

params:
  mode: "all" | "decay" | "winner"  # default: all

output_files:
  decay: workspace/output/reports/{YYYY-MM-DD}-{HHmmss}-decay-report.json
  winner: workspace/output/reports/{YYYY-MM-DD}-{HHmmss}-winner-report.json

# ═══════════════════════════════════════════
#  脚本执行（steps 1-8 + 12-14 由脚本完成）
# ═══════════════════════════════════════════

steps:
  - step: 1
    action: run_script
    script: creative_lifecycle/creative_health.py
    cli: |
      python workspace/skills/creative-lifecycle/scripts/cli.py \
        --chat-id <Source 行的群名或 oc_xxx> \
        creative-health \
        --project <project_id> --date <YYYY-MM-DD> --mode <all|decay|winner>
    note: |
      --chat-id 传群名或 oc_xxx 均可，FeishuClient 自动解析。
      从 system prompt Source 行取值（如 "uatest" 或 "oc_xxx..."）。
      CLI 完成后自动上传报告文件并发送到对应群，无需 agent 额外发文件。
    output:
      decay_report: workspace/output/reports/{YYYY-MM-DD}-{HHmmss}-decay-report.json
      winner_report: workspace/output/reports/{YYYY-MM-DD}-{HHmmss}-winner-report.json

  # ═══════════════════════════════════════════
  #  衰退后续操作（Agent处理）
  # ═══════════════════════════════════════════

  - step: 2
    condition: "mode in ['all', 'decay'] AND decay_report.decayed 不为空"
    action: feishu_card
    template: templates/feishu-alerts/p1-creative-decay-confirm.md
    note: "从 decay-report.json 中读取 decayed 列表，展示给用户"
    fields:
      - material_name
      - online_days
      - "daily[-3:].{date, cpi, roi, spend}"
      - target_cpi
      - target_roi
    options: ["确认关停", "继续观察 3 天"]

  - step: 3
    condition: step2 triggered
    action: await_user
    on_confirm:
      - tool: ads-channel batch-update-status
        params: { --entity-ids: "<decayed[].ad_ids>", --type: ad, --status: PAUSED }
      - action: feishu_notify
        level: P1
        content: "关停完成 — {material_name}, 在线{online_days}天, 近3天CPI={daily[-3:].cpi}, ROAS={daily[-3:].roi}"
      - action: write_memory
        path: "MEMORY.md"
        content: "- [{date}] 素材\"{material_name}\"关停: 连续{consecutive_days}天 CPI/ROAS 不达标"
    on_watch:
      - action: write_memory
        path: "memory/{YYYY-MM-DD}.md"
        content: "[继续观察] {material_name}, 重评日期: {date + 3d}"

  - step: 4
    condition: "mode in ['all', 'decay'] AND decay_report.watching 不为空"
    action: write_memory
    path: "memory/{YYYY-MM-DD}.md"
    content: "[素材观察] {material_name} 连续衰退 {consecutive_decay_days} 天（需 {consecutive_days} 天触发）"

  # ═══════════════════════════════════════════
  #  爆款 + 库存后续操作（Agent处理）
  # ═══════════════════════════════════════════

  - step: 5
    condition: mode in ["all", "winner"]
    action: feishu_notify
    level: P2
    note: "从 winner-report.json 中读取 winners 和 inventory"
    content: |
      素材库存盘点 — {project}
      可用素材: {usable_count}（安全线: {safety_line}）[{inventory_status}]
      爆款素材: {winner_count}（最低: {min_hot_count}）[{winner_status}]
      爆款列表: {for w in winners: "{w.material_name} CPI=${w.avg_cpi} ROI={w.avg_roi} {w.sustain_days}天"}

  - step: 6
    action: write_memory
    path: "memory/{YYYY-MM-DD}.md"
    content: |
      [素材健康-{mode}] 衰退pause={pause_count}/watch={watch_count},
      爆款={winner_count}, 库存={usable_count}
```

## 衰退报告 JSON 规范

文件: `workspace/output/reports/{YYYY-MM-DD}-{HHmmss}-decay-report.json`

```json
{
  "report_type": "creative_decay",
  "project": "ROK",
  "date": "2026-04-10",
  "target_cpi": 2.0,
  "target_roi": 1.0,
  "thresholds": {
    "min_online_days": 7,
    "level_1": {"consecutive_days": 3, "roi_below_prev_avg_days": 3},
    "level_2": {"consecutive_days": 5, "roi_below_prev_avg_days": 5}
  },
  "decayed": [
    {
      "material_id": "101",
      "creative_name": "ROK_EN_video_v3",
      "online_days": 14,
      "consecutive_decay_days": 3,
      "action": "pause",
      "daily": [
        {"date": "2026-04-08", "cpi": 2.45, "roi": 0.88, "spend": 150.0},
        {"date": "2026-04-09", "cpi": 2.52, "roi": 0.85, "spend": 140.0},
        {"date": "2026-04-10", "cpi": 2.60, "roi": 0.80, "spend": 130.0}
      ],
      "ad_ids": ["123456", "789012"]
    }
  ],
  "watching": [...],
  "skipped": [...],
  "conclusion": "本次评估 50 个素材：3 个衰退（ROK_EN_video_v3 连续3天不达标...），2 个观察中，45 个跳过（上线不足7天）。"
}
```

## 爆款报告 JSON 规范

文件: `workspace/output/reports/{YYYY-MM-DD}-{HHmmss}-winner-report.json`

```json
{
  "report_type": "winner_creative",
  "project": "ROK",
  "date": "2026-04-10",
  "target_cpi": 2.0,
  "target_roi": 1.0,
  "thresholds": {
    "calculation_months": 3,
    "project_spend_thresholds": {"3D": 450000, "Banner": 200000}
  },
  "inventory": {
    "usable_count": 25,
    "safety_line": 10,
    "status": "normal"
  },
  "winners": [
    {
      "material_id": "101",
      "creative_name": "ROK_EN_video_v1",
      "total_spend": 500000,
      "spend_threshold": 450000,
      "creative_type": "3D",
      "ad_ids": ["123456"]
    }
  ],
  "winner_summary": {
    "winner_count": 5,
    "min_hot_count": 3,
    "status": "normal"
  },
  "conclusion": "本次爆款盘点：6 个爆款素材（最低3个），库存 25 个可用素材（安全线10）状态正常。TOP: ROK_EN_video_v1 CPI=$1.20 ROI=1.85 持续7天。"
}
```
