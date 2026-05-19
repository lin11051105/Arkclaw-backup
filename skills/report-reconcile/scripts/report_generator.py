"""报表生成 — 6.1 自动拉取数据 & 生成报表。

定时拉取数据，填充报表模板（日报/周报/月报），输出 Markdown 文件。
支持环比计算、异常标注、模板占位符替换。

Design: dependency-injected fetchers for testability.
"""
from __future__ import annotations

import logging
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

# F-07: surface suspicious DAP rows (spend>0 AND Actual_ROI in {None, 0}) via
# stdlib logging so operators see a breadcrumb instead of silently zero
# revenue. Module-level logger keyed by ``__name__`` per python/coding-style.md.
_logger = logging.getLogger(__name__)

# Allow ``from lib.os_aggregator import combine`` regardless of import path.
# Tests load this module as ``workspace.skills.report-reconcile.scripts...``;
# CLI loads via ``_loader.make_loader``. Adding ``workspace/skills/`` to
# sys.path is idempotent.
_SKILLS_ROOT = Path(__file__).resolve().parents[2]
if str(_SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILLS_ROOT))

from lib.os_aggregator import combine as _combine_os  # noqa: E402


# ── 异常检测阈值（偏离 7 日均值百分比）──
_DEFAULT_ANOMALY_THRESHOLDS = {
    "spend": 0.30,
    "installs": 0.30,
    "cpi": 0.25,
    "roi": 0.25,
    "ctr": 0.25,
}


def _compute_date_range(
    report_type: str,
    date_override: str | None,
) -> tuple[str, str, str, str]:
    """计算报表日期范围和对比日期范围。

    date_override 含义：
    - daily: 报表日期本身（如 2026-04-19 → 报 4/19，环比 4/18）
    - weekly: 目标周内任一天（如 2026-04-14 → 报 4/14~4/20 那一周）
    - monthly: 目标月内任一天（如 2026-03-15 → 报 3 月整月）
    - 不传: 日报=昨天，周报=上周，月报=上月

    Returns:
        (start, end, prev_start, prev_end)
    """
    today = date.today()

    if report_type == "daily":
        target = date.fromisoformat(date_override) if date_override else today - timedelta(days=1)
        prev = target - timedelta(days=1)
        return (
            target.isoformat(), target.isoformat(),
            prev.isoformat(), prev.isoformat(),
        )
    elif report_type == "weekly":
        if date_override:
            ref = date.fromisoformat(date_override)
            monday = ref - timedelta(days=ref.weekday())
        else:
            monday = today - timedelta(days=today.weekday() + 7)
        sunday = monday + timedelta(days=6)
        prev_monday = monday - timedelta(days=7)
        prev_sunday = prev_monday + timedelta(days=6)
        return (
            monday.isoformat(), sunday.isoformat(),
            prev_monday.isoformat(), prev_sunday.isoformat(),
        )
    elif report_type == "monthly":
        if date_override:
            ref = date.fromisoformat(date_override)
            month_start = ref.replace(day=1)
            month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        else:
            first_this_month = today.replace(day=1)
            month_end = first_this_month - timedelta(days=1)
            month_start = month_end.replace(day=1)
        prev_month_end = month_start - timedelta(days=1)
        prev_month_start = prev_month_end.replace(day=1)
        return (
            month_start.isoformat(), month_end.isoformat(),
            prev_month_start.isoformat(), prev_month_end.isoformat(),
        )
    else:
        raise ValueError(f"Unknown report_type: {report_type}")


