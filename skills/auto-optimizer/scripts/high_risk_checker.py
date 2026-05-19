"""高风险消耗检测 — C04。

Detects campaigns/adsets with high daily spend AND low ROI.

Design: pure functions, no I/O.
"""
from __future__ import annotations

from typing import Any


def check_high_risk_spend(
    entities: list[dict[str, Any]],
    *,
    target_roi: float,
    thresholds: dict,
) -> list[dict[str, Any]]:
    """检测高风险消耗实体（C04）。

    Args:
        entities: [{"id", "name", "daily_spend", "roi"}]
        target_roi: 项目目标 ROI
        thresholds: {"high_risk_spend": {"daily_spend_threshold", "roi_below_target_pct"}}

    Returns:
        List of high-risk alert dicts.
    """
    hr = thresholds.get("high_risk_spend", {})
    spend_threshold = hr.get("daily_spend_threshold", 500)
    roi_pct = hr.get("roi_below_target_pct", 0.80)
    roi_threshold = target_roi * roi_pct

    alerts: list[dict[str, Any]] = []
    for e in entities:
        spend = e.get("daily_spend", 0)
        roi = e.get("roi", 0)
        if spend > spend_threshold and roi < roi_threshold:
            alerts.append({
                "type": "high_risk_spend",
                "severity": "P1",
                "entity_id": e["id"],
                "entity_name": e.get("name", ""),
                "daily_spend": spend,
                "roi": roi,
                "roi_threshold": round(roi_threshold, 4),
                "message": f"高风险消耗: {e.get('name', e['id'])} "
                           f"日耗 ${spend:.0f}, ROI {roi:.2f} < {roi_threshold:.2f}",
            })
    return alerts
