"""creative-lifecycle CLI 入口。

用法（从项目根目录）:
    python workspace/skills/creative-lifecycle/scripts/cli.py <command> [options]

子命令:
    creative-health    素材衰退+爆款+库存评估
    scale-candidates   扩量候选评估
    upload-creative    纯素材上传（命名校验+上传文件→creative_id）
    create-ads         纯广告搭建（Campaign→AdSet→Ad，需提供 creative_id）
    summary            素材数据汇总
    short-name         素材短名规则数据汇总
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import importlib.util

_SCRIPTS = Path(__file__).resolve().parent
_WORKSPACE = _SCRIPTS.parents[2]


_loader_spec = importlib.util.spec_from_file_location("_loader", _SCRIPTS.parents[1] / "lib" / "loader.py")
_loader = importlib.util.module_from_spec(_loader_spec); _loader_spec.loader.exec_module(_loader)
_load = _loader.make_loader(__file__)


_health_mod = _load("creative_health")
_scale_mod = _load("scale_candidates")
_upload_mod = _load("upload_pipeline")
_summary_mod = _load("material_summary")
_short_name_mod = _load("short_name_summary")
_fetchers_mod = _load("_fetchers")

_CONFIG_DIR = _WORKSPACE / "config"
_OUTPUT_DIR = _WORKSPACE / "output" / "reports"


def _load_config() -> dict:
    """Load and merge config files into a single dict."""
    apps = json.loads((_CONFIG_DIR / "apps.json").read_text(encoding="utf-8"))
    thresholds = json.loads((_CONFIG_DIR / "thresholds.json").read_text(encoding="utf-8"))
    naming_rules = json.loads((_CONFIG_DIR / "naming-rules.json").read_text(encoding="utf-8"))
    return {"apps": apps, "thresholds": thresholds, "naming_rules": naming_rules}


def _make_fetchers(command: str, args=None, config: dict | None = None) -> dict:
    """Build the callback dict needed by the target command."""
    if command == "creative-health":
        return {
            "fetch_active_ads": _fetchers_mod.make_fetch_active_ads(),
            "fetch_material_daily": _fetchers_mod.make_fetch_material_daily(),
            "fetch_country_report": _fetchers_mod.make_fetch_country_report(),
        }
    if command == "scale-candidates":
        return {"fetch_material_report": _fetchers_mod.make_fetch_material_report()}
    if command == "upload-creative":
        return {
            "upload_creative_fn": _fetchers_mod.make_upload_creative_fn(),
        }
    if command == "create-ads":
        project_id = args.project if args is not None else ""
        os_type = args.os if args is not None else "iOS"
        return {
            "create_campaign_fn": _fetchers_mod.make_create_campaign_fn(),
            "create_adset_fn": _fetchers_mod.make_create_adset_fn(),
            "create_ad_fn": _fetchers_mod.make_create_ad_fn(),
            "ensure_creative_fn": _fetchers_mod.make_ensure_creative_fn(),
            "upload_creative_fn": _fetchers_mod.make_upload_creative_fn(),
            "create_ad_creative_fn": _fetchers_mod.make_create_ad_creative_fn(
                project_id=project_id,
                os_type=os_type,
                config=config or {},
            ),
        }
    if command == "summary":
        return {"fetch_material_report": _fetchers_mod.make_fetch_material_report()}
    if command == "short-name":
        return {"fetch_material_report": _fetchers_mod.make_fetch_material_report()}
    return {}


def parse_countries(raw: str) -> list[str]:
    """Split comma-separated country string into list."""
    return [c.strip() for c in raw.split(",") if c.strip()]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments. Exposed for testing."""
    parser = argparse.ArgumentParser(description="creative-lifecycle CLI")
    parser.add_argument(
        "--chat-id", default=None,
        help="飞书群 chat_id（oc_xxx）。Hermes 从 system prompt Source 行读取并传入，"
             "有则创建飞书文档并发链接到群；不传则只本地保存",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # creative-health
    p = sub.add_parser("creative-health", help="素材衰退+爆款+库存评估")
    p.add_argument("--project", required=True, help="项目代号: ROK, PTSLG, IGAME")
    p.add_argument("--date", required=True, help="评估日期 YYYY-MM-DD")
    p.add_argument("--mode", default="all", choices=["all", "decay", "winner"], help="评估模式")

    # scale-candidates
    p = sub.add_parser("scale-candidates", help="扩量候选评估")
    p.add_argument("--project", required=True)
    p.add_argument("--date", required=True, help="评估日期 YYYY-MM-DD")

    # upload-creative (纯素材上传)
    p = sub.add_parser("upload-creative", help="纯素材上传（命名校验+上传→creative_id）")
    p.add_argument("--name", required=True, help="素材名称")
    p.add_argument("--file-url", required=True, help="素材文件 URL 或本地路径")
    p.add_argument("--asset-type", required=True, choices=["video", "image"], help="素材类型")
    p.add_argument("--os", required=True, choices=["iOS", "Android"], help="操作系统")
    p.add_argument("--project", required=True)

    # create-ads (广告搭建，支持两种模式)
    p = sub.add_parser("create-ads", help="广告搭建（Campaign→AdSet→Ad），支持传 creative-id 或直接传素材文件")
    p.add_argument("--name", required=True, help="素材名称")
    p.add_argument("--creative-id", default=None, help="已有的 creative ID（与 --file-url 二选一）")
    p.add_argument("--file-url", default=None, help="素材文件 URL 或本地路径（与 --creative-id 二选一，自动上传+创建 Creative）")
    p.add_argument("--asset-type", default=None, choices=["video", "image"], help="素材类型（传 --file-url 时必填）")
    p.add_argument("--budget", default=None, type=float,
                   help="Campaign 日预算 USD（CBO 模式，默认）。与 --adset-budget 二选一")
    p.add_argument("--adset-budget", default=None, type=float,
                   help="AdSet 日预算 USD（ABO 模式）。与 --budget 二选一")
    p.add_argument("--countries", required=True, help="逗号分隔: US,JP")
    p.add_argument("--audience", required=True, help="受众: Broad / Lookalike / ...")
    p.add_argument("--os", required=True, choices=["iOS", "Android"], help="操作系统")
    p.add_argument("--project", required=True)
    # Campaign optional overrides
    p.add_argument("--campaign-name", default=None, help="覆盖自动生成的 Campaign 名称")
    p.add_argument("--objective", default="OUTCOME_APP_PROMOTION",
                   help="Campaign 广告目标（默认 OUTCOME_APP_PROMOTION）")
    p.add_argument("--campaign-status", default="PAUSED", choices=["PAUSED", "ACTIVE"],
                   help="Campaign 初始状态（默认 PAUSED）")
    # AdSet optional overrides
    p.add_argument("--optimization-goal", default="APP_INSTALLS",
                   help="AdSet 优化目标（默认 APP_INSTALLS）")
    p.add_argument("--billing-event", default="IMPRESSIONS",
                   help="AdSet 计费事件（默认 IMPRESSIONS）")
    p.add_argument("--bid-strategy", default=None,
                   choices=["LOWEST_COST_WITHOUT_CAP", "LOWEST_COST_WITH_BID_CAP", "COST_CAP"],
                   help="AdSet 出价策略（不填则使用账户默认）")
    p.add_argument("--bid-amount", default=None, type=float,
                   help="出价上限 USD（bid-strategy=COST_CAP 时使用）")
    p.add_argument("--adset-status", default="PAUSED", choices=["PAUSED", "ACTIVE"],
                   help="AdSet 初始状态（默认 PAUSED）")

    # summary
    p = sub.add_parser("summary", help="素材数据汇总")
    p.add_argument("--project", required=True)
    p.add_argument("--date-start", required=True, help="开始日期 YYYY-MM-DD")
    p.add_argument("--date-end", required=True, help="结束日期 YYYY-MM-DD")

    # short-name
    p = sub.add_parser("short-name", help="素材短名规则数据汇总")
    p.add_argument("--project", required=True)
    p.add_argument("--date-start", required=True, help="开始日期 YYYY-MM-DD")
    p.add_argument("--date-end", required=True, help="结束日期 YYYY-MM-DD")

    return parser.parse_args(argv)


# ═══════════════════════════════════════════════════════════════════════════
# Command handlers
# ═══════════════════════════════════════════════════════════════════════════

def _render_report(report_data: dict) -> str:
    """Render a creative-lifecycle report to Markdown via Jinja2 template.

    Selects the template based on ``report_data["report_type"]``.  Falls back
    to a JSON dump when no matching template exists.
    """
    from jinja2 import Environment, FileSystemLoader

    env = Environment(
        loader=FileSystemLoader(str(_SCRIPTS.parent / "templates")),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template_map = {
        "creative_decay": "decay_report.md.j2",
        "winner_creative": "winner_report.md.j2",
        "scale_candidate": "scale_report.md.j2",
        "material_summary": "summary_report.md.j2",
        "short_name_summary": "short_name_report.md.j2",
    }
    report_type = report_data.get("report_type", "")
    template_name = template_map.get(report_type)
    if not template_name:
        return json.dumps(report_data, ensure_ascii=False, indent=2)
    template = env.get_template(template_name)
    return template.render(**report_data)


def _save_and_upload_report(
    report_data: dict, report_name: str, date: str,
    *,
    chat_id: str | None = None,
) -> tuple[str, str | None]:
    """报告持久化 + 飞书上传，委托 lib/feishu.save_and_upload_report。"""
    _feishu_path = _SCRIPTS.parents[1] / "lib" / "feishu.py"
    _feishu_spec = importlib.util.spec_from_file_location("feishu", _feishu_path)
    _feishu_mod = importlib.util.module_from_spec(_feishu_spec)
    _feishu_spec.loader.exec_module(_feishu_mod)
    return _feishu_mod.save_and_upload_report(
        report_data, report_name, date,
        output_dir=_OUTPUT_DIR, chat_id=chat_id,
        render_fn=_render_report,
    )


def _cmd_creative_health(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    result = _health_mod.run_creative_health(
        project_id=args.project,
        date=args.date,
        mode=args.mode,
        config=config,
        fetch_active_ads=fetchers["fetch_active_ads"],
        fetch_material_daily=fetchers["fetch_material_daily"],
        fetch_country_report=fetchers["fetch_country_report"],
    )

    for report_key, report_name in [("decay_report", "decay"), ("winner_report", "winner")]:
        if report_key not in result:
            continue
        file_ref, err = _save_and_upload_report(result[report_key], report_name, args.date, chat_id=args.chat_id)
        result[f"{report_key}_doc_url"] = file_ref
        if err:
            result[f"{report_key}_upload_error"] = err

    return result


def _cmd_scale_candidates(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    result = _scale_mod.run_scale_candidates(
        project_id=args.project,
        date=args.date,
        config=config,
        fetch_material_report=fetchers["fetch_material_report"],
    )
    file_ref, err = _save_and_upload_report(result, "scale", args.date, chat_id=args.chat_id)
    result["scale_report_doc_url"] = file_ref
    if err:
        result["scale_report_upload_error"] = err
    return result


def _cmd_upload_creative(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    return _upload_mod.do_upload_creative(
        name=args.name,
        file_url=args.file_url,
        asset_type=args.asset_type,
        os_type=args.os,
        project_id=args.project,
        config=config,
        upload_creative_fn=fetchers["upload_creative_fn"],
    )


def _cmd_create_ads(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    creative_id = args.creative_id
    file_url = getattr(args, "file_url", None)
    asset_type = getattr(args, "asset_type", None)
    budget = getattr(args, "budget", None)
    adset_budget = getattr(args, "adset_budget", None)

    # Budget mode validation (let validate_params handle details)
    if budget is None and adset_budget is None:
        return {"status": "error", "error": "必须传 --budget（CBO，Campaign 预算）或 --adset-budget（ABO，AdSet 预算）之一"}

    # Collect optional override kwargs shared by both modes
    overrides = dict(
        campaign_name=getattr(args, "campaign_name", None),
        campaign_objective=getattr(args, "objective", "OUTCOME_APP_PROMOTION"),
        campaign_status=getattr(args, "campaign_status", "PAUSED"),
        optimization_goal=getattr(args, "optimization_goal", "APP_INSTALLS"),
        billing_event=getattr(args, "billing_event", "IMPRESSIONS"),
        bid_strategy=getattr(args, "bid_strategy", None),
        bid_amount=getattr(args, "bid_amount", None),
        adset_status=getattr(args, "adset_status", "PAUSED"),
    )

    # Mode 1: file-url provided → full pipeline (upload + create creative + build ads)
    if file_url:
        if not asset_type:
            return {"status": "error", "error": "传 --file-url 时必须同时传 --asset-type (video/image)"}
        return _upload_mod.run_upload_pipeline(
            name=args.name,
            budget=budget,
            adset_budget=adset_budget,
            countries=parse_countries(args.countries),
            audience=args.audience,
            os_type=args.os,
            file_url=file_url,
            asset_type=asset_type,
            project_id=args.project,
            config=config,
            upload_creative_fn=fetchers["upload_creative_fn"],
            create_ad_creative_fn=fetchers["create_ad_creative_fn"],
            create_campaign_fn=fetchers["create_campaign_fn"],
            create_adset_fn=fetchers["create_adset_fn"],
            create_ad_fn=fetchers["create_ad_fn"],
            **overrides,
        )

    # Mode 2: creative-id provided → build ads with existing creative (auto platform adapt)
    if creative_id:
        return _upload_mod.do_build_ad_structure(
            name=args.name,
            creative_id=creative_id,
            budget=budget,
            adset_budget=adset_budget,
            countries=parse_countries(args.countries),
            audience=args.audience,
            os_type=args.os,
            project_id=args.project,
            config=config,
            create_campaign_fn=fetchers["create_campaign_fn"],
            create_adset_fn=fetchers["create_adset_fn"],
            create_ad_fn=fetchers["create_ad_fn"],
            ensure_creative_fn=fetchers["ensure_creative_fn"],
            **overrides,
        )

    return {"status": "error", "error": "必须传 --creative-id 或 --file-url 之一"}


def _cmd_summary(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    result = _summary_mod.run_material_summary(
        project_id=args.project,
        date_start=args.date_start,
        date_end=args.date_end,
        config=config,
        fetch_material_report=fetchers["fetch_material_report"],
    )
    report_name = f"summary-{args.date_start}_{args.date_end}"
    file_ref, err = _save_and_upload_report(result, report_name, args.date_start, chat_id=args.chat_id)
    result["summary_report_doc_url"] = file_ref
    if err:
        result["summary_report_upload_error"] = err
    return result


def _cmd_short_name(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    result = _short_name_mod.run_short_name_summary(
        project_id=args.project,
        date_start=args.date_start,
        date_end=args.date_end,
        config=config,
        fetch_material_report=fetchers["fetch_material_report"],
    )
    report_name = f"short-name-{args.date_start}_{args.date_end}"
    file_ref, err = _save_and_upload_report(result, report_name, args.date_start, chat_id=args.chat_id)
    result["short_name_report_doc_url"] = file_ref
    if err:
        result["short_name_report_upload_error"] = err
    return result


_CMD_MAP = {
    "creative-health": _cmd_creative_health,
    "scale-candidates": _cmd_scale_candidates,
    "upload-creative": _cmd_upload_creative,
    "create-ads": _cmd_create_ads,
    "summary": _cmd_summary,
    "short-name": _cmd_short_name,
}


# ═══════════════════════════════════════════════════════════════════════════
# run — main entry point (testable)
# ═══════════════════════════════════════════════════════════════════════════

def run(argv: list[str] | None = None) -> None:
    """Parse args, load config, build fetchers, execute command, print JSON."""
    args = parse_args(argv)
    try:
        config = _load_config()
        fetchers = _make_fetchers(args.command, args=args, config=config)
        result = _CMD_MAP[args.command](args, config, fetchers)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run()
