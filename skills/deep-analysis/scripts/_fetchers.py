"""Callback wrappers for deep-analysis.

Provides factory functions that return closures matching the signatures
expected by contribution_decomposer and marginal_roi.

DAP calls delegate to shared lib/fetchers.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lib.fetchers import call_dap, make_fetch_custom_report, make_fetch_material_report
