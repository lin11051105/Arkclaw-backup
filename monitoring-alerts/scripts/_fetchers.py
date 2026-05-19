"""Callback wrappers for monitoring-alerts.

Provides factory functions that return closures matching the signatures
expected by balance_checker, gap_checker, roi_progress, daily_monitor,
and trend_detector.

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
from lib.fetchers import make_fetch_custom_report, make_fetch_material_report
from lib.fetchers import make_fetch_insights as _make_fetch_insights
from lib.fetchers import list_all_account_ids as _shared_list_all_account_ids
from lib.fetchers import make_fetch_skan_by_game_day  # noqa: F401  iOS path (T7)


# ═══════════════════════════════════════════════════════════════════════════
# Unique to this skill
# ═══════════════════════════════════════════════════════════════════════════

def make_fetch_account_info(account_id: str | None = None) -> Callable[[], dict]:
    """Return fn() -> {"balance": float, "currency": str, ...}.

    Used by: balance_checker.check_account_balance
    Queries ads-channel for account info.
    """
    def fetch() -> dict:
        client_mod = _load("ads-channel", "facebook", "client")
        client = client_mod.MetaAdsClient(account_id=account_id)
        info = client.get_account_info()
        return info
    return fetch


# ═══════════════════════════════════════════════════════════════════════════
# Facebook Insights fetcher (wraps shared factory with local _load)
# ═══════════════════════════════════════════════════════════════════════════

def make_fetch_insights(account_ids: list[str] | None = None) -> Callable[..., list[dict]]:
    """Return fn(date_start, date_end, level, **kw) -> list[dict].

    Used by: balance_checker.check_account_balance, gap_checker.check_data_gap
    Wraps ads-channel insights_manager.get_ad_insights.
    account_ids: 传入则遍历所有账户汇总；不传则只查 .env 默认账户。
    """
    return _make_fetch_insights(_load, account_ids=account_ids)


def _list_all_account_ids(name_filter: str | None = None) -> list[str]:
    return _shared_list_all_account_ids(_load, name_filter=name_filter)
