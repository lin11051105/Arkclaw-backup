"""Generic Trino-over-HiveServer2 client for the Lilith data-warehouse gateway.

Public surface: ``query_trino(sql, *, engine_type, fetch_buffer)``.

Reads ``DW_API_KEY`` / ``DW_API_SECRET`` / ``DW_OPERATOR`` from the environment
on every call. No connection pooling -- each call opens and closes a single
HiveServer2 thrift connection. The cursor is configured with three Lilith
dispatcher keys that route the query through Trino (default) or Hive.

This module exists so SKAN-specific repository code (``lib.skan_repo``) and any
future warehouse query helpers can share a single, mockable point of entry.
"""
from __future__ import annotations

import os
from typing import Any

# Re-exported so tests can `patch.object(dw_client, "connect", ...)`.
from impala.dbapi import connect  # noqa: F401

DEFAULT_HOST: str = "bbx.lilithgame.com"
DEFAULT_PORT: int = 10000
QUERY_SOURCE: str = "ua_agent"

_REQUIRED_ENV_VARS: tuple[str, ...] = ("DW_API_KEY", "DW_API_SECRET", "DW_OPERATOR")


def _require_env(name: str) -> str:
    """Return the env var or raise RuntimeError naming the missing var."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Populate workspace/.env with {name} before invoking dw_client.query_trino."
        )
    return value


def query_trino(
    sql: str,
    *,
    engine_type: str = "trino",
    fetch_buffer: int = 1000,
) -> list[dict[str, Any]]:
    """Execute ``sql`` on the Lilith DW gateway and return rows as dicts.

    Args:
        sql: Raw Trino (or Hive, when ``engine_type='hive'``) SQL. Caller is
            responsible for SQL injection safety; this is internal use over a
            controlled connection.
        engine_type: Routes via the ``lilith.dispatcher.exec.engine.type``
            cursor configuration key. ``"trino"`` (default) or ``"hive"``.
        fetch_buffer: Rows-per-``fetchmany`` chunk. Pure memory tuning; does
            not affect semantics.

    Returns:
        A list of dicts, one per row. Keys come from ``cursor.description``
        (column 0 of each tuple). Empty list when the query yields no rows.

    Raises:
        RuntimeError: If any of ``DW_API_KEY``, ``DW_API_SECRET``,
            ``DW_OPERATOR`` is missing from the environment.
        impala.error.*: Propagated unchanged on driver/SQL failure.
    """
    api_key = _require_env("DW_API_KEY")
    api_secret = _require_env("DW_API_SECRET")
    operator = _require_env("DW_OPERATOR")

    configuration = {
        "lilith.dispatcher.exec.engine.type": engine_type,
        "lilith.dispatcher.exec.engine.query.operator": operator,
        "lilith.dispatcher.exec.engine.query.source": QUERY_SOURCE,
    }

    conn = connect(
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        user=api_key,
        password=api_secret,
        auth_mechanism="plain",
        timeout=60,
    )
    try:
        cursor = conn.cursor(configuration=configuration)
        try:
            cursor.execute(sql)
            columns = [d[0] for d in (cursor.description or [])]
            rows: list[dict[str, Any]] = []
            while True:
                chunk = cursor.fetchmany(fetch_buffer)
                if not chunk:
                    break
                for row in chunk:
                    rows.append(dict(zip(columns, row)))
            return rows
        finally:
            try:
                cursor.close()
            except Exception:  # pragma: no cover -- best-effort cleanup
                pass
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover -- best-effort cleanup
            pass
