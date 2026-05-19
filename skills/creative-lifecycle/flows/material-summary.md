# 四、素材数据汇总（需求 1.7）

**输入**: `project_id`, `date_start`, `date_end`, `channel`（可选）

**步骤**:

1. **运行汇总脚本**:
   ```bash
   python workspace/skills/creative-lifecycle/scripts/cli.py \
     --chat-id <从 Source 行群名解析出的 oc_xxx> \
     summary \
     --project <project_id> --date-start <date_start> --date-end <date_end>
   ```
   CLI 自动查询 DAP 素材数据、按素材 ID 聚合指标、写入 `{date_start}_{date_end}-summary-report.json`。
   输出 JSON 中 `summary` 字段包含聚合结果，可用 `format_summary_table()` 生成 markdown 表格。

2. **推送飞书**: 将 `format_summary_table` 输出的 markdown 表格推送到飞书

3. **写入 memory**: `memory/YYYY-MM-DD.md`
   ```
   [素材汇总] {project} {date_start}~{date_end}: {len(summary)}个素材
   ```
