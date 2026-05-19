"""Trend detector — 4.3 大盘趋势预警。

Detects:
- CPM systematic decline (E01): 7-day moving avg consecutive decline
- Batch fatigue (E04): >50% of active creatives CTR declining
- ROI worsening (B05): ROI consecutive day-over-day decline

Design: pure functions, no I/O — caller provides time-series data.
"""
from __future__ import annotations

from typing import Any


def _moving_averages(values: list[float], window: int) -> list[float]:
    """Compute moving averages for a time series."""
    if len(values) < window:
        return []
    result = []
    for i in range(len(values) - window + 1):
        result.append(sum(values[i:i + window]) / window)
    return result


def _max_consecutive_declines(values: list[float]) -> int:
    """Count max consecutive day-over-day declines."""
    if len(values) < 2:
        return 0
    max_run = 0
    current_run = 0
    for i in range(1, len(values)):
        if values[i] < values[i - 1]:
            current_run += 1
            max_run = max(max_run, current_run)
        else:
            current_run = 0
    return max_run


def detect_cpm_decline(
    daily_cpms: list[float],
    thresholds: dict,
) -> dict[str, Any] | None:
    """检测 CPM 系统性下滑。

    Args:
        daily_cpms: 近 14 天 CPM 日序列（从旧到新）
        thresholds: {"trend_detection": {"moving_avg_window", "consecutive_decline_days"}}
    """
    td = thresholds.get("trend_detection", {})
    window = td.get("moving_avg_window", 7)
    required_days = td.get("consecutive_decline_days", 5)

    mas = _moving_averages(daily_cpms, window)
    if len(mas) < 2:
        return None

    max_decline = _max_consecutive_declines(mas)
    if max_decline >= required_days:
        return {
            "type": "cpm_systematic_decline",
            "severity": "P2",
            "consecutive_decline_days": max_decline,
            "message": f"CPM 移动均值连续下降 {max_decline} 天",
        }
    return None


def detect_batch_fatigue(
    creatives: list[dict[str, Any]],
    thresholds: dict,
) -> dict[str, Any] | None:
    """检测素材批量疲劳。

    Args:
        creatives: [{"id", "ctr_trend": [float, ...]}] — CTR 日序列
        thresholds: {"trend_detection": {"batch_fatigue_pct", "consecutive_decline_days"}}
    """
    if not creatives:
        return None

    td = thresholds.get("trend_detection", {})
    fatigue_threshold = td.get("batch_fatigue_pct", 0.50)
    required_days = td.get("consecutive_decline_days", 5)

    fatigued = 0
    for c in creatives:
        trend = c.get("ctr_trend", [])
        if _max_consecutive_declines(trend) >= required_days:
            fatigued += 1

    pct = fatigued / len(creatives)
    if pct > fatigue_threshold:
        return {
            "type": "batch_fatigue",
            "severity": "P1",
            "fatigued_pct": round(pct, 4),
            "fatigued_count": fatigued,
            "total_count": len(creatives),
            "message": f"素材批量疲劳：{fatigued}/{len(creatives)} ({pct:.0%}) CTR 持续下降",
        }
    return None


def detect_roi_decline(
    daily_rois: list[float],
    thresholds: dict,
) -> dict[str, Any] | None:
    """检测 ROI 持续恶化。

    Args:
        daily_rois: 近 N 天 ROI 日序列
        thresholds: {"trend_detection": {"consecutive_decline_days"}}
    """
    td = thresholds.get("trend_detection", {})
    required_days = td.get("consecutive_decline_days", 5)

    max_decline = _max_consecutive_declines(daily_rois)
    if len(daily_rois) < 2:
        return None

    if max_decline >= required_days:
        return {
            "type": "roi_worsening",
            "severity": "P1",
            "consecutive_decline_days": max_decline,
            "message": f"ROI 连续下降 {max_decline} 天",
        }
    return None


def run_trend_detection(
    project_id: str,
    *,
    daily_cpms: list[float],
    daily_rois: list[float],
    creatives: list[dict[str, Any]],
    thresholds: dict,
) -> dict:
    """汇总趋势检测结果。"""
    alerts: list[dict[str, Any]] = []

    cpm_alert = detect_cpm_decline(daily_cpms, thresholds)
    if cpm_alert:
        alerts.append(cpm_alert)

    fatigue_alert = detect_batch_fatigue(creatives, thresholds)
    if fatigue_alert:
        alerts.append(fatigue_alert)

    roi_alert = detect_roi_decline(daily_rois, thresholds)
    if roi_alert:
        alerts.append(roi_alert)

    return {
        "status": "alert" if alerts else "ok",
        "project_id": project_id,
        "alerts": alerts,
    }
