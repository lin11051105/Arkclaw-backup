"""monitoring-alerts CLI 入口。

用法（从项目根目录）:
    python workspace/skills/monitoring-alerts/scripts/cli.py <command> [options]

子命令:
    balance               账户余额 + 当日消耗进度（同一 JSON：根级余额 + spend_progress）
    data-gap              前端/DAP 数据 Gap 预警
    postback-continuity   DAP 分日回传连续性
    roi-progress          回本进度预警
    daily          日常投放数据监控（昨日 vs 7d/30d 基线）
    trend          大盘趋势预警（CPM/ROI 趋势 + 素材批量疲劳）
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import date as _date, timedelta as _td
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILLS_ROOT = str(_SCRIPTS.parents[1])
if _SKILLS_ROOT not in sys.path:
    sys.path.insert(0, _SKILLS_ROOT)

_WORKSPACE = _SCRIPTS.parents[2]


_loader_spec = importlib.util.spec_from_file_location("_loader", _SCRIPTS.parents[1] / "lib" / "loader.py")
_loader = importlib.util.module_from_spec(_loader_spec); _loader_spec.loader.exec_module(_loader)
_load = _loader.make_loader(__file__)


_balance_mod = _load("balance_checker")
_gap_mod = _load("gap_checker")
_roi_mod = _load("roi_progress")
_daily_mod = _load("daily_monitor")
_trend_mod = _load("trend_detector")
_fetchers_mod = _load("_fetchers")
from lib.fetchers import get_account_ids as _get_account_ids  # noqa: E402

_CONFIG_DIR = _WORKSPACE / "config"


def _load_config() -> dict:
    apps = json.loads((_CONFIG_DIR / "apps.json").read_text(encoding="utf-8"))
    thresholds = json.loads((_CONFIG_DIR / "thresholds.json").read_text(encoding="utf-8"))
    return {"apps": apps, "thresholds": thresholds}


def _resolve_balance_account_ids(args, config: dict) -> list[str] | None:
    """For 'balance': explicit --account-id > apps.json facebook.accounts > env default."""
    explicit = getattr(args, "account_id", None) if args else None
    if explicit:
        return [explicit]
    project = getattr(args, "project", None) if args else None
    return _get_account_ids(config, project)


def _make_fetchers(command: str, args=None, config: dict | None = None) -> dict:
    game = getattr(args, "project", None) if args else None
    cfg = config or {}
    if command == "balance":
        account_ids = _resolve_balance_account_ids(args, cfg)
        # fetch_account_info still takes a single id; use first resolved or None
        first_id = account_ids[0] if account_ids else None
        return {
            "fetch_account_info": _fetchers_mod.make_fetch_account_info(account_id=first_id),
            "fetch_insights": _fetchers_mod.make_fetch_insights(account_ids=account_ids),
        }
    if command == "postback-continuity":
        return {
            "fetch_custom_report": _fetchers_mod.make_fetch_custom_report(game=game),
        }
    if command == "data-gap":
        all_ids = _fetchers_mod._list_all_account_ids()
        return {
            "fetch_custom_report": _fetchers_mod.make_fetch_custom_report(game=game),
            "fetch_insights": _fetchers_mod.make_fetch_insights(account_ids=all_ids),
        }
    if command == "roi-progress":
        return {
            "fetch_custom_report": _fetchers_mod.make_fetch_custom_report(game=game),
        }
    if command == "daily":
        os_arg = getattr(args, "os", "android") if args else "android"
        result: dict = {
            "fetch_insights": _fetchers_mod.make_fetch_insights(),
        }
        # iOS path (and "both") needs SKAN by-game fetcher. Resolve game_id from
        # apps.json[project].game_id; fail fast with ValueError if absent so
        # operators see a clear config error at factory time rather than a
        # confusing KeyError deep inside _cmd_daily (F-03).
        if os_arg in ("ios", "both"):
            project_name = getattr(args, "project", "") or ""
            project_cfg = (cfg.get("apps") or {}).get(project_name, {})
            game_id = project_cfg.get("game_id")
            if game_id is None:
                raise ValueError(
                    f"--os={os_arg} requires apps.json[{project_name!r}].game_id "
                    f"to be set; cannot fetch SKAN data without a game_id. "
                    f"Add the missing key to workspace/config/apps.json."
                )
            result["fetch_skan_by_game_day"] = (
                _fetchers_mod.make_fetch_skan_by_game_day(int(game_id))
            )
        return result
    if command == "trend":
        return {
            "fetch_insights": _fetchers_mod.make_fetch_insights(),
            "fetch_material_report": _fetchers_mod.make_fetch_material_report(),
        }
    return {}


_OUTPUT_DIR = _WORKSPACE / "memory" / "monitoring-reports"


def _save_and_upload_report(
    report_data: dict, report_name: str, date: str,
    *,
    chat_id: str | None = None,
) -> tuple[str | None, str | None]:
    _feishu_path = _SCRIPTS.parents[1] / "lib" / "feishu.py"
    _feishu_spec = importlib.util.spec_from_file_location("feishu", _feishu_path)
    _feishu_mod = importlib.util.module_from_spec(_feishu_spec)
    _feishu_spec.loader.exec_module(_feishu_mod)
    return _feishu_mod.save_and_upload_report(
        report_data, report_name, date,
        output_dir=_OUTPUT_DIR, chat_id=chat_id,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="monitoring-alerts CLI")
    parser.add_argument("--chat-id", default=None, help="飞书群 chat_id，有则生成飞书文档")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("balance", help="账户余额 & 消耗进度预警（同条 JSON：balance + spend_progress）")
    p.add_argument("--project", required=True)
    p.add_argument("--account-id", default=None, help="指定账户 ID（默认 .env 中的主力账户）")
    p.add_argument("--all", action="store_true", help="遍历所有 Active 账户汇总输出")

    _yesterday = (_date.today() - _td(days=1)).isoformat()

    p = sub.add_parser("data-gap", help="前端/DAP 数据 Gap 预警")
    p.add_argument("--project", required=True)
    p.add_argument("--date", default=_yesterday, help="检测日期 YYYY-MM-DD（默认昨天）")

    p = sub.add_parser("postback-continuity", help="DAP 分日回传连续性")
    p.add_argument("--project", required=True)
    p.add_argument("--end-date", default=_yesterday, help="区间结束日 YYYY-MM-DD（默认昨天）")
    p.add_argument("--days", type=int, default=3, help="回溯天数（默认 3）")

    p = sub.add_parser("roi-progress", help="回本进度预警")
    p.add_argument("--project", required=True)
    p.add_argument("--channel", default="Facebook")
    p.add_argument("--date", default=_yesterday, help="开始日期 YYYY-MM-DD（默认昨天）")
    p.add_argument("--date-end", default=None, help="结束日期 YYYY-MM-DD（传了则查区间聚合，如本月进度）")
    p.add_argument("--month", default=None, help="月份 YYYY-MM（自动展开为月初~昨天，用于本月回本进度）")
    p.add_argument(
        "--os", choices=["ios", "android", "both"], default="android",
        help="OS 路径：ios 走 SKAN 真值，android 走 DAP 概率归因（默认 android）",
    )

    p = sub.add_parser("daily", help="日常投放数据监控（昨日 vs 7d/30d 基线）")
    p.add_argument("--project", required=True)
    p.add_argument("--date", default=_yesterday, help="检测日期 YYYY-MM-DD（默认昨天）")
    p.add_argument(
        "--os", choices=["ios", "android", "both"], default="android",
        help="OS 路径：ios 走 SKAN 真值（72h postback 延迟门禁），android 走 DAP（默认 android）",
    )

    p = sub.add_parser("trend", help="大盘趋势预警（CPM/ROI 趋势 + 素材批量疲劳）")
    p.add_argument("--project", required=True)
    p.add_argument("--days", type=int, default=14, help="检测天数（默认 14）")

    return parser.parse_args(argv)


# ═══════════════════════════════════════════════════════════════════════════
# Command handlers
# ═══════════════════════════════════════════════════════════════════════════

def _cmd_balance(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    """余额 + 当日消耗进度。支持 --all 遍历所有 Active 账户。"""
    if getattr(args, "all", False):
        all_ids = _fetchers_mod._list_all_account_ids()
        accounts: list[dict] = []
        total_balance = 0.0
        total_daily_spend = 0.0
        all_alerts: list[dict] = []
        for aid in all_ids:
            info_fn = _fetchers_mod.make_fetch_account_info(account_id=aid)
            insights_fn = _fetchers_mod.make_fetch_insights(account_ids=[aid])
            bal = _balance_mod.check_account_balance(
                args.project, config=config,
                fetch_account_info=info_fn, fetch_insights=insights_fn,
            )
            total_balance += bal.get("balance", 0.0)
            total_daily_spend += bal.get("daily_avg_spend_7d", 0.0)
            all_alerts.extend(bal.get("alerts", []))
            accounts.append({
                "account_id": aid,
                "account_name": bal.get("account_name", ""),
                "balance": bal.get("balance", 0.0),
                "daily_avg_spend_7d": bal.get("daily_avg_spend_7d", 0.0),
                "balance_days": bal.get("balance_days", 0.0),
                "alerts": bal.get("alerts", []),
            })
        balance_days = total_balance / total_daily_spend if total_daily_spend > 0 else 999.0
        return {
            "project_id": args.project,
            "mode": "all_accounts",
            "total_balance": round(total_balance, 2),
            "total_daily_avg_spend": round(total_daily_spend, 2),
            "total_balance_days": round(balance_days, 1),
            "account_count": len(accounts),
            "accounts": accounts,
            "alerts": all_alerts,
        }

    bal = _balance_mod.check_account_balance(
        args.project,
        config=config,
        fetch_account_info=fetchers["fetch_account_info"],
        fetch_insights=fetchers["fetch_insights"],
    )
    spend = _balance_mod.check_spend_progress(
        args.project,
        config=config,
        fetch_insights=fetchers["fetch_insights"],
    )
    bal["spend_progress"] = spend
    return bal


def _cmd_data_gap(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    return _gap_mod.check_data_gap(
        args.project,
        args.date,
        config=config,
        fetch_custom_report=fetchers["fetch_custom_report"],
        fetch_insights=fetchers["fetch_insights"],
    )


def _cmd_postback_continuity(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    return _gap_mod.check_postback_continuity(
        args.project,
        end_date=args.end_date,
        days=args.days,
        config=config,
        fetch_custom_report=fetchers["fetch_custom_report"],
    )


def _cmd_roi_progress(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    start = args.date
    end = getattr(args, "date_end", None)
    month = getattr(args, "month", None)
    if month and not end:
        start = f"{month}-01"
        end = (_date.today() - _td(days=1)).isoformat()
    os_arg = getattr(args, "os", "android")
    return _roi_mod.check_roi_progress(
        args.project,
        args.channel,
        start,
        config=config,
        fetch_custom_report=fetchers["fetch_custom_report"],
        date_end=end,
        os=os_arg,
    )


def _insights_row_to_metrics(row: dict) -> dict[str, float]:
    """Convert a raw insights row to spend/cpi/ctr/cvr metrics."""
    spend = float(row.get("spend", 0))
    imps = int(row.get("impressions", 0))
    clicks = int(row.get("clicks", 0))
    installs = int(row.get("installs", 0))
    return {
        "spend": spend,
        "cpi": spend / installs if installs > 0 else 0,
        "ctr": clicks / imps if imps > 0 else 0,
        "cvr": installs / clicks if clicks > 0 else 0,
    }


def _skan_row_to_metrics(row: dict) -> dict[str, float]:
    """Convert a SKAN view row to spend/cpi/ctr/cvr metrics.

    SKAN has no impression/click signal, so ``ctr`` and ``cvr`` are always 0
    (the ctr_drop / cvr_drop alerts are then naturally suppressed in
    :func:`daily_monitor.check_daily_metrics` because their baselines are
    also zero).
    """
    spend = float(row.get("cost") or 0)
    installs = float(row.get("sk_install") or 0)
    return {
        "spend": spend,
        "cpi": (spend / installs) if installs > 0 else 0,
        "ctr": 0.0,
        "cvr": 0.0,
    }


def _avg_metrics(metrics: list[dict[str, float]], n: int) -> dict[str, float]:
    """Average the last *n* entries of a metrics list."""
    subset = metrics[-n:] if len(metrics) >= n else metrics
    if not subset:
        return {"spend": 0, "cpi": 0, "ctr": 0, "cvr": 0}
    return {
        k: sum(m[k] for m in subset) / len(subset)
        for k in ("spend", "cpi", "ctr", "cvr")
    }


_SKAN_GRACE_DAYS = 3  # iOS SKAN postback delay (~72h) — see thresholds.skan


def _should_skip_for_skan_delay(
    *,
    date_obj,
    today,
    project_id: str,
) -> dict | None:
    """Pure SKAN 72h-delay guard predicate (F-02 — testable without clock mocks).

    Returns the canonical skip-result dict when ``today - date_obj < 3 days``
    (Apple buckets SKAN postbacks for ~72h after install, so any iOS query
    whose end-date is within 3 days of today is incomplete data).
    Returns ``None`` when the window has settled and the SKAN fetcher should
    proceed.

    Args:
        date_obj: ``datetime.date`` representing the query end-date
            (i.e. ``args.date`` parsed).
        today: ``datetime.date`` representing "now" — accepted as a parameter
            so callers (tests included) supply it explicitly. Production
            callers pass ``datetime.now().date()``.
        project_id: Echoed onto the skip result for traceability.

    Returns:
        ``{"skipped": True, "reason": ..., "min_query_date": <today-3>,
        "project_id": project_id, "os": "ios"}`` when within grace; ``None``
        otherwise.
    """
    from datetime import timedelta

    delta_days = (today - date_obj).days
    if delta_days < _SKAN_GRACE_DAYS:
        return {
            "skipped": True,
            "reason": "iOS SKAN postback delay 72h: query window too recent",
            "min_query_date": (today - timedelta(days=_SKAN_GRACE_DAYS)).isoformat(),
            "project_id": project_id,
            "os": "ios",
        }
    return None


def _cmd_daily(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    """日常监控：昨日指标 vs 7d/30d 基线。

    OS routing (T7.5):
      - ``--os ios``: 走 SKAN 真值路径（``fetch_skan_by_game_day``），
        72h postback 延迟门禁先于任何 fetcher 执行；指标列从 SKAN 列名
        派生（``cost`` → spend, ``sk_install`` → installs, ctr/cvr 缺信号
        固定为 0）。
      - 默认 ``--os android``：保留原 DAP/Insights 行为不变。
    """
    from datetime import datetime, timedelta

    os_arg = getattr(args, "os", "android")
    date_obj = datetime.strptime(args.date, "%Y-%m-%d").date()
    today = datetime.now().date()

    # iOS 72h SKAN postback delay guard. Pure predicate — see
    # _should_skip_for_skan_delay docstring. Tests cover the predicate
    # directly with synthetic dates; this call site just wires today.
    if os_arg == "ios":
        skip_result = _should_skip_for_skan_delay(
            date_obj=date_obj, today=today, project_id=args.project,
        )
        if skip_result is not None:
            return skip_result

    start = (date_obj - timedelta(days=30)).isoformat()

    if os_arg == "ios":
        skan_fetcher = fetchers["fetch_skan_by_game_day"]
        rows = skan_fetcher(date_start=start, date_end=args.date)
        rows = sorted(rows, key=lambda r: r.get("third_dt", ""))
        all_metrics = [_skan_row_to_metrics(r) for r in rows]
    else:
        rows = fetchers["fetch_insights"](
            date_start=start, date_end=args.date, level="account", time_increment=1,
        )
        rows.sort(key=lambda r: r.get("date_start", ""))
        all_metrics = [_insights_row_to_metrics(r) for r in rows]

    if not all_metrics:
        return {
            "status": "ok",
            "project_id": args.project,
            "os": os_arg,
            "metrics": {},
            "alerts": [],
        }

    yesterday = all_metrics[-1]
    history = all_metrics[:-1]

    return _daily_mod.check_daily_metrics(
        args.project,
        yesterday=yesterday,
        baseline_7d=_avg_metrics(history, 7),
        baseline_30d=_avg_metrics(history, 30),
        thresholds=config["thresholds"],
        os=os_arg,
    )


def _cmd_trend(args: argparse.Namespace, config: dict, fetchers: dict) -> dict:
    """大盘趋势预警：CPM/ROI 趋势 + 素材批量疲劳。"""
    from datetime import datetime, timedelta

    today = datetime.now()
    start = (today - timedelta(days=args.days)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")

    rows = fetchers["fetch_insights"](
        date_start=start, date_end=end, level="account", time_increment=1,
    )
    rows.sort(key=lambda r: r.get("date_start", ""))

    daily_cpms: list[float] = []
    daily_rois: list[float] = []
    for r in rows:
        spend = float(r.get("spend", 0))
        imps = int(r.get("impressions", 0))
        daily_cpms.append((spend / imps * 1000) if imps > 0 else 0)
        daily_rois.append(float(r.get("roi", 0)))

    from lib.fetchers import game_alias_for_project

    game = game_alias_for_project(config["apps"], args.project)
    material_rows = fetchers["fetch_material_report"](
        game, "Facebook", start=start, end=end,
    )
    creatives = [
        {"id": m.get("material_id", ""), "ctr_trend": m["ctr_by_day"]}
        for m in material_rows
        if m.get("ctr_by_day")
    ]

    return _trend_mod.run_trend_detection(
        project_id=args.project,
        daily_cpms=daily_cpms,
        daily_rois=daily_rois,
        creatives=creatives,
        thresholds=config["thresholds"],
    )


_CMD_MAP = {
    "balance": _cmd_balance,
    "data-gap": _cmd_data_gap,
    "postback-continuity": _cmd_postback_continuity,
    "roi-progress": _cmd_roi_progress,
    "daily": _cmd_daily,
    "trend": _cmd_trend,
}


def run(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        config = _load_config()
        fetchers = _make_fetchers(args.command, args=args, config=config)
        result = _CMD_MAP[args.command](args, config, fetchers)

        chat_id = getattr(args, "chat_id", None)
        if chat_id:
            ref_date = getattr(args, "date", None) or _date.today().isoformat()
            project = getattr(args, "project", "unknown")
            report_name = f"{args.command}-{project}"
            doc_url, err = _save_and_upload_report(
                result, report_name, ref_date, chat_id=chat_id,
            )
            result["doc_url"] = doc_url
            if err:
                result["doc_upload_error"] = err

        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run()