def _sum_dap_slice(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum DAP day rows into the slice shape consumed by ``os_aggregator.combine``.

    DAP's day table doesn't expose ``revenue`` directly; derive it from
    ``消耗数 × Actual_ROI`` per row, then sum. This mirrors the implicit
    revenue semantics already used by the legacy ROI weighted-average path.

    F-07: rows with real spend (``消耗数 > 0``) but ``Actual_ROI in (None, 0)``
    silently zero the revenue contribution. That usually means DAP postback
    hasn't completed for the day, not that the day truly earned $0. Emit a
    WARNING per such row so operators see a breadcrumb in the logs; the
    return value is unaffected.
    """
    for r in rows:
        spend = float(r.get("消耗数") or 0)
        if spend <= 0:
            continue
        roi_raw = r.get("Actual_ROI")
        # Suspicious when ROI is missing or zero despite real spend.
        if roi_raw is None or float(roi_raw or 0) == 0:
            _logger.warning(
                "DAP row has 消耗数=%.2f but Actual_ROI=%r (date=%s); "
                "revenue contribution silently 0 — likely incomplete postback",
                spend,
                roi_raw,
                r.get("date", "<unknown>"),
            )
    return {
        "spend": sum(float(r.get("消耗数") or 0) for r in rows),
        "installs": sum(int(r.get("安装数") or 0) for r in rows),
        "revenue": sum(
            float(r.get("消耗数") or 0) * float(r.get("Actual_ROI") or 0)
            for r in rows
        ),
    }


def _sum_skan_slice(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum SKAN view rows into the slice shape consumed by ``os_aggregator.combine``.

    SKAN columns from ``hive.da_bi_dw.v_tb_skan_report_day_v2``: ``cost`` →
    spend, ``sk_install`` → installs, ``revenue`` → revenue. The view's
    ``revenue`` is already null-grossed (see ``lib.skan_repo`` docstring),
    so no further calibration here.
    """
    return {
        "spend": sum(float(r.get("cost") or 0) for r in rows),
        "installs": sum(int(r.get("sk_install") or 0) for r in rows),
        "revenue": sum(float(r.get("revenue") or 0) for r in rows),
    }


def _extract_metrics(
    rows: list[dict[str, Any]],
    ios_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Extract aggregated metrics from DAP day rows.

    Two output shapes (backwards-compat):

    * **Legacy** (``ios_rows is None``): flat dict
      ``{"spend", "installs", "cpi", "roi", "ctr"}`` — same shape as today.
    * **OS-aware** (``ios_rows`` provided as list, including empty list): output
      of :func:`lib.os_aggregator.combine` — top-level totals plus a
      ``by_os`` breakdown. ``rows`` is treated as the Android slice (DAP
      probabilistic attribution) and ``ios_rows`` as the iOS slice (SKAN truth).

    See plan ``2026-05-08-skan-ios-attribution.md`` Task 8 for the contract.
    """
    if ios_rows is not None:
        ios_slice = _sum_skan_slice(ios_rows)
        android_slice = _sum_dap_slice(rows)
        return _combine_os(ios=ios_slice, android=android_slice)

    if not rows:
        return {"spend": 0.0, "installs": 0, "cpi": 0.0, "roi": 0.0, "ctr": 0.0}

    total_spend = sum(float(r.get("消耗数") or 0) for r in rows)
    total_installs = sum(int(r.get("安装数") or 0) for r in rows)
    cpi = total_spend / total_installs if total_installs > 0 else 0.0

    roi_values = [float(r.get("Actual_ROI") or 0) for r in rows]
    ctr_values = [float(r.get("CTR") or 0) for r in rows]

    spends = [float(r.get("消耗数") or 0) for r in rows]
    total = sum(spends)

    roi = sum(r * s for r, s in zip(roi_values, spends)) / total if total > 0 else 0.0
    ctr = sum(c * s for c, s in zip(ctr_values, spends)) / total if total > 0 else 0.0

    return {
        "spend": round(total_spend, 2),
        "installs": total_installs,
        "cpi": round(cpi, 2),
        "roi": round(roi, 4),
        "ctr": round(ctr, 4),
    }


def _calc_change_pct(current: float, previous: float) -> float:
    """(current - previous) / previous * 100，previous = 0 时返回 0。"""
    if previous == 0:
        return 0.0
    return round((current - previous) / previous * 100, 1)


def _detect_anomalies(
    current: dict[str, float],
    avg_7d: dict[str, float],
    thresholds: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """与 7 日均值比较，偏差超过阈值则标注异常。"""
    thresholds = thresholds or _DEFAULT_ANOMALY_THRESHOLDS
    anomalies: list[dict[str, Any]] = []

    metric_names = {"spend": "消耗", "installs": "安装", "cpi": "CPI", "roi": "ROI", "ctr": "CTR"}

    for metric, threshold in thresholds.items():
        cur = current.get(metric, 0.0)
        avg = avg_7d.get(metric, 0.0)
        if avg == 0:
            continue
        deviation = abs(cur - avg) / abs(avg)
        if deviation > threshold:
            direction = "突增" if cur > avg else "突降"
            anomalies.append({
                "metric": metric,
                "deviation": round(deviation * 100, 1),
                "description": f"{metric_names.get(metric, metric)} {direction} {deviation:.0%}",
            })

    return anomalies


def _fill_template(
    template: str,
    metrics: dict[str, Any],
    anomalies: list[dict],
    project_id: str,
    date_str: str,
    report_type: str = "daily",
    channel_summary: str | None = None,
    config: dict | None = None,
) -> str:
    """{{variable}} 替换模板填充，未匹配的占位符兜底为 '—'。"""

    result = template

    replacements: dict[str, str] = {
        "project_name": project_id,
        "date": date_str,
        "data_cutoff_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    if report_type == "weekly" and "~" in date_str:
        parts = date_str.split("~")
        replacements["week_start"] = parts[0]
        replacements["week_end"] = parts[1]
    if report_type == "monthly" and "~" in date_str:
        replacements["month"] = date_str.split("~")[0][:7]

    channel_key = "channel_summary_table" if report_type == "daily" else "channel_comparison_table"
    replacements[channel_key] = channel_summary or "（无渠道明细）"

    app_cfg = {}
    if config:
        apps = config.get("apps", {})
        app_cfg = apps.get(project_id, apps.get(apps.get("_default_project", ""), {}))
        fb = app_cfg.get("facebook", {})
        replacements["spend_target"] = f"{fb.get('daily_budget', 0) * 30:,.0f}"
        replacements["installs_target"] = f"{fb.get('cpe_monthly_target', 0):,}"
        replacements["cpi_target"] = f"{fb.get('target_cpi', 0):.2f}"
        replacements["roi_target"] = f"{fb.get('target_roi', 0):.2f}"
        monthly_budget = fb.get("daily_budget", 0) * 30
        if monthly_budget > 0:
            replacements["spend_achieve"] = f"{metrics.get('spend', 0) / monthly_budget * 100:.1f}"
        monthly_installs = fb.get("cpe_monthly_target", 0)
        if monthly_installs > 0:
            replacements["installs_achieve"] = f"{metrics.get('installs', 0) / monthly_installs * 100:.1f}"
        target_roi = fb.get("target_roi", 0)
        if target_roi > 0:
            replacements["roi_achieve"] = f"{metrics.get('roi', 0) / target_roi * 100:.1f}"

    _pct_suffixes = ("dod", "wow", "mom", "dev")
    for k, v in metrics.items():
        if isinstance(v, float):
            use_comma = "spend" in k and not any(k.endswith(s) for s in _pct_suffixes)
            replacements[k] = f"{v:,.2f}" if use_comma else f"{v:.2f}"
        elif isinstance(v, int):
            replacements[k] = f"{v:,}"
        else:
            replacements[k] = str(v)

    placeholder_defaults = {
        "active_creatives": "—",
        "new_creatives": "—",
        "paused_creatives": "—",
        "new_this_week": "—",
        "paused_this_week": "—",
        "new_this_month": "—",
        "paused_this_month": "—",
        "winners_this_month": "—",
        "avg_lifecycle_days": "—",
        "usable_count": "—",
        "safety_line": "—",
        "winner_count": "—",
        "min_hot": "—",
        "trend_analysis": "（暂无趋势分析数据）",
        "next_week_focus": "（待 Agent 根据数据补充）",
        "roi_progress_section": "（详见 monitoring-alerts roi-progress 输出）",
        "budget_execution_section": "（详见 monitoring-alerts balance 输出）",
    }
    for k, v in placeholder_defaults.items():
        replacements.setdefault(k, v)

    for key, val in replacements.items():
        result = result.replace(f"{{{{{key}}}}}", str(val))

    if anomalies:
        anomaly_text = "\n".join(
            f"- ⚠️ {a['description']}（偏离 {a['deviation']}%）"
            for a in anomalies
        )
        result = re.sub(
            r"\{\{#anomalies\}\}(.*?)\{\{/anomalies\}\}",
            anomaly_text, result, flags=re.DOTALL,
        )
        result = re.sub(
            r"\{\{\^anomalies\}\}(.*?)\{\{/anomalies\}\}",
            "", result, flags=re.DOTALL,
        )
    else:
        result = re.sub(
            r"\{\{#anomalies\}\}(.*?)\{\{/anomalies\}\}",
            "", result, flags=re.DOTALL,
        )
        result = re.sub(
            r"\{\{\^anomalies\}\}(.*?)\{\{/anomalies\}\}",
            r"\1", result, flags=re.DOTALL,
        )

    result = re.sub(r"\{\{[a-zA-Z_]+\}\}", "—", result)

    return result


def generate_report(
    report_type: str,
    project_id: str,
    *,
    date_override: str | None = None,
    config: dict,
    fetch_custom_report: Callable[[str, str, str], list[dict]],
    fetch_channel_summary: Callable | None = None,
    fetch_skan_by_game_day: Callable | None = None,
    game_id: int | None = None,
    os: str = "android",
) -> dict:
    """生成日报/周报/月报。

    Args:
        report_type: "daily" | "weekly" | "monthly"
        project_id: 项目 ID
        date_override: 指定日期（默认 today）
        config: {"apps": ..., "thresholds": ...}
        fetch_custom_report: fn(table, start, end) → [row, ...]
        fetch_channel_summary: fn(project_id, start, end) → markdown str (optional)
        fetch_skan_by_game_day: fn(*, date_start, date_end) → SKAN day rows from
            ``hive.da_bi_dw.v_tb_skan_report_day_v2``. Required when ``os`` ∈
            {"ios", "both"} (iOS truth path).
        game_id: 数据仓库 ``game_id`` (e.g. ROK=10043). Required when
            ``os`` ∈ {"ios", "both"}; the SKAN fetcher closure binds this id.
        os: "android" (default, legacy DAP-only) | "ios" | "both". Selects the
            attribution surface: Android stays on DAP probabilistic; iOS pulls
            from the SKAN view; "both" returns spend-weighted totals plus a
            ``by_os`` breakdown via :func:`lib.os_aggregator.combine`.

    Returns pure data dict — file I/O and Feishu upload are the caller's responsibility.

    Raises:
        ValueError: if ``os`` ∈ {"ios", "both"} and either
            ``fetch_skan_by_game_day`` or ``game_id`` is missing.
    """
    if os in ("ios", "both") and (fetch_skan_by_game_day is None or game_id is None):
        raise ValueError(
            "os='ios'|'both' requires both fetch_skan_by_game_day and game_id "
            "(SKAN view query needs game_id from apps.json)"
        )

    use_skan = os in ("ios", "both")

    start, end, prev_start, prev_end = _compute_date_range(report_type, date_override)

    # Fetch current period data
    current_rows = fetch_custom_report("day", start, end)
    current_ios_rows = (
        fetch_skan_by_game_day(date_start=start, date_end=end) if use_skan else None
    )
    current_metrics = _extract_metrics(current_rows, ios_rows=current_ios_rows)

    # Fetch previous period data
    prev_rows = fetch_custom_report("day", prev_start, prev_end)
    prev_ios_rows = (
        fetch_skan_by_game_day(date_start=prev_start, date_end=prev_end)
        if use_skan
        else None
    )
    prev_metrics = _extract_metrics(prev_rows, ios_rows=prev_ios_rows)

    # Fetch average period (for anomaly detection)
    if report_type == "daily":
        ref_date = date.fromisoformat(start)
        avg_start = (ref_date - timedelta(days=7)).isoformat()
        avg_end = (ref_date - timedelta(days=1)).isoformat()
    else:
        avg_start = prev_start
        avg_end = prev_end
    avg_rows = fetch_custom_report("day", avg_start, avg_end)
    avg_ios_rows = (
        fetch_skan_by_game_day(date_start=avg_start, date_end=avg_end)
        if use_skan
        else None
    )
    avg_metrics = _extract_metrics(avg_rows, ios_rows=avg_ios_rows)

    # Per-day averages for baseline comparison
    avg_days = (date.fromisoformat(avg_end) - date.fromisoformat(avg_start)).days + 1
    num_avg_days = max(avg_days, 1)
    avg_per_day = {
        k: v / num_avg_days if isinstance(v, (int, float)) else v
        for k, v in avg_metrics.items()
    }

    # For weekly/monthly: normalize current period to per-day too
    current_days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    if report_type == "daily":
        current_per_day = current_metrics
    else:
        current_per_day = {
            k: v / current_days if isinstance(v, (int, float)) else v
            for k, v in current_metrics.items()
        }

    # Calculate change percentages
    dod_suffix = {"daily": "dod", "weekly": "wow", "monthly": "mom"}[report_type]
    prev_suffix = {"daily": "prev", "weekly": "prev_week", "monthly": "prev_month"}[report_type]
    avg_key = {"daily": "7d_avg", "weekly": "month_avg", "monthly": "month_avg"}[report_type]
    change_metrics = {}
    for metric in ("spend", "installs", "cpi", "roi", "ctr"):
        cur_val = current_metrics.get(metric, 0.0)
        prev_val = prev_metrics.get(metric, 0.0)
        cur_day_val = current_per_day.get(metric, 0.0)
        avg_day_val = avg_per_day.get(metric, 0.0)
        change_metrics[f"{metric}_{dod_suffix}"] = _calc_change_pct(
            float(cur_val), float(prev_val)
        )
        change_metrics[f"{metric}_{prev_suffix}"] = prev_val
        change_metrics[f"{metric}_{avg_key}"] = round(avg_per_day.get(metric, 0.0), 2)
        dev = abs(float(cur_day_val) - avg_day_val) / abs(avg_day_val) * 100 if avg_day_val != 0 else 0.0
        change_metrics[f"{metric}_dev"] = round(dev, 1)

    # Merge all metrics
    all_metrics = {**current_metrics, **change_metrics}

    # Detect anomalies (compare per-day averages to avoid total-vs-daily mismatch)
    anomalies = _detect_anomalies(current_per_day, avg_per_day)

    # Channel summary
    channel_md = None
    if fetch_channel_summary:
        channel_md = fetch_channel_summary(project_id, start, end)

    # Load and fill template
    template_map = {
        "daily": "daily-report.md",
        "weekly": "weekly-report.md",
        "monthly": "monthly-report.md",
    }
    template_path = Path(__file__).resolve().parents[3] / "templates" / template_map[report_type]

    if template_path.exists():
        template = template_path.read_text(encoding="utf-8")
        markdown = _fill_template(
            template, all_metrics, anomalies,
            project_id, f"{start}~{end}" if start != end else start,
            report_type=report_type,
            channel_summary=channel_md,
            config=config,
        )
    else:
        # Fallback: generate simple markdown
        markdown = _generate_fallback_markdown(
            report_type, project_id, start, end,
            all_metrics, anomalies, channel_md,
        )

    return {
        "report_type": report_type,
        "project_id": project_id,
        "date_range": [start, end],
        "metrics": all_metrics,
        "anomalies": anomalies,
        "markdown": markdown,
    }


def _generate_fallback_markdown(
    report_type: str,
    project_id: str,
    start: str,
    end: str,
    metrics: dict,
    anomalies: list[dict],
    channel_md: str | None,
) -> str:
    """当模板文件不存在时的 fallback markdown。"""
    type_name = {"daily": "日报", "weekly": "周报", "monthly": "月报"}[report_type]
    date_str = f"{start}~{end}" if start != end else start

    lines = [
        f"# {type_name} — {project_id}（{date_str}）",
        "",
        "## 核心指标",
        "",
        f"- 消耗: {metrics.get('spend', 0):,.2f}",
        f"- 安装: {metrics.get('installs', 0):,}",
        f"- CPI: {metrics.get('cpi', 0):.2f}",
        f"- ROI: {metrics.get('roi', 0):.2f}",
    ]

    if anomalies:
        lines.extend(["", "## 异常标注", ""])
        for a in anomalies:
            lines.append(f"- ⚠️ {a['description']}（偏离 {a['deviation']}%）")

    if channel_md:
        lines.extend(["", "## 渠道明细", "", channel_md])

    return "\n".join(lines)
