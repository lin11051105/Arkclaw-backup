"""Material summary script.

Implements the material summary flow in creative-lifecycle:
- List materials with metrics from DAP
- Format as markdown table
- Build JSON summary report
- End-to-end orchestration with injected fetcher

Design: dependency-injected fetcher for testability.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

_SKILLS_ROOT = str(Path(__file__).resolve().parents[2])
if _SKILLS_ROOT not in sys.path:
    sys.path.insert(0, _SKILLS_ROOT)
from lib.fetchers import get_app_config


# ═══════════════════════════════════════════════════════════════════════════
# aggregate_by_material
# ═══════════════════════════════════════════════════════════════════════════

def aggregate_by_material(
    materials: list[dict],
) -> list[dict]:
    """Build per-material summary with derived metrics.

    Each material must have: name, id, impressions, clicks, installs, revenue, spend.
    Returns list of dicts with metrics + derived CTR/CPI/ROI.
    Skips materials with no name and no id.
    """
    results = []

    for m in materials:
        mid = m.get("id", "")
        name = m.get("name", "")
        if not mid and not name:
            continue

        imp = m.get("impressions", 0)
        clicks = m.get("clicks", 0)
        inst = m.get("installs", 0)
        rev = m.get("revenue", 0.0)
        spend = m.get("spend", 0.0)

        results.append({
            "material_id": mid or name,
            "material_name": name,
            "impressions": imp,
            "clicks": clicks,
            "installs": inst,
            "revenue": rev,
            "spend": spend,
            "ctr": (clicks / imp * 100) if imp > 0 else 0.0,
            "cpi": (spend / inst) if inst > 0 else 0.0,
            "roi": (rev / spend) if spend > 0 else 0.0,
        })

    return results


# ═══════════════════════════════════════════════════════════════════════════
# format_summary_table
# ═══════════════════════════════════════════════════════════════════════════

COLUMNS = [
    ("素材名称", "material_name"),
    ("曝光", "impressions"),
    ("点击", "clicks"),
    ("安装", "installs"),
    ("收入", "revenue"),
    ("CTR%", "ctr"),
    ("CPI", "cpi"),
    ("ROI", "roi"),
]


def format_summary_table(aggregated: list[dict]) -> str:
    """Format aggregated data as a markdown table."""
    header = "| " + " | ".join(label for label, _ in COLUMNS) + " |"
    separator = "| " + " | ".join("---" for _ in COLUMNS) + " |"

    rows = []
    for row in aggregated:
        cells = []
        for _, key in COLUMNS:
            val = row.get(key, "")
            if isinstance(val, float):
                cells.append(f"{val:.2f}")
            else:
                cells.append(str(val))
        rows.append("| " + " | ".join(cells) + " |")

    return "\n".join([header, separator, *rows])


# ═══════════════════════════════════════════════════════════════════════════
# build_summary_report
# ═══════════════════════════════════════════════════════════════════════════

def build_summary_report(
    *,
    project_id: str,
    date_start: str,
    date_end: str,
    aggregated: list[dict],
) -> dict:
    """Build the summary report JSON."""
    return {
        "report_type": "material_summary",
        "project": project_id,
        "date_range": {
            "start": date_start,
            "end": date_end,
        },
        "summary": aggregated,
    }


# ═══════════════════════════════════════════════════════════════════════════
# run_material_summary — orchestrator
# ═══════════════════════════════════════════════════════════════════════════

def run_material_summary(
    *,
    project_id: str,
    date_start: str,
    date_end: str,
    config: dict,
    fetch_material_report: Callable[[str, str, str, str], list[dict]],
) -> dict:
    """Run material summary with injected fetcher.

    Args:
        project_id: e.g. "ROK"
        date_start: "YYYY-MM-DD"
        date_end: "YYYY-MM-DD"
        config: merged dict with keys: apps
        fetch_material_report: fn(game_alias, channel, start, end) -> [{name, id, impressions, clicks, installs, revenue, spend}]

    Returns pure data dict — file I/O and Feishu upload are the caller's responsibility.
    """
    app = get_app_config(config, project_id)
    game_alias = app.get("game_alias", project_id)

    materials = fetch_material_report(game_alias, "Facebook", date_start, date_end)
    aggregated = aggregate_by_material(materials)
    markdown = format_summary_table(aggregated)

    report = build_summary_report(
        project_id=project_id,
        date_start=date_start,
        date_end=date_end,
        aggregated=aggregated,
    )
    report["markdown"] = markdown

    return report

