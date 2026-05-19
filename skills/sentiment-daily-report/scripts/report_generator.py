"""Build the 5-module sentiment report (PRD module ordering enforced).

Public entry point::

    build_report(comments, *, product, channel, window_start, window_end,
                 generated_at, baseline_yesterday_total, baseline_7d_avg,
                 tracking_state) -> dict

Module order (must match report_schema.json + PRD PDF):
    1. module_1_volume          — 24h 量级总览
    2. module_2_qualitative     — 24h 定性分析（含 2.4 警报）
    3. module_3_creative_details — 24h 素材评论明细（按负面数倒序）
    4. module_4_tracking         — 持续跟踪重点素材
    5. module_5_actions          — 建议动作清单（暂停/扩量/观察）
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable

from . import config


# ── Helpers ──────────────────────────────────────────────────


def _safe_pct_change(curr: float, base: float | None) -> float | None:
    if base is None or base == 0:
        return None
    return round((curr - base) / base * 100, 2)


def _risk_level(
    *,
    negative: int,
    total: int,
    positive: int,
    has_political_sensitive: bool = False,
    is_tracked: bool = False,
    consecutive_rise_days: int = 0,
    negative_rate_7d_avg: float | None = None,
) -> str:
    """Map counts → risk_level (6-level: red/orange/yellow/grey/green/star).

    Priority order: red → orange → yellow → grey → green → star.
    """
    t = config.load_sentiment_thresholds()
    negative_rate = negative / total if total > 0 else 0.0
    positive_rate = positive / total if total > 0 else 0.0

    # 1. RED — 立即暂停
    if negative >= t["risk_red_negative_count"]:
        return "red"
    if total >= t["risk_red_sample_min"] and negative_rate >= t["risk_red_negative_rate"]:
        return "red"
    if has_political_sensitive:
        return "red"

    # 2. ORANGE — 24h内暂停
    if (t["risk_orange_negative_min"] <= negative <= t["risk_orange_negative_max"]
            and total < t["risk_orange_sample_cap"]):
        return "orange"
    if (total >= t["risk_red_sample_min"]
            and t["risk_orange_negative_rate_min"] <= negative_rate < t["risk_orange_negative_rate_max"]):
        return "orange"
    if consecutive_rise_days >= t["risk_orange_consecutive_rise_days"]:
        return "orange"

    # 3. YELLOW — 重点监控
    if (t["risk_yellow_negative_min"] <= negative <= t["risk_yellow_negative_max"]
            and negative_rate >= t["risk_yellow_negative_rate_min"]):
        return "yellow"
    if is_tracked:
        return "yellow"
    if (negative_rate_7d_avg is not None and negative_rate_7d_avg > 0
            and negative_rate / negative_rate_7d_avg >= t["risk_yellow_7d_ratio_threshold"]):
        return "yellow"

    # 4. GREY — 样本不足
    if total < t["risk_grey_min_total"]:
        return "grey"

    # 5. GREEN / 6. STAR
    if (positive_rate > t["risk_star_positive_rate"]
            and total >= t["risk_star_min_total"]
            and negative < t["risk_star_max_negative"]):
        return "star"

    return "green"


def _theme_severity(count: int) -> str:
    """Map theme count → severity (thresholds.json)."""
    t = config.load_sentiment_thresholds()
    if count >= t["alert_negative_burst"]:
        return "critical"
    if count >= t["theme_severity_high"]:
        return "high"
    if count >= t["theme_severity_medium"]:
        return "medium"
    return "low"


def _creative_key(comment: dict[str, Any]) -> str:
    """Return the best available creative identifier: DAP ID > FB story ID."""
    dap_id = comment.get("dap_id")
    if dap_id:
        return str(dap_id)
    return comment["creative_id"]


def _creative_display_name(comment: dict[str, Any]) -> str:
    """Return best available short name for display."""
    if comment.get("dap_short_name"):
        return comment["dap_short_name"]
    source = comment.get("source", "")
    name = comment.get("creative_name", "")
    if source == "facebook_page":
        return f"[页面帖子] {name}" if name else "[页面帖子]"
    if source == "instagram":
        return f"[IG帖子] {name}" if name else "[IG帖子]"
    return _extract_short_name(name) if name else comment.get("creative_id", "")


def _bucket_by_creative(
    comments: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in comments:
        by_id[_creative_key(c)].append(c)
    return dict(by_id)


def _count_by_sentiment(rows: Iterable[dict[str, Any]]) -> tuple[int, int, int]:
    pos = neu = neg = 0
    for r in rows:
        s = r.get("sentiment")
        if s == "positive":
            pos += 1
        elif s == "neutral":
            neu += 1
        elif s == "negative":
            neg += 1
    return pos, neu, neg


# ── Module 1 — Volume ────────────────────────────────────────


def _build_module_1(
    comments: list[dict[str, Any]],
    *,
    baseline_yesterday_total: float | None,
    baseline_7d_avg_total: float | None,
) -> dict[str, Any]:
    pos, neu, neg = _count_by_sentiment(comments)
    total = pos + neu + neg

    # By language
    by_lang_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in comments:
        by_lang_buckets[c.get("language", "other")].append(c)

    by_language: list[dict[str, Any]] = []
    for lang, rows in by_lang_buckets.items():
        lp, ln, lneg = _count_by_sentiment(rows)
        ltotal = lp + ln + lneg
        by_language.append(
            {
                "language": lang,
                "total": ltotal,
                "positive": lp,
                "neutral": ln,
                "negative": lneg,
                "negative_rate": round(lneg / ltotal, 4) if ltotal else 0.0,
                "vs_7d_avg_pct": None,  # 占位：7d 分语种基线待 DAP 接口
            }
        )
    # Stable ordering: total desc, then language asc for determinism
    by_language.sort(key=lambda x: (-x["total"], x["language"]))

    return {
        "totals": {
            "total": total,
            "positive": pos,
            "neutral": neu,
            "negative": neg,
            "vs_yesterday_pct": _safe_pct_change(total, baseline_yesterday_total),
            "vs_7d_avg_pct": _safe_pct_change(total, baseline_7d_avg_total),
        },
        "by_language": by_language,
    }


# ── Module 2 — Qualitative + Alerts ──────────────────────────


def _format_comment_text(c: dict[str, Any]) -> str:
    text = c.get("text") or ""
    zh = c.get("zh") or ""
    if zh:
        return f"{text}（{zh}）"
    return text


def _aggregate_themes(
    comments: list[dict[str, Any]],
    sentiment: str,
) -> list[dict[str, Any]]:
    bucket: dict[str, dict[str, Any]] = {}
    for c in comments:
        if c.get("sentiment") != sentiment:
            continue
        theme = c.get("theme") or "unclassified"
        slot = bucket.setdefault(
            theme,
            {
                "theme": theme,
                "count": 0,
                "source_creatives": set(),
                "comments": [],
            },
        )
        slot["count"] += 1
        slot["source_creatives"].add(_creative_display_name(c))
        text = _format_comment_text(c)
        if text.strip():
            slot["comments"].append(text)
    out = []
    for slot in bucket.values():
        out.append(
            {
                "theme": slot["theme"],
                "count": slot["count"],
                "source_creatives": sorted(slot["source_creatives"]),
                "comments": list(slot["comments"]),
            }
        )
    out.sort(key=lambda x: (-x["count"], x["theme"]))
    return out


def _aggregate_negative_themes(
    comments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    bucket: dict[str, dict[str, Any]] = {}
    for c in comments:
        if c.get("sentiment") != "negative":
            continue
        theme = c.get("theme") or "unclassified"
        slot = bucket.setdefault(
            theme,
            {
                "category": theme,
                "count": 0,
                "source_creatives": set(),
                "main_languages": set(),
                "comments": [],
            },
        )
        slot["count"] += 1
        slot["source_creatives"].add(_creative_display_name(c))
        slot["main_languages"].add(c.get("language", "other"))
        text = _format_comment_text(c)
        if text.strip():
            slot["comments"].append(text)
    out = []
    for slot in bucket.values():
        out.append(
            {
                "category": slot["category"],
                "count": slot["count"],
                "source_creatives": sorted(slot["source_creatives"]),
                "main_languages": sorted(slot["main_languages"]),
                "severity": _theme_severity(slot["count"]),
                "comments": list(slot["comments"]),
            }
        )
    out.sort(key=lambda x: (-x["count"], x["category"]))
    return out


def _build_alerts(
    comments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """PRD 2.4 重大舆情警报：A / C 两类。"""
    t = config.load_sentiment_thresholds()
    alerts: list[dict[str, Any]] = []

    # Trigger A: per-creative negative count > alert_negative_burst (10)
    neg_counts: Counter[str] = Counter()
    for c in comments:
        if c.get("sentiment") == "negative":
            neg_counts[_creative_key(c)] += 1
    for cid, ncount in neg_counts.items():
        threshold = t["alert_negative_burst"]
        if ncount > threshold:
            alerts.append(
                {
                    "trigger_type": "A_creative_negative_burst",
                    "creative_id": cid,
                    "evidence": {
                        "negative_count": ncount,
                        "threshold": threshold,
                        "exceeded": True,
                        "near_threshold": False,
                    },
                }
            )
        elif ncount >= int(threshold * t["near_threshold_ratio"]):
            alerts.append(
                {
                    "trigger_type": "A_creative_negative_burst",
                    "creative_id": cid,
                    "evidence": {
                        "negative_count": ncount,
                        "threshold": threshold,
                        "exceeded": False,
                        "near_threshold": True,
                    },
                }
            )

    # Trigger C: NotImplementedTrigger placeholder — emitted only when
    # callers explicitly opt in. By default omitted from production reports
    # to avoid noise. Reserved for future signals (e.g. cross-platform
    # virality on TikTok/UAC once those data sources land).
    return alerts


def _build_module_2(
    comments: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "positive_themes": _aggregate_themes(comments, "positive"),
        "neutral_themes": _aggregate_themes(comments, "neutral"),
        "negative_themes": _aggregate_negative_themes(comments),
        "alerts": _build_alerts(comments),
    }


# ── Module 3 — Creative details (sorted by negative DESC) ────


def _extract_short_name(creative_name: str) -> str:
    """Extract short name from DAP naming convention (5th segment, index 4)."""
    if not creative_name:
        return ""
    parts = creative_name.split("_")
    if len(parts) >= 5:
        return parts[4]
    return creative_name


def _top_negative_themes(rows: list[dict[str, Any]], n: int = 3) -> list[str]:
    """Return top-N negative theme names for a set of comments."""
    counts: dict[str, int] = {}
    for r in rows:
        if r.get("sentiment") == "negative":
            theme = r.get("theme") or "unclassified"
            counts[theme] = counts.get(theme, 0) + 1
    return [t for t, _ in sorted(counts.items(), key=lambda x: -x[1])[:n]]


def _dominant_language(rows: list[dict[str, Any]]) -> str:
    """Return the most frequent language code among rows."""
    counts: dict[str, int] = {}
    for r in rows:
        lang = r.get("language", "other")
        counts[lang] = counts.get(lang, 0) + 1
    if not counts:
        return "other"
    return max(counts, key=counts.get)


_SOURCE_LABEL = {
    "facebook_ad": "Facebook广告",
    "facebook_page": "Facebook页面",
    "instagram": "Instagram",
}


def _source_group(comment: dict[str, Any]) -> str:
    return comment.get("source", "facebook_ad")


def _has_theme(rows: list[dict[str, Any]], theme: str) -> bool:
    return any(r.get("theme") == theme for r in rows)


def _count_consecutive_negative_rise(history: list[dict[str, Any]]) -> int:
    if len(history) < 2:
        return 0
    count = 0
    for i in range(len(history) - 1, 0, -1):
        if history[i].get("negative", 0) > history[i - 1].get("negative", 0):
            count += 1
        else:
            break
    return count


def _calc_7d_negative_rate_avg(
    comments_7d: list[dict[str, Any]],
    creative_key: str,
) -> float | None:
    by_creative = defaultdict(list)
    for c in comments_7d:
        by_creative[_creative_key(c)].append(c)
    rows = by_creative.get(creative_key, [])
    if not rows:
        return None
    _, _, neg_7d = _count_by_sentiment(rows)
    total_7d = len(rows)
    if total_7d == 0:
        return None
    return neg_7d / total_7d


def _build_module_3(
    comments: list[dict[str, Any]],
    *,
    tracking_state: dict[str, Any] | None = None,
    comments_7d: list[dict[str, Any]] | None = None,
    alerts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tracked_ids = set()
    tracking_history: dict[str, list[dict]] = {}
    if tracking_state:
        for entry in tracking_state.get("entries", []):
            tracked_ids.add(entry["creative_id"])
            tracking_history[entry["creative_id"]] = entry.get("history", [])

    by_creative = _bucket_by_creative(comments)
    creatives: list[dict[str, Any]] = []
    for cid, rows in by_creative.items():
        pos, neu, neg = _count_by_sentiment(rows)
        total = pos + neu + neg
        rate = round(neg / total, 4) if total else 0.0
        raw_name = rows[0].get("creative_name", "")
        dap_id = rows[0].get("dap_id")
        if not dap_id and raw_name:
            import re
            m = re.search(r"_(\d{4,})$", raw_name)
            if m:
                dap_id = int(m.group(1))
        source = _source_group(rows[0])
        display_name = _creative_display_name(rows[0])
        display_id = str(dap_id) if dap_id else cid
        dap_lang = rows[0].get("dap_language")

        history = tracking_history.get(cid, [])
        consecutive_rise = _count_consecutive_negative_rise(history + [{"negative": neg}])
        neg_rate_7d = _calc_7d_negative_rate_avg(comments_7d or [], cid)

        risk = _risk_level(
            negative=neg,
            total=total,
            positive=pos,
            has_political_sensitive=_has_theme(rows, "political_sensitive"),
            is_tracked=cid in tracked_ids,
            consecutive_rise_days=consecutive_rise,
            negative_rate_7d_avg=neg_rate_7d,
        )

        creatives.append(
            {
                "creative_id": display_id,
                "creative_name": raw_name,
                "dap_id": dap_id,
                "short_name": display_name,
                "label": f"{display_id} {display_name}",
                "source": source,
                "dominant_language": dap_lang or _dominant_language(rows),
                "total": total,
                "positive": pos,
                "neutral": neu,
                "negative": neg,
                "negative_rate": rate,
                "negative_themes_top3": _top_negative_themes(rows),
                "risk_level": risk,
            }
        )
    creatives.sort(key=lambda x: (-x["negative"], -x["total"], x["creative_id"]))

    groups: dict[str, list[dict[str, Any]]] = {}
    for c in creatives:
        groups.setdefault(c["source"], []).append(c)

    return {
        "creatives": creatives,
        "by_source": {_SOURCE_LABEL.get(k, k): v for k, v in groups.items()},
    }


# ── Module 4 — Tracking ──────────────────────────────────────


def _remove_entry(state: dict[str, Any], creative_id: str) -> dict[str, Any]:
    """Return a NEW state with the given creative_id removed (immutable)."""
    return {
        **state,
        "entries": [e for e in state.get("entries", []) if e["creative_id"] != creative_id],
    }


def _build_module_4(
    tracking_state: dict[str, Any] | None,
    today_creatives: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
    snapshot_date: str,
) -> dict[str, Any]:
    """Evaluate today's creative data against enter/exit tracking criteria.

    For each creative in today_creatives:
    - If already tracked and should exit -> remove from tracking.
    - If already tracked and should not exit -> upsert with today's data.
    - If not tracked and should enter -> upsert as new entry.
    """
    from . import tracking_store as ts

    state = tracking_state or {"entries": []}
    alerted_ids = {a["creative_id"] for a in alerts}

    creative_names = {c["creative_id"]: c.get("short_name", "") for c in today_creatives}

    for c in today_creatives:
        cid = c["creative_id"]
        neg = c["negative"]
        rate = c["negative_rate"]
        had_alert = cid in alerted_ids

        existing = next((e for e in state["entries"] if e["creative_id"] == cid), None)
        history = existing["history"] if existing else []
        history_with_today = [*history, {"date": snapshot_date, "negative": neg, "negative_rate": rate}]

        if existing:
            if ts.should_exit_tracking(history_with_today):
                state = _remove_entry(state, cid)
            else:
                trend = ts.derive_trend(history_with_today)
                state = ts.upsert(state, creative_id=cid, snapshot_date=snapshot_date,
                                  negative=neg, negative_rate=rate, trend=trend)
        else:
            cumulative = sum(h.get("negative", 0) for h in history_with_today)
            if ts.should_enter_tracking(history_with_today, cumulative_negative=cumulative, had_major_alert=had_alert):
                trend = ts.derive_trend(history_with_today)
                state = ts.upsert(state, creative_id=cid, snapshot_date=snapshot_date,
                                  negative=neg, negative_rate=rate, trend=trend)

    enriched = []
    for e in state.get("entries", []):
        enriched.append({**e, "short_name": creative_names.get(e["creative_id"], "")})
    return {"entries": enriched}


# ── Module 5 — Actions ───────────────────────────────────────


def _build_module_5(
    creatives: list[dict[str, Any]],
) -> dict[str, Any]:
    t = config.load_sentiment_thresholds()
    pause: list[dict[str, Any]] = []
    scale: list[dict[str, Any]] = []
    observe: list[dict[str, Any]] = []
    for c in creatives:
        rate = c["negative_rate"]
        risk = c["risk_level"]
        base = {"creative_id": c["creative_id"], "short_name": c.get("short_name", "")}
        if risk == "red":
            pause.append({
                **base,
                "reason": f"负面率{rate:.0%}, 风险={risk}",
                "data": f"负面{c['negative']}条/总{c['total']}条",
            })
        elif risk == "yellow":
            observe.append({
                **base,
                "reason": f"负面率{rate:.0%}, 风险={risk}",
                "data": f"负面{c['negative']}条/总{c['total']}条",
            })
        elif risk == "star":
            pos_rate = c["positive"] / c["total"] if c.get("total") else 0
            scale.append({
                **base,
                "reason": f"积极率{pos_rate:.0%}, 总数{c.get('total', 0)}",
                "data": f"积极{c['positive']}条/总{c['total']}条",
            })
    return {"pause": pause, "scale": scale, "observe": observe}


# ── Top-level builder ────────────────────────────────────────


def build_report(
    comments: list[dict[str, Any]],
    *,
    product: str,
    channel: str = "facebook",
    window_start: str,
    window_end: str,
    generated_at: str,
    baseline_yesterday_total: float | None = None,
    baseline_7d_avg_total: float | None = None,
    tracking_state: dict[str, Any] | None = None,
    comments_7d: list[dict[str, Any]] | None = None,
    doc_url: str | None = None,
    degradation_flag: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the full report — keys emitted in PRD order (1→2→3→4→5).

    ``degradation_flag``: if classify() reported any fallback events, pass
    the diagnostics dict here. Stored under ``meta.degradation_flag`` so
    consumers can detect partial-fallback labels (schema-validated).
    """
    module_1 = _build_module_1(
        comments,
        baseline_yesterday_total=baseline_yesterday_total,
        baseline_7d_avg_total=baseline_7d_avg_total,
    )
    module_2 = _build_module_2(comments)
    module_3 = _build_module_3(
        comments,
        tracking_state=tracking_state,
        comments_7d=comments_7d,
        alerts=module_2["alerts"],
    )
    module_4 = _build_module_4(
        tracking_state,
        today_creatives=module_3["creatives"],
        alerts=module_2["alerts"],
        snapshot_date=window_end[:10],
    )
    module_5 = _build_module_5(module_3["creatives"])

    return {
        "meta": {
            "product": product,
            "channel": channel,
            "window_start": window_start,
            "window_end": window_end,
            "generated_at": generated_at,
            "doc_url": doc_url,
            "degradation_flag": degradation_flag,
        },
        "module_1_volume": module_1,
        "module_2_qualitative": module_2,
        "module_3_creative_details": module_3,
        "module_4_tracking": module_4,
        "module_5_actions": module_5,
    }
