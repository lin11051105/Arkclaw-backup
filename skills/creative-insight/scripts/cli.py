"""creative-insight CLI 入口。

用法（从项目根目录）:
    python workspace/skills/creative-insight/scripts/cli.py <command> [options]

子命令:
    volume     起量素材筛选
    winners    爆款素材筛选
    tags       标签 × 效果交叉分析
    ab-face    A面/B面素材分类
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


_volume_mod = _load("volume_filter")
_tag_mod = _load("tag_analyzer")
_fetchers_mod = _load("_fetchers")

_CONFIG_DIR = _WORKSPACE / "config"


def _load_config() -> dict:
    apps = json.loads((_CONFIG_DIR / "apps.json").read_text(encoding="utf-8"))
    thresholds = json.loads((_CONFIG_DIR / "thresholds.json").read_text(encoding="utf-8"))
    return {"apps": apps, "thresholds": thresholds}


def _make_fetchers() -> dict:
    return {
        "fetch_material_report": _fetchers_mod.make_fetch_material_report(),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="creative-insight CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("volume", help="起量素材筛选")
    p.add_argument("--project", required=True)
    p.add_argument("--channel", default="Facebook")
    p.add_argument("--start", required=True, help="开始日期")
    p.add_argument("--end", required=True, help="结束日期")
    p.add_argument("--min-spend", type=float, default=50, help="最低日耗")

    p = sub.add_parser("winners", help="爆款素材筛选")
    p.add_argument("--project", required=True)
    p.add_argument("--channel", default="Facebook")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)

    p = sub.add_parser("tags", help="标签 × 效果交叉分析")
    p.add_argument("--project", required=True)
    p.add_argument("--channel", default="Facebook")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--metric", default="ctr", help="分析指标 (ctr/cpi/roi)")

    p = sub.add_parser("ab-face", help="A面/B面素材分类")
    p.add_argument("--project", required=True)
    p.add_argument("--channel", default="Facebook")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--top-pct", type=float, default=0.20, help="Top N%% (默认 20%%)")

    return parser.parse_args(argv)


# ═══════════════════════════════════════════════════════════════════════════
# Command handlers
# ═══════════════════════════════════════════════════════════════════════════

def _cmd_volume(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    """起量素材筛选."""
    fetch = fetchers["fetch_material_report"]
    game = game_alias_for_project(config["apps"], args.project)
    rows = fetch(game, args.channel, args.start, args.end)

    fb = config["apps"].get(args.project, {}).get("facebook", {})
    target_cpi = fb.get("target_cpi", 12.0)

    result = _volume_mod.filter_high_volume(
        rows, min_daily_spend=args.min_spend, target_cpi=target_cpi,
    )
    return {
        "command": "volume",
        "project": args.project,
        "total_rows": len(rows),
        "filtered_count": len(result),
        "creatives": result,
    }


def _cmd_winners(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    """爆款素材筛选 (M02: 累计消耗达项目×品类阈值)."""
    fetch = fetchers["fetch_material_report"]
    game = game_alias_for_project(config["apps"], args.project)
    rows = fetch(game, args.channel, args.start, args.end)

    app = config["apps"].get(args.project, {})
    winner_thresholds = app.get("winner_thresholds", {})

    result = _volume_mod.filter_winners(
        rows, project_id=args.project, winner_thresholds={args.project: winner_thresholds},
    )
    return {
        "command": "winners",
        "project": args.project,
        "total_rows": len(rows),
        "winner_count": len(result),
        "winners": result,
    }


def _cmd_tags(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    """标签 × 效果交叉分析."""
    fetch = fetchers["fetch_material_report"]
    game = game_alias_for_project(config["apps"], args.project)
    rows = fetch(game, args.channel, args.start, args.end)
    return _tag_mod.cross_analyze(rows, metric=args.metric)


def _cmd_ab_face(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    """A面/B面素材分类."""
    fetch = fetchers["fetch_material_report"]
    game = game_alias_for_project(config["apps"], args.project)
    rows = fetch(game, args.channel, args.start, args.end)
    return _tag_mod.classify_ab_face(rows, top_pct=args.top_pct)


_CMD_MAP = {
    "volume": _cmd_volume,
    "winners": _cmd_winners,
    "tags": _cmd_tags,
    "ab-face": _cmd_ab_face,
}


def run(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        config = _load_config()
        fetchers = _make_fetchers()
        result = _CMD_MAP[args.command](args, config, fetchers)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run()
