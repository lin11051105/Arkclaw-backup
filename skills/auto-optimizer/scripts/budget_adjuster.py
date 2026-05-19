"""预算调整计算 — 降预算幅度和确认判定 + OS-aware 行动决策。

Design: pure functions, no I/O.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

# SKAN iOS 默认 72h 回传延迟保护期（与 thresholds.json 中
# budget_adjustment.min_age_hours_ios 保持一致）。
_DEFAULT_MIN_AGE_HOURS_IOS = 72

# 行动决策阈值（相对 target_roi）：
#   actual < 0.5 * target → pause
#   0.5 * target <= actual < target → reduce
#   target <= actual < 1.5 * target → maintain
#   actual >= 1.5 * target → scale
_PAUSE_RATIO = 0.5
_SCALE_RATIO = 1.5


def compute_adjustment(
    current_budget: float,
    reduction_pct: float,
    *,
    max_auto_reduction_pct: float,
    daily_spend: float = 0.0,
    high_spend_threshold: float = 500.0,
) -> dict[str, Any]:
    """计算预算调整。

    Args:
        current_budget: 当前预算
        reduction_pct: 期望降低比例 (0.30 = 降 30%)
        max_auto_reduction_pct: 自动执行的最大降幅
        daily_spend: 当前日耗（用于判定是否需要确认）
        high_spend_threshold: 日耗超过此值暂停/降预算需人工确认

    Returns:
        {"current_budget", "new_budget", "reduction_pct",
         "needs_confirmation", "confirmation_reason"}
    """
    new_budget = round(current_budget * (1 - reduction_pct), 2)

    needs_confirmation = False
    reasons: list[str] = []

    if reduction_pct > max_auto_reduction_pct:
        needs_confirmation = True
        reasons.append(
            f"降幅 {reduction_pct:.0%} 超过自动执行上限 {max_auto_reduction_pct:.0%}"
        )

    if daily_spend > high_spend_threshold:
        needs_confirmation = True
        reasons.append(
            f"日耗 ${daily_spend:.0f} 超过 ${high_spend_threshold:.0f} 阈值"
        )

    return {
        "current_budget": current_budget,
        "new_budget": new_budget,
        "reduction_pct": reduction_pct,
        "needs_confirmation": needs_confirmation,
        "confirmation_reason": "; ".join(reasons) if reasons else "",
    }


def _compute_age_hours(launch_date: str | None, today: str | None) -> float | None:
    """Compute age in hours between two ISO YYYY-MM-DD strings.

    Returns None if either date is missing or unparseable — caller treats
    that as "can't apply grace period, fall through to action logic".
    """
    if not launch_date or not today:
        return None
    try:
        launch_dt = datetime.strptime(launch_date, "%Y-%m-%d")
        today_dt = datetime.strptime(today, "%Y-%m-%d")
    except ValueError:
        return None
    delta = today_dt - launch_dt
    return delta.total_seconds() / 3600.0


def _classify_action_by_roi(actual_roi: float, target_roi: float) -> str:
    """Classify action based on actual vs target ROI ratio.

    Returns one of: "pause" | "reduce" | "maintain" | "scale".
    """
    if target_roi <= 0:
        # Defensive: avoid div-by-zero. Treat as "maintain" — caller has
        # bigger problems than budget action if target is unset.
        return "maintain"
    ratio = actual_roi / target_roi
    if ratio < _PAUSE_RATIO:
        return "pause"
    if ratio < 1.0:
        return "reduce"
    if ratio < _SCALE_RATIO:
        return "maintain"
    return "scale"


def decide_budget_action(
    campaign_id: str,
    *,
    os: str = "android",
    launch_date: str | None = None,
    today: str | None = None,
    actual_roi: float,
    target_roi: float,
    daily_spend: float,
    config: dict[str, Any],
) -> dict[str, Any]:
    """OS-aware budget-action decision with iOS 72h SKAN grace period.

    SKAN iOS 回传有 ~72h 延迟，刚启动的 iOS Campaign 不能基于"未到账"的
    指标做暂停/降预算判断。本函数在 ROI 决策前加一道保护期闸：

      若 ``os == "ios"`` 且 (``today`` - ``launch_date``) < min_age_hours_ios
      → 直接返回 ``action="skip"``，跳过该 Campaign 本次调整。

    保护期外（或 Android）按 ROI 比例分级决策：

      - ``actual_roi < 0.5 * target_roi`` → ``"pause"``
      - ``0.5 * target_roi <= actual_roi < target_roi`` → ``"reduce"``
      - ``target_roi <= actual_roi < 1.5 * target_roi`` → ``"maintain"``
      - ``actual_roi >= 1.5 * target_roi`` → ``"scale"``

    Args:
        campaign_id: 回显字段。
        os: ``"ios"`` 或 ``"android"``，默认 ``"android"``（旧版兼容）。
        launch_date: Campaign 启动日，ISO ``YYYY-MM-DD``。可选。
        today: 当前日期，ISO ``YYYY-MM-DD``。可选；与 ``launch_date`` 须同时提供
            才会触发 iOS 保护期检查。
        actual_roi: 当前 Actual_ROI（已按 OS 分流取得，调用方负责）。
        target_roi: 目标 ROI（OS-aware，调用方通过 ``get_os_target`` 取得）。
        daily_spend: 当前日耗（USD）。**审计字段，不参与 action 分类**：
            action 仅由 ``actual_roi`` 与 ``target_roi`` 比值决定，日耗不会
            让 action 在 ``pause`` / ``reduce`` / ``maintain`` / ``scale`` 之间翻转。
            非零值会被附加到返回的 ``reason`` 字符串中以便人工追溯；零值则
            不出现在 reason 中，保持日志整洁。该参数是预留位，未来可在高日耗
            Campaign 上叠加额外保护策略，但当前一期不参与判定。该契约由
            ``tests/unit/test_auto_optimizer/test_budget_adjuster.py::``
            ``TestDailySpendIsAuditOnly`` 锁定。
        config: 含 ``thresholds.budget_adjustment.min_age_hours_ios`` 的 config。
            缺省值 72h。

    Returns:
        ``{"campaign_id", "action", "reason", "os"}``，其中 ``action`` ∈
        ``{"skip", "pause", "reduce", "maintain", "scale"}``。
    """
    min_age_hours = (
        config.get("thresholds", {})
        .get("budget_adjustment", {})
        .get("min_age_hours_ios", _DEFAULT_MIN_AGE_HOURS_IOS)
    )

    # iOS 72h SKAN 保护期：必须同时提供 launch_date 和 today 才能计算年龄。
    if os == "ios":
        age_hours = _compute_age_hours(launch_date, today)
        if age_hours is not None and age_hours < min_age_hours:
            return {
                "campaign_id": campaign_id,
                "action": "skip",
                "reason": (
                    f"iOS SKAN grace period: {age_hours:.0f}h < {min_age_hours}h "
                    f"since launch ({launch_date}); skip until SKAN postbacks settle"
                ),
                "os": os,
            }

    # 保护期外（或 Android）—— 按 ROI 比例分级决策。
    action = _classify_action_by_roi(actual_roi, target_roi)
    reason = (
        f"actual_roi={actual_roi:.2f} vs target_roi={target_roi:.2f} "
        f"(ratio={actual_roi / target_roi:.2f})"
        if target_roi > 0
        else f"target_roi={target_roi} invalid; default to maintain"
    )
    # daily_spend is audit-only — never flips action. Pinned by
    # TestDailySpendIsAuditOnly in tests/unit/test_auto_optimizer/.
    # Nonzero values surface in reason for traceability; zero is omitted
    # to keep the trace clean.
    if daily_spend:
        reason = f"{reason}; daily_spend=${daily_spend:.0f}"

    return {
        "campaign_id": campaign_id,
        "action": action,
        "reason": reason,
        "os": os,
    }
