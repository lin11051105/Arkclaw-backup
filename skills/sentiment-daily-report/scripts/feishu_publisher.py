"""Feishu publication: send brief + upload detail JSON.

Reuses ``workspace.skills.lib.feishu.FeishuClient`` per repo convention. Does
NOT instantiate ``requests`` or build an alternative client.

The lib package lives at ``workspace/skills/lib/feishu.py`` (no ``__init__.py``),
so ``FeishuClient`` is loaded lazily via ``importlib.util.spec_from_file_location``
inside :func:`_load_feishu_module` — the same pattern creative-lifecycle/
report-reconcile use.
"""
from __future__ import annotations

import importlib.util
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config

_log = logging.getLogger(__name__)

# IC-V13 (phase3 r5): 之前在这里有
#     _SKILLS_ROOT = str(_SCRIPTS.parents[1])
#     if _SKILLS_ROOT not in sys.path:
#         sys.path.insert(0, _SKILLS_ROOT)
# 那是 IC-V8 之前的旧加载路径；IC-V8 已切换到 spec_from_file_location 显式
# 加载 lib/feishu.py，sys.path 注入早已不再被使用却仍在污染全局 import 路径。
# 本轮删除，并撤掉对应的 ``import sys``，避免误以为该副作用还在。
_SCRIPTS = Path(__file__).resolve().parent


# ── Jinja2 environment (IC-V11: module-level singleton) ──────────────
#
# 模板文件已在 ``templates/`` 维护，render_brief 之前用 Python 字符串拼接
# 跟模板分叉。phase4_review F4 要求布局变更只走模板，不走代码。
# IC-V11 (phase3 r4): 之前每次 render 都重建 Environment + FileSystemLoader，
# 热路径下重复编译模板；改为模块级单例，``_render_template`` 仅做
# get_template + render。
_BRIEF_TEMPLATE_NAME = "feishu_brief.md.j2"
_DOC_TEMPLATE_NAME = "feishu_doc.md.j2"

CELL_NEWLINE = "⏎"


def _bullet_list(items: list) -> str:
    if not items:
        return ""
    return CELL_NEWLINE.join(f"- {item}" for item in items)


_ENV = Environment(
    loader=FileSystemLoader(str(config.TEMPLATES_DIR)),
    autoescape=select_autoescape(disabled_extensions=("md", "j2")),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=False,
)
_ENV.filters["bullet_list"] = _bullet_list


def _render_template(template_name: str, ctx: dict[str, Any]) -> str:
    """Load a template from ``config.TEMPLATES_DIR`` and render with ``ctx``.

    ``trim_blocks`` + ``lstrip_blocks`` make ``{% if %}`` blocks emit clean
    Markdown without spurious blank lines (matches the template authoring
    style under ``templates/``).
    """
    template = _ENV.get_template(template_name)
    return template.render(**ctx)


def render_brief(report: dict[str, Any]) -> str:
    """Render the Feishu chat brief via ``templates/feishu_brief.md.j2``."""
    return _render_template(_BRIEF_TEMPLATE_NAME, report)


def render_doc(report: dict[str, Any]) -> str:
    """Render the full 5-module Markdown report via ``templates/feishu_doc.md.j2``."""
    return _render_template(_DOC_TEMPLATE_NAME, report)


