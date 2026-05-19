"""Sentiment classification cache.

Stores per-comment classification results (sentiment + theme) to avoid
re-calling LLM for comments already classified in previous runs.

Cache file: workspace/memory/sentiment-cache/{product}.json
Auto-expires entries older than 8 days.

IMPORTANT: Degraded results (timeout/error fallbacks to neutral/unclassified)
are NOT cached. They will be re-classified on the next run.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import config

_log = logging.getLogger(__name__)

_CACHE_DIR = config._WORKSPACE_DIR / "memory" / "sentiment-cache"
_EXPIRE_DAYS = 8


def _cache_path(product: str) -> Path:
    return _CACHE_DIR / f"{product.lower()}.json"


def load_cache(product: str) -> dict[str, dict[str, str]]:
    p = _cache_path(product)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("comments", {})
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(product: str, comments: dict[str, dict[str, str]]) -> None:
    p = _cache_path(product)
    p.parent.mkdir(parents=True, exist_ok=True)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_EXPIRE_DAYS)).isoformat()
    pruned = {
        cid: entry for cid, entry in comments.items()
        if entry.get("cached_at", "") >= cutoff
    }
    p.write_text(
        json.dumps({"comments": pruned}, ensure_ascii=False),
        encoding="utf-8",
    )


def apply_cache(
    comments: list[dict[str, Any]],
    cache: dict[str, dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split comments into cached (already classified) and uncached (need LLM).

    Returns:
        (cached_comments, uncached_comments)
    """
    cached = []
    uncached = []
    for c in comments:
        cid = c.get("id", "")
        if cid in cache:
            entry = cache[cid]
            row = {
                **c,
                "sentiment": entry["sentiment"],
                "theme": entry["theme"],
            }
            if entry.get("zh"):
                row["zh"] = entry["zh"]
            cached.append(row)
        else:
            uncached.append(c)
    return cached, uncached


def update_cache(
    cache: dict[str, dict[str, str]],
    classified: list[dict[str, Any]],
    *,
    degraded_ids: set[str] | None = None,
) -> dict[str, dict[str, str]]:
    """Add newly classified comments to cache.

    Degraded results (IDs in degraded_ids) are excluded from cache
    so they get re-classified on the next run.
    """
    now = datetime.now(timezone.utc).isoformat()
    updated = dict(cache)
    skip_ids = degraded_ids or set()
    for c in classified:
        cid = c.get("id", "")
        if not cid or cid in skip_ids:
            continue
        sentiment = c.get("sentiment")
        theme = c.get("theme")
        if not sentiment or sentiment == "neutral" and theme == "unclassified":
            continue
        entry = {
            "sentiment": sentiment,
            "theme": theme or "unclassified",
            "cached_at": now,
        }
        zh = c.get("zh")
        if zh and isinstance(zh, str) and zh.strip():
            entry["zh"] = zh.strip()
        updated[cid] = entry
    return updated
