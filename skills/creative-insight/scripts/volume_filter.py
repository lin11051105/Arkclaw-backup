"""volume_filter — 起量素材 / 爆款素材筛选.

纯函数模块，不做 I/O。
"""
from __future__ import annotations

from typing import Any


def filter_high_volume(
    rows: list[dict[str, Any]],
    *,
    min_daily_spend: float,
    target_cpi: float,
) -> list[dict[str, Any]]:
    """筛选高消耗且 CPI 低于目标值的素材.

    条件: spend > min_daily_spend AND cpi < target_cpi
    返回按 spend 降序排列的素材列表。
    """
    result = []
    for r in rows:
        cpi = r.get("cpi")
        spend = r.get("spend", 0)
        if cpi is None or cpi <= 0:
            continue
        if spend > min_daily_spend and cpi < target_cpi:
            result.append(r)
    result.sort(key=lambda x: x.get("spend", 0), reverse=True)
    return result


def filter_winners(
    rows: list[dict[str, Any]],
    *,
    project_id: str,
    winner_thresholds: dict[str, Any],
) -> list[dict[str, Any]]:
    """筛选爆款素材 (M02).

    条件: 累计消耗 >= 项目×品类阈值 (来自 apps.json winner_thresholds)。
    同一短名不分渠道/尺寸/时长统一计算。
    """
    project_spend = winner_thresholds.get(project_id, {})
    if not project_spend:
        return []

    result = []
    for r in rows:
        creative_type = r.get("creative_type", "")
        total_spend = float(r.get("total_spend") or r.get("spend") or 0)

        threshold = _match_threshold(creative_type, project_spend)
        if threshold is None:
            continue

        if total_spend >= threshold:
            r_copy = dict(r)
            r_copy["spend_threshold"] = threshold
            r_copy["is_winner"] = True
            result.append(r_copy)

    result.sort(key=lambda x: float(x.get("total_spend") or x.get("spend") or 0), reverse=True)
    return result


def _match_threshold(creative_type: str, project_spend: dict) -> float | None:
    if not creative_type:
        return None
    ct = creative_type.lower()
    for key, val in project_spend.items():
        if key.startswith("_") or not isinstance(val, (int, float)):
            continue
        if ct == key.lower():
            return float(val)
    for key, val in project_spend.items():
        if key.startswith("_") or not isinstance(val, (int, float)):
            continue
        parts = key.lower().split("/")
        if any(p in ct or ct in p for p in parts):
            return float(val)
    return None
