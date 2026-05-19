"""Callback wrappers for DAP and ads-channel.

Provides factory functions for creative-lifecycle:
creative_health, scale_candidates, upload_pipeline, material_summary.

Shared DAP/Facebook fetchers from lib.fetchers.
Skill-specific: material pagination, daily fetcher, ads-channel create wrappers.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Callable

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS.parents[1]))
from lib.fetchers import call_dap, game_alias_for_project, get_app_config, get_fb_config

_loader_spec = importlib.util.spec_from_file_location("_loader", _SCRIPTS.parents[1] / "lib" / "loader.py")
_loader = importlib.util.module_from_spec(_loader_spec); _loader_spec.loader.exec_module(_loader)
_load = _loader.make_loader(__file__)

_DAP_PAGE_SIZE = 200
_WORKSPACE_ROOT = _SCRIPTS.parents[2]


def _apps_map() -> dict:
    import json
    p = _WORKSPACE_ROOT / "config" / "apps.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, dict)}


# ═══════════════════════════════════════════════════════════════════════════
# DAP fetchers
# ═══════════════════════════════════════════════════════════════════════════

def _extract_material_list(resp: dict) -> list[dict]:
    """Extract 素材列表 table from DAP response and convert to list of dicts.

    Maps Chinese column names to English. Handles pagination via truncated flag.
    """
    _COL_MAP = {
        "名称": "name", "ID": "id", "消耗": "spend", "展示": "impressions",
        "点击": "clicks", "安装": "installs", "类型": "type",
        "CTR": "ctr", "CVR": "cvr", "CPI": "cpi", "ROAS": "roi",
        "首消耗": "first_spend_date", "预览": "preview_url",
    }
    for table in resp.get("tables", []):
        if "素材列表" not in table.get("name", ""):
            continue
        cols = [_COL_MAP.get(c["name"], c["name"]) for c in table["columns"]]
        data = table.get("data") or []
        return [{col: row[i] for i, col in enumerate(cols) if i < len(row)} for row in data]
    return []


def _fetch_all_material_pages(args: dict) -> list[dict]:
    """Fetch all pages of query_material_report and merge into one list."""
    all_rows: list[dict] = []
    page = 1
    while True:
        paged_args = {**args, "page": page, "page_size": _DAP_PAGE_SIZE}
        resp = call_dap("query_material_report", paged_args)
        rows = _extract_material_list(resp)
        all_rows.extend(rows)
        # Check truncation on last table
        tables = resp.get("tables", [])
        last_table = tables[-1] if tables else {}
        if not last_table.get("truncated", False):
            break
        page += 1
    return all_rows


def make_fetch_material_report() -> Callable[[str, str, str, str], list[dict]]:
    """Return fn(game_alias, channel, start, end) → list[dict].

    Used by: scale_candidates.run_scale_candidates, material_summary.run_material_summary
    Each dict has: name, id, spend, impressions, installs, ctr, cpi, roi, ...
    """
    def fetch(game_alias: str, channel: str, start: str, end: str) -> list[dict]:
        return _fetch_all_material_pages({
            "game": game_alias,
            "channel": channel,
            "start_date": start,
            "end_date": end,
        })
    return fetch


def make_fetch_material_daily() -> Callable[[str, str, str], list[dict]]:
    """Return fn(project_id, start, end) → list[dict].

    Queries DAP once per day, adds 'date' and 'material_name' fields.
    Each dict has: date, material_name, cpi, roi, spend, ...
    Used by: creative_health.run_creative_health (fetch_material_daily)
    """
    def fetch(project_id: str, start: str, end: str) -> list[dict]:
        from datetime import datetime, timedelta

        game = game_alias_for_project(_apps_map(), project_id)
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")

        all_rows: list[dict] = []
        cur = start_dt
        while cur <= end_dt:
            day_str = cur.strftime("%Y-%m-%d")
            rows = _fetch_all_material_pages({
                "game": game,
                "channel": "Facebook",
                "start_date": day_str,
                "end_date": day_str,
            })
            for row in rows:
                row["date"] = day_str
                row["material_name"] = row.get("name", "")
            all_rows.extend(rows)
            cur += timedelta(days=1)

        return all_rows
    return fetch


def make_fetch_country_report(game: str | None = None) -> Callable[[str, str, str], list[dict]]:
    """Return fn(project_id, start, end) → list[dict] with per-country metrics.

    Wraps DAP get_custom_report(table="country").
    Used by: creative_health.run_creative_health (fetch_country_report)
    """
    from lib.fetchers import dap_report_id

    rid = dap_report_id(game)

    def fetch(project_id: str, start: str, end: str) -> list[dict]:
        resp = call_dap("get_custom_report", {
            "report_id": rid,
            "table": "country",
            "start_date": start,
            "end_date": end,
        })
        if isinstance(resp, list):
            return resp
        tables = resp.get("tables", [])
        if not tables:
            return []
        table = tables[0]
        cols = [c.get("name", "") for c in table.get("columns", [])]
        return [
            {col: row[i] for i, col in enumerate(cols) if i < len(row)}
            for row in table.get("data", [])
        ]
    return fetch


# ═══════════════════════════════════════════════════════════════════════════
# DAP HTTP API wrappers (素材库搜索、详情、多版本)
# ═══════════════════════════════════════════════════════════════════════════


def _get_dap_client():
    from lib.dap_client import DapHttpClient
    return DapHttpClient()


def make_search_dap_materials() -> Callable:
    """Return fn(game_id, **search_params) → list[dict].

    Wraps DapHttpClient.search_materials(). Accepts all DAP search filters:
    keyword, material_ids, region_id, language, status, review_status,
    material_type, ratio, marketing_tag_ids, order, sort, page, page_size.
    """
    def fetch(game_id: int, **kwargs) -> list[dict]:
        try:
            return _get_dap_client().search_materials(game_id, **kwargs)
        except ValueError:
            return []
    return fetch


def make_search_all_dap_materials() -> Callable:
    """Return fn(game_id, **search_params) → list[dict] (auto-paginated)."""
    def fetch(game_id: int, **kwargs) -> list[dict]:
        try:
            return _get_dap_client().search_all_materials(game_id, **kwargs)
        except ValueError:
            return []
    return fetch


def make_get_dap_material_detail() -> Callable:
    """Return fn(material_id) → dict | None."""
    def fetch(material_id: int) -> dict | None:
        try:
            return _get_dap_client().get_material_detail(material_id)
        except ValueError:
            return None
    return fetch


def make_find_material_versions() -> Callable:
    """Return fn(game_id, short_name, **kwargs) → list[dict].

    Finds all size/version variants of a material by short name keyword search.
    """
    def fetch(game_id: int, short_name: str, **kwargs) -> list[dict]:
        try:
            return _get_dap_client().find_versions_by_short_name(game_id, short_name, **kwargs)
        except ValueError:
            return []
    return fetch


def make_resolve_fb_names() -> Callable:
    """Return fn(fb_ad_names) → dict[str, dict].

    Batch-resolve FB ad names to DAP material info (dap_id, short_name, language).
    """
    def fetch(fb_ad_names: list[str]) -> dict:
        try:
            return _get_dap_client().batch_resolve_fb_names(fb_ad_names)
        except ValueError:
            return {}
    return fetch


# ═══════════════════════════════════════════════════════════════════════════
# ads-channel read wrappers
# ═══════════════════════════════════════════════════════════════════════════

def make_fetch_active_ads() -> Callable[[str], list[dict]]:
    """Return fn(project_id) → list[dict] with {ad_id, ad_name, adset_id, online_days}.

    Used by: creative_health.run_creative_health (fetch_active_ads)

    Derives active ad list from DAP yesterday data (no Facebook API needed).
    online_days = (today - first_spend_date).days.
    """
    def fetch(project_id: str) -> list[dict]:
        from datetime import datetime, timedelta

        game = game_alias_for_project(_apps_map(), project_id)
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        rows = _fetch_all_material_pages({
            "game": game,
            "channel": "Facebook",
            "start_date": yesterday,
            "end_date": yesterday,
        })

        all_ads: list[dict] = []
        for r in rows:
            name = r.get("name", "")
            if not name:
                continue
            first_date = r.get("first_spend_date", "")
            online_days = 0
            if first_date:
                try:
                    fd = datetime.strptime(first_date, "%Y-%m-%d")
                    online_days = max(0, (datetime.now() - fd).days)
                except ValueError:
                    pass
            all_ads.append({
                "ad_id": r.get("id", name),
                "ad_name": name,
                "adset_id": "",
                "online_days": online_days,
            })

        return all_ads
    return fetch


# ═══════════════════════════════════════════════════════════════════════════
# ads-channel create wrappers
# ═══════════════════════════════════════════════════════════════════════════

def _import_ads_channel():
    """Import ads-channel modules. Returns (client_mod, campaign_manager_mod)."""
    client_mod = _load("ads-channel", "facebook", "client")
    cm_mod = _load("ads-channel", "facebook", "campaign_manager")
    return client_mod, cm_mod


def make_create_campaign_fn() -> Callable[[dict], dict]:
    """Return fn(params) → {"campaign_id": ..., "status": ...}."""
    client_mod, cm_mod = _import_ads_channel()

    def create(params: dict) -> dict:
        client = client_mod.MetaAdsClient()
        return cm_mod.create_campaign(client, params)
    return create


def make_create_adset_fn() -> Callable[[dict], dict]:
    """Return fn(params) → {"adset_id": ..., "status": ...}."""
    client_mod, cm_mod = _import_ads_channel()

    def create(params: dict) -> dict:
        client = client_mod.MetaAdsClient()
        return cm_mod.create_adset(client, params)
    return create


def make_create_ad_fn() -> Callable[[dict], dict]:
    """Return fn(params) → {"ad_id": ..., "status": ...}."""
    client_mod, cm_mod = _import_ads_channel()

    def create(params: dict) -> dict:
        client = client_mod.MetaAdsClient()
        return cm_mod.create_ad(client, params)
    return create


def make_ensure_creative_fn() -> Callable[..., str]:
    """Return fn(creative_id, os_type, project_id, config) → creative_id.

    Delegates to creative_manager.ensure_creative_for_os, resolving store_url,
    page_id, and instagram_actor_id from config["apps"][project_id].
    Returns the (possibly new) creative_id.
    """
    client_mod = _load("ads-channel", "facebook", "client")
    creative_mod = _load("ads-channel", "facebook", "creative_manager")

    def ensure(
        creative_id: str,
        os_type: str,
        project_id: str,
        config: dict,
    ) -> str:
        client = client_mod.MetaAdsClient()
        app = get_app_config(config, project_id)
        store_url = app.get("store_urls", {}).get(os_type, "")
        page_id = get_fb_config(app, "page_id", "")
        ig_id = get_fb_config(app, "instagram_actor_id", "")
        return creative_mod.ensure_creative_for_os(
            client,
            creative_id=creative_id,
            os_type=os_type,
            store_url=store_url,
            page_id=page_id,
            instagram_actor_id=ig_id,
        )

    return ensure


def make_create_ad_creative_fn(
    project_id: str,
    os_type: str,
    config: dict,
) -> Callable[[dict], dict]:
    """Return fn(upload_result) → {"creative_id": ..., "name": ...}.

    Takes the output of upload_media (containing video_id or image_hash)
    and creates an AdCreative with the correct page_id, store URL, and Instagram ID
    from config["apps"][project_id].

    Args:
        project_id: project key to look up in config["apps"]
        os_type:    "iOS" or "Android" — selects the correct store URL
        config:     merged config dict with apps section
    """
    client_mod = _load("ads-channel", "facebook", "client")
    creative_mod = _load("ads-channel", "facebook", "creative_manager")

    app = get_app_config(config, project_id)
    page_id = get_fb_config(app, "page_id", "")
    link_url = app.get("store_urls", {}).get(os_type, "")
    ig_id = get_fb_config(app, "instagram_actor_id", "")

    def create(upload_result: dict) -> dict:
        client = client_mod.MetaAdsClient()
        asset_type = upload_result.get("asset_type", "video")

        if asset_type == "video":
            return creative_mod.create_ad_creative_for_video(
                client,
                video_id=upload_result["video_id"],
                name=upload_result.get("name", ""),
                page_id=page_id,
                link_url=link_url,
                instagram_actor_id=ig_id,
                image_hash=upload_result.get("image_hash", ""),
            )
        else:
            return creative_mod.create_ad_creative_for_image(
                client,
                image_hash=upload_result["image_hash"],
                name=upload_result.get("name", ""),
                page_id=page_id,
                link_url=link_url,
                instagram_actor_id=ig_id,
            )
    return create


def make_upload_creative_fn() -> Callable[..., dict]:
    """Return fn(asset_type, file_url, name) → {"image_hash"|"video_id": ..., "asset_type": ..., ...}.

    Wraps creative_manager.upload_media from ads-channel — 纯媒体上传，不创建 AdCreative。
    """
    client_mod = _load("ads-channel", "facebook", "client")
    creative_mod = _load("ads-channel", "facebook", "creative_manager")

    def upload(*, asset_type: str, file_url: str, name: str) -> dict:
        client = client_mod.MetaAdsClient()
        return creative_mod.upload_media(
            client,
            asset_type=asset_type,
            file_url=file_url,
            name=name,
        )
    return upload
