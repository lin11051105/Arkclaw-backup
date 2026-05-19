"""Shared data fetcher factories.

Provides reusable factory functions for DAP and Facebook API calls.
Each skill's _fetchers.py imports from here instead of duplicating.

Usage from any skill's _fetchers.py:
    from lib.fetchers import call_dap, make_fetch_custom_report, make_fetch_insights, make_fetch_material_report

Auth source（Hermes / cron 通用）:
- ``~/.atlas-ai-gateway-oauth.json``: 必须存在。由 atlas-skillhub 的 OAuth 流颁发
  （首次跑 ``atlas-skillhub gateway login``），token 过期重跑即可。
- ``ATLAS_GATEWAY_URL``（可选）: 覆盖 oauth.json 里的 gateway_url，测试用。
- ``UA_AGENT_DAP_REPORT_ID``: ``get_custom_report`` 的默认 report_id，默认 26888（PTSLG）。
  仅在未通过 game 参数指定时生效。
"""
from __future__ import annotations

import os
from typing import Callable

_DAP_PAGE_SIZE = 500

# 游戏 → DAP 自定义报表 ID 映射
# 新增游戏报表时在此添加一行即可，所有 skill 自动生效。
GAME_REPORT_MAP: dict[str, int] = {
    "PTSLG": 26888,   # ptslg_all_info_wangyis
    "ROK":   26608,   # ua_agent_test_vincent
}
_DEFAULT_REPORT_ID = 26888  # 默认 PTSLG


def dap_report_id(game: str | None = None) -> int:
    """Return report_id for get_custom_report.

    优先级: game 参数 → GAME_REPORT_MAP → 环境变量 → 默认值(PTSLG 26888)。
    game 参数大小写不敏感。
    """
    if game:
        rid = GAME_REPORT_MAP.get(game.upper())
        if rid:
            return rid
    return int(os.environ.get("UA_AGENT_DAP_REPORT_ID", str(_DEFAULT_REPORT_ID)))


def game_alias_for_project(apps: dict, project_id: str) -> str:
    """Resolve DAP ``game`` parameter: 使用 apps.json 的 game_alias，缺失时回退 project_id。"""
    app = apps.get(project_id) or {}
    return str(app.get("game_alias") or project_id)


def get_app_config(config: dict, project_id: str) -> dict:
    """Safely get project config from apps.json. Returns the project dict or empty dict if missing."""
    return config.get("apps", {}).get(project_id, {})


def get_fb_config(app: dict, field: str, default=None):
    """Safely get a field from app's facebook config. Returns default if missing."""
    return app.get("facebook", {}).get(field, default)


def get_os_target(app: dict, os: str, field: str, default=None):
    """Resolve OS-aware target field with legacy fallback.

    Lookup order:
      1. ``app["facebook"][f"{os}_{field}"]`` (e.g. ``ios_target_cpi``)
      2. ``app["facebook"][field]`` (legacy unsplit key, e.g. ``target_cpi``)
      3. ``default``

    Args:
        app: Project-level dict from ``apps.json[project_id]``.
        os: ``"ios"`` or ``"android"``.
        field: Legacy field name like ``"target_cpi"`` or ``"target_roi"``.
        default: Fallback when neither OS-specific nor legacy key exists.

    Returns:
        The resolved value, or ``default``.
    """
    fb = app.get("facebook", {}) or {}
    os_key = f"{os}_{field}"
    if os_key in fb:
        return fb[os_key]
    if field in fb:
        return fb[field]
    return default


def get_account_ids(config: dict, project_id: str | None) -> list[str] | None:
    """Resolve FB ad account ids from apps.json ``facebook.accounts``.

    Returns the id list, or ``None`` if the project has no configured accounts.
    Caller should treat ``None`` as a signal to fall back to the env default.
    """
    if not project_id:
        return None
    app = get_app_config(config, project_id)
    accounts = get_fb_config(app, "accounts", []) or []
    ids = [a.get("id") for a in accounts if isinstance(a, dict) and a.get("id")]
    return ids or None


def call_dap(tool: str, args: dict) -> list | dict:
    """Call a DAP tool via atlas-ai-gateway (MCP JSON-RPC over HTTPS).

    Auth 走 ``~/.atlas-ai-gateway-oauth.json`` 里的 access_token。
    返回 unwrap 后的内层 JSON（DAP 工具原始响应），保持向后兼容：
    历史上 atlas-skillhub stdout 也是同样的 ``content[0].text -> JSON`` shape。

    Raises:
        atlas_gateway.AtlasOAuthFileMissingError: ~/.atlas-ai-gateway-oauth.json 不存在。
        atlas_gateway.AtlasTokenExpiredError: token 过期，请跑 ``atlas-skillhub gateway login``。
        atlas_gateway.AtlasGatewayError: 其他网关错误（JSON-RPC error 段 / 5xx 等）。
    """
    from .atlas_gateway import call_tool
    return call_tool(service="dap", tool=tool, arguments=args)


def _normalize_col(name: str) -> str:
    """去掉 DAP 列名中的单位后缀，如 '消耗数(RMB)' → '消耗数'。保留原名作为备用 key。"""
    import re
    return re.sub(r"\([^)]*\)$", "", name).strip()