def compute_report_path(
    report: dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> Path:
    """Resolve the absolute persistence path for ``report`` without writing it.

    Filename pattern: ``YYYY-MM-DD-{product_lower}.json`` (PRD 规约)。

    暴露成独立函数后，``_cmd_generate`` 可以提前算出最终路径并回填到
    ``meta.doc_url``，再交给 ``write_report_file`` 落盘——避免飞书简报
    缺链接（phase4_review fix）。

    IC-V12 (phase3 r4): ``meta.window_end`` 必须是 ISO-8601 字符串；非法
    输入直接 raise ``ValueError``，由 cli 顶层 safety net 转为非零退出码。
    之前的 ``end[:10]`` 兜底会静默生成命名错误的产物。
    """
    out_dir = Path(output_dir or config.REPORTS_DIR)
    end = report["meta"]["window_end"]
    # 显式校验：fromisoformat 自带 ValueError 抛出，无需 try/except 包裹。
    date_str = datetime.fromisoformat(end).date().isoformat()
    product_lower = report["meta"]["product"].lower()
    return (out_dir / f"{date_str}-{product_lower}.json").resolve()


def write_report_file(
    report: dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> Path:
    """Persist the report as JSON under ``workspace/memory/sentiment-reports/``.

    Filename pattern: ``YYYY-MM-DD-{product_lower}.json``.
    """
    out_path = compute_report_path(report, output_dir=output_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


# ── IC-V8 + IC-V14: Feishu module loader with lazy module cache ──────
#
# phase4_review HIGH F1 (phase3 r4): publish() 之前调用了未定义且未导入的
# ``_get_feishu_client``，触发飞书推送的真实分支会立即抛 NameError；前
# 三轮 phase3 retry 都漏掉，根因是测试只走 cli 层 monkeypatch 或仅断言
# render_brief。此处显式定义模块级工厂，并在 publish() 中通过它构造客户端，
# 保证 monkeypatch 与生产路径共用同一符号。
#
# IC-V14 (phase3 r5): 之前每次 publish 都重新 spec_from_file_location 加载
# lib/feishu.py，热路径下重复 IO + 字节码解析；改为模块级 lazy singleton——
# 首次加载后复用，加载语义不变。测试若需换实现，可通过 monkeypatch 直接
# 替换 ``_feishu_module`` 或 ``_get_feishu_client``。
_feishu_module: Any = None


def _load_feishu_module() -> Any:
    """Load (or return cached) ``workspace/skills/lib/feishu.py`` module.

    ``lib/`` 没有 ``__init__.py``，无法走普通 ``import`` 链；这里用
    ``importlib.util.spec_from_file_location``（参考 creative-lifecycle /
    report-reconcile）按需加载，并以模块级变量缓存复用。
    """
    global _feishu_module
    if _feishu_module is not None:
        return _feishu_module

    feishu_path = _SCRIPTS.parents[1] / "lib" / "feishu.py"
    spec = importlib.util.spec_from_file_location("feishu", feishu_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"failed to load lib/feishu.py from {feishu_path}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _feishu_module = module
    return module


def _get_feishu_client(*, chat_id: str) -> Any:
    """Construct a ``FeishuClient`` for ``chat_id``.

    Args:
        chat_id: 飞书群 chat_id（``oc_xxx``）或群名（``FeishuClient`` 自动解析）。

    Raises:
        ValueError: ``chat_id`` 为 None / 空串。
        RuntimeError: 由 ``FeishuClient`` 抛出，缺少 ``FEISHU_APP_ID`` 或
            ``FEISHU_APP_SECRET`` 时（避免 publish 时才发现）。
    """
    if chat_id is None or not str(chat_id).strip():
        raise ValueError("chat_id is required for Feishu publish")
    module = _load_feishu_module()
    return module.FeishuClient(chat_id=chat_id)


def publish(
    report: dict[str, Any],
    *,
    chat_id: str | None,
    output_dir: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Persist and (optionally) push to Feishu.

    Args:
        report:    full schema-conformant report dict.
        chat_id:   Feishu chat_id or group name; ``None`` skips the push.
        output_dir: override REPORTS_DIR (tests).
        dry_run:   write file only — no Feishu calls.

    Returns:
        Dict describing publication result (path, doc_url, errors).
    """
    out_path = write_report_file(report, output_dir=output_dir)
    result: dict[str, Any] = {
        "report_path": str(out_path),
        "doc_url": None,
        "feishu_sent": False,
        "errors": [],
    }
    if dry_run:
        return result

    if not chat_id:
        result["errors"].append("chat_id not provided; skipping Feishu push")
        return result

    try:
        client = _get_feishu_client(chat_id=chat_id)
    except Exception as e:
        _log.exception("Feishu publish failed")
        result["errors"].append(str(e))
        return result

    title = f"{report['meta']['product']} 舆情日报 · {report['meta']['window_end'][:10]}"

    # Create Feishu document only — no send_text.
    # Hermes agent handles messaging to avoid duplicate messages.
    try:
        feishu_mod = _load_feishu_module()
        blocks = feishu_mod.report_to_doc_blocks(report, title=title, render_fn=render_doc)
        doc_info = client.create_document(title, blocks)
        result["doc_url"] = doc_info["url"]
    except Exception as e:
        _log.warning("Feishu doc creation failed: %s", e)
        result["errors"].append(f"doc_creation: {e}")

    result["brief"] = render_brief(report)
    return result
