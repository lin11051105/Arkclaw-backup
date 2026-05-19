# 二、吸量/付费素材扩量上新（需求 1.2）

```yaml
flow: scale_candidate
trigger: heartbeat_daily(上传 24h 后) | manual("扩量 XX 素材")
input:
  - 待评估素材列表（Heartbeat 自动获取或手动指定）
  - 扩量目标账户/Campaign（可选，默认按规则匹配）

steps:
  - step: 1
    action: run_script
    script: creative_lifecycle/scale_candidates.py
    cli: |
      python workspace/skills/creative-lifecycle/scripts/cli.py scale-candidates \
        --project <project_id> --date <YYYY-MM-DD>
    note: "CLI 自动加载 config、查询 DAP 素材数据、评估扩量候选、写入报告 JSON。"
    output:
      scale_report: workspace/output/reports/{YYYY-MM-DD}-{HHmmss}-scale-report.json

  # ═══════════════════════════════════════════
  #  Agent处理: 推送 + 用户确认 + 执行扩量
  # ═══════════════════════════════════════════

  - step: 2
    action: feishu_card
    template: templates/feishu-alerts/p1-creative-scale-confirm.md
    note: "从 scale-report.json 读取 volume_candidates 和 paying_candidates"
    fields:
      - "volume_candidates[].{material_id, material_name, ctr, cpi, daily_spend}"
      - "paying_candidates[].{material_id, material_name, roi, cpi}"
      - suggested_budget
    options: ["确认扩量", "暂不扩量"]

  - step: 3
    action: await_user
    on_confirm:
      - step: 3a
        action: call_tool
        note: "同账户扩量"
        tool: ads-channel duplicate-adset
        params: { --adset-id: "<source>", --campaign-id: "<target>" }
      - step: 3b
        condition: "跨账户/跨地区"
        action: call_tool_sequence
        tools:
          - ads-channel create-campaign
          - ads-channel create-adset
          - ads-channel create-ad
      - step: 3c
        action: write_memory
        path: "memory/{YYYY-MM-DD}.md"
        content: "[素材扩量] {material_name} → {tag}（CTR={ctr}, CPI=${cpi}, ROI={roi}）→ Campaign {id}"
      - step: 3d
        action: feishu_notify
        content: "扩量完成 — 素材列表 + 目标账户 + 初始预算 + 新建实体 ID"
    on_skip:
      - action: write_memory
        path: "memory/{YYYY-MM-DD}.md"
        content: "[扩量跳过] 用户选择暂不扩量"
```