def _parse_dap_table(resp: dict | list) -> list[dict]:
    """将 DAP get_custom_report 响应解析为 list[dict]。

    DAP 返回 {"tables": [{"columns": [{"name": ...}], "data": [[...], ...]}]}。
    将二维数组转为 [{col_name: value, ...}, ...]。
    列名标准化：去掉单位后缀（如 '消耗数(RMB)' → '消耗数'），同时保留原列名。
    跳过"总计"行。
    """
    if isinstance(resp, list):
        return resp
    tables = resp.get("tables", [])
    if not tables:
        return []
    table = tables[0]
    raw_cols = [c.get("name", f"col_{i}") for i, c in enumerate(table.get("columns", []))]
    norm_cols = [_normalize_col(c) for c in raw_cols]
    rows: list[dict] = []
    for row in table.get("data", []):
        if row and row[0] == "总计":
            continue
        d: dict = {}
        for i, raw_col in enumerate(raw_cols):
            if i >= len(row):
                break
            d[raw_col] = row[i]
            normed = norm_cols[i]
            if normed != raw_col:
                d[normed] = row[i]
        rows.append(d)
    return rows


def make_fetch_custom_report(page_size: int = _DAP_PAGE_SIZE, game: str | None = None) -> Callable[[str, str, str], list[dict]]:
    """Return fn(table, start_date, end_date) -> list[dict].

    DAP tool: get_custom_report（显式传 report_id，避免网关默认值与项目不一致）
    game 参数用于路由到对应游戏的报表（见 GAME_REPORT_MAP）。
    """
    rid = dap_report_id(game)
    def fetch(table: str, start_date: str, end_date: str) -> list[dict]:
        resp = call_dap("get_custom_report", {
            "report_id": rid,
            "table": table,
            "start_date": start_date,
            "end_date": end_date,
            "page_size": page_size,
        })
        return _parse_dap_table(resp)
    return fetch


def make_fetch_insights(load_fn: Callable, account_ids: list[str] | None = None) -> Callable[..., list[dict]]:
    """Return fn(date_start, date_end, level, **kw) -> list[dict].

    Wraps ads-channel insights_manager.get_ad_insights.

    Args:
        load_fn: The _load function from the caller's loader (for cross-skill import).
        account_ids: Optional list of Facebook ad account IDs (e.g. ["act_123", "act_456"]).
                     Results from all accounts are concatenated before returning.
                     If None or empty, falls back to META_AD_ACCOUNT_ID env var.
    """
    def fetch(date_start: str, date_end: str, level: str, **kw) -> list[dict]:
        client_mod = load_fn("ads-channel", "facebook", "client")
        insights_mod = load_fn("ads-channel", "facebook", "insights_manager")
        targets = account_ids or [None]
        rows: list[dict] = []
        for aid in targets:
            client = client_mod.MetaAdsClient(account_id=aid)
            rows.extend(insights_mod.get_ad_insights(
                client,
                date_start=date_start,
                date_end=date_end,
                level=level,
                **kw,
            ))
        return rows
    return fetch


def list_all_account_ids(load_fn: Callable, name_filter: str | None = None) -> list[str]:
    """获取当前 token 下所有 Active 广告账户 ID。"""
    client_mod = load_fn("ads-channel", "facebook", "client")
    client = client_mod.MetaAdsClient()
    accounts = client.list_ad_accounts(name_filter=name_filter)
    return [a["id"] for a in accounts if a.get("account_status") == "Active"]


def make_fetch_material_report(page_size: int = _DAP_PAGE_SIZE) -> Callable[..., list[dict]]:
    """Return fn(game, channel, start, end, **kw) -> list[dict].

    DAP tool: query_material_report
    """
    def fetch(game: str, channel: str, start: str, end: str, **kw) -> list[dict]:
        resp = call_dap("query_material_report", {
            "game": game,
            "channel": channel,
            "start_date": start,
            "end_date": end,
            "page_size": page_size,
            **kw,
        })
        if isinstance(resp, list):
            return resp
        return resp.get("data", [])
    return fetch


# ── SKAN view fetchers (iOS path) ──────────────────────────────
#
# Both factories capture ``game_id`` and return a kwargs-only callable
# ``(*, date_start, date_end) -> list[dict]`` matching the contract used by
# channel_aggregator / monitoring_alerts.

def make_fetch_skan_by_channel_day(game_id: int) -> Callable[..., list[dict]]:
    """Return fn(*, date_start, date_end) -> list[dict] over SKAN by channel-day.

    Thin wrapper over ``lib.skan_repo.fetch_skan_by_channel_day``.
    Used by channel-summary (iOS path).
    """
    from .skan_repo import fetch_skan_by_channel_day

    def fetch(*, date_start: str, date_end: str) -> list[dict]:
        return fetch_skan_by_channel_day(int(game_id), date_start, date_end)

    return fetch


def make_fetch_skan_by_game_day(game_id: int) -> Callable[..., list[dict]]:
    """Return fn(*, date_start, date_end) -> list[dict] over SKAN by game-day.

    Thin wrapper over ``lib.skan_repo.fetch_skan_by_game_day``.
    Used by monitoring-alerts (iOS daily metrics).
    """
    from .skan_repo import fetch_skan_by_game_day

    def fetch(*, date_start: str, date_end: str) -> list[dict]:
        return fetch_skan_by_game_day(int(game_id), date_start, date_end)

    return fetch


# ── DAP 素材名解析（委托 lib/dap_client）────────────────────────

from .dap_client import extract_dap_id as extract_dap_id_from_name  # noqa: F401
from .dap_client import extract_short_name  # noqa: F401
