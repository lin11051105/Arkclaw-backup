"""report-reconcile CLI 入口。

用法（从项目根目录）:
    python workspace/skills/report-reconcile/scripts/cli.py <command> [options]

子命令:
    report         生成日报/周报/月报
    reconcile      月度对账 & 结算单
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_WORKSPACE = _SCRIPTS.parents[2]


_loader_spec = importlib.util.spec_from_file_location("_loader", _SCRIPTS.parents[1] / "lib" / "loader.py")
_loader = importlib.util.module_from_spec(_loader_spec); _loader_spec.loader.exec_module(_loader)
_load = _loader.make_loader(__file__)


_report_mod = _load("report_generator")
_recon_mod = _load("reconciliation")
_fetchers_mod = _load("_fetchers")

_CONFIG_DIR = _WORKSPACE / "config"
_OUTPUT_DIR = _WORKSPACE / "output" / "reports"


def _load_config() -> dict:
    apps = json.loads((_CONFIG_DIR / "apps.json").read_text(encoding="utf-8"))
    thresholds = json.loads((_CONFIG_DIR / "thresholds.json").read_text(encoding="utf-8"))
    return {"apps": apps, "thresholds": thresholds}


def _make_fetchers(command: str, args=None) -> dict:
    game = getattr(args, "project", None) if args else None
    if command == "report":
        return {
            "fetch_custom_report": _fetchers_mod.make_fetch_custom_report(game=game),
            "fetch_channel_summary": _fetchers_mod.make_fetch_channel_summary(),
        }
    if command == "reconcile":
        return {
            "fetch_insights": _fetchers_mod.make_fetch_insights(all_accounts=True),
            "fetch_custom_report": _fetchers_mod.make_fetch_custom_report(game=game),
        }
    return {}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="report-reconcile CLI")
    parser.add_argument(
        "--chat-id", default=None,
        help="飞书群 chat_id（oc_xxx）。Hermes 从 system prompt Source 行读取并传入，"
             "有则创建飞书文档并发链接到群；不传则只本地保存",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("report", help="生成日报/周报/月报")
    p.add_argument("--project", required=True)
    p.add_argument("--type", required=True, choices=["daily", "weekly", "monthly"],
                   dest="report_type")
    p.add_argument("--date", default=None, help="指定日期 YYYY-MM-DD（默认 today）")

    p = sub.add_parser("reconcile", help="月度对账 & 结算单")
    p.add_argument("--project", required=True)
    p.add_argument("--month", required=True, help="月份 YYYY-MM")
    p.add_argument("--exchange-rate", type=float, default=None, help="USD→RMB 汇率")

    return parser.parse_args(argv)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _render_report(report_data: dict) -> str:
    """Render a report-reconcile report to Markdown via Jinja2 template.

    Selects the template based on the report structure.  Falls back to a
    JSON dump when no matching template exists.
    """
    from jinja2 import Environment, FileSystemLoader

    env = Environment(
        loader=FileSystemLoader(str(_SCRIPTS.parent / "templates")),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    # Distinguish between reconciliation and daily/weekly/monthly report
    if "month" in report_data and "exchange_rate" in report_data:
        template_name = "reconciliation_report.md.j2"
    elif "report_type" in report_data and report_data["report_type"] in ("daily", "weekly", "monthly"):
        template_name = "daily_report.md.j2"
    else:
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


# ═══════════════════════════════════════════════════════════════════════════
# Command handlers
# ═══════════════════════════════════════════════════════════════════════════

def _cmd_report(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    result = _report_mod.generate_report(
        args.report_type,
        args.project,
        date_override=args.date,
        config=config,
        fetch_custom_report=fetchers["fetch_custom_report"],
        fetch_channel_summary=fetchers["fetch_channel_summary"],
    )
    ref_date = args.date or result["date_range"][0]
    file_ref, err = _save_and_upload_report(result, args.report_type, ref_date, chat_id=args.chat_id)
    result["report_doc_url"] = file_ref
    if err:
        result["report_upload_error"] = err
    return result


def _cmd_reconcile(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    result = _recon_mod.run_reconciliation(
        args.project,
        args.month,
        config=config,
        fetch_insights=fetchers["fetch_insights"],
        fetch_custom_report=fetchers["fetch_custom_report"],
        exchange_rate=args.exchange_rate,
    )
    file_ref, err = _save_and_upload_report(
        result, "reconciliation", args.month, chat_id=args.chat_id,
    )
    result["reconciliation_doc_url"] = file_ref
    if err:
        result["reconciliation_upload_error"] = err
    return result


_CMD_MAP = {
    "report": _cmd_report,
    "reconcile": _cmd_reconcile,
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
