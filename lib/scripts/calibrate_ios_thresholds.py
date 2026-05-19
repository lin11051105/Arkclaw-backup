"""One-off CLI: 30-day SKAN backfill -> recommended iOS threshold JSON.

Output of this script feeds Task 5 (``workspace/config/thresholds.json``) by
seeding the ``daily_monitoring_ios`` and ``roi_progress_ios`` blocks from
each game's observed cpi/skan_roi distribution.

Public surface (3 pure helpers + 1 IO-touching entry):
- ``compute_percentiles(values)`` -> ``{"p50", "p75", "p90"}``.
- ``recommend_thresholds(cpi, roi)`` -> threshold dict with safety floors.
- ``calibrate_for_game(game_id, lookback_days=30)`` -> per-game summary
  (calls ``fetch_skan_by_game_day``).
- ``main(argv=None)`` -> CLI entry: prints JSON array to stdout.

CLI contract::

    python -m workspace.skills.lib.scripts.calibrate_ios_thresholds \\
        --games 10043,10046,10048 [--lookback-days 30]

Each output array element has the shape documented on
``calibrate_for_game``.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import date, timedelta
from typing import Any

from ..skan_repo import fetch_skan_by_game_day

# Safety floors -- distribution can be too tight to derive a useful spike
# percentage. We keep monitoring sensitive even when the historical data
# barely fluctuated.
_CPI_SPIKE_FLOOR: float = 0.30
_DEVIATION_ALERT_FLOOR: float = 0.10
_SKAN_POSTBACK_BUFFER_DAYS: int = 2


def compute_percentiles(values: list[float]) -> dict[str, float]:
    """Return p50/p75/p90 of ``values`` using the inclusive method.

    - Empty input -> all zeros (no exception).
    - Single value -> all three percentiles equal that value (statistics
      module rejects n=1, so we short-circuit).
    """
    if not values:
        return {"p50": 0.0, "p75": 0.0, "p90": 0.0}
    if len(values) == 1:
        v = float(values[0])
        return {"p50": v, "p75": v, "p90": v}

    cuts = statistics.quantiles(values, n=100, method="inclusive")
    # quantiles returns 99 cut points (indices 0..98 represent the 1st..99th
    # percentiles). We want p50, p75, p90 which sit at indices 49, 74, 89.
    return {
        "p50": float(cuts[49]),
        "p75": float(cuts[74]),
        "p90": float(cuts[89]),
    }


def _safe_relative_spread(p50: float, p_high: float, floor: float) -> float:
    """Return ``max(floor, (p_high - p50) / p50)``, treating p50<=0 as floor."""
    if p50 <= 0:
        return floor
    return max(floor, (p_high - p50) / p50)


def recommend_thresholds(
    cpi: dict[str, float], roi: dict[str, float],
) -> dict[str, Any]:
    """Build the iOS thresholds blocks from cpi/roi percentile dicts.

    The constants in ``daily_monitoring_ios`` (baseline weights, spend
    spike/drop, ctr/cvr drops) are stable across the fleet; only
    ``cpi_spike_pct`` and ``deviation_alert_pct`` are derived from the
    distribution. Both have safety floors (0.30 / 0.10) so a flat
    distribution still produces sensitive monitoring.
    """
    cpi_spike_pct = _safe_relative_spread(
        cpi.get("p50", 0.0), cpi.get("p90", 0.0), _CPI_SPIKE_FLOOR,
    )
    deviation_alert_pct = _safe_relative_spread(
        roi.get("p50", 0.0), roi.get("p75", 0.0), _DEVIATION_ALERT_FLOOR,
    )
    return {
        "daily_monitoring_ios": {
            "baseline_7d_weight": 0.6,
            "baseline_30d_weight": 0.4,
            "spend_spike_pct": 0.5,
            "spend_drop_pct": 0.3,
            "cpi_spike_pct": cpi_spike_pct,
            "ctr_drop_pct": 0.25,
            "cvr_drop_pct": 0.25,
            "delay_hours": 72,
        },
        "roi_progress_ios": {
            "deviation_alert_pct": deviation_alert_pct,
            "delay_hours": 72,
        },
    }


def calibrate_for_game(game_id: int, lookback_days: int = 30) -> dict[str, Any]:
    """Run the calibration pipeline for one game over ``lookback_days``.

    The window ends 2 days before today (SKAN postback delay buffer) and
    spans ``lookback_days`` calendar days backwards from there. Non-zero
    cpi and skan_roi values are extracted to two distributions; both are
    summarized by p50/p75/p90 and fed to ``recommend_thresholds``.
    """
    today = date.today()
    end = (today - timedelta(days=_SKAN_POSTBACK_BUFFER_DAYS)).isoformat()
    start = (today - timedelta(days=_SKAN_POSTBACK_BUFFER_DAYS + lookback_days)).isoformat()

    rows = fetch_skan_by_game_day(int(game_id), start, end)

    cpi_values = [
        float(r["cpi"]) for r in rows
        if r.get("cpi") is not None and float(r.get("cpi") or 0.0) > 0
    ]
    roi_values = [
        float(r["skan_roi"]) for r in rows
        if r.get("skan_roi") is not None and float(r.get("skan_roi") or 0.0) > 0
    ]

    cpi_dist = compute_percentiles(cpi_values)
    roi_dist = compute_percentiles(roi_values)
    thresholds = recommend_thresholds(cpi=cpi_dist, roi=roi_dist)

    return {
        "game_id": int(game_id),
        "lookback_days": int(lookback_days),
        "sample_count": len(rows),
        "cpi_distribution": cpi_dist,
        "roi_distribution": roi_dist,
        "thresholds": thresholds,
    }


def _parse_games(raw: str) -> list[int]:
    """Parse ``--games`` CSV string into a list of ints, ignoring blanks."""
    return [int(s.strip()) for s in raw.split(",") if s.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="calibrate_ios_thresholds",
        description="Calibrate iOS monitoring thresholds from 30-day SKAN data.",
    )
    parser.add_argument(
        "--games",
        required=True,
        help="Comma-separated game_ids (e.g. 10043,10046,10048).",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=30,
        help="Days of history to sample (default: 30).",
    )
    ns = parser.parse_args(argv)

    games = _parse_games(ns.games)
    out = [calibrate_for_game(g, ns.lookback_days) for g in games]
    json.dump(out, sys.stdout, indent=2, default=float)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover -- CLI shim
    raise SystemExit(main())
