"""Creative Health evaluation script.

Implements the creative_health flow (Step 三 in creative-lifecycle):
- Decay detection (B01): CPI above target AND ROI below target, consecutive days
- Winner evaluation (C03): CPI below target AND ROI above target AND spend above min
- Inventory counting (T07/T08): safety_line / min_hot_count

Design: dependency-injected fetchers for testability.
Production fetchers use ads-channel (Python) + DAP (CLI subprocess).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

_SKILLS_ROOT = str(Path(__file__).resolve().parents[2])
if _SKILLS_ROOT not in sys.path:
    sys.path.insert(0, _SKILLS_ROOT)
from lib.fetchers import get_app_config, get_fb_config, extract_short_name as _extract_short_name
from typing import Any, Callable


# ═══════════════════════════════════════════════════════════════════════════
# align_by_material_id
# ═══════════════════════════════════════════════════════════════════════════

def align_by_material_id(
    active_ads: list[dict],
    daily_data: list[dict],
) -> list[dict]:
    """Merge active ads with daily data by DAP material ID.

    Both sources come from DAP and share the same material ID:
    - active_ads: ad_id is the material ID
    - daily_data: id field is the material ID

    Returns list of:
      {material_id, material_name, ad_ids[], online_days, daily[{date, cpi, roi, spend}]}
    """
    groups: dict[str, dict] = {}

    for ad in active_ads:
        mid = ad.get("ad_id", "")
        if not mid:
            continue
        if mid not in groups:
            groups[mid] = {
                "material_id": mid,
                "material_name": ad.get("ad_name", ""),
                "ad_ids": [],
                "online_days": ad.get("online_days", 0),
                "daily": [],
            }
        groups[mid]["ad_ids"].append(ad["ad_id"])
        groups[mid]["online_days"] = max(
            groups[mid]["online_days"], ad.get("online_days", 0)
        )

    daily_by_id: dict[str, list[dict]] = {}
    for row in daily_data:
        mid = row.get("id", "")
        if not mid:
            continue
        daily_by_id.setdefault(mid, []).append({
            "date": row["date"],
            "cpi": row.get("cpi"),
            "roi": row.get("roi"),
            "spend": row.get("spend", 0.0),
        })

    for mid, daily_rows in daily_by_id.items():
        if mid in groups:
            groups[mid]["daily"] = sorted(daily_rows, key=lambda d: d["date"])

    return list(groups.values())


# ═══════════════════════════════════════════════════════════════════════════
# evaluate_decay (B01)
# ═══════════════════════════════════════════════════════════════════════════

def evaluate_decay(
    creatives: list[dict],
    *,
    min_online_days: int,
    decay_levels: dict,
) -> list[dict]:
    """Evaluate decay for each creative per 指标确认.pdf M03:

    Decay Level 1: consecutive 3 days, ROI below previous 3-day average
    Decay Level 2: consecutive 5 days, ROI below previous 5-day average
    Only at creative level (not campaign/adset).

    Skip if online_days < min_online_days.
    """
    level_1 = decay_levels.get("level_1", {"consecutive_days": 3, "roi_below_prev_avg_days": 3})
    level_2 = decay_levels.get("level_2", {"consecutive_days": 5, "roi_below_prev_avg_days": 5})

    results = []

    for c in creatives:
        online = c.get("online_days", 0)
        if online < min_online_days:
            results.append({
                "material_id": c.get("material_id", ""),
                "material_name": c.get("material_name", ""),
                "action": "skip",
                "decay_level": None,
                "consecutive_decay_days": 0,
                "online_days": online,
                "daily": c.get("daily", []),
                "ad_ids": c.get("ad_ids", []),
                "reason": f"online_days({online}) < min_online_days({min_online_days})",
            })
            continue

        daily_sorted = sorted(
            [d for d in c.get("daily", []) if d.get("roi") is not None],
            key=lambda d: d["date"],
        )

        detected_level = None
        consecutive = 0

        # Check Level 2 first (stricter: 5 days below 5-day avg)
        l2_consec = _count_consecutive_below_avg(daily_sorted, level_2["roi_below_prev_avg_days"])
        if l2_consec >= level_2["consecutive_days"]:
            detected_level = 2
            consecutive = l2_consec

        # Check Level 1 (3 days below 3-day avg)
        if detected_level is None:
            l1_consec = _count_consecutive_below_avg(daily_sorted, level_1["roi_below_prev_avg_days"])
            if l1_consec >= level_1["consecutive_days"]:
                detected_level = 1
                consecutive = l1_consec

        if detected_level is None:
            consecutive = _count_consecutive_below_avg(daily_sorted, level_1["roi_below_prev_avg_days"])

        action = "pause" if detected_level == 2 else ("watch" if detected_level == 1 else "watch")
        if detected_level is None and consecutive == 0:
            action = "ok"

        results.append({
            "material_id": c.get("material_id", ""),
            "material_name": c.get("material_name", ""),
            "action": action,
            "decay_level": detected_level,
            "consecutive_decay_days": consecutive,
            "online_days": online,
            "daily": c.get("daily", []),
            "ad_ids": c.get("ad_ids", []),
            "reason": None,
        })

    return results


def _count_consecutive_below_avg(daily_sorted: list[dict], avg_window: int) -> int:
    """Count consecutive recent days where ROI < previous N-day average ROI.

    Walks backwards from the most recent day. For each day, computes the
    average ROI of the preceding `avg_window` days, and checks if today's
    ROI is below that average.
    """
    if len(daily_sorted) <= avg_window:
        return 0

    consecutive = 0
    for i in range(len(daily_sorted) - 1, avg_window - 1, -1):
        current_roi = daily_sorted[i].get("roi", 0)
        prev_rois = [
            daily_sorted[j].get("roi", 0)
            for j in range(i - avg_window, i)
            if daily_sorted[j].get("roi") is not None
        ]
        if not prev_rois:
            break
        prev_avg = sum(prev_rois) / len(prev_rois)
        if current_roi < prev_avg:
            consecutive += 1
        else:
            break

    return consecutive


# ═══════════════════════════════════════════════════════════════════════════
# evaluate_winner (C03)
# ═══════════════════════════════════════════════════════════════════════════

def evaluate_winner(
    creatives: list[dict],
    *,
    project_id: str,
    winner_thresholds: dict,
    project_total_spend: float = 0.0,
) -> list[dict]:
    """Evaluate winner per 指标确认.pdf M02:

    爆款 = 3个月内累计消耗达到项目×品类阈值。
    同一短名不分渠道/尺寸/时长统一计算。

    Args:
        creatives: list of {material_id, material_name, creative_type, total_spend, daily, ad_ids, ...}
        project_id: e.g. "ROK"
        winner_thresholds: thresholds["winner_creative"] section containing per-project spend thresholds
    """
    results = []

    project_thresholds = winner_thresholds.get(project_id, {})

    if project_id in winner_thresholds and not project_thresholds:
        for c in creatives:
            results.append({
                "material_id": c.get("material_id", ""),
                "material_name": c.get("material_name", ""),
                "is_winner": False,
                "total_spend": c.get("total_spend", 0.0),
                "spend_threshold": None,
                "creative_type": c.get("creative_type", ""),
                "ad_ids": c.get("ad_ids", []),
                "reason": "not_configured",
            })
        return results

    default_threshold = max(
        (v for v in project_thresholds.values() if isinstance(v, (int, float))),
        default=100000,
    )

    for c in creatives:
        creative_type = c.get("creative_type", "")
        total_spend = c.get("total_spend", 0.0)

        # If daily data available, sum spend
        if total_spend <= 0 and c.get("daily"):
            total_spend = sum(d.get("spend", 0.0) for d in c.get("daily", []))

        # Find matching threshold by creative type
        raw_threshold = _match_creative_type_threshold(creative_type, project_thresholds, default_threshold)
        if isinstance(raw_threshold, dict):
            amount = raw_threshold.get("amount", float("inf"))
            pct = raw_threshold.get("pct", 1.0)
            pct_threshold = project_total_spend * pct if project_total_spend > 0 else float("inf")
            is_winner = total_spend >= amount or total_spend >= pct_threshold
            spend_threshold = amount  # for reporting
        else:
            spend_threshold = raw_threshold
            is_winner = total_spend >= spend_threshold

        results.append({
            "material_id": c.get("material_id", ""),
            "material_name": c.get("material_name", ""),
            "is_winner": is_winner,
            "total_spend": total_spend,
            "spend_threshold": spend_threshold,
            "creative_type": creative_type,
            "ad_ids": c.get("ad_ids", []),
            "reason": None,
        })

    return results


def _match_creative_type_threshold(
    creative_type: str,
    project_thresholds: dict,
    default: float,
) -> float | dict:
    """Match a creative_type string to the nearest threshold key.

    Handles partial matches: "3D" matches "3D", "剪辑" matches "剪辑/AI",
    "UA-KOL" matches "剪辑/UA-KOL/AI", etc.

    Returns either a float (simple threshold) or a dict (compound threshold
    with "amount" and/or "pct" keys).
    """
    if not creative_type:
        return default

    ct_lower = creative_type.lower()
    for key, value in project_thresholds.items():
        if key.startswith("_"):
            continue
        if not isinstance(value, (int, float, dict)):
            continue
        if ct_lower == key.lower():
            return float(value) if isinstance(value, (int, float)) else value

    for key, value in project_thresholds.items():
        if key.startswith("_"):
            continue
        if not isinstance(value, (int, float, dict)):
            continue
        parts = key.lower().split("/")
        if any(p in ct_lower or ct_lower in p for p in parts):
            return float(value) if isinstance(value, (int, float)) else value

    return default


# ═══════════════════════════════════════════════════════════════════════════
# count_inventory (T07/T08)
# ═══════════════════════════════════════════════════════════════════════════

def count_inventory(
    *,
    usable_count: int,
    winner_count: int,
    safety_line: int,
    min_hot_count: int,
) -> dict:
    """Inventory status check."""
    return {
        "usable_count": usable_count,
        "inventory_status": "warning" if usable_count < safety_line else "normal",
        "winner_count": winner_count,
        "winner_status": "warning" if winner_count < min_hot_count else "normal",
    }


def summarize_inventory_by_region(
    country_rows: list[dict],
) -> list[dict]:
    """按 DAP country 表数据汇总各国表现（纯数据展示，不做爆款判定）。"""
    rows: list[dict] = []
    for r in country_rows:
        region = r.get("国家", r.get("country", "unknown"))
        spend = float(r.get("消耗数") or 0)
        installs = int(r.get("安装数") or 0)
        cpi = float(r.get("安装成本") or r.get("CPI") or 0)
        roi = float(r.get("Actual_ROI") or 0)

        if spend <= 0:
            continue

        rows.append({
            "region": region.upper(),
            "spend": round(spend, 2),
            "installs": installs,
            "cpi": round(cpi, 2),
            "roi": round(roi, 4),
        })

    rows.sort(key=lambda x: x["spend"], reverse=True)
    return rows


def format_region_inventory_feishu(rows: list[dict]) -> str:
    """飞书正文：逐行列表格式。"""
    if not rows:
        return ""
    lines = [f"【分地区表现】共 {len(rows)} 个国家/地区："]
    for r in rows:
        lines.append(
            f"· {r['region']}: 消耗 {r['spend']:,.0f} | 安装 {r['installs']:,} "
            f"| CPI {r['cpi']:.2f} | ROI {r['roi']:.2%}"
        )
    return "\n".join(lines)


def evaluate_availability(
    creatives: list[dict],
    *,
    project_id: str,
    availability_config: dict,
    reference_date: str,
) -> list[dict]:
    """M01 素材可用量判定。

    可用标准（取较大值）：
    - 上线首日 + max_months 内
    - 消耗峰值 + max_months 内
    且累计消耗 >= min_spend。

    同一短名不分渠道/尺寸/时长统一计算。
    """
    from datetime import datetime, timedelta

    ref = datetime.strptime(reference_date, "%Y-%m-%d")
    results = []

    if not availability_config:
        for c in creatives:
            results.append({"material_id": c.get("material_id", ""), "material_name": c.get("material_name", ""),
                            "is_available": False, "reason": "not_configured"})
        return results

    for c in creatives:
        creative_type = c.get("creative_type", "")
        spec = _match_availability_spec(creative_type, availability_config)

        if spec is None:
            results.append({"material_id": c.get("material_id", ""), "is_available": False,
                            "reason": "no_availability_spec"})
            continue

        max_months = spec.get("max_months", 2)
        min_spend = spec.get("min_spend", 0)
        max_days = int(max_months * 30)

        first_date_str = c.get("first_online_date", "")
        peak_date_str = c.get("peak_spend_date", "")
        total_spend = c.get("total_spend", 0.0)
        if total_spend <= 0 and c.get("daily"):
            total_spend = sum(d.get("spend", 0.0) for d in c.get("daily", []))

        within_time = False
        if first_date_str:
            try:
                first_date = datetime.strptime(first_date_str.split("T")[0], "%Y-%m-%d")
                if (ref - first_date).days <= max_days:
                    within_time = True
            except ValueError:
                pass
        if not within_time and peak_date_str:
            try:
                peak_date = datetime.strptime(peak_date_str.split("T")[0], "%Y-%m-%d")
                if (ref - peak_date).days <= max_days:
                    within_time = True
            except ValueError:
                pass

        min_roi_ratio = spec.get("min_roi_ratio")
        if min_roi_ratio is not None:
            production_cost = c.get("production_cost", 0)
            if production_cost <= 0:
                spend_met = True
                roi_ratio_met = True
            else:
                actual_ratio = total_spend / production_cost
                roi_ratio_met = actual_ratio >= min_roi_ratio
                spend_met = roi_ratio_met
        else:
            spend_met = total_spend >= min_spend
            roi_ratio_met = None

        is_available = within_time and spend_met

        results.append({
            "material_id": c.get("material_id", ""),
            "material_name": c.get("material_name", ""),
            "creative_type": creative_type,
            "is_available": is_available,
            "within_time": within_time,
            "spend_met": spend_met,
            "total_spend": total_spend,
            "min_spend": min_spend,
            "max_months": max_months,
            "roi_ratio_met": roi_ratio_met,
        })

    return results


def _match_availability_spec(creative_type: str, availability_config: dict) -> dict | None:
    if not creative_type or not availability_config:
        return None
    ct = creative_type.lower()
    for key, val in availability_config.items():
        if key.startswith("_") or not isinstance(val, dict):
            continue
        if ct == key.lower():
            return val
    for key, val in availability_config.items():
        if key.startswith("_") or not isinstance(val, dict):
            continue
        parts = key.lower().split("/")
        if any(p in ct or ct in p for p in parts):
            return val
    return None


# ═══════════════════════════════════════════════════════════════════════════
# build_decay_report
# ═══════════════════════════════════════════════════════════════════════════

def build_decay_report(
    *,
    project_id: str,
    date: str,
    config: dict,
    decay_results: list[dict],
) -> dict:
    """Build the decay report JSON pulling all values from config."""
    app = get_app_config(config, project_id)
    t = config["thresholds"]["creative_decay"]
    l1 = t.get("level_1", {"consecutive_days": 3, "roi_below_prev_avg_days": 3})
    l2 = t.get("level_2", {"consecutive_days": 5, "roi_below_prev_avg_days": 5})

    decayed = []
    watching = []
    skipped = []

    for r in decay_results:
        raw_name = r.get("material_name", "")
        entry: dict[str, Any] = {
            "material_id": r.get("material_id", ""),
            "creative_name": _extract_short_name(raw_name) or raw_name,
        }
        if r["action"] == "pause":
            entry.update({
                "online_days": r["online_days"],
                "consecutive_decay_days": r["consecutive_decay_days"],
                "decay_level": r.get("decay_level"),
                "action": "pause",
                "daily": r.get("daily", []),
                "ad_ids": r.get("ad_ids", []),
            })
            decayed.append(entry)
        elif r["action"] == "watch":
            entry.update({
                "consecutive_decay_days": r["consecutive_decay_days"],
                "decay_level": r.get("decay_level"),
                "action": "watch",
            })
            watching.append(entry)
        elif r["action"] == "skip":
            entry.update({
                "online_days": r.get("online_days", 0),
                "reason": r.get("reason", ""),
            })
            skipped.append(entry)

    conclusion_lines = [
        f"【{project_id} 素材衰退检测 {date}】",
    ]
    total_evaluated = len(decayed) + len(watching) + len(skipped)
    conclusion_lines.append(
        f"共评估 {total_evaluated} 个素材：{len(decayed)} 个衰退（建议暂停）、"
        f"{len(watching)} 个观察中、{len(skipped)} 个因上线天数不足跳过。"
    )
    if decayed:
        conclusion_lines.append("衰退素材（建议暂停）：")
        for d in decayed:
            lvl = f"Level {d.get('decay_level', '?')}" if d.get("decay_level") else ""
            conclusion_lines.append(
                f"  - {d['creative_name']}（{lvl} 连续衰退 {d['consecutive_decay_days']} 天，"
                f"上线 {d['online_days']} 天）"
            )
    else:
        conclusion_lines.append("当前无素材触发衰退暂停条件。")

    return {
        "report_type": "creative_decay",
        "project": project_id,
        "date": date,
        "target_cpi": get_fb_config(app, "target_cpi", 0),
        "target_roi": get_fb_config(app, "target_roi", 0),
        "thresholds": {
            "min_online_days": t["min_online_days"],
            "level_1": l1,
            "level_2": l2,
        },
        "decayed": decayed,
        "watching": watching,
        "skipped": skipped,
        "formula": (
            f"衰退判定 (M03): Level 1 = 连续 {l1['consecutive_days']} 天 "
            f"ROI 低于前 {l1['roi_below_prev_avg_days']} 天均值 → watch; "
            f"Level 2 = 连续 {l2['consecutive_days']} 天 "
            f"ROI 低于前 {l2['roi_below_prev_avg_days']} 天均值 → pause。"
            f"上线天数 >= {t['min_online_days']} 天才参与评估。"
        ),
        "conclusion": "\n".join(conclusion_lines),
    }


# ═══════════════════════════════════════════════════════════════════════════
# build_winner_report
# ═══════════════════════════════════════════════════════════════════════════

def build_winner_report(
    *,
    project_id: str,
    date: str,
    config: dict,
    winner_results: list[dict],
    inventory: dict,
) -> dict:
    """Build the winner report JSON pulling all values from config."""
    app = get_app_config(config, project_id)
    wt = config["thresholds"]["winner_creative"]
    inv_t = config["thresholds"]["creative_inventory"]
    calc_months = wt.get("calculation_months", 3)
    project_thresholds = app.get("winner_thresholds", {})

    winners = []
    for r in winner_results:
        if not r["is_winner"]:
            continue
        raw_name = r.get("material_name", "")
        winners.append({
            "material_id": r.get("material_id", ""),
            "material_name": raw_name,
            "creative_name": _extract_short_name(raw_name) or raw_name,
            "total_spend": r.get("total_spend", 0),
            "spend_threshold": r.get("spend_threshold", 0),
            "creative_type": r.get("creative_type", ""),
            "ad_ids": r.get("ad_ids", []),
        })

    winner_count = len(winners)

    conclusion_lines = [
        f"【{project_id} 爆款素材检测 {date}】",
    ]
    total_evaluated = len(winner_results)
    conclusion_lines.append(
        f"共评估 {total_evaluated} 个素材，发现 {winner_count} 个爆款。"
    )

    inv_status = inventory["inventory_status"]
    win_status = inventory["winner_status"]
    conclusion_lines.append(
        f"素材库存：{inventory['usable_count']} 个可用"
        f"（安全线 {inv_t['safety_line']}，状态{'不足' if inv_status == 'warning' else '正常'}）；"
        f"爆款数量：{winner_count}"
        f"（最低要求 {inv_t['min_hot_count']}，状态{'不足' if win_status == 'warning' else '正常'}）。"
    )

    if winners:
        conclusion_lines.append("爆款素材：")
        for w in winners:
            conclusion_lines.append(
                f"  - {w['creative_name']}"
                f"（{w.get('creative_type', '')} 累计消耗=${w['total_spend']:,.0f}，"
                f"阈值=${w['spend_threshold']:,.0f}）"
            )
    else:
        conclusion_lines.append("当前无素材达到爆款标准。")

    if inv_status == "warning" or win_status == "warning":
        conclusion_lines.append("建议：补充新素材或扩量现有优质素材。")

    return {
        "report_type": "winner_creative",
        "project": project_id,
        "date": date,
        "target_cpi": get_fb_config(app, "target_cpi", 0),
        "target_roi": get_fb_config(app, "target_roi", 0),
        "thresholds": {
            "calculation_months": calc_months,
            "project_spend_thresholds": {
                k: v for k, v in project_thresholds.items()
                if not k.startswith("_") and isinstance(v, (int, float))
            },
        },
        "inventory": {
            "usable_count": inventory["usable_count"],
            "safety_line": inv_t["safety_line"],
            "status": inventory["inventory_status"],
        },
        "winners": winners,
        "winner_summary": {
            "winner_count": winner_count,
            "min_hot_count": inv_t["min_hot_count"],
            "status": inventory["winner_status"],
        },
        "formula": (
            f"爆款判定 (M02): {calc_months} 个月内累计消耗达到项目×品类阈值即为爆款。"
            f"同一短名不分渠道/尺寸/时长统一计算。"
        ),
        "conclusion": "\n".join(conclusion_lines),
    }


# ═══════════════════════════════════════════════════════════════════════════
# run_creative_health — orchestrator
# ═══════════════════════════════════════════════════════════════════════════

def run_creative_health(
    *,
    project_id: str,
    date: str,
    mode: str,
    config: dict,
    fetch_active_ads: Callable[[str], list[dict]],
    fetch_material_daily: Callable[[str, str, str], list[dict]],
    fetch_country_report: Callable[[str, str, str], list[dict]] | None = None,
) -> dict:
    """Run the creative health flow with injected fetchers.

    Args:
        project_id: e.g. "ROK"
        date: today's date "YYYY-MM-DD"
        mode: "all" | "decay" | "winner"
        config: merged dict with keys: apps, thresholds
        fetch_active_ads: fn(project_id) → list of {ad_id, ad_name, adset_id, online_days}
        fetch_material_daily: fn(project_id, start, end) → list of {date, material_name, cpi, roi, spend}
        fetch_country_report: fn(project_id, start, end) → list of DAP country 表行

    Returns pure data dict — file I/O and Feishu upload are the caller's responsibility.
    """
    decay_t = config["thresholds"]["creative_decay"]
    winner_t_global = config["thresholds"]["winner_creative"]
    inv_t = config["thresholds"]["creative_inventory"]
    app = get_app_config(config, project_id)
    target_cpi = get_fb_config(app, "target_cpi", 0)
    target_roi = get_fb_config(app, "target_roi", 0)

    # Build winner_thresholds: merge global params + per-project spend from apps.json
    winner_t = dict(winner_t_global)
    winner_t[project_id] = app.get("winner_thresholds", {})

    # For decay: need enough days for level_2 (5-day avg + 5 consecutive = 10 days window)
    l2 = decay_t.get("level_2", {"consecutive_days": 5, "roi_below_prev_avg_days": 5})
    decay_lookback = l2["consecutive_days"] + l2["roi_below_prev_avg_days"] + 2
    # For winner: need calculation_months worth of data
    calc_months = winner_t.get("calculation_months", 3)
    winner_lookback = calc_months * 30
    lookback = max(decay_lookback, winner_lookback)

    from datetime import datetime, timedelta
    date_obj = datetime.strptime(date, "%Y-%m-%d")
    start_date = (date_obj - timedelta(days=lookback)).strftime("%Y-%m-%d")
    end_date = (date_obj - timedelta(days=1)).strftime("%Y-%m-%d")
    active_ads = fetch_active_ads(project_id)
    daily_data = fetch_material_daily(project_id, start_date, end_date)

    aligned = align_by_material_id(active_ads, daily_data)

    result: dict[str, Any] = {}

    if mode in ("all", "decay"):
        decay_results = evaluate_decay(
            aligned,
            min_online_days=decay_t["min_online_days"],
            decay_levels=decay_t,
        )
        decay_report = build_decay_report(
            project_id=project_id,
            date=date,
            config=config,
            decay_results=decay_results,
        )
        result["decay_report"] = decay_report

    if mode in ("all", "winner"):
        winner_results = evaluate_winner(
            aligned,
            project_id=project_id,
            winner_thresholds=winner_t,
        )

        availability_config = app.get("creative_availability", {})
        avail_not_configured = not availability_config
        winner_not_configured = all(r.get("reason") == "not_configured" for r in winner_results) if winner_results else not app.get("winner_thresholds")

        if availability_config:
            avail_results = evaluate_availability(
                aligned,
                project_id=project_id,
                availability_config=availability_config,
                reference_date=date,
            )
            usable_count = sum(1 for a in avail_results if a["is_available"])
        else:
            usable_count = len(aligned)

        winner_count = sum(1 for w in winner_results if w["is_winner"])
        inventory = count_inventory(
            usable_count=usable_count,
            winner_count=winner_count,
            safety_line=inv_t["safety_line"],
            min_hot_count=inv_t["min_hot_count"],
        )

        winner_report = build_winner_report(
            project_id=project_id,
            date=date,
            config=config,
            winner_results=winner_results,
            inventory=inventory,
        )
        if avail_not_configured:
            winner_report["availability_status"] = "not_configured"
        if winner_not_configured:
            winner_report["winner_status"] = "not_configured"
        by_region = []
        if fetch_country_report:
            country_rows = fetch_country_report(project_id, start_date, end_date)
            by_region = summarize_inventory_by_region(country_rows)
        winner_report["inventory_by_region"] = by_region
        winner_report["inventory_by_region_feishu"] = format_region_inventory_feishu(by_region)
        if by_region:
            winner_report["conclusion"] = (
                winner_report.get("conclusion", "")
                + "\n\n"
                + winner_report["inventory_by_region_feishu"]
            )
        result["winner_report"] = winner_report

    return result
