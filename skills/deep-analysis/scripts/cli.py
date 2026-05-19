"""deep-analysis CLI 入口。

用法（从项目根目录）:
    python workspace/skills/deep-analysis/scripts/cli.py <command> [options]

子命令:
    contribution   多维贡献度分解（5.1）
    budget         边际 ROI & 预算分配建议（5.4）
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILLS_ROOT = str(_SCRIPTS.parents[1])
if _SKILLS_ROOT not in sys.path:
    sys.path.insert(0, _SKILLS_ROOT)

_WORKSPACE = _SCRIPTS.parents[2]


_loader_spec = importlib.util.spec_from_file_location("_loader", _SCRIPTS.parents[1] / "lib" / "loader.py")
_loader = importlib.util.module_from_spec(_loader_spec); _loader_spec.loader.exec_module(_loader)
_load = _loader.make_loader(__file__)

from lib.fetchers import game_alias_for_project


_contrib_mod = _load("contribution_decomposer")
_marginal_mod = _load("marginal_roi")
_fetchers_mod = _load("_fetchers")

_CONFIG_DIR = _WORKSPACE / "config"


def _load_config() -> dict:
    apps = json.loads((_CONFIG_DIR / "apps.json").read_text(encoding="utf-8"))
    thresholds = json.loads((_CONFIG_DIR / "thresholds.json").read_text(encoding="utf-8"))
    return {"apps": apps, "thresholds": thresholds}


def _make_fetchers(command: str, args=None) -> dict:
    game = getattr(args, "project", None) if args else None
    if command == "contribution":
        return {
            "fetch_material_report": _fetchers_mod.make_fetch_material_report(),
        }
    if command == "budget":
        return {
            "fetch_custom_report": _fetchers_mod.make_fetch_custom_report(game=game),
        }
    return {}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="deep-analysis CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("contribution", help="多维贡献度分解（5.1）")
    p.add_argument("--project", required=True)
    p.add_argument("--channel", default="Facebook")
    p.add_argument("--period-a-start", required=True, help="时段 A 开始日期")
    p.add_argument("--period-a-end", required=True, help="时段 A 结束日期")
    p.add_argument("--period-b-start", required=True, help="时段 B 开始日期")
    p.add_argument("--period-b-end", required=True, help="时段 B 结束日期")
    p.add_argument("--metric", default="cpi", help="分析指标 (cpi/spend/ctr)")

    p = sub.add_parser("budget", help="边际 ROI & 预算分配建议（5.4）")
    p.add_argument("--project", required=True)
    p.add_argument("--total-budget", type=float, required=True, help="总预算")
    p.add_argument("--roi-target", type=float, required=True, help="回本目标")
    p.add_argument("--days", type=int, default=30, help="回溯天数（默认 30）")

    return parser.parse_args(argv)


# ═══════════════════════════════════════════════════════════════════════════
# Command handlers
# ═══════════════════════════════════════════════════════════════════════════

def _cmd_contribution(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    """多维贡献度分解。"""
    fetch = fetchers["fetch_material_report"]
    game = game_alias_for_project(config["apps"], args.project)
    rows_a = fetch(game, args.channel, args.period_a_start, args.period_a_end)
    rows_b = fetch(game, args.channel, args.period_b_start, args.period_b_end)

    # Map material_report rows to decomposer input format.
    # Use "country" or "pub" as dimension depending on what's available.
    def to_dim_rows(rows: list[dict]) -> list[dict]:
        result = []
        for r in rows:
            result.append({
                "dimension": r.get("country", r.get("pub", r.get("material_id", "unknown"))),
                "spend": r.get("spend", 0),
                "installs": r.get("installs", 0),
                "clicks": r.get("clicks", 0),
                "impressions": r.get("impressions", 0),
            })
        return result

    return _contrib_mod.decompose_contribution(
        to_dim_rows(rows_a),
        to_dim_rows(rows_b),
        metric=args.metric,
    )


def _cmd_budget(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    """边际 ROI & 预算分配建议。"""
    from datetime import datetime, timedelta

    today = datetime.now()
    start = (today - timedelta(days=args.days)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")

    # Fetch ROI data per channel
    fetch = fetchers["fetch_custom_report"]
    roi_rows = fetch("roi_by_channel", start, end)

    # Group by channel, compute marginal ROI for each
    from collections import defaultdict
    by_channel: dict[str, list[dict]] = defaultdict(list)
    for r in roi_rows:
        ch = r.get("channel", "unknown")
        by_channel[ch].append(r)

    channels = []
    for ch, history in by_channel.items():
        mr = _marginal_mod.compute_marginal_roi(history)
        channels.append({
            "channel": ch,
            "marginal_roi": mr["marginal_roi"],
            "current_spend": mr["total_spend"],
        })

    return _marginal_mod.allocate_budget(
        channels,
        total_budget=args.total_budget,
        roi_target=args.roi_target,
    )


_CMD_MAP = {
    "contribution": _cmd_contribution,
    "budget": _cmd_budget,
}


def run(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        config = _load_config()
        fetchers = _make_fetchers(args.command, args)
        result = _CMD_MAP[args.command](args, config, fetchers)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run()
