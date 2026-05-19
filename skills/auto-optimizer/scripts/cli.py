"""auto-optimizer CLI 入口。

用法（从项目根目录）:
    python workspace/skills/auto-optimizer/scripts/cli.py <command> [options]

子命令:
    decay        Campaign/AdSet 衰退检测（B02/B03）
    high-risk    高风险消耗检测（C04）
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_WORKSPACE = _SCRIPTS.parents[2]


_loader_spec = importlib.util.spec_from_file_location("_loader", _SCRIPTS.parents[1] / "lib" / "loader.py")
_loader = importlib.util.module_from_spec(_loader_spec); _loader_spec.loader.exec_module(_loader)
_load = _loader.make_loader(__file__)


_decay_mod = _load("campaign_decay")
_risk_mod = _load("high_risk_checker")
_budget_mod = _load("budget_adjuster")
_fetchers_mod = _load("_fetchers")

_CONFIG_DIR = _WORKSPACE / "config"


def _load_config() -> dict:
    apps = json.loads((_CONFIG_DIR / "apps.json").read_text(encoding="utf-8"))
    thresholds = json.loads((_CONFIG_DIR / "thresholds.json").read_text(encoding="utf-8"))
    return {"apps": apps, "thresholds": thresholds}


def _make_fetchers(command: str) -> dict:
    if command in ("decay", "high-risk"):
        return {
            "fetch_insights": _fetchers_mod.make_fetch_insights(),
        }
    return {}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="auto-optimizer CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("decay", help="Campaign/AdSet 衰退检测（B02/B03）")
    p.add_argument("--project", required=True)
    p.add_argument("--days", type=int, default=7, help="检测天数（默认 7）")

    p = sub.add_parser("high-risk", help="高风险消耗检测（C04）")
    p.add_argument("--project", required=True)

    return parser.parse_args(argv)


# ═══════════════════════════════════════════════════════════════════════════
# Command handlers
# ═══════════════════════════════════════════════════════════════════════════

def _cmd_decay(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    """Campaign/AdSet 衰退检测。

    拉取 campaign 级 insights，按 campaign_id 分组，
    提取每日 CPI 序列，调用 run_decay_check。
    """
    from datetime import datetime, timedelta

    today = datetime.now()
    start = (today - timedelta(days=args.days)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")

    rows = fetchers["fetch_insights"](
        date_start=start, date_end=end, level="campaign", time_increment=1,
    )

    app_config = config["apps"].get(args.project, {}).get("facebook", {})
    thresholds = config["thresholds"]

    # Group by campaign_id, extract daily CPI series
    by_campaign: dict[str, dict] = defaultdict(lambda: {
        "id": "", "name": "", "daily_cpis": [], "daily_rois": [],
    })
    for r in sorted(rows, key=lambda x: x.get("date_start", "")):
        cid = r.get("campaign_id", "unknown")
        entry = by_campaign[cid]
        entry["id"] = cid
        entry["name"] = r.get("campaign_name", "")

        spend = float(r.get("spend", 0))
        installs = int(r.get("installs", 0))
        cpi = float(r["cpi"]) if "cpi" in r else (spend / installs if installs > 0 else 0)
        roi = float(r.get("roi", 0))
        entry["daily_cpis"].append(cpi)
        entry["daily_rois"].append(roi)

    campaigns = list(by_campaign.values())
    # For now, AdSets use the same data (campaign-level).
    # Full adset-level granularity requires adset-level insights fetch.
    adsets: list[dict] = []

    return _decay_mod.run_decay_check(
        args.project,
        campaigns=campaigns,
        adsets=adsets,
        app_config=app_config,
        thresholds=thresholds,
    )


def _cmd_high_risk(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    """高风险消耗检测。

    拉取最近一天 campaign 级 insights，检测高消耗低 ROI 实体。
    """
    rows = fetchers["fetch_insights"](
        date_start="", date_end="", level="campaign",
    )

    app_config = config["apps"].get(args.project, {}).get("facebook", {})
    target_roi = app_config.get("target_roi", 0)
    thresholds = config["thresholds"]

    # Build entity list from latest insights
    entities = []
    for r in rows:
        spend = float(r.get("spend", 0))
        roi = float(r.get("roi", 0))
        entities.append({
            "id": r.get("campaign_id", "unknown"),
            "name": r.get("campaign_name", ""),
            "daily_spend": spend,
            "roi": roi,
        })

    alerts = _risk_mod.check_high_risk_spend(
        entities, target_roi=target_roi, thresholds=thresholds,
    )
    return {
        "project_id": args.project,
        "alerts": alerts,
    }


_CMD_MAP = {
    "decay": _cmd_decay,
    "high-risk": _cmd_high_risk,
}


def run(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        config = _load_config()
        fetchers = _make_fetchers(args.command)
        result = _CMD_MAP[args.command](args, config, fetchers)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run()
