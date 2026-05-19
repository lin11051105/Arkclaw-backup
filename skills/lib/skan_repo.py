"""SKAN-specific query helpers built on lib.dw_client.

Public surface (4 functions):
- ``fetch_skan_by_game_day(game_id, dt_start, dt_end)``
- ``fetch_skan_by_channel_day(game_id, dt_start, dt_end)``
- ``fetch_skan_by_campaign_day(game_id, dt_start, dt_end)``
- ``fetch_calibration_factor(game_id, channel, lookback_days=30) -> float``

All read from ``hive.da_bi_dw.v_tb_skan_report_day_v2`` (a Trino view exposed
through the Lilith warehouse gateway). The first three return per-day
aggregated rows enriched with two derived metrics:

- ``cpi = cost / sk_install`` (or 0 when ``sk_install == 0``)
- ``skan_roi = revenue / (1 - sk_conversion_null/sk_install) / cost``
  (Apple's null-conversion buckets are treated as missing data, so the
  observed revenue is grossed up by the null fraction. Returns 0 when
  ``cost == 0`` or every install is null.)

Date arguments are ISO ``YYYY-MM-DD`` strings; the view's ``third_dt`` is a
varchar, so string comparison works as expected for ranges.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .dw_client import query_trino

SKAN_VIEW: str = "hive.da_bi_dw.v_tb_skan_report_day_v2"

# Columns shared across the by-game / by-channel / by-campaign aggregations.
_BASE_AGG_COLUMNS: tuple[str, ...] = (
    "SUM(cost) AS cost",
    "SUM(sk_install) AS sk_install",
    "SUM(sk_conversion_null) AS sk_conversion_null",
    "SUM(revenue) AS revenue",
    "SUM(mmp_cv_revenue) AS mmp_cv_revenue",
    "SUM(mmp_cv_revenue_without_pltv) AS mmp_cv_revenue_without_pltv",
    "SUM(amount_taxed_30d_24h) AS amount_taxed_30d_24h",
)


def _enrich_with_derived(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Append ``cpi`` and ``skan_roi`` to each row, never raising on zero divisors."""
    out: list[dict[str, Any]] = []
    for row in rows:
        cost = float(row.get("cost") or 0.0)
        installs = float(row.get("sk_install") or 0.0)
        nulls = float(row.get("sk_conversion_null") or 0.0)
        revenue = float(row.get("revenue") or 0.0)

        cpi = (cost / installs) if installs > 0 else 0.0

        skan_roi: float
        if cost > 0 and installs > 0 and (nulls / installs) < 1.0:
            grossed_revenue = revenue / (1.0 - nulls / installs)
            skan_roi = grossed_revenue / cost
        else:
            skan_roi = 0.0

        enriched = dict(row)
        enriched["cpi"] = cpi
        enriched["skan_roi"] = skan_roi
        out.append(enriched)
    return out


def fetch_skan_by_game_day(
    game_id: int, dt_start: str, dt_end: str,
) -> list[dict[str, Any]]:
    """Per-day per-game aggregation for one ``game_id`` over ``[dt_start, dt_end]``.

    Output rows include: ``third_dt, game_id, game_name``, the seven base
    metric columns, plus derived ``cpi`` and ``skan_roi``. Sorted ASC by
    ``third_dt``.
    """
    sql = f"""
        SELECT
            third_dt,
            game_id,
            game_name,
            {", ".join(_BASE_AGG_COLUMNS)}
        FROM {SKAN_VIEW}
        WHERE game_id = {int(game_id)}
          AND third_dt BETWEEN '{dt_start}' AND '{dt_end}'
        GROUP BY third_dt, game_id, game_name
        ORDER BY third_dt ASC
    """
    return _enrich_with_derived(query_trino(sql))


def fetch_skan_by_channel_day(
    game_id: int, dt_start: str, dt_end: str,
) -> list[dict[str, Any]]:
    """Per-day per-channel aggregation. Adds ``spreader_name`` to the grain.

    Output rows: ``third_dt, game_id, game_name, spreader_name`` + base metrics
    + derived. Sorted ``(third_dt, spreader_name)``.
    """
    sql = f"""
        SELECT
            third_dt,
            game_id,
            game_name,
            spreader_name,
            {", ".join(_BASE_AGG_COLUMNS)}
        FROM {SKAN_VIEW}
        WHERE game_id = {int(game_id)}
          AND third_dt BETWEEN '{dt_start}' AND '{dt_end}'
        GROUP BY third_dt, game_id, game_name, spreader_name
        ORDER BY third_dt ASC, spreader_name ASC
    """
    return _enrich_with_derived(query_trino(sql))


def fetch_skan_by_campaign_day(
    game_id: int, dt_start: str, dt_end: str,
) -> list[dict[str, Any]]:
    """Per-day per-campaign aggregation. Adds ``campaign_name`` to the grain.

    Output rows: ``third_dt, game_id, game_name, spreader_name, campaign_name``
    + base metrics + derived. Sorted ``(third_dt, spreader_name, campaign_name)``.
    """
    sql = f"""
        SELECT
            third_dt,
            game_id,
            game_name,
            spreader_name,
            campaign_name,
            {", ".join(_BASE_AGG_COLUMNS)}
        FROM {SKAN_VIEW}
        WHERE game_id = {int(game_id)}
          AND third_dt BETWEEN '{dt_start}' AND '{dt_end}'
        GROUP BY third_dt, game_id, game_name, spreader_name, campaign_name
        ORDER BY third_dt ASC, spreader_name ASC, campaign_name ASC
    """
    return _enrich_with_derived(query_trino(sql))


def fetch_calibration_factor(
    game_id: int, channel: str, lookback_days: int = 30,
) -> float:
    """Return ``SUM(revenue) / SUM(amount_taxed_30d_24h)`` over the last N days.

    A multiplier indicating how much DAP underestimates revenue compared to
    SKAN. Returns ``1.0`` if DAP revenue is zero or the query returned no
    rows (treats ratio as undefined and falls back to a no-op multiplier).
    """
    today = date.today()
    end = (today - timedelta(days=2)).isoformat()  # 2-day SKAN postback buffer
    start = (today - timedelta(days=2 + lookback_days)).isoformat()
    safe_channel = str(channel).replace("'", "''")
    sql = f"""
        SELECT
            SUM(revenue) AS skan_revenue,
            SUM(amount_taxed_30d_24h) AS dap_revenue
        FROM {SKAN_VIEW}
        WHERE game_id = {int(game_id)}
          AND spreader_name = '{safe_channel}'
          AND third_dt BETWEEN '{start}' AND '{end}'
    """
    rows = query_trino(sql)
    if not rows:
        return 1.0
    skan_rev = float(rows[0].get("skan_revenue") or 0.0)
    dap_rev = float(rows[0].get("dap_revenue") or 0.0)
    if dap_rev == 0:
        return 1.0
    return skan_rev / dap_rev
