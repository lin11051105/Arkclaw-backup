"""channel-summary CLI 入口。

用法（从项目根目录）:
    python workspace/skills/channel-summary/scripts/cli.py <command> [options]

子命令:
    channel        渠道汇总（按渠道/渠道+项目/渠道+国家维度）
    cpe            CPE 渠道点位达成率总览
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_WORKSPACE = _SCRIPTS.parents[2]
_SKILLS_ROOT = str(_SCRIPTS.parents[1])
if _SKILLS_ROOT not in sys.path:
    sys.path.insert(0, _SKILLS_ROOT)


_loader_spec = importlib.util.spec_from_file_location("_loader", _SCRIPTS.parents[1] / "lib" / "loader.py")
_loader = importlib.util.module_from_spec(_loader_spec); _loader_spec.loader.exec_module(_loader)
_load = _loader.make_loader(__file__)


_aggregator_mod = _load("channel_aggregator")
_cpe_mod = _load("cpe_achievement")
_fetchers_mod = _load("_fetchers")
from lib.fetchers import get_account_ids as _get_account_ids  # noqa: E402

_CONFIG_DIR = _WORKSPACE / "config"


def _load_config() -> dict:
    apps = json.loads((_CONFIG_DIR / "apps.json").read_text(encoding="utf-8"))
    thresholds = json.loads((_CONFIG_DIR / "thresholds.json").read_text(encoding="utf-8"))
    return {"apps": apps, "thresholds": thresholds}


def _resolve_account_ids(args: argparse.Namespace, config: dict) -> list[str] | None:
    """Priority: explicit --account-ids > apps.json facebook.accounts > env default (None)."""
    explicit = getattr(args, "account_ids", None)
    if explicit:
        return explicit
    return _get_account_ids(config, getattr(args, "project", None))


def _make_fetchers(command: str, args: argparse.Namespace, config: dict) -> dict:
    game = getattr(args, "project", None)
    if command == "channel":
        fetchers: dict = {
            "fetch_custom_report": _fetchers_mod.make_fetch_custom_report(game=game),
        }
        # iOS / both path needs SKAN fetcher; only build it when actually used.
        if getattr(args, "os", "both") in ("ios", "both"):
            game_id = getattr(args, "game_id", None)
            if game_id is None:
                raise ValueError(
                    "--os ios|both 时必须传 --game-id（SKAN 视图按 game_id 过滤）"
                )
            fetchers["fetch_skan_by_channel_day"] = (
                _fetchers_mod.make_fetch_skan_by_channel_day(game_id=int(game_id))
            )
        return fetchers
    if command == "cpe":
        account_ids = _resolve_account_ids(args, config)
        return {
            "fetch_insights": _fetchers_mod.make_fetch_insights(account_ids=account_ids),
        }
    return {}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="channel-summary CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("channel", help="渠道汇总")
    p.add_argument("--project", default=None, help="项目代号（用于 DAP 报表路由 + 兜底；不传则使用默认报表）")
    p.add_argument("--date-start", required=True, help="开始日期 YYYY-MM-DD")
    p.add_argument("--date-end", required=True, help="结束日期 YYYY-MM-DD")
    p.add_argument("--group-by", default="channel",
                   help="聚合维度: channel（渠道，media_src 表）或 country（国家，country 表）")
    p.add_argument("--os", choices=["ios", "android", "both"], default="both",
                   help="OS 拆分: ios=仅 SKAN 真值, android=仅 DAP 概率归因, both=合并（默认）")
    p.add_argument("--game-id", type=int, default=None, dest="game_id",
                   help="SKAN 视图过滤用 game_id（--os ios|both 必填，对应 hive.da_bi_dw.v_tb_skan_report_day_v2.game_id）")
    p.add_argument("--top-n", type=int, default=0,
                   help="按消耗排序后只返回前 N 行（默认 0 = 全部）。country/channel_country 维度建议传 20-30")

    p = sub.add_parser("cpe", help="CPE 达成率总览")
    p.add_argument("--project", required=True)
    p.add_argument("--month", required=True, help="月份 YYYY-MM")
    p.add_argument("--account-ids", default=None, dest="account_ids",
                   type=lambda s: [x.strip() for x in s.split(",")],
                   help="Facebook 广告账户 ID，逗号分隔（如 act_xxx,act_yyy）。不传时使用 META_AD_ACCOUNT_ID 环境变量")

    return parser.parse_args(argv)


# ═══════════════════════════════════════════════════════════════════════════
# Command handlers
# ═══════════════════════════════════════════════════════════════════════════

def _cmd_channel(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    return _aggregator_mod.run_channel_summary(
        args.date_start,
        args.date_end,
        group_by=args.group_by,
        os=args.os,
        top_n=args.top_n,
        config=config,
        fetch_custom_report=fetchers["fetch_custom_report"],
        fetch_skan_by_channel_day=fetchers.get("fetch_skan_by_channel_day"),
        game_id=getattr(args, "game_id", None),
    )


def _cmd_cpe(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    return _cpe_mod.check_cpe_achievement(
        args.project,
        args.month,
        config=config,
        fetch_insights=fetchers["fetch_insights"],
    )


_CMD_MAP = {
    "channel": _cmd_channel,
    "cpe": _cmd_cpe,
}


def run(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        config = _load_config()
        fetchers = _make_fetchers(args.command, args, config)
        result = _CMD_MAP[args.command](args, config, fetchers)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run()
