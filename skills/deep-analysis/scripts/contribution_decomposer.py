"""多维贡献度分解 — 5.1 深度对比分析。

Computes per-dimension contribution to a metric's total change
between two time periods.

Design: pure functions, no I/O.
"""
from __future__ import annotations

from typing import Any


def _compute_metric(rows: list[dict[str, Any]], metric: str) -> dict[str, float]:
    """Aggregate rows by dimension and compute the requested metric.

    Supported metrics: spend, cpi (spend/installs), ctr (clicks/impressions).
    Returns {dimension_value: metric_value}.
    """
    by_dim: dict[str, dict[str, float]] = {}
    for r in rows:
        dim = r.get("dimension", "unknown")
        entry = by_dim.setdefault(dim, {"spend": 0, "installs": 0, "clicks": 0, "impressions": 0})
        entry["spend"] += float(r.get("spend", 0))
        entry["installs"] += int(r.get("installs", 0))
        entry["clicks"] += int(r.get("clicks", 0))
        entry["impressions"] += int(r.get("impressions", 0))

    result: dict[str, float] = {}
    for dim, agg in by_dim.items():
        if metric == "spend":
            result[dim] = agg["spend"]
        elif metric == "cpi":
            result[dim] = agg["spend"] / agg["installs"] if agg["installs"] > 0 else 0
        elif metric == "ctr":
            result[dim] = agg["clicks"] / agg["impressions"] if agg["impressions"] > 0 else 0
        else:
            result[dim] = agg.get(metric, 0)
    return result


def _total_metric(rows: list[dict[str, Any]], metric: str) -> float:
    """Compute the total (overall, not per-dimension) metric value."""
    total_spend = sum(float(r.get("spend", 0)) for r in rows)
    total_installs = sum(int(r.get("installs", 0)) for r in rows)
    total_clicks = sum(int(r.get("clicks", 0)) for r in rows)
    total_impressions = sum(int(r.get("impressions", 0)) for r in rows)

    if metric == "spend":
        return total_spend
    elif metric == "cpi":
        return total_spend / total_installs if total_installs > 0 else 0
    elif metric == "ctr":
        return total_clicks / total_impressions if total_impressions > 0 else 0
    return 0


def decompose_contribution(
    period_a: list[dict[str, Any]],
    period_b: list[dict[str, Any]],
    *,
    metric: str,
) -> dict[str, Any]:
    """分解各维度对指标变动的贡献度。

    Args:
        period_a: 时段 A 数据 [{"dimension", "spend", "installs", ...}]
        period_b: 时段 B 数据 [{"dimension", "spend", "installs", ...}]
        metric: 分析指标 ("cpi", "spend", "ctr")

    Returns:
        {"metric", "total_a", "total_b", "total_delta",
         "contributions": [{"dimension", "value_a", "value_b", "delta",
                            "contribution_pct"}]}
    """
    total_a = _total_metric(period_a, metric)
    total_b = _total_metric(period_b, metric)
    total_delta = total_b - total_a

    dim_a = _compute_metric(period_a, metric)
    dim_b = _compute_metric(period_b, metric)

    all_dims = sorted(set(dim_a.keys()) | set(dim_b.keys()))

    contributions: list[dict[str, Any]] = []
    for dim in all_dims:
        va = dim_a.get(dim, 0)
        vb = dim_b.get(dim, 0)
        delta = vb - va
        pct = (delta / total_delta * 100) if total_delta != 0 else 0
        contributions.append({
            "dimension": dim,
            "value_a": round(va, 4),
            "value_b": round(vb, 4),
            "delta": round(delta, 4),
            "contribution_pct": round(pct, 2),
        })

    contributions.sort(key=lambda c: abs(c["delta"]), reverse=True)

    return {
        "metric": metric,
        "total_a": round(total_a, 4),
        "total_b": round(total_b, 4),
        "total_delta": round(total_delta, 4),
        "contributions": contributions,
    }
