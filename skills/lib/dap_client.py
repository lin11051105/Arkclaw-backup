"""DAP HTTP API client — 素材搜索、详情查询、多版本发现。

统一所有 skill 的 DAP 素材查询路径。

API endpoints:
  POST /dapper/api/material/v2/list/materials  — 素材列表搜索（支持 keyword/type/region/language 等）
  GET  /dapper/api/materiel_2/edit             — 单素材详情

认证: Authorization: Basic {DAP_API_TOKEN}
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

import requests

_log = logging.getLogger(__name__)

_DAP_BASE = "https://dap.lilithgame.com/dapper/api"
_ID_SUFFIX_RE = re.compile(r"_(\d{4,})$")


def extract_dap_id(name: str) -> int | None:
    m = _ID_SUFFIX_RE.search(name)
    return int(m.group(1)) if m else None


def extract_short_name(material_name: str) -> str:
    if not material_name:
        return ""
    parts = material_name.split("_")
    if len(parts) >= 5:
        return parts[4]
    return material_name


class DapHttpClient:
    def __init__(self, token: str | None = None):
        self._token = token or os.environ.get("DAP_API_TOKEN", "")
        if not self._token:
            raise ValueError("DAP_API_TOKEN is required")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Basic {self._token}",
            "Content-Type": "application/json",
        }

    def search_materials(
        self,
        game_id: int,
        *,
        keyword: str | None = None,
        material_ids: list[int] | None = None,
        region_id: str | None = None,
        language: str | None = None,
        status: int | None = None,
        review_status: str | None = None,
        material_type: str | None = None,
        ratio: str | None = None,
        marketing_tag_ids: list[int] | None = None,
        order: str = "upload_datetime",
        sort: str = "desc",
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "game_id": game_id,
            "page": page,
            "page_size": page_size,
            "order": order,
            "sort": sort,
        }
        if keyword:
            body["keyword"] = keyword
        if material_ids:
            body["material_ids"] = material_ids
        if region_id:
            body["region_id"] = region_id
        if language:
            body["language"] = language
        if status is not None:
            body["status"] = status
        if review_status:
            body["review_status"] = review_status
        if material_type:
            body["type"] = material_type
        if ratio:
            body["ratio"] = ratio
        if marketing_tag_ids:
            body["marketing_tag_ids"] = marketing_tag_ids

        try:
            resp = requests.post(
                f"{_DAP_BASE}/material/v2/list/materials",
                json=body,
                headers=self._headers(),
                timeout=15,
            )
            if resp.status_code != 200:
                _log.warning("DAP search failed: status=%s", resp.status_code)
                return []
            data = resp.json().get("data", {})
            return data.get("rows", [])
        except Exception as exc:
            _log.warning("DAP search error: %s", exc)
            return []

    def search_all_materials(
        self,
        game_id: int,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        all_rows: list[dict[str, Any]] = []
        page = 1
        page_size = kwargs.pop("page_size", 50)
        while True:
            rows = self.search_materials(game_id, page=page, page_size=page_size, **kwargs)
            if not rows:
                break
            all_rows.extend(rows)
            if len(rows) < page_size:
                break
            page += 1
        return all_rows

    def get_material_detail(self, material_id: int) -> dict[str, Any] | None:
        try:
            resp = requests.get(
                f"{_DAP_BASE}/materiel_2/edit",
                params={"materiel_id": material_id},
                headers={"Authorization": f"Basic {self._token}"},
                timeout=10,
            )
            if resp.status_code != 200:
                return None
            data = resp.json().get("data")
            if not data or not isinstance(data, dict):
                return None
            return data
        except Exception as exc:
            _log.warning("DAP detail lookup failed for %s: %s", material_id, exc)
            return None

    def batch_resolve_fb_names(
        self,
        fb_ad_names: list[str],
    ) -> dict[str, dict[str, Any]]:
        name_to_id: dict[str, int] = {}
        for name in fb_ad_names:
            dap_id = extract_dap_id(name)
            if dap_id is not None:
                name_to_id[name] = dap_id

        if not name_to_id:
            return {}

        unique_ids = set(name_to_id.values())
        id_to_detail: dict[int, dict[str, Any]] = {}
        for mid in unique_ids:
            detail = self.get_material_detail(mid)
            if detail:
                id_to_detail[mid] = detail

        result: dict[str, dict[str, Any]] = {}
        for name, dap_id in name_to_id.items():
            detail = id_to_detail.get(dap_id)
            if detail:
                result[name] = {
                    "dap_id": dap_id,
                    "short_name": detail.get("name", ""),
                    "material_name": detail.get("material_name", ""),
                    "language": (detail.get("language") or "").upper() or None,
                }
        return result

    def find_versions_by_short_name(
        self,
        game_id: int,
        short_name: str,
        *,
        region_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.search_materials(
            game_id,
            keyword=short_name,
            region_id=region_id,
            page_size=100,
        )
