"""24h FB ad comment fetcher.

Reuses ads-channel.facebook.client.MetaAdsClient via the standard skill
loader (see workspace/skills/lib/loader.py). Does NOT instantiate
``requests`` or ``facebook_business`` directly.

`MetaAdsClient.fetch_ad_comments` is expected to land in ads-channel as a
follow-up; meanwhile we duck-type any object that exposes the method.
"""
from __future__ import annotations

import importlib.util
import logging
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import config

_log = logging.getLogger(__name__)

# ── Cross-skill loader bootstrap (per repo convention) ──────
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

# ── Cross-skill shared fetcher import (per creative_health.py convention) ──
_SKILLS_ROOT = str(Path(__file__).resolve().parents[2])
if _SKILLS_ROOT not in sys.path:
    sys.path.insert(0, _SKILLS_ROOT)
from lib.fetchers import list_all_account_ids as _shared_list_all_account_ids


def _get_meta_ads_client(account_id: str | None = None) -> Any:
    """Return a MetaAdsClient instance (or compatible duck).

    Indirected so tests can monkeypatch this single seam instead of mocking
    facebook_business globally.
    """
    client_mod = _load("ads-channel", "facebook", "client")
    return client_mod.MetaAdsClient(account_id=account_id)


def compute_window(snapshot: datetime) -> tuple[datetime, datetime]:
    """Return ``(start, end)`` for the 24h rolling window ending at *snapshot*.

    The window end is anchored to the most recent 18:00 boundary at or before
    *snapshot* (PDF spec: daily report runs at 18:00).  If *snapshot* is exactly
    18:00 the anchor equals *snapshot*; if it is 18:15 the anchor is the same-day
    18:00; if it is 10:00 the anchor is the previous day's 18:00.

    Raises ``ValueError`` if *snapshot* is a naive (timezone-unaware) datetime.
    """
    if snapshot.tzinfo is None:
        raise ValueError("snapshot must be timezone-aware")
    anchor = snapshot.replace(hour=18, minute=0, second=0, microsecond=0)
    if anchor > snapshot:
        anchor -= timedelta(days=1)
    end = anchor
    t = config.load_sentiment_thresholds()
    start = end - timedelta(hours=t["rolling_window_hours"])
    return start, end


def _normalize_language(raw: str | None) -> str:
    """Lowercase ISO-639-1, or 'other' for missing/non-string values."""
    if not raw or not isinstance(raw, str):
        return "other"
    return raw.strip().lower()


# ── Gap 2: character-range language detection ─────────────────────────
# FB API does not return comment language; we infer from character sets
# and common word markers to produce the RU/EN/ES/PT breakdown the PDF
# requires.  No external dependency needed.

_CYRILLIC_RE = re.compile(r'[Ѐ-ӿ]')
_CJK_RE = re.compile(r'[一-鿿぀-ヿ]')

_ES_MARKERS = (
    '¿', '¡', 'está', 'esto', 'juego', 'pero',
    'como', 'para', 'muy', 'tiene', 'hacer',
)
_PT_MARKERS = (
    'não', 'jogo', 'você', 'muito', 'também',
    'porque', 'isso', 'está', 'fazer', 'ão',
)


def _detect_language(text: str) -> str:
    """Simple language detection by character set and common words.

    Returns an ISO-639-1 code: ``"ru"``, ``"es"``, ``"pt"``, ``"en"``,
    or ``"other"`` for CJK / too-short / unrecognised text.
    """
    if not text or len(text.strip()) < 3:
        return "other"

    # Cyrillic -> Russian
    if _CYRILLIC_RE.search(text):
        return "ru"

    # CJK -> other (Chinese/Japanese/Korean)
    if _CJK_RE.search(text):
        return "other"

    text_lower = text.lower()

    # Spanish markers
    if any(m in text_lower for m in _ES_MARKERS):
        return "es"

    # Portuguese markers
    if any(m in text_lower for m in _PT_MARKERS):
        return "pt"

    # Default to English for Latin script
    return "en"


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Produce a canonical comment dict for downstream stages."""
    raw_lang = _normalize_language(row.get("language"))
    if raw_lang == "other":
        raw_lang = _detect_language(row.get("text", ""))
    return {
        "id": str(row.get("id", "")),
        "creative_id": str(row.get("creative_id", "")),
        "creative_name": str(row.get("creative_name", "")),
        "language": raw_lang,
        "text": str(row.get("text", "")),
        "likes": int(row.get("likes", 0) or 0),
        "replies": int(row.get("replies", 0) or 0),
        "created_at": str(row.get("created_at", "")),
        # Sentiment + theme are populated by the classifier later
        "sentiment": row.get("sentiment"),
        "theme": row.get("theme"),
    }


def fetch_comments(
    *,
    snapshot: datetime,
    product: str = "Pgame",
    limit: int = 1000,
    window_hours: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch & normalize FB ad comments within a rolling window.

    Args:
        snapshot: window-end datetime (timezone-aware).
        product:  product name used to discover FB ad accounts via
                  ``list_all_account_ids(name_filter=product)``.
        limit:    upper bound on comments returned (FB pagination).
        window_hours: override window size in hours (default: use compute_window 24h).

    Returns:
        List of normalized comment dicts with stable shape.
    """
    if window_hours:
        end = snapshot
        start = end - timedelta(hours=window_hours)
    else:
        start, end = compute_window(snapshot)

    # Discover accounts by product name (e.g. "PGame" matches
    # "Lilith-PGame-FB-CE专项-SINO-01").  Falls back to the default
    # account from env when no matches are found.
    all_account_ids = _shared_list_all_account_ids(_load, name_filter=product)
    account_id = all_account_ids[0] if all_account_ids else None
    _log.info("fetch_comments: product=%s → account=%s", product, account_id or "default")

    client = _get_meta_ads_client(account_id)

    if not hasattr(client, "fetch_ad_comments"):
        raise NotImplementedError(
            "ads-channel.MetaAdsClient.fetch_ad_comments is not yet "
            "available. This skill requires ads-channel to expose a "
            "comment-listing API for the FB ad account."
        )

    from lib.fetchers import get_app_config, get_fb_config
    import json
    _ws = Path(__file__).resolve().parents[3]
    _apps = json.loads((_ws / "config" / "apps.json").read_text(encoding="utf-8"))
    app = get_app_config({"apps": _apps}, product.upper())
    page_id = get_fb_config(app, "page_id") or None

    raw_rows = client.fetch_ad_comments(start=start, end=end, limit=limit, page_id=page_id)
    _log.info(
        "fetch_comments: account=%s window=[%s, %s] rows=%d",
        getattr(client, "account_id", "?"),
        start.isoformat(),
        end.isoformat(),
        len(raw_rows),
    )
    return [_normalize_row(r) for r in raw_rows]
