"""Daily monitoring — 4.1 日常投放数据监控。

Computes 7d/30d weighted baselines and checks yesterday's metrics
for spikes/drops in spend, CPI, CTR, CVR.

Design:
- ``check_daily_metrics``: 纯计算函数，调用方提供已聚合的指标。
- ``run_daily_check``: 编排入口，给 (project_id, date, fetch_insights) →
  内部拉 30 天数据 + 算基线 + 调 check_daily_metrics。
  PlanRunner / CLI 都用此入口；纯函数留作内部和测试使用。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable


def compute_baseline(
    avg_7d: float,
    avg_30d: float,
    w7: float,
    w30: float,
) -> float:
    """加权基线 = avg_7d × w7 + avg_30d × w30。"""
    return avg_7d * w7 + avg_30d * w30


def check_daily_metrics(
    project_id: str,
    *,
    yesterday: dict[str, float],
    baseline_7d: dict[str, float],
    baseline_30d: dict[str, float],
    thresholds: dict,
    os: str = "android",
) -> dict:
    """对比昨日指标与基线，检测异常波动。

    Args:
        project_id: 项目 ID
        yesterday: {"spend", "cpi", "ctr", "cvr"}
        baseline_7d: 近 7 天各指标日均
        baseline_30d: 近 30 天各指标日均
        thresholds: 含 ``daily_monitoring`` 与（可选）``daily_monitoring_ios`` 块
        os: ``"android"`` (默认) 或 ``"ios"``。iOS 走 SKAN 真值路径，
            阈值通常更宽（``cpi_spike_pct`` ≈ 0.449 vs Android 0.30）以吸收
            SKAN postback 噪声。当传入 ``"ios"`` 但 thresholds 缺少
            ``daily_monitoring_ios`` 块时，回退到 ``daily_monitoring``。

    Returns:
        {"status", "project_id", "os", "metrics", "alerts": [...]}
    """
    # OS-aware threshold block pick. iOS path looks up ``daily_monitoring_ios``
    # first; falls back to legacy ``daily_monitoring`` so callers without the
    # iOS block configured stay on Android-equivalent behavior.
    if os == "ios":
        dm = thresholds.get("daily_monitoring_ios") or thresholds.get("daily_monitoring", {})
    else:
        dm = thresholds.get("daily_monitoring", {})
    w7 = dm.get("baseline_7d_weight", 0.6)
    w30 = dm.get("baseline_30d_weight", 0.4)

    alerts: list[dict[str, Any]] = []

    # Spend check
    bl_spend = compute_baseline(baseline_7d.get("spend", 0), baseline_30d.get("spend", 0), w7, w30)
    y_spend = yesterday.get("spend", 0)
    if bl_spend > 0:
        spend_change = (y_spend - bl_spend) / bl_spend
        if spend_change > dm.get("spend_spike_pct", 0.50):
            alerts.append({
                "type": "spend_spike",
                "severity": "P1",
                "change_pct": round(spend_change, 4),
                "message": f"消耗突增 {spend_change:.0%}（昨日 ${y_spend:.0f} vs 基线 ${bl_spend:.0f}）",
            })
        elif -spend_change > dm.get("spend_drop_pct", 0.30):
            alerts.append({
                "type": "spend_drop",
                "severity": "P1",
                "change_pct": round(spend_change, 4),
                "message": f"消耗突降 {abs(spend_change):.0%}（昨日 ${y_spend:.0f} vs 基线 ${bl_spend:.0f}）",
            })

    # CPI check (spike only — higher CPI is bad)
    bl_cpi = compute_baseline(baseline_7d.get("cpi", 0), baseline_30d.get("cpi", 0), w7, w30)
    y_cpi = yesterday.get("cpi", 0)
    if bl_cpi > 0:
        cpi_change = (y_cpi - bl_cpi) / bl_cpi
        if cpi_change > dm.get("cpi_spike_pct", 0.30):
            alerts.append({
                "type": "cpi_spike",
                "severity": "P1",
                "change_pct": round(cpi_change, 4),
                "message": f"CPI 突增 {cpi_change:.0%}（昨日 {y_cpi:.2f} vs 基线 {bl_cpi:.2f}）",
            })

    # CTR check (drop only — lower CTR is bad)
    bl_ctr = compute_baseline(baseline_7d.get("ctr", 0), baseline_30d.get("ctr", 0), w7, w30)
    y_ctr = yesterday.get("ctr", 0)
    if bl_ctr > 0:
        ctr_change = (y_ctr - bl_ctr) / bl_ctr
        if -ctr_change > dm.get("ctr_drop_pct", 0.25):
            alerts.append({
                "type": "ctr_drop",
                "severity": "P1",
                "change_pct": round(ctr_change, 4),
                "message": f"CTR 突降 {abs(ctr_change):.0%}（昨日 {y_ctr:.4f} vs 基线 {bl_ctr:.4f}）",
            })

    # CVR check (drop only — lower CVR is bad)
    bl_cvr = compute_baseline(baseline_7d.get("cvr", 0), baseline_30d.get("cvr", 0), w7, w30)
    y_cvr = yesterday.get("cvr", 0)
    if bl_cvr > 0:
        cvr_change = (y_cvr - bl_cvr) / bl_cvr
        if -cvr_change > dm.get("cvr_drop_pct", 0.25):
            alerts.append({
                "type": "cvr_drop",
                "severity": "P1",
                "change_pct": round(cvr_change, 4),
                "message": f"CVR 突降 {abs(cvr_change):.0%}（昨日 {y_cvr:.4f} vs 基线 {bl_cvr:.4f}）",
            })

    return {
        "status": "alert" if alerts else "ok",
        "project_id": project_id,
        "os": os,
        "metrics": {
            "yesterday": yesterday,
            "baseline_spend": round(bl_spend, 2),
            "baseline_cpi": round(bl_cpi, 2),
            "baseline_ctr": round(bl_ctr, 6),
            "baseline_cvr": round(bl_cvr, 6),
        },
        "alerts": alerts,
    }


def _insights_row_to_metrics(row: dict[str, Any]) -> dict[str, float]:
    """Facebook Insights 行 → metrics dict。"""
    spend = float(row.get("spend") or 0)
    impressions = float(row.get("impressions") or 0)
    clicks = float(row.get("clicks") or 0)
    installs = float(row.get("installs") or 0)
    return {
        "spend": spend,
        "cpi": (spend / installs) if installs > 0 else 0,
        "ctr": (clicks / impressions) if impressions > 0 else 0,
        "cvr": (installs / clicks) if clicks > 0 else 0,
    }


def _avg_metrics(metrics: list[dict[str, float]], n: int) -> dict[str, float]:
    """对最后 n 条 metrics 取平均。"""
    subset = metrics[-n:] if len(metrics) >= n else metrics
    if not subset:
        return {"spend": 0, "cpi": 0, "ctr": 0, "cvr": 0}
    return {
        k: sum(m[k] for m in subset) / len(subset)
        for k in ("spend", "cpi", "ctr", "cvr")
    }


def run_daily_check(
    project_id: str,
    date: str,
    *,
    config: dict,
    fetch_insights: Callable,
    os: str = "android",
) -> dict:
    """日常监控编排入口：拉 30 天 insights → 算 7d/30d 基线 → 检测异常。

    Args:
        project_id: 项目 ID
        date: 检测日期 (YYYY-MM-DD)，通常为昨天
        config: {"thresholds": ...}
        fetch_insights: fn(date_start, date_end, level, time_increment, **kw) → list[dict]
        os: "android" (默认) 或 "ios"。注：此入口当前仅支持 Android 路径；
            iOS SKAN 路径需要 fetch_skan_by_game_day fetcher，待 SkillBridge
            FETCHER_REGISTRY 补齐后扩展。

    Returns:
        与 check_daily_metrics 相同结构。无数据时 status="no_data"。
    """
    if os == "ios":
        return {
            "status": "not_supported",
            "project_id": project_id,
            "message": "iOS SKAN 路径需要 fetch_skan_by_game_day fetcher，暂未接入 SkillBridge",
        }

    date_obj = datetime.strptime(date, "%Y-%m-%d").date()
    start = (date_obj - timedelta(days=30)).isoformat()

    rows = fetch_insights(
        date_start=start, date_end=date, level="account", time_increment=1,
    )
    rows.sort(key=lambda r: r.get("date_start", ""))
    all_metrics = [_insights_row_to_metrics(r) for r in rows]

    if not all_metrics:
        return {
            "status": "no_data",
            "project_id": project_id,
            "os": os,
            "metrics": {},
            "alerts": [],
        }

    yesterday = all_metrics[-1]
    history = all_metrics[:-1]

    return check_daily_metrics(
        project_id,
        yesterday=yesterday,
        baseline_7d=_avg_metrics(history, 7),
        baseline_30d=_avg_metrics(history, 30),
        thresholds=config["thresholds"],
        os=os,
    )
