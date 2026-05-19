"""Combine iOS-from-SKAN with Android-from-DAP into unified per-OS-and-total metrics.

Public surface (1 function): ``combine(*, ios, android) -> dict``.

Each input slice is ``{"spend": float, "installs": int, "revenue": float}`` or
``None`` when that OS has no data for the period. Output carries top-level
totals plus a ``by_os`` dict keyed only by the OSes that were present.

Critical contract: top-level ``cpi`` and ``roi`` are computed from totals
(spend-weighted), NOT as simple averages of the per-OS rates. iOS and Android
typically have very different spend levels, so simple averaging would mislead.
"""
from __future__ import annotations

from typing import Any


def _enrich(slice_dict: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the slice with ``cpi`` and ``roi`` added.

    ``cpi = spend / installs`` (0 when ``installs <= 0``).
    ``roi = revenue / spend`` (0 when ``spend <= 0``).
    """
    spend = float(slice_dict.get("spend") or 0.0)
    installs = int(slice_dict.get("installs") or 0)
    revenue = float(slice_dict.get("revenue") or 0.0)

    cpi = (spend / installs) if installs > 0 else 0.0
    roi = (revenue / spend) if spend > 0 else 0.0

    return {
        "spend": spend,
        "installs": installs,
        "revenue": revenue,
        "cpi": cpi,
        "roi": roi,
    }


def combine(
    *,
    ios: dict[str, Any] | None,
    android: dict[str, Any] | None,
) -> dict[str, Any]:
    """Sum the present slices and compute spend-weighted top-level CPI/ROI.

    Args:
        ios: ``{"spend", "installs", "revenue"}`` for iOS, or ``None``.
        android: same shape for Android, or ``None``.

    Returns:
        Dict with top-level ``spend, installs, revenue, cpi, roi`` plus a
        ``by_os`` dict containing per-OS enriched rows for whichever OSes
        were not ``None``. Both ``None`` yields zeros and an empty ``by_os``.
    """
    by_os: dict[str, dict[str, Any]] = {}
    if ios is not None:
        by_os["ios"] = _enrich(ios)
    if android is not None:
        by_os["android"] = _enrich(android)

    total_spend = sum(s["spend"] for s in by_os.values())
    total_installs = sum(s["installs"] for s in by_os.values())
    total_revenue = sum(s["revenue"] for s in by_os.values())

    combined_cpi = (total_spend / total_installs) if total_installs > 0 else 0.0
    combined_roi = (total_revenue / total_spend) if total_spend > 0 else 0.0

    return {
        "spend": total_spend,
        "installs": total_installs,
        "revenue": total_revenue,
        "cpi": combined_cpi,
        "roi": combined_roi,
        "by_os": by_os,
    }
