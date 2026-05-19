"""tag_analyzer — 标签 × 效果交叉分析 & A/B 面分类.

纯函数模块，不做 I/O。
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


def cross_analyze(
    rows: list[dict[str, Any]],
    *,
    metric: str = "ctr",
) -> dict[str, Any]:
    """标签 × 效果交叉分析.

    对每个标签维度，计算各标签值的平均指标值。

    Args:
        rows: 素材列表，每条含 tags (dict) 和指标字段
        metric: 分析指标名 (ctr/cpi/roi)

    Returns:
        {
            "metric": str,
            "dimensions": [
                {
                    "dimension": str,
                    "tags": [{"tag_value": str, "avg_metric": float, "count": int}]
                }
            ]
        }
    """
    if not rows:
        return {"metric": metric, "dimensions": []}

    # dim -> tag_value -> [metric_values]
    dim_data: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    for r in rows:
        tags = r.get("tags")
        if not tags or not isinstance(tags, dict):
            continue
        val = r.get(metric)
        if val is None:
            continue
        for dim, tag_value in tags.items():
            dim_data[dim][tag_value].append(float(val))

    dimensions = []
    for dim in sorted(dim_data.keys()):
        tag_entries = []
        for tag_value, values in dim_data[dim].items():
            avg = sum(values) / len(values) if values else 0.0
            tag_entries.append({
                "tag_value": tag_value,
                "avg_metric": avg,
                "count": len(values),
            })
        tag_entries.sort(key=lambda x: x["avg_metric"], reverse=True)
        dimensions.append({"dimension": dim, "tags": tag_entries})

    return {"metric": metric, "dimensions": dimensions}


def classify_ab_face(
    rows: list[dict[str, Any]],
    *,
    top_pct: float = 0.20,
) -> dict[str, Any]:
    """A面/B面素材分类.

    A 面: CTR 排名 Top N%（拉新力强）
    B 面: ROI 排名 Top N%（付费/留存好）

    Returns:
        {"a_face": [...], "b_face": [...], "overlap": [...]}
    """
    if not rows:
        return {"a_face": [], "b_face": [], "overlap": []}

    n = max(1, math.ceil(len(rows) * top_pct))

    by_ctr = sorted(rows, key=lambda r: r.get("ctr", 0), reverse=True)
    by_roi = sorted(rows, key=lambda r: r.get("roi", 0), reverse=True)

    a_face = by_ctr[:n]
    b_face = by_roi[:n]

    a_ids = {r.get("material_id") for r in a_face}
    b_ids = {r.get("material_id") for r in b_face}
    overlap_ids = a_ids & b_ids
    overlap = [r for r in rows if r.get("material_id") in overlap_ids]

    return {"a_face": a_face, "b_face": b_face, "overlap": overlap}
