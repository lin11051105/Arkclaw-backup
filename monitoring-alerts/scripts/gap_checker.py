"""Data gap checker — 4.4+4.5 前端/DAP 数据 Gap 预警。

Compares Facebook frontend data vs DAP attribution data to detect:
- Spend gap (>0.5% → P1)
- Install gap (>20% → P1)
- Revenue gap (>20% → P1)
- Pipeline break (FB has data, DAP has 0 → P0)

Formula: |前端值 - DAP值| / DAP值  (per 指标确认.pdf M08)

Design: dependency-injected fetchers for testability.
"""
from __future__ import annotations

from typing import Any, Callable


def check_data_gap(
    project_id: str,
    date: str,
    *,
    config: dict,
    fetch_custom_report: Callable[[str, str, str], list[dict]],
    fetch_insights: Callable[[str, str, str], list[dict]],
    dap_lag_days: int = 2,
) -> dict:
    """对比 Facebook 前端数据与 DAP 归因数据，检测 Gap。

    Args:
        project_id: 项目 ID
        date: 检测日期 "YYYY-MM-DD"
        config: {"apps": ..., "thresholds": ...}
        fetch_custom_report: fn(table, start_date, end_date) → [{"安装数": int, "收入": float}]
        fetch_insights: fn(date_start, date_end, level) → [{"installs": int, "revenue": float}]
        dap_lag_days: DAP 归因延迟天数（默认 2）。DAP 在 T+lag 之前数据未稳定，
                      不应将 DAP=0 判定为管线中断。
    """
    from datetime import date as date_cls, timedelta

    thresholds = config.get("thresholds", {}).get("data_gap", {})
    spend_gap_threshold = thresholds.get("spend_gap_pct", 0.005)
    install_gap_threshold = thresholds.get("install_gap_pct", 0.20)
    revenue_gap_threshold = thresholds.get("revenue_gap_pct", 0.20)

    # Fetch Facebook data
    fb_rows = fetch_insights(date, date, "campaign")
    fb_installs = sum(int(r.get("installs", 0)) for r in fb_rows)
    fb_revenue = sum(float(r.get("revenue", 0.0)) for r in fb_rows)
    fb_spend = sum(float(r.get("spend", 0.0)) for r in fb_rows)

    # Fetch DAP data — 用 media_src 表取 Facebook 渠道数据，与 FB Insights 口径对齐
    dap_rows = fetch_custom_report("media_src", date, date)
    fb_channel_names = {"facebook", "meta", "fb"}
    dap_fb_rows = [
        r for r in dap_rows
        if r.get("渠道", r.get("media_src", "")).lower() in fb_channel_names
    ]
    # 如果 media_src 表没有渠道列或无 Facebook 行，回退到 day 表
    if not dap_fb_rows and dap_rows:
        dap_fb_rows = dap_rows
    dap_installs = sum(int(r.get("安装数") or 0) for r in dap_fb_rows)
    dap_spend = sum(float(r.get("消耗数") or 0) for r in dap_fb_rows)
    dap_has_revenue = any(r.get("收入") is not None for r in dap_fb_rows)
    if dap_has_revenue:
        dap_revenue = sum(float(r.get("收入") or 0) for r in dap_fb_rows)
    else:
        dap_revenue = sum(
            float(r.get("消耗数") or 0) * float(r.get("Actual_ROI") or 0)
            for r in dap_fb_rows
        )

    # Both empty → no_data
    if not fb_rows and not dap_rows:
        return {
            "status": "no_data",
            "project_id": project_id,
            "date": date,
            "facebook": {"installs": 0, "revenue": 0.0, "spend": 0.0},
            "dap": {"installs": 0, "revenue": 0.0, "spend": 0.0},
            "gaps": {"spend_gap_pct": 0.0, "install_gap_pct": 0.0, "revenue_gap_pct": 0.0},
            "alerts": [],
        }

    # Calculate gaps: |前端 - DAP| / DAP (per 指标确认.pdf M08)
    spend_gap = abs(fb_spend - dap_spend) / dap_spend if dap_spend > 0 else (0.0 if fb_spend == 0 else 1.0)
    install_gap = abs(fb_installs - dap_installs) / dap_installs if dap_installs > 0 else (0.0 if fb_installs == 0 else 1.0)
    revenue_gap = abs(fb_revenue - dap_revenue) / dap_revenue if dap_revenue > 0 else (0.0 if fb_revenue == 0 else 1.0)

    alerts: list[dict] = []

    # Check if the date is within DAP's attribution lag window (data not yet stable)
    check_date = date_cls.fromisoformat(date)
    today = date_cls.today()
    days_ago = (today - check_date).days
    within_lag_window = days_ago < dap_lag_days

    # Pipeline break: FB has installs but DAP has 0
    if fb_installs > 0 and dap_installs == 0:
        if within_lag_window:
            # DAP data likely not yet available — downgrade to info, not P0
            alerts.append({
                "type": "dap_data_pending",
                "severity": "info",
                "message": (
                    f"DAP 数据尚未就绪（{date} 距今 {days_ago} 天，DAP 归因延迟约 {dap_lag_days} 天）。"
                    f"Facebook 已有 {fb_installs} 安装，待 DAP 数据稳定后重新比对。"
                ),
            })
        else:
            alerts.append({
                "type": "pipeline_break",
                "severity": "P0",
                "message": f"管线中断: Facebook 有 {fb_installs} 安装但 DAP 为 0（{date} 已过 {days_ago} 天，超出归因延迟窗口）",
            })
    else:
        # Install gap check
        if install_gap > install_gap_threshold:
            alerts.append({
                "type": "install_gap",
                "severity": "P1",
                "gap_pct": round(install_gap, 4),
                "threshold": install_gap_threshold,
                "message": f"安装数据 Gap {install_gap:.1%}（FB {fb_installs} vs DAP {dap_installs}），超过阈值 {install_gap_threshold:.0%}",
            })

    # Spend gap check
    if dap_spend > 0 and spend_gap > spend_gap_threshold:
        alerts.append({
            "type": "spend_gap",
            "severity": "P1",
            "gap_pct": round(spend_gap, 4),
            "threshold": spend_gap_threshold,
            "message": f"花费数据 Gap {spend_gap:.2%}（FB {fb_spend:.0f} vs DAP {dap_spend:.0f}），超过阈值 {spend_gap_threshold:.1%}",
        })

    # Revenue gap check
    if dap_revenue > 0 and revenue_gap > revenue_gap_threshold:
        alerts.append({
            "type": "revenue_gap",
            "severity": "P1",
            "gap_pct": round(revenue_gap, 4),
            "threshold": revenue_gap_threshold,
            "message": f"收入数据 Gap {revenue_gap:.1%}（FB {fb_revenue:.0f} vs DAP {dap_revenue:.0f}），超过阈值 {revenue_gap_threshold:.0%}",
        })

    status = "alert" if alerts else "ok"

    return {
        "status": status,
        "project_id": project_id,
        "date": date,
        "facebook": {"installs": fb_installs, "revenue": fb_revenue, "spend": fb_spend},
        "dap": {"installs": dap_installs, "revenue": dap_revenue, "spend": dap_spend},
        "gaps": {
            "spend_gap_pct": round(spend_gap, 4),
            "install_gap_pct": round(install_gap, 4),
            "revenue_gap_pct": round(revenue_gap, 4),
        },
        "alerts": alerts,
    }


