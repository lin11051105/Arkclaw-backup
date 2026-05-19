"""渠道汇总 — 5.6 按渠道维度聚合核心投放指标（OS-aware）。

支持的维度（DAP 端）:
- channel: 按渠道（DAP media_src 表）
- country: 按国家（DAP country 表）

每张 DAP 表只有一个维度列 + 29 个指标列，不支持跨表组合。

OS 拆分（SKAN refactor 2026-05-08）:
- ``os="android"`` → 仅 DAP 概率归因（``fetch_custom_report``）
- ``os="ios"``     → 仅 SKAN 真值（``fetch_skan_by_channel_day``）
                     iOS 路径目前仅支持 ``group_by="channel"``
- ``os="both"``    → 两路并行，最终通过 ``lib.os_aggregator.combine`` 合并

数据来源:
- Android: DAP get_custom_report(table="media_src" 或 "country")
- iOS: hive.da_bi_dw.v_tb_skan_report_day_v2 via lib.skan_repo
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

# Allow ``from lib.os_aggregator import combine`` regardless of how this
# module was imported (test loads it as ``workspace.skills.channel-summary…``;
# CLI loads it via _loader.make_loader). Adding workspace/skills/ to sys.path
# is idempotent.
_SKILLS_ROOT = Path(__file__).resolve().parents[2]
if str(_SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILLS_ROOT))

from lib.os_aggregator import combine as _combine_os  # noqa: E402


_VALID_OS = ("ios", "android", "both")


# DAP 字段 → 内部字段映射
_FIELD_MAP = {
    "渠道": "channel",
    "项目": "project",
    "国家": "country",
    "消耗数": "spend",
    "安装数": "installs",
    "安装成本": "cpi",
    "Actual_ROI": "roi",
    "CTR": "ctr",
    "CVR": "cvr",
}

# 维度 → DAP 表的映射
_DIM_TABLE = {
    "channel": "media_src",
    "country": "country",
}

# 旧枚举值 → 新逗号格式（向后兼容）
_LEGACY_MAP = {
    "channel_project": "channel",
    "channel_country": "country",
}


# ---------------------------------------------------------------------------
# Dimension resolution
# ---------------------------------------------------------------------------

def _resolve_dimensions(group_by: str) -> tuple[str, tuple[str, ...], str | None]:
    """解析 group_by 字符串，返回 ``(dap_table, group_keys, warning_or_none)``."""
    group_by = _LEGACY_MAP.get(group_by, group_by)
    dims = tuple(d.strip() for d in group_by.split(",") if d.strip())

    for d in dims:
        if d not in _DIM_TABLE:
            raise ValueError(
                f"未知维度: {d}。支持的维度: {', '.join(sorted(_DIM_TABLE))}"
            )

    tables = {_DIM_TABLE[d] for d in dims}
    if len(tables) == 1:
        return tables.pop(), dims, None

    # 跨表: 优先 country 表（country 维度只在 country 表有）
    actual_dims = tuple(d for d in dims if _DIM_TABLE[d] == "country")
    warning = (
        f"维度 {','.join(dims)} 涉及多张 DAP 表，降级为 {','.join(actual_dims)} "
        f"(country 表无 {','.join(d for d in dims if _DIM_TABLE[d] != 'country')} 列)"
    )
    return "country", actual_dims, warning


# ---------------------------------------------------------------------------
# DAP-side normalisation + aggregation
# ---------------------------------------------------------------------------

def _normalize_row(raw: dict[str, Any]) -> dict[str, Any]:
    """将 DAP 中文字段名映射为内部英文字段名."""
    result: dict[str, Any] = {}
    for cn_key, en_key in _FIELD_MAP.items():
        if cn_key in raw:
            result[en_key] = raw[cn_key]
    return result


def _aggregate_rows(
    rows: list[dict[str, Any]],
    group_keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    """按 group_keys 聚合 DAP 行，输出含 ``revenue``/``cpi``/``roi``/``ctr``/``cvr``."""
    groups: dict[tuple, dict[str, Any]] = {}

    for row in rows:
        key = tuple(row.get(k, "") for k in group_keys)
        if key not in groups:
            groups[key] = {
                **{k: row.get(k, "") for k in group_keys},
                "spend": 0.0,
                "installs": 0,
                "revenue": 0.0,
                "_ctr_spend": 0.0,
                "_cvr_spend": 0.0,
            }
        g = groups[key]
        spend = float(row.get("spend") or 0)
        installs = int(row.get("installs") or 0)
        roi = float(row.get("roi") or 0)

        g["spend"] += spend
        g["installs"] += installs
        g["revenue"] += spend * roi
        g["_ctr_spend"] += float(row.get("ctr") or 0) * spend
        g["_cvr_spend"] += float(row.get("cvr") or 0) * spend

    result: list[dict[str, Any]] = []
    for g in groups.values():
        spend = g["spend"]
        installs = g["installs"]
        revenue = g["revenue"]
        cpi = spend / installs if installs > 0 else 0.0
        roi = revenue / spend if spend > 0 else 0.0
        ctr = g["_ctr_spend"] / spend if spend > 0 else 0.0
        cvr = g["_cvr_spend"] / spend if spend > 0 else 0.0

        entry = {k: g[k] for k in group_keys}
        entry.update({
            "spend": round(spend, 2),
            "installs": installs,
            "revenue": round(revenue, 2),
            "cpi": round(cpi, 2),
            "roi": round(roi, 4),
            "ctr": round(ctr, 4),
            "cvr": round(cvr, 4),
        })
        result.append(entry)

    return result


# ---------------------------------------------------------------------------
# SKAN-side aggregation (iOS path)
# ---------------------------------------------------------------------------

def _aggregate_skan_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """聚合 SKAN 行 by ``spreader_name``。

    输出每行: ``{channel, spend, installs, revenue, cpi, roi}``，
    其中 ``roi`` 是按 null-bucket 校正的 SKAN ROI（与 ``skan_repo._enrich``
    保持一致）。
    """
    groups: dict[str, dict[str, Any]] = {}

    for row in rows:
        ch = str(row.get("spreader_name") or "")
        if ch not in groups:
            groups[ch] = {
                "channel": ch,
                "spend": 0.0,
                "installs": 0,
                "revenue": 0.0,
                "_nulls": 0,
            }
        g = groups[ch]
        g["spend"] += float(row.get("cost") or 0)
        g["installs"] += int(row.get("sk_install") or 0)
        g["revenue"] += float(row.get("revenue") or 0)
        g["_nulls"] += int(row.get("sk_conversion_null") or 0)

    out: list[dict[str, Any]] = []
    for g in groups.values():
        spend = g["spend"]
        installs = g["installs"]
        revenue = g["revenue"]
        nulls = g["_nulls"]

        cpi = spend / installs if installs > 0 else 0.0
        if spend > 0 and installs > 0 and (nulls / installs) < 1.0:
            grossed = revenue / (1.0 - nulls / installs)
            skan_roi = grossed / spend
        else:
            skan_roi = 0.0

        out.append({
            "channel": g["channel"],
            "spend": round(spend, 2),
            "installs": installs,
            "revenue": round(revenue, 2),
            "cpi": round(cpi, 2),
            "roi": round(skan_roi, 4),
        })

    return out


# ---------------------------------------------------------------------------
# Slice builders for ``os_aggregator.combine``
# ---------------------------------------------------------------------------

def _sum_dap_slice(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum aggregated DAP rows into the slice shape consumed by combine()."""
    return {
        "spend": sum(float(r.get("spend") or 0) for r in rows),
        "installs": sum(int(r.get("installs") or 0) for r in rows),
        "revenue": sum(float(r.get("revenue") or 0) for r in rows),
    }


