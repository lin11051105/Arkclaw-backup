"""Callback wrappers for channel-summary.

Provides factory functions that return closures matching the signatures
expected by channel_aggregator and cpe_achievement.

DAP calls and Facebook Insights calls delegate to shared lib/fetchers.
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
from lib.fetchers import call_dap, make_fetch_custom_report
from lib.fetchers import make_fetch_insights as _make_fetch_insights
from lib.fetchers import make_fetch_skan_by_channel_day  # noqa: F401  (re-exported for CLI)


# ═══════════════════════════════════════════════════════════════════════════
# Facebook Insights fetcher (wraps shared factory with local _load)
# ═══════════════════════════════════════════════════════════════════════════

def make_fetch_insights(account_ids: list[str] | None = None) -> Callable[..., list[dict]]:
    """Return fn(date_start, date_end, level, **kw) -> list[dict].

    Used by: cpe_achievement.check_cpe_achievement
    Wraps ads-channel insights_manager.get_ad_insights.

    Args:
        account_ids: Optional list of Facebook ad account IDs. Results from all accounts
                     are concatenated. If None, uses META_AD_ACCOUNT_ID env var.
    """
    return _make_fetch_insights(_load, account_ids=account_ids)
