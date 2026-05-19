"""边际 ROI 计算与预算分配 — 5.4。

Computes marginal ROI from daily spend/revenue history and allocates
budget proportionally by marginal ROI.

Design: pure functions, no I/O.
"""
from __future__ import annotations

from typing import Any


def compute_marginal_roi(
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    """计算渠道的平均 ROI 和边际 ROI。

    Args:
        history: [{"date", "spend", "revenue"}] sorted by date

    Returns:
        {"avg_roi", "marginal_roi", "total_spend", "total_revenue"}

    Marginal ROI = slope of revenue vs spend (Δrevenue/Δspend) using
    the last two non-zero spend entries.  Falls back to avg_roi if
    insufficient data.
    """
    total_spend = sum(float(r.get("spend", 0)) for r in history)
    total_revenue = sum(float(r.get("revenue", 0)) for r in history)
    avg_roi = total_revenue / total_spend if total_spend > 0 else 0

    # Compute marginal ROI from consecutive day deltas
    non_zero = [r for r in history if float(r.get("spend", 0)) > 0]
    if len(non_zero) < 2:
        marginal_roi = avg_roi
    else:
        deltas_rev: list[float] = []
        deltas_spend: list[float] = []
        for i in range(1, len(non_zero)):
            ds = float(non_zero[i]["spend"]) - float(non_zero[i - 1]["spend"])
            dr = float(non_zero[i]["revenue"]) - float(non_zero[i - 1]["revenue"])
            if ds != 0:
                deltas_rev.append(dr)
                deltas_spend.append(ds)
        if deltas_spend:
            marginal_roi = sum(deltas_rev) / sum(deltas_spend)
        else:
            marginal_roi = avg_roi

    return {
        "avg_roi": round(avg_roi, 4),
        "marginal_roi": round(marginal_roi, 4),
        "total_spend": round(total_spend, 2),
        "total_revenue": round(total_revenue, 2),
    }


def allocate_budget(
    channels: list[dict[str, Any]],
    total_budget: float,
    roi_target: float,
) -> dict[str, Any]:
    """按边际 ROI 权重分配预算。

    Args:
        channels: [{"channel", "marginal_roi", "current_spend"}]
        total_budget: 总预算
        roi_target: 回本目标（用于报告，不改变分配逻辑）

    Returns:
        {"total_budget", "roi_target",
         "allocations": [{"channel", "marginal_roi", "current_spend",
                          "allocated_budget", "share_pct"}]}

    Simple proportional allocation by marginal ROI weight.
    Channels with marginal_roi <= 0 get minimum share.
    """
    if not channels:
        return {
            "total_budget": total_budget,
            "roi_target": roi_target,
            "allocations": [],
        }

    # Use marginal ROI as weight (floor at 0.01 to avoid zero allocation)
    weights = [max(c.get("marginal_roi", 0), 0.01) for c in channels]
    total_weight = sum(weights)

    allocations: list[dict[str, Any]] = []
    for ch, w in zip(channels, weights):
        share = w / total_weight
        allocated = round(total_budget * share, 2)
        allocations.append({
            "channel": ch["channel"],
            "marginal_roi": ch.get("marginal_roi", 0),
            "current_spend": ch.get("current_spend", 0),
            "allocated_budget": allocated,
            "share_pct": round(share * 100, 2),
        })

    allocations.sort(key=lambda a: a["allocated_budget"], reverse=True)

    return {
        "total_budget": total_budget,
        "roi_target": roi_target,
        "allocations": allocations,
    }
