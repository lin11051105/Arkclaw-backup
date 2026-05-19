"""sop_checker — SOP 清单校验 + OS-aware 预算合规校验.

纯函数模块，不做 I/O。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Resolve sibling skills/lib for cross-skill imports (lib.fetchers).
_SKILLS_ROOT = Path(__file__).resolve().parents[2]
if str(_SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILLS_ROOT))

from lib.fetchers import get_os_target  # noqa: E402  must follow sys.path setup

# Channel-agnostic single-create daily-budget guards (USD).
# Source: docs/ua_p1_architecture.md — single-line-item safety caps.
# These are *defaults* used when ``thresholds["budget_sop"]`` is omitted;
# production callers should inject the block from ``thresholds.json`` so the
# caps stay declarative alongside ``daily_monitoring`` / ``roi_progress``.
_DEFAULT_MIN_DAILY_BUDGET_USD = 10.0
_DEFAULT_MAX_DAILY_BUDGET_USD = 5000.0


def _resolve_budget_caps(
    thresholds: dict[str, Any] | None,
) -> tuple[float, float]:
    """Resolve (min, max) daily-budget caps with defaults for missing keys.

    Looks up ``thresholds["budget_sop"]["min_daily_usd"]`` and
    ``thresholds["budget_sop"]["max_daily_usd"]``; falls back to the module
    defaults for either key independently when missing or when the entire
    block is absent. Keeps callers free to override only one bound.
    """
    block = (thresholds or {}).get("budget_sop") or {}
    min_usd = block.get("min_daily_usd", _DEFAULT_MIN_DAILY_BUDGET_USD)
    max_usd = block.get("max_daily_usd", _DEFAULT_MAX_DAILY_BUDGET_USD)
    return float(min_usd), float(max_usd)


def check_sop(
    template: dict[str, Any],
    check_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """校验 SOP 清单.

    Args:
        template: SOP 模板，含 checklist 列表
        check_results: 自动检查结果，key 为 checklist item id

    Returns:
        {
            "passed_count": int,
            "failed_count": int,
            "manual_count": int,
            "overall": "pass" | "pending_manual" | "blocked",
            "items": [{"id", "name", "status", "detail"}, ...],
        }
    """
    checklist = template.get("checklist", [])
    items: list[dict[str, Any]] = []
    passed = 0
    failed = 0
    manual = 0

    for item in checklist:
        item_id = item["id"]
        auto_check = item.get("auto_check", False)

        if not auto_check:
            items.append({
                "id": item_id,
                "name": item.get("name", ""),
                "status": "pending_manual",
            })
            manual += 1
            continue

        result = check_results.get(item_id)
        if result is None:
            items.append({
                "id": item_id,
                "name": item.get("name", ""),
                "status": "failed",
                "detail": "无数据",
            })
            failed += 1
            continue

        if result.get("passed", False):
            items.append({
                "id": item_id,
                "name": item.get("name", ""),
                "status": "passed",
                "detail": result.get("detail", ""),
            })
            passed += 1
        else:
            items.append({
                "id": item_id,
                "name": item.get("name", ""),
                "status": "failed",
                "detail": result.get("detail", ""),
            })
            failed += 1

    if failed > 0:
        overall = "blocked"
    elif manual > 0:
        overall = "pending_manual"
    else:
        overall = "pass"

    return {
        "passed_count": passed,
        "failed_count": failed,
        "manual_count": manual,
        "overall": overall,
        "items": items,
    }


def check_budget_sop(
    project_id: str,
    proposed_daily_budget: float,
    *,
    config: dict[str, Any],
    thresholds: dict[str, Any] | None = None,
    os: str = "android",
) -> dict[str, Any]:
    """OS-aware single-create daily-budget SOP check.

    Resolves the *effective* target_cpi / target_roi for an app via
    ``lib.fetchers.get_os_target`` (which prefers OS-specific keys
    ``{ios|android}_target_cpi`` / ``{ios|android}_target_roi`` and falls
    back to the legacy ``target_cpi`` / ``target_roi`` when the OS-specific
    key is missing). Then validates ``proposed_daily_budget`` against the
    channel-agnostic single-create safety caps (configurable via
    ``thresholds["budget_sop"]`` with module-default fallback).

    Args:
        project_id: App identifier (key under ``config["apps"]``).
        proposed_daily_budget: Daily budget proposed for one campaign/ad-set
            line item (USD).
        config: Apps config blob — typically loaded from ``apps.json`` —
            shaped as ``{"apps": {project_id: {channel: {target_cpi, ...}}}}``.
            The first channel under the app is used for target lookup
            (per current single-channel-per-app convention; T9 plan).
        thresholds: Optional thresholds blob — typically loaded from
            ``thresholds.json``. The ``budget_sop`` block, if present,
            supplies ``min_daily_usd`` / ``max_daily_usd`` overrides:

                {"budget_sop": {"min_daily_usd": 50.0, "max_daily_usd": 2000.0}}

            Either key may be omitted — missing keys fall back to the
            module-level defaults ($10 min / $5000 cap). When the kwarg
            is ``None`` (legacy callers), both defaults apply.
        os: ``"ios"`` or ``"android"``. Defaults to ``"android"`` for legacy
            back-compat (callers that haven't been migrated yet).

    Returns:
        Dict with keys::

            {
                "project_id": str,
                "os": str,
                "effective_target_cpi": float,
                "effective_target_roi": float,
                "proposed_daily_budget": float,
                "issues": [{"code": str, "severity": str, "detail": str}, ...],
            }

        ``issues`` is always a list (possibly empty). Issue codes:

        - ``"budget_below_min"`` — proposed < min cap (default $10)
        - ``"budget_above_cap"`` — proposed > max cap (default $5000)

    Raises:
        ValueError: If ``project_id`` is not present in ``config["apps"]``.
            We never silently fall back to defaults — unknown apps are a
            config bug the caller must fix.
    """
    apps = config.get("apps", {})
    app = apps.get(project_id)
    if app is None:
        raise ValueError(
            f"Unknown project_id={project_id!r}; not found in config['apps']. "
            f"Available: {sorted(apps.keys())}"
        )

    # `get_os_target` already extracts `app["facebook"]` internally and
    # handles {ios|android}_{field} lookup with legacy fallback —
    # pass the project-level dict directly.
    if not isinstance(app, dict) or not app:
        raise ValueError(
            f"Malformed config for project_id={project_id!r}: expected "
            f"non-empty channel dict, got {type(app).__name__}"
        )

    effective_target_cpi = float(
        get_os_target(app, os=os, field="target_cpi", default=0.0) or 0.0
    )
    effective_target_roi = float(
        get_os_target(app, os=os, field="target_roi", default=0.0) or 0.0
    )

    min_usd, max_usd = _resolve_budget_caps(thresholds)

    issues: list[dict[str, Any]] = []
    if proposed_daily_budget < min_usd:
        issues.append({
            "code": "budget_below_min",
            "severity": "P1",
            "detail": (
                f"proposed_daily_budget=${proposed_daily_budget:.2f} < "
                f"channel min ${min_usd:.2f}"
            ),
        })
    if proposed_daily_budget > max_usd:
        issues.append({
            "code": "budget_above_cap",
            "severity": "P1",
            "detail": (
                f"proposed_daily_budget=${proposed_daily_budget:.2f} > "
                f"single-create safety cap ${max_usd:.2f}"
            ),
        })

    return {
        "project_id": project_id,
        "os": os,
        "effective_target_cpi": effective_target_cpi,
        "effective_target_roi": effective_target_roi,
        "proposed_daily_budget": float(proposed_daily_budget),
        "issues": issues,
    }
