"""Tracking-state persistence (PRD Module 4 — 持续跟踪重点素材).

State is stored at ``workspace/memory/sentiment-tracking/{product_lower}.json``,
one JSON document per product. The schema mirrors module_4_tracking in
report_schema.json.

All transformation helpers return NEW state objects (immutability rule).

BLOCKED ON PRD module 4: ``upsert`` / ``save`` / ``derive_trend`` 路径目前不可
达——PM 尚未定义 first_flagged_at / days_tracked / resolved 状态机的语义闭环
（phase4 r7 IC-V6 标注）。在 PRD 给出最终判定规则之前，这些 API 保留 do_not_
return 契约：现有调用方仅消费 ``load`` 返回的只读快照，写路径走 dry-run。
"""
from __future__ import annotations

import json
import logging
from datetime import date as _date_t
from pathlib import Path
from typing import Any

from . import config

_log = logging.getLogger(__name__)

# Allow tests to monkeypatch a tmp_path; default lives under workspace/memory/.
TRACKING_DIR: Path = config.TRACKING_DIR


def tracking_path(product: str) -> Path:
    """Return the JSON file path for ``product`` (e.g. ``Pgame`` →
    ``…/sentiment-tracking/pgame.json``)."""
    return Path(TRACKING_DIR) / f"{product.lower()}.json"


def load(product: str) -> dict[str, Any]:
    """Load tracking state, or a fresh empty container if file is missing."""
    p = tracking_path(product)
    if not p.exists():
        return {"product": product, "entries": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        _log.error("Tracking state corrupted at %s: %s", p, e)
        # Fail closed: return empty rather than crash the whole report.
        return {"product": product, "entries": []}


def save(product: str, state: dict[str, Any]) -> Path:
    """Persist tracking state atomically (write-then-rename)."""
    p = tracking_path(product)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(p)
    return p


def upsert(
    state: dict[str, Any],
    *,
    creative_id: str,
    snapshot_date: str,
    negative: int,
    negative_rate: float,
    trend: str,
) -> dict[str, Any]:
    """Return a NEW state with the creative's tracking entry updated.

    - First time seen: append new entry, days_tracked=1.
    - Subsequent days: append history row, increment days_tracked, refresh trend.

    Never mutates the input.
    """
    entries = state.get("entries", [])
    history_row = {
        "date": snapshot_date,
        "negative": int(negative),
        "negative_rate": round(float(negative_rate), 4),
    }

    for i, entry in enumerate(entries):
        if entry["creative_id"] == creative_id:
            updated_history = [*entry["history"], history_row]
            updated_entry = {
                **entry,
                "history": updated_history,
                "days_tracked": len(updated_history),
                "trend": trend,
            }
            return {
                **state,
                "entries": [*entries[:i], updated_entry, *entries[i + 1:]],
            }

    return {
        **state,
        "entries": [
            *entries,
            {
                "creative_id": creative_id,
                "first_flagged_at": snapshot_date,
                "days_tracked": 1,
                "trend": trend,
                "history": [history_row],
            },
        ],
    }


def derive_trend(history: list[dict[str, Any]]) -> str:
    """Heuristic trend over the last few snapshots based on negative_rate.

    判断顺序（phase4_review HIGH 修复，确保 resolved 可达）::

        resolved   ← 历史曾达到/超过 watch(0.30) 且最新跌破 safe(0.10)
        worsening  ← 最新比上一帧上升 > 5pp
        improving  ← 最新比上一帧下降 > 5pp
        stable     ← 其余情况

    改前 worsening → improving → resolved → stable 的顺序导致
    rate 大幅下降时 improving 先命中，resolved 永远走不到。
    """
    if not history:
        return "stable"
    if len(history) == 1:
        return "stable"

    t = config.load_sentiment_thresholds()
    safe_threshold = t["risk_yellow_negative_rate_min"]  # below this → green
    watch_threshold = t["risk_red_negative_rate"]  # above this → red

    last = history[-1]["negative_rate"]
    prev = history[-2]["negative_rate"]
    historic_max = max(row["negative_rate"] for row in history)

    # resolved 必须早于 improving 判断，否则跌破 safe 时永远命中 improving。
    if last < safe_threshold and historic_max >= watch_threshold:
        return "resolved"
    if last > prev + 0.05:
        return "worsening"
    if last < prev - 0.05:
        return "improving"
    return "stable"


def should_enter_tracking(
    recent_history: list[dict],
    *,
    cumulative_negative: int,
    had_major_alert: bool,
) -> bool:
    """Evaluate whether a creative should enter continuous tracking.

    Conditions (any one triggers entry):
    1. ``had_major_alert`` is True (module 2 alert fired).
    2. ``cumulative_negative`` >= threshold (default 20).
    3. Last N consecutive days each had >= daily_min negatives.
    """
    t = config.load_sentiment_thresholds()
    if had_major_alert:
        return True
    if cumulative_negative >= t["tracking_enter_cumulative_negative"]:
        return True
    consecutive_days = t["tracking_enter_consecutive_days"]
    daily_min = t["tracking_enter_daily_negative_min"]
    if len(recent_history) >= consecutive_days:
        tail = recent_history[-consecutive_days:]
        if all(d.get("negative", 0) >= daily_min for d in tail):
            return True
    return False


def should_exit_tracking(recent_history: list[dict]) -> bool:
    """Evaluate whether a creative should exit continuous tracking.

    Condition: last N days all have zero negatives.
    """
    t = config.load_sentiment_thresholds()
    clean_days = t["tracking_exit_clean_days"]
    if len(recent_history) < clean_days:
        return False
    tail = recent_history[-clean_days:]
    return all(d.get("negative", 0) == 0 for d in tail)


def today_iso() -> str:
    """Return today's date as YYYY-MM-DD (system local)."""
    return _date_t.today().isoformat()
