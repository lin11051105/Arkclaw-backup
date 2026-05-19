"""ROI progress checker — 回本进度预警。

Checks actual ROI vs target ROI from apps.json.
Deviation > 10% → P1 alert (bidirectional).

Design: dependency-injected fetcher for testability.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

_SKILLS_ROOT = str(Path(__file__).resolve().parents[2])
if _SKILLS_ROOT not in sys.path:
    sys.path.insert(0, _SKILLS_ROOT)
from lib.fetchers import get_app_config, get_os_target


def check_roi_progress(
    project_id: str,
    channel: str,
    date: str,
    *,
    config: dict,
    fetch_custom_report: Callable[[str, str, str], list[dict]],
    date_end: str | None = None,
    os: str = "android",
) -> dict:
    """检查 ROI 进度偏差。

    Args:
        project_id: 项目 ID
        channel: 渠道名 (e.g. "Facebook")
        date: 开始日期（单日查询时也是结束日期）
        config: {"apps": ..., "thresholds": ...}
        fetch_custom_report: fn(table, start_date, end_date) → [{"ROI_最新": "9.99%", ...}]
        date_end: 结束日期（传了则查区间聚合，用于"本月回本进度"场景）
        os: ``"android"``（默认）或 ``"ios"``。iOS 走 SKAN 真值路径，
            ``target_roi`` 通过 :func:`lib.fetchers.get_os_target` 解析
            （优先 ``ios_target_roi``，回退至传统 ``target_roi``），
            阈值块优先选 ``roi_progress_ios``，缺失时回退 ``roi_progress``。
    """
    app = get_app_config(config, project_id)
    target_roi = get_os_target(app, os=os, field="target_roi", default=0.0)

    # OS-aware threshold block pick. iOS SKAN postback 噪声更大，``roi_progress_ios``
    # 通常 deviation_alert_pct 更宽（0.15 vs Android 0.10）。缺失时回退到 legacy 块。
    thresholds_root = config.get("thresholds", {})
    if os == "ios":
        roi_thresholds = thresholds_root.get("roi_progress_ios") or thresholds_root.get("roi_progress", {})
    else:
        roi_thresholds = thresholds_root.get("roi_progress", {})
    deviation_alert_pct = roi_thresholds.get("deviation_alert_pct", 0.10)

    end = date_end or date
    rows = fetch_custom_report("roi", date, end)

    if not rows:
        return {
            "status": "no_data",
            "project_id": project_id,
            "os": os,
            "actual_roi": None,
            "target_roi": target_roi,
            "deviation_pct": 0.0,
            "alerts": [],
            "daily_detail": [],
            "channel_breakdown": [],
        }

    def _parse_roi(r: dict) -> float:
        """从 DAP ROI 表行提取 ROI 值。列名 ROI_最新，值为百分比字符串如 '9.99%'，去掉%后与 target_roi 同量纲。"""
        v = r.get("ROI_最新", "0")
        if isinstance(v, str):
            v = v.rstrip("%")
        return float(v or 0)

    # 按消耗加权平均（总计行已被 _parse_dap_table 过滤）
    rois = [_parse_roi(r) for r in rows]
    spends = [float(r.get("消耗数", 1)) for r in rows]
    total_spend = sum(spends)
    actual_roi = sum(roi * s for roi, s in zip(rois, spends)) / total_spend if total_spend > 0 else 0.0

    # 分日明细：保留每日 ROI / 消耗 / 收入 / 多阶段 ROI
    _ROI_STAGES = ("ROI_1", "ROI_3", "ROI_7", "ROI_15", "ROI_30")
    daily_detail: list[dict] = []
    for r in rows:
        day: dict = {
            "date": r.get("日期", ""),
            "roi": _parse_roi(r),
            "spend": float(r.get("消耗数") or 0),
            "revenue": float(r.get("最新实收") or 0),
        }
        for stage in _ROI_STAGES:
            v = r.get(stage)
            if v is not None:
                if isinstance(v, str):
                    v = v.rstrip("%")
                day[stage.lower()] = float(v or 0)
        daily_detail.append(day)

    if target_roi > 0:
        deviation = abs(actual_roi - target_roi) / target_roi
    else:
        deviation = 0.0

    alerts: list[dict] = []

    if target_roi > 0 and deviation > deviation_alert_pct:
        direction = "偏低" if actual_roi < target_roi else "偏高"
        alerts.append({
            "type": "roi_deviation",
            "severity": "P1",
            "deviation_pct": round(deviation, 4),
            "threshold": deviation_alert_pct,
            "message": (
                f"ROI 较目标{direction}，偏差 {deviation:.0%} "
                f"（实际 {actual_roi:.2f} vs 目标 {target_roi:.2f}）"
            ),
        })

    # 渠道拆分：从 media_src 表获取各渠道 ROI
    channel_breakdown: list[dict] = []
    ch_rows = fetch_custom_report("media_src", date, end)
    for r in ch_rows:
        ch_name = r.get("渠道", r.get("media_source", ""))
        spend = float(r.get("消耗数") or 0)
        if not ch_name or spend <= 0:
            continue
        installs = int(r.get("安装数") or 0)
        cpi = float(r.get("安装成本") or (spend / installs if installs > 0 else 0))
        roi = float(r.get("Actual_ROI") or 0)
        channel_breakdown.append({
            "channel": ch_name,
            "spend": spend,
            "installs": installs,
            "cpi": cpi,
            "roi": roi,
        })
    channel_breakdown.sort(key=lambda c: c["spend"], reverse=True)

    status = "alert" if alerts else "ok"
    summary = "回本进度达标" if status == "ok" else alerts[0].get("message", "")

    return {
        "status": status,
        "project_id": project_id,
        "os": os,
        "actual_roi": actual_roi,
        "target_roi": target_roi,
        "deviation_pct": round(deviation, 4),
        "alerts": alerts,
        "daily_detail": daily_detail,
        "channel_breakdown": channel_breakdown,
        "summary": summary,
    }
