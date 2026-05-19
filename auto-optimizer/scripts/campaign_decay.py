"""Campaign/AdSet 衰退判定 — B02/B03。

Detects:
- Campaign decay (B02): consecutive days CPI > target × threshold
- AdSet decay (B03): consecutive days CPI > threshold AND ROI < threshold

Design: pure functions, no I/O — caller provides time-series data.
"""
from __future__ import annotations

from typing import Any


def _max_consecutive_above(values: list[float], threshold: float) -> int:
    """Count max consecutive entries where value > threshold."""
    max_run = 0
    current_run = 0
    for v in values:
        if v > threshold:
            current_run += 1
            max_run = max(max_run, current_run)
        else:
            current_run = 0
    return max_run


def _max_consecutive_both(
    cpis: list[float],
    rois: list[float],
    cpi_threshold: float,
    roi_threshold: float,
) -> int:
    """Count max consecutive days where CPI > threshold AND ROI < threshold."""
    n = min(len(cpis), len(rois))
    max_run = 0
    current_run = 0
    for i in range(n):
        if cpis[i] > cpi_threshold and rois[i] < roi_threshold:
            current_run += 1
            max_run = max(max_run, current_run)
        else:
            current_run = 0
    return max_run


def check_campaign_decay(
    daily_cpis: list[float],
    *,
    target_cpi: float,
    thresholds: dict,
) -> dict[str, Any] | None:
    """检测 Campaign 衰退（B02）。

    Args:
        daily_cpis: 近 7 天每日 CPI（从旧到新）
        target_cpi: 项目目标 CPI
        thresholds: {"campaign_decay": {"consecutive_days", "cpi_above_target_pct"}}
    """
    cd = thresholds.get("campaign_decay", {})
    required_days = cd.get("consecutive_days", 3)
    cpi_pct = cd.get("cpi_above_target_pct", 1.25)

    if len(daily_cpis) < required_days:
        return None

    cpi_threshold = target_cpi * cpi_pct
    consecutive = _max_consecutive_above(daily_cpis, cpi_threshold)

    if consecutive >= required_days:
        return {
            "type": "campaign_decay",
            "severity": "P1",
            "consecutive_days": consecutive,
            "cpi_threshold": round(cpi_threshold, 2),
            "message": f"Campaign 连续 {consecutive} 天 CPI 超标"
                       f"（阈值 {cpi_threshold:.2f}）",
        }
    return None


def check_adset_decay(
    daily_cpis: list[float],
    daily_rois: list[float],
    *,
    target_cpi: float,
    target_roi: float,
    thresholds: dict,
) -> dict[str, Any] | None:
    """检测 AdSet 衰退（B03）。

    Args:
        daily_cpis: 近 7 天每日 CPI
        daily_rois: 近 7 天每日 ROI
        target_cpi: 项目目标 CPI
        target_roi: 项目目标 ROI
        thresholds: {"adset_decay": {"consecutive_days", "cpi_above_target_pct", "roi_below_target_pct"}}
    """
    ad = thresholds.get("adset_decay", {})
    required_days = ad.get("consecutive_days", 3)
    cpi_pct = ad.get("cpi_above_target_pct", 1.25)
    roi_pct = ad.get("roi_below_target_pct", 0.80)

    n = min(len(daily_cpis), len(daily_rois))
    if n < required_days:
        return None

    cpi_threshold = target_cpi * cpi_pct
    roi_threshold = target_roi * roi_pct
    consecutive = _max_consecutive_both(
        daily_cpis, daily_rois, cpi_threshold, roi_threshold,
    )

    if consecutive >= required_days:
        return {
            "type": "adset_decay",
            "severity": "P1",
            "consecutive_days": consecutive,
            "cpi_threshold": round(cpi_threshold, 2),
            "roi_threshold": round(roi_threshold, 2),
            "message": f"AdSet 连续 {consecutive} 天 CPI 超标且 ROI 不达标",
        }
    return None


def run_decay_check(
    project_id: str,
    *,
    campaigns: list[dict[str, Any]],
    adsets: list[dict[str, Any]],
    app_config: dict,
    thresholds: dict,
) -> dict:
    """汇总 Campaign/AdSet 衰退检测结果。

    Args:
        campaigns: [{"id", "name", "daily_cpis": [float]}]
        adsets: [{"id", "name", "daily_cpis": [float], "daily_rois": [float]}]
        app_config: {"target_cpi", "target_roi"}
        thresholds: 阈值配置
    """
    target_cpi = app_config.get("target_cpi", 0)
    target_roi = app_config.get("target_roi", 0)

    campaign_alerts: list[dict[str, Any]] = []
    for c in campaigns:
        alert = check_campaign_decay(
            c.get("daily_cpis", []),
            target_cpi=target_cpi,
            thresholds=thresholds,
        )
        if alert:
            alert["entity_id"] = c["id"]
            alert["entity_name"] = c.get("name", "")
            campaign_alerts.append(alert)

    adset_alerts: list[dict[str, Any]] = []
    for a in adsets:
        alert = check_adset_decay(
            a.get("daily_cpis", []),
            a.get("daily_rois", []),
            target_cpi=target_cpi,
            target_roi=target_roi,
            thresholds=thresholds,
        )
        if alert:
            alert["entity_id"] = a["id"]
            alert["entity_name"] = a.get("name", "")
            adset_alerts.append(alert)

    has_alerts = bool(campaign_alerts or adset_alerts)
    return {
        "status": "alert" if has_alerts else "ok",
        "project_id": project_id,
        "campaign_alerts": campaign_alerts,
        "adset_alerts": adset_alerts,
    }
