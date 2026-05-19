"""sentiment-daily-report CLI 入口.

用法（项目根目录）::

    python workspace/skills/sentiment-daily-report/scripts/cli.py generate \
        --product Pgame [--from-fixture] [--dry-run]

    python workspace/skills/sentiment-daily-report/scripts/cli.py publish \
        --product Pgame --report-path /path/to/report.json --chat-id <name>

子命令:
    generate    采集 24h 评论 → 分类 → 生成 5 模块报告（默认打印到 stdout）
    publish     读取已生成的报告 → 飞书发送 + 持久化
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_log = logging.getLogger(__name__)

# ── Loader bootstrap ─────────────────────────────────────────
_SCRIPTS = Path(__file__).resolve().parent
_loader_spec = importlib.util.spec_from_file_location(
    "_loader",
    _SCRIPTS.parents[1] / "lib" / "loader.py",
)
if _loader_spec is None or _loader_spec.loader is None:
    raise RuntimeError(f"Failed to load skill loader from {_SCRIPTS.parents[1] / 'lib' / 'loader.py'}")
_loader = importlib.util.module_from_spec(_loader_spec)
_loader_spec.loader.exec_module(_loader)
_load = _loader.make_loader(__file__)


# Lazy module loaders — keep import-time cost low and dodge optional deps
def _config():
    return _load("config")


def _types():
    return _load("models")


def _comment_fetcher():
    return _load("comment_fetcher")


def _classifier():
    return _load("sentiment_classifier")


def _report_gen():
    return _load("report_generator")


def _publisher():
    return _load("feishu_publisher")


def _tracking_store():
    return _load("tracking_store")


def _dap_material():
    return _load("dap_material")


def _sentiment_cache():
    return _load("sentiment_cache")


# ── Argparse ─────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "sentiment-daily-report — Pgame 广告舆情日报 (FB)"
        )
    )
    parser.add_argument(
        "--chat-id", default=None,
        help="飞书群 chat_id（oc_xxx）。Hermes 从 system prompt Source 行读取并传入，"
             "有则创建飞书文档并发链接到群；不传则 fallback 到 FEISHU_CHAT_ID 环境变量",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # generate
    p_gen = sub.add_parser(
        "generate",
        help="采集 24h FB 评论 → 分类 → 输出 5 模块 JSON 报告",
    )
    p_gen.add_argument("--product", default="Pgame", help="产品名（仅支持 Pgame）")
    p_gen.add_argument(
        "--from-fixture",
        action="store_true",
        help="跳过 FB 实时拉取，使用 fixtures/sample_comments.json (CI/dry-run)",
    )
    p_gen.add_argument(
        "--dry-run",
        action="store_true",
        help="仅生成 JSON 打印到 stdout，不写 memory/、不发飞书",
    )
    p_gen.add_argument(
        "--output-dir",
        default=None,
        help="覆盖默认输出目录 workspace/memory/sentiment-reports/",
    )

    # publish
    p_pub = sub.add_parser(
        "publish",
        help="读取已生成报告并发送到飞书群",
    )
    p_pub.add_argument("--product", default="Pgame")
    p_pub.add_argument("--report-path", required=True)
    p_pub.add_argument(
        "--chat-id",
        required=True,
        help="飞书群 chat_id 或群名（FeishuClient 自动解析）",
    )
    p_pub.add_argument("--dry-run", action="store_true")

    return parser.parse_args(argv)


# ── Commands ─────────────────────────────────────────────────


def _finalize_degradation(diagnostics: dict) -> dict | None:
    """Compact a diagnostics envelope for ``meta.degradation_flag``.

    Returns ``None`` when no degradation events were recorded, so the
    happy-path JSON stays clean (schema accepts ``object|null``).
    """
    if not diagnostics or not diagnostics.get("is_degraded"):
        return None
    return {
        "is_degraded": True,
        "reasons": list(diagnostics.get("reasons", [])),
        "events": int(diagnostics.get("events", 0)),
    }


def _enrich_with_dap(comments: list[dict]) -> list[dict]:
    """Enrich comments with DAP material_id and short_name.

    Extracts DAP ID from the trailing ``_NNNNNN`` in FB ad names, batch-fetches
    material details, and adds ``dap_id`` + ``dap_short_name`` fields.
    Gracefully degrades when DAP_API_TOKEN is unset or API is unreachable.
    """
    dap = _dap_material()
    fb_names = list({c.get("creative_name", "") for c in comments if c.get("creative_name")})
    if not fb_names:
        return comments
    try:
        resolved = dap.batch_resolve_materials(fb_names)
    except Exception as exc:
        _log.warning("DAP material enrichment failed: %s", exc)
        return comments
    if not resolved:
        return comments
    return [
        {
            **c,
            "dap_id": resolved[c.get("creative_name", "")]["dap_id"]
            if c.get("creative_name", "") in resolved else None,
            "dap_short_name": resolved[c.get("creative_name", "")]["short_name"]
            if c.get("creative_name", "") in resolved else None,
            "dap_language": resolved[c.get("creative_name", "")]["language"]
            if c.get("creative_name", "") in resolved else None,
        }
        for c in comments
    ]


def _build_report_from_fixture(product: str) -> dict:
    cfg = _config()
    classifier = _classifier()
    rg = _report_gen()

    fixture_path = cfg.FIXTURES_DIR / "sample_comments.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    raw_comments = payload["comments"]
    window = payload["window"]

    diagnostics: dict = {}
    classified = classifier.classify(
        raw_comments, use_claude=False, diagnostics=diagnostics
    )

    report = rg.build_report(
        classified,
        product=product,
        channel="facebook",
        window_start=window["start"],
        window_end=window["end"],
        generated_at=datetime.now(timezone.utc).isoformat(),
        baseline_yesterday_total=payload.get("yesterday_total"),
        baseline_7d_avg_total=payload.get("baseline_7d_avg_total"),
        tracking_state={"entries": []},
        degradation_flag=_finalize_degradation(diagnostics),
    )

    return report


def _build_report_live(product: str) -> dict:
    cfg = _config()
    fetcher = _comment_fetcher()
    classifier = _classifier()
    rg = _report_gen()
    ts = _tracking_store()

    _BEIJING = timezone(timedelta(hours=8))
    snapshot = datetime.now(_BEIJING)
    window_start, window_end = fetcher.compute_window(snapshot)
    raw = fetcher.fetch_comments(snapshot=snapshot, product=product)
    diagnostics: dict = {}
    classified = classifier.classify(
        raw, use_claude=True, diagnostics=diagnostics
    )
    classified = _enrich_with_dap(classified)
    tracking_state = ts.load(product)

    # Fetch 7-day window comments for risk level 7d-avg comparison (方案B)
    # Use cache to avoid re-classifying comments from previous days
    cache_mod = _sentiment_cache()
    cache = cache_mod.load_cache(product)

    t = cfg.load_sentiment_thresholds()
    raw_7d = fetcher.fetch_comments(
        snapshot=snapshot, product=product,
        window_hours=t.get("rolling_window_7d_hours", 168),
    )
    cached_7d, uncached_7d = cache_mod.apply_cache(raw_7d, cache)
    if uncached_7d:
        diag_7d: dict = {}
        newly_classified = classifier.classify(uncached_7d, use_claude=True, diagnostics=diag_7d)
        degraded_ids = set()
        if diag_7d.get("is_degraded"):
            degraded_ids = {c["id"] for c in uncached_7d} - {
                c["id"] for c in newly_classified
                if c.get("sentiment") and not (c["sentiment"] == "neutral" and c.get("theme") == "unclassified")
            }
        cache = cache_mod.update_cache(cache, newly_classified, degraded_ids=degraded_ids)
        comments_7d = cached_7d + newly_classified
    else:
        comments_7d = cached_7d

    # Also cache today's 24h classified comments
    cache = cache_mod.update_cache(cache, classified)
    cache_mod.save_cache(product, cache)

    comments_7d = _enrich_with_dap(comments_7d)

    report = rg.build_report(
        classified,
        product=product,
        channel=cfg.DEFAULT_CHANNEL,
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        generated_at=snapshot.isoformat(),
        tracking_state=tracking_state,
        comments_7d=comments_7d,
        degradation_flag=_finalize_degradation(diagnostics),
    )

    # Module 4: persist tracking state
    tracking_entries = report.get("module_4_tracking", {}).get("entries", [])
    ts.save(product, {"product": product, "entries": tracking_entries})

    return report


def _backfill_doc_url(report: dict, target_path: Path) -> dict:
    """Return a NEW report dict with ``meta.doc_url`` set to a file:// URI.

    Uses ``Path.as_uri()`` so paths containing spaces or non-ASCII characters
    are percent-encoded into a valid URI (phase4_review IC-V2). Naive
    ``f"file://{path}"`` concatenation would emit illegal URIs that break
    Feishu link rendering.

    Pure functional copy — never mutates the input (immutability rule).
    """
    return {
        **report,
        "meta": {**report["meta"], "doc_url": target_path.as_uri()},
    }


# ── IC-V5: doc_url 协议前缀白名单 ─────────────────────────────────────
_ALLOWED_DOC_URL_SCHEMES = ("file://", "http://", "https://")


def _validate_doc_url(doc_url) -> str | None:
    """Return ``None`` if doc_url is acceptable, else a human-readable reason.

    phase4_review IC-V5: 防御式校验，避免把 None / 空串 / 非法协议
    （如 ``javascript:``）送进飞书消息体。
    """
    if doc_url is None:
        return "meta.doc_url is missing (None)"
    if not isinstance(doc_url, str) or not doc_url.strip():
        return f"meta.doc_url is empty or non-string: {doc_url!r}"
    if not doc_url.startswith(_ALLOWED_DOC_URL_SCHEMES):
        return (
            f"meta.doc_url has unsupported scheme: {doc_url!r} "
            f"(allowed: {', '.join(_ALLOWED_DOC_URL_SCHEMES)})"
        )
    return None


# ── IC-V9: report schema gate (phase4_review F3) ──────────────────────────
#
# _cmd_generate 之前直接落盘 / 打印 builder 输出，没有 schema 校验。一旦
# 上游 builder 漏字段或回退，会产出违反契约的产物。下面的 gate 必须在
# 持久化与 dry-run 两条分支之前都跑一遍，校验失败时退出非零并把失败原因
# 打到 stderr。
#
# 实现策略：优先使用 jsonschema 库（按 ``$schema`` 自动选 Draft7Validator），
# 未安装时退化为顶层必需键检查——比之前完全无校验仍是显著改善。
def _validate_report_against_schema(report: dict) -> str | None:
    """Return None if ``report`` passes ``schemas/report_schema.json``."""
    cfg = _config()
    schema_path = cfg.SCHEMAS_DIR / "report_schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return f"report_schema.json unreadable: {exc}"

    try:
        import jsonschema  # lazy import — 保持 cli.py 导入开销最小
    except ImportError:
        # Fallback: 顶层 required 键的存在性检查
        missing = [k for k in schema.get("required", []) if k not in report]
        if missing:
            return (
                "schema validation failed (jsonschema unavailable, fallback): "
                f"missing required keys {missing}"
            )
        return None

    try:
        jsonschema.validate(instance=report, schema=schema)
    except jsonschema.ValidationError as exc:
        path = list(exc.absolute_path) or ["<root>"]
        return f"schema validation failed at {path}: {exc.message}"
    return None


def _emit_generate_error(reason: str, *, report_excerpt: dict | None = None) -> None:
    """Centralised error surface for ``_cmd_generate`` rejections.

    phase3 r7 IC-V24: 输出体固定附加 ``_envelope_kind: "refusal"`` 哨兵字段。
    顶层 safety net 输出的简化错误 ``{"error": "..."}`` 不带此字段，下游
    （包括 test_cli 的 ``_extract_envelope`` 工具）可以按哨兵显式区分两类
    envelope，避免反向扫描在多 print/日志混杂场景下误抓非目标对象。
    向前兼容——旧消费者若不读 ``_envelope_kind`` 不受影响。
    """
    _log.error("generate refused: %s", reason)
    payload: dict = {
        "_envelope_kind": "refusal",
        "ok": False,
        "errors": [reason],
    }
    if report_excerpt is not None:
        # 仅暴露 meta（避免敏感数据），便于上游排查
        payload["meta"] = {
            k: report_excerpt.get(k) for k in ("product", "channel", "window_end")
        }
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)


def _cmd_generate(args: argparse.Namespace) -> int:
    if args.from_fixture:
        report = _build_report_from_fixture(args.product)
    else:
        report = _build_report_live(args.product)

    # IC-V16 (phase3 r5): dry-run 与 persist 必须共享同一条
    # `compute_report_path -> backfill_doc_url -> schema validate -> branch`
    # 流水线，校验对象保持一致——避免 dry-run 验证不带 doc_url 的报告但
    # persist 验证带 doc_url 的版本，让 doc_url 字段相关 schema 问题在 dry-run
    # 下被静默放行。
    publisher = _publisher()
    out_dir = Path(args.output_dir) if args.output_dir else None

    # IC-V19 (phase3 r6): compute_report_path 与 _backfill_doc_url 在 meta
    # 字段缺失（KeyError，如缺 ``window_end``）或非 ISO 字符串（ValueError）
    # 时会抛异常。若不显式拦截，会冒泡到 ``run()`` 顶层 safety net，输出
    # ``{"error": "..."}`` 简化形式而非 ``_emit_generate_error`` 的标准
    # refusal envelope，破坏 IC-V9『单一规范化拒绝点』承诺。
    #
    # 仅 catch KeyError/ValueError——其他异常（OSError、RuntimeError 等）
    # 仍按既有约定冒泡到顶层 safety net，避免误吞未知失败模式。
    try:
        target_path = publisher.compute_report_path(report, output_dir=out_dir)
        report = _backfill_doc_url(report, target_path)
    except (KeyError, ValueError) as exc:
        _emit_generate_error(
            f"compute_report_path / doc_url backfill failed: {exc}",
            report_excerpt=report.get("meta"),
        )
        return 1

    # IC-V9: schema gate——backfill 后再做最终校验，确保 dry-run 打印的与
    # persist 落盘的是同一个对象。校验失败严禁继续。
    invalid_reason = _validate_report_against_schema(report)
    if invalid_reason is not None:
        _emit_generate_error(
            invalid_reason, report_excerpt=report.get("meta")
        )
        return 1

    if args.dry_run:
        # dry-run 仍只打印 JSON、不调用 write_report_file；compute_report_path
        # 是纯函数，无副作用。
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    import os as _os
    chat_id = getattr(args, "chat_id", None) or _os.environ.get("FEISHU_CHAT_ID", "")
    if chat_id:
        pub_result = publisher.publish(
            report, chat_id=chat_id, output_dir=out_dir,
        )
        result: dict = {
            "ok": True,
            "doc_url": pub_result.get("doc_url"),
            "brief": pub_result.get("brief", ""),
        }
        if pub_result.get("errors"):
            result["feishu_errors"] = pub_result["errors"]
    else:
        publisher.write_report_file(report, output_dir=out_dir)
        result = {"ok": True}

    print(json.dumps(result, ensure_ascii=False))
    return 0


def _cmd_publish(args: argparse.Namespace) -> int:
    report = json.loads(Path(args.report_path).read_text(encoding="utf-8"))

    # IC-V5: 调用 publisher 之前校验 meta.doc_url，避免把 None / 空串 /
    # 非法协议送进飞书消息体（缺 doc_url 必须直接非零退出）。
    doc_url = report.get("meta", {}).get("doc_url")
    invalid_reason = _validate_doc_url(doc_url)
    if invalid_reason is not None:
        _log.error("publish refused: %s", invalid_reason)
        print(
            json.dumps(
                {
                    "ok": False,
                    "errors": [invalid_reason],
                    "report_path": args.report_path,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    publisher = _publisher()
    result = publisher.publish(
        report,
        chat_id=args.chat_id,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False))
    errors = result.get("errors") or []
    if errors:
        # P1：飞书发送失败/被跳过必须显式上报，决不静默吞错误
        _log.error(
            "Feishu publish surfaced %d error(s): %s",
            len(errors),
            "; ".join(str(e) for e in errors),
        )
        return 1
    return 0


_CMDS = {
    "generate": _cmd_generate,
    "publish": _cmd_publish,
}


def run(argv: list[str] | None = None) -> int:
    # IC-V4: 入口最低限度配置 logging，保证 cron / stdin-stdout pipeline
    # 触发时 P0/P1 告警链路日志可见。``basicConfig`` 在 root logger 已有
    # handler 时是 no-op，所以重复调用安全。
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = parse_args(argv)
    try:
        rc = _CMDS[args.command](args)
    except SystemExit:
        raise
    except Exception as e:  # pragma: no cover — top-level safety net
        _log.exception("CLI command failed")
        # IC-V28: 与 IC-V24 refusal 哨兵对称的 safety_net 哨兵，便于读取方正向识别。
        print(json.dumps({"_envelope_kind": "safety_net", "error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    sys.exit(rc)


if __name__ == "__main__":
    run()
