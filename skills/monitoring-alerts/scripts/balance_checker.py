"""Balance & spend progress checker — 4.6 消耗进度 & 账户余额预警。

Implements:
- check_account_balance: 账户余额预警（P0/P1）
- check_spend_progress: 消耗进度偏差预警（P1）

Design: dependency-injected fetchers for testability.
"""
from __future__ import annotations

from typing import Any, Callable


def check_account_balance(
    project_id: str,
    *,
    config: dict,
    fetch_account_info: Callable[[], dict[str, Any]],
    fetch_insights: Callable[[str, str, str], list[dict]],
    fetch_campaign_budgets: Callable[[], float] | None = None,
) -> dict:
    """检查账户余额，返回告警信息。

    Args:
        project_id: 项目 ID (e.g. "ROK")
        config: {"apps": apps.json, "thresholds": thresholds.json}
        fetch_account_info: fn() → {"balance_raw": float, "account_status": str, "currency": str}
        fetch_insights: fn(date_start, date_end, level) → [{"spend": float}, ...]
        fetch_campaign_budgets: fn() → total daily budget of all active campaigns (USD).
            Used when use_campaign_budget_multiplier is configured.
    """
    thresholds = config.get("thresholds", {}).get("account_balance", {})
    warning_days = thresholds.get("warning_days", 3)
    critical_days = thresholds.get("critical_days", 1)
    budget_multiplier = thresholds.get("use_campaign_budget_multiplier")

    account_info = fetch_account_info()
    balance = account_info.get("balance_raw", 0.0)
    account_status = account_info.get("account_status", "Active")
    account_name = account_info.get("name", "")
    account_id = account_info.get("id", "")
    currency = account_info.get("currency", "USD")

    # Compute daily spend baseline for coverage days calculation
    from datetime import date, timedelta
    today = date.today()
    start_7d = (today - timedelta(days=7)).isoformat()
    end_7d = (today - timedelta(days=1)).isoformat()

    # M07: 可用 campaign 总预算 × multiplier 作为日消耗基准（指标确认.pdf）
    daily_avg_spend = 0.0
    spend_basis = "7d_avg"
    if budget_multiplier and fetch_campaign_budgets:
        campaign_total_budget = fetch_campaign_budgets()
        if campaign_total_budget > 0:
            daily_avg_spend = campaign_total_budget * budget_multiplier
            spend_basis = f"campaign_budget×{budget_multiplier}"

    # Fallback to 7-day historical average
    if daily_avg_spend <= 0:
        insights = fetch_insights(start_7d, end_7d, "campaign")
        if insights:
            total_spend_7d = sum(float(r.get("spend", 0)) for r in insights)
            daily_avg_spend = total_spend_7d / 7
        spend_basis = "7d_avg"

    balance_days = balance / daily_avg_spend if daily_avg_spend > 0 else 999.0

    alerts: list[dict] = []

    # Account status check
    if account_status != "Active":
        alerts.append({
            "type": "account_abnormal",
            "severity": "P0",
            "account_status": account_status,
            "message": f"账户状态异常: {account_status}",
        })

    # Balance critical (P0)
    if balance_days < critical_days:
        alerts.append({
            "type": "balance_critical",
            "severity": "P0",
            "balance_days": round(balance_days, 2),
            "message": f"账户余额紧急告警：仅够 {balance_days:.1f} 天",
        })
    # Balance warning (P1)
    elif balance_days < warning_days:
        alerts.append({
            "type": "balance_low",
            "severity": "P1",
            "balance_days": round(balance_days, 2),
            "message": f"账户余额预计仅够 {balance_days:.1f} 天",
        })

    status = "alert" if alerts else "ok"

    return {
        "status": status,
        "project_id": project_id,
        "account_id": account_id,
        "account_name": account_name,
        "balance": balance,
        "currency": currency,
        "account_status": account_status,
        "daily_avg_spend_7d": round(daily_avg_spend, 2),
        "spend_basis": spend_basis,
        "balance_days": round(balance_days, 2),
        "alerts": alerts,
    }


def check_spend_progress(
    project_id: str,
    *,
    config: dict,
    fetch_insights: Callable[[str, str, str], list[dict]],
    tz_name: str = "Asia/Shanghai",
    _day_fraction: float | None = None,
) -> dict:
    """检查当日消耗进度偏差。

    预期消耗 = apps.json daily_budget × 当日时间进度（0~1），与当前累计 spend 对比。

    Args:
        project_id: 项目 ID
        config: {"apps": apps.json, "thresholds": thresholds.json}
        fetch_insights: fn(date_start, date_end, level) → [{"spend": float}, ...]
        tz_name: 用于计算「已过当天比例」的时区（默认北京时间）
        _day_fraction: 测试用，覆盖当日时间进度（0~1）
    """
    import os
    from datetime import datetime
    from zoneinfo import ZoneInfo

    app = config.get("apps", {}).get(project_id, {})
    fb_config = app.get("facebook", {})
    daily_budget = fb_config.get("daily_budget", 0.0)

    spend_thresholds = config.get("thresholds", {}).get("spend_progress", {})
    deviation_alert_pct = spend_thresholds.get("deviation_alert_pct", 0.25)

    tz = ZoneInfo(os.environ.get("UA_AGENT_TZ", tz_name))
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")
    if _day_fraction is not None:
        day_fraction = _day_fraction
    else:
        day_fraction = (now.hour * 3600 + now.minute * 60 + now.second) / 86400.0
    day_fraction = min(max(day_fraction, 1e-6), 1.0)

    insights = fetch_insights(today_str, today_str, "campaign")
    today_spend = sum(float(r.get("spend", 0)) for r in insights)

    if not insights and today_spend == 0:
        return {
            "status": "no_data",
            "project_id": project_id,
            "today_spend": 0.0,
            "daily_budget": daily_budget,
            "expected_spend_by_progress": 0.0,
            "time_progress_pct": round(day_fraction, 4),
            "progress_pct": 0.0,
            "deviation": 0.0,
            "alerts": [],
            "summary": "当日尚无 Insights 数据，无法判断消耗进度。",
        }

    expected_spend = daily_budget * day_fraction if daily_budget > 0 else 0.0
    deviation = (
        abs(today_spend - expected_spend) / expected_spend
        if expected_spend > 0
        else (0.0 if today_spend == 0 else 1.0)
    )
    progress_pct = today_spend / daily_budget if daily_budget > 0 else 0.0

    alerts: list[dict] = []
    if deviation > deviation_alert_pct:
        direction = "超前" if today_spend > expected_spend else "落后"
        alerts.append({
            "type": "spend_deviation",
            "severity": "P1",
            "deviation": round(deviation, 4),
            "threshold": deviation_alert_pct,
            "message": (
                f"消耗进度{direction} {deviation:.1%}（实际 ${today_spend:.0f} vs "
                f"按时间进度预期 ${expected_spend:.0f}，日预算 ${daily_budget:.0f}，已过 {day_fraction:.1%}）"
            ),
        })

    status = "alert" if alerts else "ok"
    summary = (
        "进度正常"
        if status == "ok"
        else alerts[0].get("message", "")
    )

    return {
        "status": status,
        "project_id": project_id,
        "today_spend": today_spend,
        "daily_budget": daily_budget,
        "expected_spend_by_progress": round(expected_spend, 2),
        "time_progress_pct": round(day_fraction, 4),
        "progress_pct": round(progress_pct, 4),
        "deviation": round(deviation, 4),
        "alerts": alerts,
        "summary": summary,
    }
