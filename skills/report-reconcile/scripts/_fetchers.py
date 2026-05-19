"""Callback wrappers for report-reconcile.

Provides factory functions that return closures matching the signatures
expected by report_generator and reconciliation.

DAP calls and Facebook Insights calls delegate to shared lib/fetchers.
Channel summary calls use channel-summary's channel_aggregator.
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
from lib.fetchers import list_all_account_ids as _list_all_account_ids
from lib.fetchers import make_fetch_skan_by_game_day  # noqa: F401  iOS path (T8)


# ═══════════════════════════════════════════════════════════════════════════
# Facebook Insights fetcher (wraps shared factory with local _load)
# ═══════════════════════════════════════════════════════════════════════════

def make_fetch_insights(all_accounts: bool = False) -> Callable[..., list[dict]]:
    """Return fn(date_start, date_end, level, **kw) -> list[dict].

    Used by: reconciliation.run_reconciliation
    all_accounts=True → query all Active Facebook accounts (for reconciliation).
    """
    account_ids = _list_all_account_ids(_load) if all_accounts else None
    return _make_fetch_insights(_load, account_ids=account_ids)


# ═══════════════════════════════════════════════════════════════════════════
# Channel summary fetcher (cross-skill dependency, unique to this skill)
# ═══════════════════════════════════════════════════════════════════════════

def make_fetch_channel_summary() -> Callable[[str, str, str], str]:
    """Return fn(project_id, start, end) -> markdown str.

    Used by: report_generator.generate_report (optional)
    Calls channel-summary's channel_aggregator internally.
    """
    def fetch(project_id: str, start: str, end: str) -> str:
        aggregator_mod = _load("channel-summary", "channel_aggregator")
        # Build a local DAP fetcher for channel_aggregator (route by game).
        # Reconciliation focuses on Android (DAP probabilistic attribution); iOS
        # truth comes from SKAN via report_generator's separate ios_rows path,
        # so we lock os="android" here to avoid hitting the SKAN view.
        fetch_cr = make_fetch_custom_report(game=project_id)
        result = aggregator_mod.run_channel_summary(
            start,
            end,
            config={},
            fetch_custom_report=fetch_cr,
            os="android",
        )
        return result.get("markdown", "")
    return fetch
