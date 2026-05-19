"""月度对账 & 结算单 — 6.2。

拉取上月 Facebook Insights 与 DAP 数据，按日×Campaign 逐条比对，
标记差异项，生成结算单草稿 Markdown。

Design: dependency-injected fetchers for testability.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable


_DEFAULT_EXCHANGE_RATE = 7.24
_DIFF_THRESHOLD_PCT = 0.05  # 差异超过 5% 标记为"待核查"


def _month_range(month: str) -> tuple[str, str]:
    """从 'YYYY-MM' 计算该月的 start 和 end 日期。"""
    year, mon = month.split("-")
    y, m = int(year), int(mon)
    last_day = calendar.monthrange(y, m)[1]
    return f"{year}-{mon.zfill(2)}-01", f"{year}-{mon.zfill(2)}-{last_day:02d}"


def _match_records(
    fb_rows: list[dict[str, Any]],
    dap_rows: list[dict[str, Any]],
    exchange_rate: float,
) -> tuple[list[dict], list[dict], list[dict]]:
    """按 date + campaign_name 匹配 FB 与 DAP 记录。

    Returns:
        (matched_items, discrepancy_items, unmatched_items)
    """
    # Build DAP lookup: key = campaign_name → spend_rmb (aggregated)
    # DAP campaign table has column "广告计划", no date dimension
    dap_lookup: dict[str, float] = {}
    for row in dap_rows:
        name = row.get("广告计划", row.get("campaign", ""))
        spend = float(row.get("消耗数") or 0)
        if name in dap_lookup:
            dap_lookup[name] += spend
        else:
            dap_lookup[name] = spend

    # Aggregate FB rows by campaign_name (FB is per-day, DAP is per-campaign)
    fb_by_campaign: dict[str, float] = {}
    for row in fb_rows:
        name = row.get("campaign_name", "")
        fb_by_campaign[name] = fb_by_campaign.get(name, 0.0) + float(row.get("spend") or 0)

    matched: list[dict] = []
    discrepancies: list[dict] = []
    unmatched: list[dict] = []
    seen_keys: set[str] = set()

    for campaign_name, fb_spend_usd in fb_by_campaign.items():
        fb_spend_rmb = fb_spend_usd * exchange_rate

        seen_keys.add(campaign_name)

        if campaign_name in dap_lookup:
            dap_spend_rmb = dap_lookup[campaign_name]
            diff = fb_spend_rmb - dap_spend_rmb

            if abs(diff) < 0.01:
                matched.append({
                    "campaign_name": campaign_name,
                    "fb_spend_usd": round(fb_spend_usd, 2),
                    "fb_spend_rmb": round(fb_spend_rmb, 2),
                    "dap_spend_rmb": round(dap_spend_rmb, 2),
                    "diff_rmb": 0.0,
                })
            else:
                base = max(fb_spend_rmb, dap_spend_rmb)
                diff_pct = abs(diff) / base if base > 0 else 0.0
                status = "待核查" if diff_pct > _DIFF_THRESHOLD_PCT else "可接受"
                discrepancies.append({
                    "campaign_name": campaign_name,
                    "fb_spend_usd": round(fb_spend_usd, 2),
                    "fb_spend_rmb": round(fb_spend_rmb, 2),
                    "dap_spend_rmb": round(dap_spend_rmb, 2),
                    "diff_rmb": round(diff, 2),
                    "diff_pct": round(diff_pct * 100, 1),
                    "status": status,
                })
        else:
            unmatched.append({
                "campaign_name": campaign_name,
                "fb_spend_usd": round(fb_spend_usd, 2),
                "fb_spend_rmb": round(fb_spend_rmb, 2),
                "source": "fb_only",
            })

    for name, dap_spend in dap_lookup.items():
        if name not in seen_keys:
            unmatched.append({
                "campaign_name": name,
                "dap_spend_rmb": round(dap_spend, 2),
                "source": "dap_only",
            })

    return matched, discrepancies, unmatched


def _fill_settlement_template(
    template: str,
    project_id: str,
    month: str,
    exchange_rate: float,
    fb_total_usd: float,
    dap_total_rmb: float,
    matched: list[dict],
    discrepancies: list[dict],
    unmatched: list[dict],
    summary: dict[str, Any],
) -> str:
    """加载 settlement.md 模板并填充。支持 {{#items}}...{{/items}} 循环块。"""

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fb_total_rmb = fb_total_usd * exchange_rate
    total_diff = summary["total_diff_rmb"]
    total_diff_pct = abs(total_diff) / max(fb_total_rmb, dap_total_rmb, 0.01) * 100

    replacements = {
        "project_name": project_id,
        "month": month,
        "total_internal": f"{dap_total_rmb:,.2f}",
        "total_channel": f"{fb_total_rmb:,.2f}",
        "total_diff": f"{total_diff:,.2f}",
        "total_diff_pct": f"{total_diff_pct:.1f}",
        "generated_at": now,
    }

    result = template

    # {{#channel_items}}...{{/channel_items}} — 按渠道汇总行（当前只有 Facebook）
    channel_row_tpl_match = re.search(
        r"\{\{#channel_items\}\}(.*?)\{\{/channel_items\}\}",
        result, flags=re.DOTALL,
    )
    if channel_row_tpl_match:
        status = "已匹配" if not discrepancies else f"差异 {len(discrepancies)} 条"
        row = channel_row_tpl_match.group(1)
        row = row.replace("{{channel}}", "Facebook")
        row = row.replace("{{internal_spend}}", f"{dap_total_rmb:,.2f}")
        row = row.replace("{{channel_bill}}", f"{fb_total_rmb:,.2f}")
        row = row.replace("{{diff_amount}}", f"{total_diff:,.2f}")
        row = row.replace("{{diff_pct}}", f"{total_diff_pct:.1f}")
        row = row.replace("{{status}}", status)
        result = result[:channel_row_tpl_match.start()] + row + result[channel_row_tpl_match.end():]

    # {{#diff_items}}...{{/diff_items}} — 差异明细
    diff_tpl_match = re.search(
        r"\{\{#diff_items\}\}(.*?)\{\{/diff_items\}\}",
        result, flags=re.DOTALL,
    )
    if diff_tpl_match:
        tpl = diff_tpl_match.group(1)
        diff_rows = []
        for d in discrepancies:
            row = tpl
            row = row.replace("{{channel}}", "Facebook")
            row = row.replace("{{campaign_name}}", d.get("campaign_name", ""))
            row = row.replace("{{date}}", d.get("date", ""))
            row = row.replace("{{internal_amount}}", f"{d.get('dap_spend_rmb', 0):,.2f}")
            row = row.replace("{{channel_amount}}", f"{d.get('fb_spend_rmb', 0):,.2f}")
            row = row.replace("{{diff_amount}}", f"{d.get('diff_rmb', 0):,.2f}")
            row = row.replace("{{reason}}", d.get("status", "待核查"))
            diff_rows.append(row)
        result = result[:diff_tpl_match.start()] + "".join(diff_rows) + result[diff_tpl_match.end():]

    # {{#coupon_items}}...{{/coupon_items}} — 暂无数据源，渲染为空
    result = re.sub(
        r"\{\{#coupon_items\}\}(.*?)\{\{/coupon_items\}\}",
        "（暂无 Coupon / 返点数据）",
        result, flags=re.DOTALL,
    )

    for key, val in replacements.items():
        result = result.replace(f"{{{{{key}}}}}", str(val))

    result = re.sub(r"\{\{[a-zA-Z_]+\}\}", "—", result)

    return result


def _generate_fallback_markdown(
    project_id: str,
    month: str,
    exchange_rate: float,
    fb_total_usd: float,
    dap_total_rmb: float,
    matched: list[dict],
    discrepancies: list[dict],
    unmatched: list[dict],
    summary: dict[str, Any],
) -> str:
    """当 settlement.md 模板不存在时的 fallback markdown。"""
    lines = [
        f"# 月度对账 — {project_id}（{month}）",
        "",
        f"> 汇率: 1 USD = {exchange_rate} RMB",
        "",
        "## 汇总",
        "",
        f"| 项目 | 金额 |",
        f"|------|------|",
        f"| Facebook 消耗 (USD) | {fb_total_usd:,.2f} |",
        f"| Facebook 消耗 (RMB) | {fb_total_usd * exchange_rate:,.2f} |",
        f"| DAP 消耗 (RMB) | {dap_total_rmb:,.2f} |",
        f"| 差异合计 (RMB) | {summary['total_diff_rmb']:,.2f} |",
        f"| 匹配条数 | {len(matched)} |",
        f"| 差异条数 | {len(discrepancies)} |",
        f"| 未匹配条数 | {len(unmatched)} |",
        "",
    ]

    if discrepancies:
        lines.extend([
            "## 差异明细",
            "",
            "| 日期 | Campaign | FB(RMB) | DAP(RMB) | 差异 | 差异率 | 状态 |",
            "|------|----------|---------|----------|------|--------|------|",
        ])
        for d in discrepancies:
            lines.append(
                f"| {d['date']} | {d['campaign_name']} | "
                f"{d['fb_spend_rmb']:,.2f} | {d['dap_spend_rmb']:,.2f} | "
                f"{d['diff_rmb']:,.2f} | {d.get('diff_pct', 0):.1f}% | {d.get('status', '')} |"
            )
        lines.append("")

    if unmatched:
        lines.extend([
            "## 未匹配项",
            "",
            "| 日期 | Campaign | 来源 | 金额 |",
            "|------|----------|------|------|",
        ])
        for u in unmatched:
            source = u.get("source", "unknown")
            amount = u.get("fb_spend_rmb", u.get("dap_spend_rmb", 0.0))
            lines.append(
                f"| {u['date']} | {u['campaign_name']} | {source} | {amount:,.2f} |"
            )
        lines.append("")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.extend([
        "---",
        f"生成时间: {now} | 状态: **待人工确认**",
    ])

    return "\n".join(lines)


def run_reconciliation(
    project_id: str,
    month: str,
    *,
    config: dict,
    fetch_insights: Callable,
    fetch_custom_report: Callable,
    exchange_rate: float | None = None,
) -> dict:
    """执行月度对账。

    Args:
        project_id: 项目 ID (e.g. "ROK")
        month: 月份 "YYYY-MM"
        config: {"apps": ..., "thresholds": ...}
        fetch_insights: fn(start, end, level, **kw) → list[dict]
        fetch_custom_report: fn(table, start, end) → list[dict]
        exchange_rate: USD→RMB 汇率（默认 7.24）

    Returns:
        包含对账结果、差异项和 Markdown 结算单的字典。
    """
    if exchange_rate is None:
        exchange_rate = _DEFAULT_EXCHANGE_RATE

    start, end = _month_range(month)

    # 1. 拉取 Facebook Insights（含已暂停 Campaign，对账需全量）
    fb_rows = fetch_insights(start, end, "campaign", time_increment=1, include_inactive=True)

    # 2. 拉取 DAP Campaign 消耗
    dap_rows = fetch_custom_report("campaign", start, end)

    # 3. 逐条匹配
    matched, discrepancies, unmatched = _match_records(
        fb_rows, dap_rows, exchange_rate
    )

    # 4. 汇总 — DAP campaign 表是全渠道，用 media_src 表取 Facebook 渠道总消耗对齐
    fb_total_usd = sum(float(r.get("spend") or 0) for r in fb_rows)
    media_src_rows = fetch_custom_report("media_src", start, end)
    fb_channel_names = {"facebook", "meta", "fb"}
    dap_fb_rows = [
        r for r in media_src_rows
        if r.get("渠道", "").lower() in fb_channel_names
    ]
    dap_total_rmb = sum(float(r.get("消耗数") or 0) for r in dap_fb_rows)
    total_diff_rmb = sum(d["diff_rmb"] for d in discrepancies)

    summary = {
        "total_diff_rmb": round(total_diff_rmb, 2),
        "coupon_amount": 0.0,
        "refund_amount": 0.0,
    }

    # 5. 加载模板并生成 Markdown
    template_path = Path(__file__).resolve().parents[3] / "templates" / "settlement.md"
    if template_path.exists():
        template = template_path.read_text(encoding="utf-8")
        markdown = _fill_settlement_template(
            template, project_id, month, exchange_rate,
            fb_total_usd, dap_total_rmb,
            matched, discrepancies, unmatched, summary,
        )
    else:
        markdown = _generate_fallback_markdown(
            project_id, month, exchange_rate,
            fb_total_usd, dap_total_rmb,
            matched, discrepancies, unmatched, summary,
        )

    return {
        "project_id": project_id,
        "month": month,
        "fb_total_spend_usd": round(fb_total_usd, 2),
        "dap_total_spend_rmb": round(dap_total_rmb, 2),
        "exchange_rate": exchange_rate,
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
        "discrepancy_items": discrepancies,
        "summary": summary,
        "markdown": markdown,
    }
