"""应用配置管理 — 从 config/apps.json 读取项目配置。

跨渠道共享：promoted_object 解析不依赖特定渠道 SDK。
"""

import json
from pathlib import Path

_APPS_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent.parent.parent / "config" / "apps.json"


def load_app_config(project: str | None = None) -> dict:
    """读取 config/apps.json。传 project 返回单个项目配置，不传返回全部。"""
    if not _APPS_CONFIG_PATH.exists():
        return {}
    with open(_APPS_CONFIG_PATH) as f:
        apps = json.load(f)
    if project:
        return apps.get(project, apps.get(project.upper(), {}))
    return apps


def resolve_promoted_object(project: str, os: str) -> dict | None:
    """从 apps.json 解析 promoted_object。

    返回 {"application_id": "...", "object_store_url": "..."} 或 None。
    """
    app = load_app_config(project)
    if not app:
        return None
    app_id = app.get("application_id")
    store_url = app.get("store_urls", {}).get(os)
    if not app_id or not store_url:
        return None
    return {"application_id": app_id, "object_store_url": store_url}
