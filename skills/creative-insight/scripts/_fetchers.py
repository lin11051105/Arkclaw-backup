"""Callback wrappers for creative-insight.

Provides factory functions that return closures matching the signatures
expected by volume_filter and tag_analyzer.

DAP calls delegate to shared lib/fetchers.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lib.fetchers import make_fetch_material_report
