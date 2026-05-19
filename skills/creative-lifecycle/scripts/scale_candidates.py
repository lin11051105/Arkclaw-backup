"""Scale candidate evaluation script.

Implements the scale_candidate flow (Step 二 in creative-lifecycle):
- C01 Volume candidate: CTR > P80, CPI < target, spend > min, days >= min
- C02 Paying candidate: ROI > target, days >= min (paying_rate 待 DAP)

Design: dependency-injected fetcher for testability.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

_SKILLS_ROOT = str(Path(__file__).resolve().parents[2])
if _SKILLS_ROOT not in sys.path:
    sys.path.insert(0, _SKILLS_ROOT)
from lib.fetchers import get_app_config, get_fb_config, extract_short_name as _extract_short_name



# ═══════════════════════════════════════════════════════════════════════════
# compute_p80_baseline — numpy-free percentile
# ═══════════════════════════════════════════════════════════════════════════

def compute_p80_baseline(values: list[float], percentile: int) -> float:
    """Compute the given percentile from a list of values without numpy.

    Uses linear interpolation (same as numpy default).
    Returns 0.0 for empty list.
    """
    if not values:
        return 0.0

    sorted_vals = sorted(values)
    n = len(sorted_vals)

    if n == 1:
        return sorted_vals[0]

    # Linear interpolation index
    k = (percentile / 100.0) * (n - 1)
    lower = int(k)
    upper = lower + 1
    if upper >= n:
        return sorted_vals[-1]

    frac = k - lower
    return sorted_vals[lower] + frac * (sorted_vals[upper] - sorted_vals[lower])


# ═══════════════════════════════════════════════════════════════════════════
# evaluate_volume (C01)
# ═══════════════════════════════════════════════════════════════════════════

def evaluate_volume(
    creatives: list[dict],
    *,
    cohort_p80_ctr: float,
    target_cpi: float,
    thresholds: dict,
) -> list[dict]:
    """Evaluate volume candidates per C01 rule.

    Conditions (all must pass):
    - ctr > cohort_p80_ctr
    - cpi < target_cpi * cpi_below_target_pct
    - daily_spend > min_daily_spend
    - online_days >= min_online_days
    """
    cpi_threshold = target_cpi * thresholds["cpi_below_target_pct"]
    min_spend = thresholds["min_daily_spend"]
    min_days = thresholds["min_online_days"]

    results = []
    for c in creatives:
        if c["ctr"] <= cohort_p80_ctr:
            results.append(_reject(c, "ctr_not_above_p80"))
        elif c["cpi"] >= cpi_threshold:
            results.append(_reject(c, "cpi_not_below_threshold"))
        elif c["daily_spend"] <= min_spend:
            results.append(_reject(c, "daily_spend_too_low"))
        elif c["online_days"] < min_days:
            results.append(_reject(c, "online_days_insufficient"))
        else:
            results.append({
                "material_id": c.get("material_id", ""),
                "material_name": c.get("material_name", ""),
                "is_candidate": True,
                "candidate_type": "volume",
                "reason": "",
                "ctr": c["ctr"],
                "cpi": c["cpi"],
                "daily_spend": c["daily_spend"],
                "ad_ids": c.get("ad_ids", []),
            })
    return results


def _reject(c: dict, reason: str) -> dict:
    return {
        "material_id": c.get("material_id", ""),
        "material_name": c.get("material_name", ""),
        "is_candidate": False,
        "candidate_type": None,
        "reason": reason,
        "ctr": c.get("ctr"),
        "cpi": c.get("cpi"),
        "daily_spend": c.get("daily_spend"),
        "ad_ids": c.get("ad_ids", []),
    }


# ═══════════════════════════════════════════════════════════════════════════
# evaluate_paying (C02)
# ═══════════════════════════════════════════════════════════════════════════

def evaluate_paying(
    creatives: list[dict],
    *,
    target_roi: float,
    thresholds: dict,
) -> list[dict]:
    """Evaluate paying candidates per C02 rule.

    Conditions:
    - roi > target_roi * roi_above_target_pct
    - online_days >= min_online_days
    Note: paying_rate check is [待 DAP 就绪] — currently skipped.
    """
    roi_threshold = target_roi * thresholds["roi_above_target_pct"]
    min_days = thresholds["min_online_days"]

    results = []
    for c in creatives:
        if c.get("roi", 0) <= roi_threshold:
            results.append({
                "material_id": c.get("material_id", ""),
                "material_name": c.get("material_name", ""),
                "is_candidate": False,
                "candidate_type": None,
                "reason": "roi_not_above_threshold",
                "roi": c.get("roi"),
                "cpi": c.get("cpi"),
                "ad_ids": c.get("ad_ids", []),
            })
        elif c["online_days"] < min_days:
            results.append({
                "material_id": c.get("material_id", ""),
                "material_name": c.get("material_name", ""),
                "is_candidate": False,
                "candidate_type": None,
                "reason": "online_days_insufficient",
                "roi": c.get("roi"),
                "cpi": c.get("cpi"),
                "ad_ids": c.get("ad_ids", []),
            })
        else:
            results.append({
                "material_id": c.get("material_id", ""),
                "material_name": c.get("material_name", ""),
                "is_candidate": True,
                "candidate_type": "paying",
                "reason": "",
                "roi": c.get("roi"),
                "cpi": c.get("cpi"),
                "ad_ids": c.get("ad_ids", []),
            })
    return results


# ═══════════════════════════════════════════════════════════════════════════
# build_scale_report
# ═══════════════════════════════════════════════════════════════════════════

def build_scale_report(
    *,
    project_id: str,
    date: str,
    config: dict,
    volume_results: list[dict],
    paying_results: list[dict],
    p80_ctr_baseline: float,
) -> dict:
    """Build the scale candidate report JSON from config."""
    app = get_app_config(config, project_id)
    vt = config["thresholds"]["scale_candidate"]["volume"]
    pt = config["thresholds"]["scale_candidate"]["paying"]

    def _add_short(r: dict) -> dict:
        raw = r.get("material_name", "")
        return {**r, "short_name": _extract_short_name(raw) or raw}

    vol_candidates = [_add_short(r) for r in volume_results if r["is_candidate"]]
    pay_candidates = [_add_short(r) for r in paying_results if r["is_candidate"]]
    non_candidates = [
        _add_short(r) for r in volume_results if not r["is_candidate"]
    ]

    return {
        "report_type": "scale_candidate",
        "project": project_id,
        "date": date,
        "target_cpi": get_fb_config(app, "target_cpi", 0),
        "target_roi": get_fb_config(app, "target_roi", 0),
        "thresholds": {
            "volume": {
                "ctr_above_cohort_percentile": vt["ctr_above_cohort_percentile"],
                "cpi_below_target_pct": vt["cpi_below_target_pct"],
                "min_daily_spend": vt["min_daily_spend"],
                "min_online_days": vt["min_online_days"],
            },
            "paying": {
                "roi_above_target_pct": pt["roi_above_target_pct"],
                "min_paying_rate_pct": pt["min_paying_rate_pct"],
                "min_online_days": pt["min_online_days"],
            },
        },
        "p80_ctr_baseline": p80_ctr_baseline,
        "volume_candidates": vol_candidates,
        "paying_candidates": pay_candidates,
        "non_candidates": non_candidates,
    }


# ═══════════════════════════════════════════════════════════════════════════
# run_scale_candidates — orchestrator
# ═══════════════════════════════════════════════════════════════════════════

def run_scale_candidates(
    *,
    project_id: str,
    date: str,
    config: dict,
    fetch_material_report: Callable[[str, str, str, str], list[dict]],
) -> dict:
    """Run scale candidate evaluation with injected fetcher.

    Args:
        project_id: e.g. "ROK"
        date: today "YYYY-MM-DD"
        config: merged dict with keys: apps, thresholds
        fetch_material_report: fn(game_alias, channel, start, end) → [{name, id, spend, ctr, cpi, roi, online_days, ...}]

    Returns pure data dict — file I/O and Feishu upload are the caller's responsibility.
    """
    app = get_app_config(config, project_id)
    target_cpi = get_fb_config(app, "target_cpi", 0)
    target_roi = get_fb_config(app, "target_roi", 0)
    if target_cpi == 0 and target_roi == 0:
        return {"status": "not_configured", "project_id": project_id,
                "message": f"项目 {project_id} 未配置 target_cpi/target_roi，跳过扩量判定",
                "volume_candidates": [], "paying_candidates": []}
    vt = config["thresholds"]["scale_candidate"]["volume"]
    pt = config["thresholds"]["scale_candidate"]["paying"]

    game_alias = app.get("game_alias", project_id)
    lookback_days = vt.get("min_online_days", 7)
    start_date = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    materials = fetch_material_report(game_alias, "Facebook", start_date, date)

    # Build creative list from materials (each material is unique by ID)
    today = datetime.strptime(date, "%Y-%m-%d")
    creatives = []
    for m in materials:
        mid = m.get("id", "")
        name = m.get("name", "")
        if not mid and not name:
            continue
        spend = m.get("spend", 0.0)
        # Compute online_days from first_spend_date
        first_spend = m.get("first_spend_date", "")
        online_days = 0
        if first_spend:
            try:
                fd = datetime.strptime(str(first_spend).split("T")[0], "%Y-%m-%d")
                online_days = max(0, (today - fd).days)
            except ValueError:
                pass
        days = online_days if online_days > 0 else 1
        creatives.append({
            "material_id": mid or name,
            "material_name": name,
            "ctr": float(m.get("ctr") or 0),
            "cpi": float(m.get("cpi") or 0),
            "roi": float(m.get("roi") or 0),
            "daily_spend": float(spend or 0) / days,
            "online_days": online_days,
            "ad_ids": [],
        })

    # P80 baseline
    all_ctr = [c["ctr"] for c in creatives if c["ctr"] > 0]
    p80 = compute_p80_baseline(all_ctr, vt["ctr_above_cohort_percentile"])

    # Evaluate
    vol_results = evaluate_volume(
        creatives,
        cohort_p80_ctr=p80,
        target_cpi=target_cpi,
        thresholds=vt,
    )
    pay_results = evaluate_paying(
        creatives,
        target_roi=target_roi,
        thresholds=pt,
    )

    return build_scale_report(
        project_id=project_id,
        date=date,
        config=config,
        volume_results=vol_results,
        paying_results=pay_results,
        p80_ctr_baseline=p80,
    )
