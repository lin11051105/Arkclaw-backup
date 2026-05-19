"""DAP material lookup — delegates to lib/dap_client.py.

Thin wrapper preserving the existing API surface for sentiment-daily-report.
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)
_SCRIPTS = Path(__file__).resolve().parent

_dap_client_mod = None


def _load_dap_client():
    global _dap_client_mod
    if _dap_client_mod is not None:
        return _dap_client_mod
    path = _SCRIPTS.parents[1] / "lib" / "dap_client.py"
    spec = importlib.util.spec_from_file_location("dap_client", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load dap_client from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _dap_client_mod = mod
    return mod


def extract_dap_id(fb_ad_name: str) -> int | None:
    return _load_dap_client().extract_dap_id(fb_ad_name)


def batch_resolve_materials(fb_ad_names: list[str]) -> dict[str, dict[str, Any]]:
    mod = _load_dap_client()
    try:
        client = mod.DapHttpClient()
    except ValueError:
        _log.warning("DAP_API_TOKEN not set, skipping material lookup")
        return {}
    return client.batch_resolve_fb_names(fb_ad_names)