def check_postback_continuity(
    project_id: str,
    end_date: str,
    days: int,
    *,
    config: dict,
    fetch_custom_report: Callable[[str, str, str], list[dict]],
) -> dict:
    """检查 DAP 分日回传是否连续。

    对区间内每一天拉取 ``table=day`` 的安装/收入汇总；若某天安装与收入均为 0，
    视为当日回传异常，输出 P0（不受静默期限制）。
    """
    from datetime import date as date_cls, timedelta

    end = date_cls.fromisoformat(end_date)
    day_rows: list[dict] = []
    alerts: list[dict] = []

    for i in range(days - 1, -1, -1):
        d = (end - timedelta(days=i)).isoformat()
        rows = fetch_custom_report("day", d, d)
        inst = sum(int(r.get("安装数") or 0) for r in rows)
        has_rev = any(r.get("收入") is not None for r in rows)
        if has_rev:
            rev = sum(float(r.get("收入") or 0) for r in rows)
        else:
            rev = sum(float(r.get("消耗数") or 0) * float(r.get("Actual_ROI") or 0) for r in rows)
        is_zero = inst == 0 and rev == 0.0
        st = "zero" if is_zero else "ok"
        day_rows.append({
            "date": d,
            "dap_installs": inst,
            "dap_revenue": rev,
            "status": st,
        })
        if is_zero:
            alerts.append({
                "type": "dap_day_all_zero",
                "severity": "P0",
                "date": d,
                "message": f"{d} DAP 分日数据安装与收入均为 0，疑似回传/同步中断",
            })

    status = "alert" if alerts else "ok"
    return {
        "status": status,
        "project_id": project_id,
        "end_date": end_date,
        "days": days,
        "daily": day_rows,
        "alerts": alerts,
        "summary": (
            "回传连续性：区间内无全零日"
            if not alerts
            else f"发现 {len(alerts)} 个 DAP 全零日，需排查管线"
        ),
    }
