"""Short-name summary script.

Implements the short-name aggregation flow in creative-lifecycle:
- parse_short_name: 从素材全名解析短名（去掉 region + language）
- aggregate_by_short_name: 按短名聚合指标
- run_short_name_summary: 端到端编排

Design: dependency-injected fetcher for testability.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Callable


# ═══════════════════════════════════════════════════════════════════════════
# naming validation + parse_short_name
# ═══════════════════════════════════════════════════════════════════════════

def is_standard_material_name(material_name: str, naming_rules: dict) -> bool:
    """是否满足标准命名（可解析为短名）。不满足时聚合 key 使用原全名。"""
    from lib.naming import validate_material_name
    return validate_material_name(material_name, naming_rules)["is_valid"]


def parse_short_name(material_name: str, naming_rules: dict) -> str:
    """从素材名解析短名，去掉 region 和 language 字段。

    规则: {project}_{region}_{language}_{type}_{version}
    短名: {project}_{type}_{version}

    若不符合标准命名，返回原全名作为聚合 key（不丢弃、不抛错）。
    """
    from lib.naming import parse_short_name as _parse
    return _parse(material_name, naming_rules)


# ═══════════════════════════════════════════════════════════════════════════
# aggregate_by_short_name
# ═══════════════════════════════════════════════════════════════════════════

def aggregate_by_short_name(
    materials: list[dict],
    naming_rules: dict,
) -> list[dict]:
    """按短名聚合素材数据。

    每条素材需包含: name, id, impressions, clicks, installs, revenue, spend.
    返回按短名聚合后的 list[dict]，包含 total_* 指标和派生指标。
    """
    groups: dict[str, dict] = defaultdict(lambda: {
        "total_impressions": 0,
        "total_clicks": 0,
        "total_installs": 0,
        "total_revenue": 0.0,
        "total_spend": 0.0,
        "materials": [],
    })

    for m in materials:
        name = m.get("name", "")
        short = parse_short_name(name, naming_rules)

        g = groups[short]
        g["total_impressions"] += m.get("impressions", 0)
        g["total_clicks"] += m.get("clicks", 0)
        g["total_installs"] += m.get("installs", 0)
        g["total_revenue"] += m.get("revenue", 0.0)
        g["total_spend"] += m.get("spend", 0.0)
        g["materials"].append(name)

    results = []
    for short_name, g in groups.items():
        total_installs = g["total_installs"]
        total_spend = g["total_spend"]
        total_impressions = g["total_impressions"]
        total_clicks = g["total_clicks"]
        total_revenue = g["total_revenue"]

        results.append({
            "short_name": short_name,
            "material_count": len(g["materials"]),
            "materials": g["materials"],
            "total_impressions": total_impressions,
            "total_clicks": total_clicks,
            "total_installs": total_installs,
            "total_revenue": total_revenue,
            "total_spend": total_spend,
            "cpi": total_spend / total_installs if total_installs > 0 else 0.0,
            "roi": total_revenue / total_spend if total_spend > 0 else 0.0,
            "ctr": total_clicks / total_impressions * 100 if total_impressions > 0 else 0.0,
        })

    return results


# ═══════════════════════════════════════════════════════════════════════════
# format_short_name_table
# ═══════════════════════════════════════════════════════════════════════════

_COLUMNS = [
    ("短名", "short_name"),
    ("素材数", "material_count"),
    ("总曝光", "total_impressions"),
    ("总点击", "total_clicks"),
    ("总安装", "total_installs"),
    ("总花费", "total_spend"),
    ("总收入", "total_revenue"),
    ("CPI", "cpi"),
    ("ROI", "roi"),
    ("CTR%", "ctr"),
]


def format_short_name_table(aggregated: list[dict]) -> str:
    """Format aggregated short-name data as a markdown table（附件 / 本地报告用）。"""
    header = "| " + " | ".join(label for label, _ in _COLUMNS) + " |"
    separator = "| " + " | ".join("---" for _ in _COLUMNS) + " |"

    rows = []
    for row in aggregated:
        cells = []
        for _, key in _COLUMNS:
            val = row.get(key, "")
            if val is None:
                cells.append("N/A")
            elif isinstance(val, float):
                cells.append(f"{val:.2f}")
            else:
                cells.append(str(val))
        rows.append("| " + " | ".join(cells) + " |")

    return "\n".join([header, separator, *rows])


def format_short_name_feishu_lines(aggregated: list[dict], *, max_rows: int = 40) -> str:
    """飞书正文用：逐行列表，无 markdown 表格（AC-MSG-1）。超过 max_rows 条则提示看附件。"""
    lines: list[str] = []
    shown = aggregated[:max_rows]
    for row in shown:
        lines.append(
            f"· {row.get('short_name', '')} | 素材数 {row.get('material_count', 0)} | "
            f"消耗 {row.get('total_spend', 0):.2f} | 安装 {row.get('total_installs', 0)} | "
            f"CPI {row.get('cpi', 0):.2f} | ROI {row.get('roi', 0):.2f} | CTR {row.get('ctr', 0):.2f}%"
        )
    if len(aggregated) > max_rows:
        lines.append(f"… 共 {len(aggregated)} 条短名，其余见附件 JSON。")
    return "\n".join(lines) if lines else "（无数据）"


# ═══════════════════════════════════════════════════════════════════════════
# run_short_name_summary — orchestrator
# ═══════════════════════════════════════════════════════════════════════════

def run_short_name_summary(
    *,
    project_id: str,
    date_start: str,
    date_end: str,
    config: dict,
    fetch_material_report: Callable[[str, str, str, str], list[dict]],
) -> dict:
    """Run short-name summary with injected fetcher.

    Args:
        project_id: e.g. "ROK"
        date_start: "YYYY-MM-DD"
        date_end: "YYYY-MM-DD"
        config: merged dict with keys: apps, naming_rules
        fetch_material_report: fn(game_alias, channel, start, end) -> [...]

    Returns pure data dict — file I/O and Feishu upload are the caller's responsibility.
    """
    apps = config.get("apps", {})
    app = apps.get(project_id, {})
    game_alias = app.get("game_alias", project_id)
    naming_rules = config.get("naming_rules", {})

    materials = fetch_material_report(game_alias, "Facebook", date_start, date_end)
    by_short_name = aggregate_by_short_name(materials, naming_rules)
    markdown = format_short_name_table(by_short_name)
    feishu_summary = format_short_name_feishu_lines(by_short_name)

    return {
        "report_type": "short_name_summary",
        "project_id": project_id,
        "date_range": {"start": date_start, "end": date_end},
        "by_short_name": by_short_name,
        "markdown": markdown,
        "feishu_summary": feishu_summary,
    }