def _sum_skan_slice(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum raw SKAN rows into the slice shape consumed by combine()."""
    return {
        "spend": sum(float(r.get("cost") or 0) for r in rows),
        "installs": sum(int(r.get("sk_install") or 0) for r in rows),
        "revenue": sum(float(r.get("revenue") or 0) for r in rows),
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def _format_markdown(
    rows: list[dict[str, Any]],
    totals_row: dict[str, Any],
    group_keys: tuple[str, ...],
) -> str:
    """生成 Markdown 表格。``totals_row`` 仅需含 ``spend/installs/cpi`` 三键."""
    if not rows:
        return "（无数据）"

    header_map = {
        "channel": "渠道",
        "project": "项目",
        "country": "国家",
        "spend": "消耗",
        "installs": "安装",
        "cpi": "CPI",
        "roi": "ROI",
        "ctr": "CTR",
        "cvr": "CVR",
    }

    metric_cols = ["spend", "installs", "cpi", "roi", "ctr", "cvr"]
    # SKAN 行没有 ctr/cvr，过滤掉所有行都不含的列。
    metric_cols = [c for c in metric_cols if any(c in r for r in rows)]
    all_cols = list(group_keys) + metric_cols

    headers = [header_map.get(c, c) for c in all_cols]
    header_line = "| " + " | ".join(headers) + " |"
    sep_line = "| " + " | ".join("---" for _ in all_cols) + " |"

    lines = [header_line, sep_line]
    for row in rows:
        cells = []
        for c in all_cols:
            val = row.get(c, "")
            if isinstance(val, float):
                if c in ("ctr", "cvr"):
                    cells.append(f"{val:.2%}")
                elif c == "roi":
                    cells.append(f"{val:.2f}")
                else:
                    cells.append(f"{val:,.2f}")
            elif isinstance(val, int):
                cells.append(f"{val:,}")
            else:
                cells.append(str(val))
        lines.append("| " + " | ".join(cells) + " |")

    # 汇总行
    total_cells = []
    for c in all_cols:
        if c == group_keys[0]:
            total_cells.append("**合计**")
        elif c in totals_row:
            val = totals_row[c]
            if isinstance(val, float):
                total_cells.append(f"**{val:,.2f}**")
            else:
                total_cells.append(f"**{val:,}**")
        else:
            total_cells.append("")
    lines.append("| " + " | ".join(total_cells) + " |")

    return "\n".join(lines)


def _render_os_markdown(
    *,
    os: str,
    group_keys: tuple[str, ...],
    ios_rows: list[dict[str, Any]],
    android_rows: list[dict[str, Any]],
    by_os: dict[str, dict[str, Any]],
) -> str:
    """OS-aware Markdown: 单 section 或两个 stacked sections。"""
    sections: list[str] = []

    if os in ("ios", "both"):
        ios_totals = by_os.get("ios", {})
        ios_md = _format_markdown(
            ios_rows,
            {
                "spend": round(float(ios_totals.get("spend", 0.0) or 0.0), 2),
                "installs": int(ios_totals.get("installs", 0) or 0),
                "cpi": round(float(ios_totals.get("cpi", 0.0) or 0.0), 2),
            },
            ("channel",),
        )
        sections.append(f"## iOS（SKAN 真值）\n\n{ios_md}")

    if os in ("android", "both"):
        android_totals = by_os.get("android", {})
        android_md = _format_markdown(
            android_rows,
            {
                "spend": round(float(android_totals.get("spend", 0.0) or 0.0), 2),
                "installs": int(android_totals.get("installs", 0) or 0),
                "cpi": round(float(android_totals.get("cpi", 0.0) or 0.0), 2),
            },
            group_keys,
        )
        sections.append(f"## Android（DAP 概率归因）\n\n{android_md}")

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_channel_summary(
    date_start: str,
    date_end: str,
    *,
    group_by: str = "channel",
    os: str = "both",
    top_n: int | None = None,
    config: dict,
    fetch_custom_report: Callable[[str, str, str], list[dict]],
    fetch_skan_by_channel_day: Callable[..., list[dict]] | None = None,
    game_id: int | None = None,
) -> dict:
    """OS-aware channel summary.

    Args:
        date_start, date_end: ISO YYYY-MM-DD inclusive range.
        group_by: comma-separated dims, e.g. ``"channel"`` or ``"country"``.
        os: ``"ios"`` / ``"android"`` / ``"both"``.
        top_n: keep only top-N rows by spend in the rendered output
               (``None`` or ``0`` = unlimited). Truncation happens after
               totals are computed, so totals always reflect ALL rows.
        config: full config dict (apps + thresholds).
        fetch_custom_report: DAP fetcher ``(table, start, end) -> list[dict]``.
        fetch_skan_by_channel_day: SKAN fetcher
            ``(*, date_start, date_end) -> list[dict]`` —
            required when ``os in {"ios","both"}``.
        game_id: required when ``os in {"ios","both"}`` (SKAN view filter).

    Returns:
        dict with keys
            ``os``, ``group_by``, ``totals``, ``ios_rows``, ``android_rows``,
            ``rows`` (back-compat primary view), ``markdown``.
        Plus optional ``warning``, ``top_n``, ``total_count``.

    Raises:
        ValueError: invalid ``os``; or iOS path without
            ``fetch_skan_by_channel_day``/``game_id``; or SKAN path requested
            with ``group_by != "channel"`` (only channel grain is supported
            for SKAN today).
    """
    if os not in _VALID_OS:
        raise ValueError(
            f"未知 os: {os!r}。支持: {', '.join(_VALID_OS)}"
        )

    if os in ("ios", "both"):
        if fetch_skan_by_channel_day is None:
            raise ValueError(
                "os='ios' 或 'both' 时必须提供 fetch_skan_by_channel_day"
            )
        if game_id is None:
            raise ValueError(
                "os='ios' 或 'both' 时必须提供 game_id（SKAN 视图按 game_id 过滤）"
            )

    table, group_keys, warning = _resolve_dimensions(group_by)

    if os in ("ios", "both") and group_keys != ("channel",):
        raise ValueError(
            "iOS (SKAN) 路径目前仅支持 group_by='channel'；"
            f"收到 group_by={group_by!r} (group_keys={group_keys!r})"
        )

    # ── Android (DAP) path ──
    android_rows: list[dict[str, Any]] = []
    if os in ("android", "both"):
        raw_dap = fetch_custom_report(table, date_start, date_end)
        normalized = [_normalize_row(r) for r in raw_dap]
        android_rows = _aggregate_rows(normalized, group_keys)
        android_rows.sort(key=lambda r: r.get("spend", 0), reverse=True)

    # ── iOS (SKAN) path ──
    raw_skan: list[dict[str, Any]] = []
    ios_rows: list[dict[str, Any]] = []
    if os in ("ios", "both"):
        raw_skan = fetch_skan_by_channel_day(
            date_start=date_start, date_end=date_end
        )
        ios_rows = _aggregate_skan_rows(raw_skan)
        ios_rows.sort(key=lambda r: r.get("spend", 0), reverse=True)

    # ── Combine slices BEFORE truncation so totals reflect all data ──
    ios_slice = _sum_skan_slice(raw_skan) if os in ("ios", "both") else None
    android_slice = (
        _sum_dap_slice(android_rows) if os in ("android", "both") else None
    )
    totals = _combine_os(ios=ios_slice, android=android_slice)

    total_count_android = len(android_rows)
    total_count_ios = len(ios_rows)

    # ── Truncation for display only ──
    if top_n is not None and top_n > 0:
        android_rows = android_rows[:top_n]
        ios_rows = ios_rows[:top_n]

    markdown = _render_os_markdown(
        os=os,
        group_keys=group_keys,
        ios_rows=ios_rows,
        android_rows=android_rows,
        by_os=totals.get("by_os", {}),
    )

    # Back-compat primary rows view:
    if os == "ios":
        primary_rows = ios_rows
    elif os == "android":
        primary_rows = android_rows
    else:  # both
        primary_rows = android_rows + ios_rows

    result: dict[str, Any] = {
        "os": os,
        "group_by": group_by,
        "totals": totals,
        "ios_rows": ios_rows,
        "android_rows": android_rows,
        "rows": primary_rows,
        "markdown": markdown,
    }
    if warning:
        result["warning"] = warning
    if top_n is not None and top_n > 0:
        result["top_n"] = top_n
        result["total_count"] = max(total_count_android, total_count_ios)
    return result
