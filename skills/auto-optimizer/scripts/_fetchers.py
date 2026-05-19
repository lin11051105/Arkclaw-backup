"""Callback wrappers for auto-optimizer.

Provides factory functions that return closures matching the signatures
expected by campaign_decay, high_risk_checker, and budget_adjuster.

Facebook Insights calls delegate to shared lib/fetchers.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Callable

_SCRIPTS = Path(__file__).resolve().parent
_loader_spec = importlib.util.spec_from_file_location("_loader", _SCRIPTS.parents[1] / "lib" / "loader.py")
_loader = importlib.util.module_from_spec(_loader_spec); _loader_spec.loader.exec_module(_loader)
_load = _loader.make_loader(__file__)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lib.fetchers import make_fetch_insights as _make_fetch_insights


# ═══════════════════════════════════════════════════════════════════════════
# Facebook Insights fetcher (wraps shared factory with local _load)
# ═══════════════════════════════════════════════════════════════════════════

def make_fetch_insights() -> Callable[..., list[dict]]:
    """Return fn(date_start, date_end, level, **kw) -> list[dict].

    Used by: decay (campaign-level CPI time series), high-risk (spend+ROI).
    Wraps ads-channel insights_manager.get_ad_insights.
    """
    return _make_fetch_insights(_load)
