"""CPE 达成率总览 — 5.5 CPE 渠道点位达成率。

计算各项目 CPE 约定事件的月度达成率，从 Facebook Insights actions 中提取实际完成量，
与 apps.json 的 cpe_monthly_target 对比，输出达成率报表和告警。

Design: dependency-injected fetcher for testability.
"""
from __future__ import annotations

import calendar
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

_SKILLS_ROOT = str(Path(__file__).resolve().parents[2])
if _SKILLS_ROOT not in sys.path:
    sys.path.insert(0, _SKILLS_ROOT)
from lib.fetchers import get_app_config, get_fb_config


def _extract_action_value(
    insights: list[dict],
    event_name: str,
) -> int:
    """从 Insights 的 actions 数组中提取指定 event 的 value 总和。

    支持精确匹配和后缀匹配：
    - "fb_mobile_purchase" 匹配 "fb_mobile_purchase" 和 "app_custom_event.fb_mobile_purchase"
    - "purchase" 匹配 "purchase" 和 "onsite_app_purchase" 等
    """
    total = 0
    for row in insights:
        actions = row.get("actions", [])
        for action in actions:
            at = action.get("action_type", "")
            if at == event_name or at.endswith(f".{event_name}"):
                total += int(action.get("value", 0))
    return total


def check_cpe_achievement(
    project_id: str,
    month: str,
    *,
    config: dict,
    fetch_insights: Callable[[str, str, str], list[dict]],
    today: str | None = None,
) -> dict:
    """检查单项目 CPE 达成率。

    Args:
        project_id: 项目 ID
        month: 月份 "YYYY-MM"
        config: {"apps": ..., "thresholds": ...}
        fetch_insights: fn(date_start, date_end, level) → [row, ...]
        today: 当前日期 "YYYY-MM-DD"（可选，默认 date.today()）
    """
    app = get_app_config(config, project_id)
    target = get_fb_config(app, "cpe_monthly_target", 0)
    event_name = get_fb_config(app, "cpe_event_name", "fb_mobile_purchase")

    cpe_thresholds = config.get("thresholds", {}).get("cpe", {})
    alert_threshold = cpe_thresholds.get("achievement_rate_alert_pct", 0.70)

    # Parse month and today
    year, mon = int(month[:4]), int(month[5:7])
    days_total = calendar.monthrange(year, mon)[1]

    if today:
        today_date = date.fromisoformat(today)
    else:
        today_date = date.today()

    month_start = f"{month}-01"
    month_start_date = date.fromisoformat(month_start)

    # Determine the end date for fetching: min(today, month_end)
    month_end_date = date(year, mon, days_total)
    fetch_end_date = min(today_date, month_end_date)
    fetch_end_str = fetch_end_date.isoformat()

    # Calendar days elapsed within the queried month
    days_elapsed = (fetch_end_date - month_start_date).days + 1

    # Fetch insights for month-to-date
    insights = fetch_insights(month_start, fetch_end_str, "account")

    # Extract actual count
    actual = _extract_action_value(insights, event_name)

    # Calculate rates
    achievement_rate = actual / target if target > 0 else 0.0
    projected_monthly = int(actual / days_elapsed * days_total) if days_elapsed > 0 else 0

    # Determine status
    if achievement_rate >= alert_threshold and projected_monthly >= target:
        status = "on_track"
    elif achievement_rate >= alert_threshold:
        status = "at_risk"
    else:
        status = "behind"

    # Alerts
    alerts: list[dict] = []
    if achievement_rate < alert_threshold:
        alerts.append({
            "type": "cpe_behind",
            "severity": "P1",
            "achievement_rate": round(achievement_rate, 4),
            "message": f"CPE 达成率 {achievement_rate:.0%}（目标 {target:,}，实际 {actual:,}），低于 {alert_threshold:.0%} 预警线",
        })

    # Markdown
    md_lines = [
        f"| 项目 | 事件 | 目标 | 实际 | 达成率 | 预估月末 | 状态 |",
        f"| --- | --- | --- | --- | --- | --- | --- |",
        f"| {project_id} | {event_name} | {target:,} | {actual:,} | {achievement_rate:.0%} | {projected_monthly:,} | {status} |",
    ]

    return {
        "project_id": project_id,
        "month": month,
        "event_name": event_name,
        "target": target,
        "actual": actual,
        "achievement_rate": round(achievement_rate, 4),
        "days_elapsed": days_elapsed,
        "days_total": days_total,
        "projected_monthly": projected_monthly,
        "status": status,
        "alerts": alerts,
        "markdown": "\n".join(md_lines),
    }


def run_cpe_overview(
    month: str,
    *,
    config: dict,
    fetch_insights_map: dict[str, Callable],
    today: str | None = None,
) -> dict:
    """汇总所有项目的 CPE 达成率。

    Args:
        month: "YYYY-MM"
        config: {"apps": ..., "thresholds": ...}
        fetch_insights_map: {project_id: fetch_insights_fn}
        today: 当前日期
    """
    projects: list[dict] = []

    for project_id, fetch_fn in fetch_insights_map.items():
        result = check_cpe_achievement(
            project_id, month,
            config=config,
            fetch_insights=fetch_fn,
            today=today,
        )
        projects.append(result)

    # Compose overview markdown
    if projects:
        md_lines = [
            f"# CPE 达成率总览 — {month}",
            "",
            "| 项目 | 事件 | 目标 | 实际 | 达成率 | 预估月末 | 状态 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for p in projects:
            md_lines.append(
                f"| {p['project_id']} | {p['event_name']} | {p['target']:,} | {p['actual']:,} | {p['achievement_rate']:.0%} | {p['projected_monthly']:,} | {p['status']} |"
            )
        markdown = "\n".join(md_lines)
    else:
        markdown = "（无项目数据）"

    return {
        "month": month,
        "projects": projects,
        "markdown": markdown,
    }
