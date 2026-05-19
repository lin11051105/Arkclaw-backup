"""Creative asset management — 上传 + AdCreative 创建 + Media Library 查找。

职责：
1. 上传媒体文件（AdVideo / AdImage）→ 拿到 video_id / image_hash
2. 创建 AdCreative 引用该媒体 → 拿到 creative_id
3. 从 DAP 素材 ID 定位 FB Media Library 中已有素材 → 拿到 video_id

ads-channel 只负责与 API 交互，不做业务判定。
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

from . import config
from .client import MetaAdsClient

# 一次性把 workspace/skills/ 加入 sys.path，让 ``from lib.dap_client import ...`` 可用。
# 替代 resolve_video_id* 函数体内重复的 sys.path hack（P1-1）。
_SKILLS_ROOT = str(Path(__file__).resolve().parents[3])
if _SKILLS_ROOT not in sys.path:
    sys.path.insert(0, _SKILLS_ROOT)
from lib.dap_client import DapHttpClient as _DapHttpClient  # noqa: E402


def _extract_thumbnail(video_path: str) -> str | None:
    """用 ffmpeg 提取视频第一帧作为缩略图，返回临时文件路径。失败返回 None。"""
    thumb_path = tempfile.mktemp(suffix=".jpg")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-vframes", "1", "-q:v", "2", thumb_path],
            capture_output=True, timeout=30, check=True,
        )
        return thumb_path if os.path.isfile(thumb_path) else None
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


# ─── Upload Video ────────────────────────────────────────────────────

def upload_video(client: MetaAdsClient, *, file_path: str, name: str) -> dict:
    """上传本地视频文件到 Facebook 广告库。

    Args:
        client: MetaAdsClient 实例
        file_path: 本地视频文件路径
        name: 视频名称

    Returns:
        {"video_id": str, "name": str}
    """
    from facebook_business.adobjects.advideo import AdVideo

    video = AdVideo(parent_id=client.account_id)
    video[AdVideo.Field.name] = name
    video[AdVideo.Field.filepath] = file_path
    video.remote_create()
    return {"video_id": video["id"], "name": name}


def upload_video_from_url(client: MetaAdsClient, *, file_url: str, name: str) -> dict:
    """从 URL 下载视频后上传到 Facebook 广告库。

    Args:
        client: MetaAdsClient 实例
        file_url: 视频文件 URL
        name: 视频名称

    Returns:
        {"video_id": str, "name": str}
    """
    result = client.account.create_ad_video(
        params={"name": name, "file_url": file_url},
    )
    return {"video_id": result["id"], "name": name}


# ─── Upload Image ────────────────────────────────────────────────────

def upload_image(client: MetaAdsClient, *, file_path: str, name: str) -> dict:
    """上传本地图片文件到 Facebook 广告库。

    Args:
        client: MetaAdsClient 实例
        file_path: 本地图片文件路径
        name: 内部跟踪名称（不会设置到 Facebook）

    Returns:
        {"image_hash": str, "image_url": str, "name": str}
    """
    from facebook_business.adobjects.adimage import AdImage

    image = AdImage(parent_id=client.account_id)
    image[AdImage.Field.filename] = file_path
    image.remote_create()
    return {
        "image_hash": image.get(AdImage.Field.hash, ""),
        "image_url": image.get(AdImage.Field.url, ""),
        "name": name,
    }


# ─── Create AdCreative ──────────────────────────────────────────────

def create_ad_creative_for_video(
    client: MetaAdsClient,
    *,
    video_id: str,
    name: str,
    page_id: str = "",
    link_url: str = "",
    message: str = "",
    instagram_actor_id: str = "",
    image_hash: str = "",
    image_url: str = "",
) -> dict:
    """创建引用视频的 AdCreative。

    Args:
        instagram_actor_id: Instagram 账户 ID，用于 IG 版位投放。
                           不传则 IG 版位可能报 format validation error。
        image_hash: 视频缩略图的 image hash。Facebook 某些版位要求 video_data
                    中必须指定缩略图，优先使用 image_hash（已上传）。
        image_url:  视频缩略图 URL（备选，image_hash 存在时忽略）。

    Returns:
        {"creative_id": str, "name": str}
    """
    video_data: dict = {
        "video_id": video_id,
        "call_to_action": {
            "type": "INSTALL_MOBILE_APP",
            "value": {"link": link_url} if link_url else {},
        },
        "message": message,
    }
    if image_hash:
        video_data["image_hash"] = image_hash
    elif image_url:
        video_data["image_url"] = image_url

    story_spec: dict = {
        "page_id": page_id,
        "video_data": video_data,
    }
    if instagram_actor_id:
        story_spec["instagram_user_id"] = instagram_actor_id

    creative_params: dict = {
        "name": name,
        "object_story_spec": story_spec,
    }
    result = client.account.create_ad_creative(params=creative_params)
    return {"creative_id": result["id"], "name": name}


def create_ad_creative_for_image(
    client: MetaAdsClient,
    *,
    image_hash: str,
    name: str,
    page_id: str = "",
    link_url: str = "",
    message: str = "",
    instagram_actor_id: str = "",
) -> dict:
    """创建引用图片的 AdCreative。

    Args:
        instagram_actor_id: Instagram 账户 ID，用于 IG 版位投放。

    Returns:
        {"creative_id": str, "name": str}
    """
    story_spec: dict = {
        "page_id": page_id,
        "link_data": {
            "image_hash": image_hash,
            "link": link_url,
            "message": message,
            "call_to_action": {
                "type": "INSTALL_MOBILE_APP",
                "value": {"link": link_url} if link_url else {},
            },
        },
    }
    if instagram_actor_id:
        story_spec["instagram_user_id"] = instagram_actor_id

    creative_params: dict = {
        "name": name,
        "object_story_spec": story_spec,
    }
    result = client.account.create_ad_creative(params=creative_params)
    return {"creative_id": result["id"], "name": name}


# ─── Unified upload_media (pure upload, no AdCreative) ──────────────

def upload_media(
    client: MetaAdsClient,
    *,
    asset_type: str,
    file_url: str,
    name: str,
) -> dict:
    """纯媒体上传到 Facebook 广告库（不创建 AdCreative）。

    Args:
        client: MetaAdsClient 实例
        asset_type: "video" 或 "image"
        file_url: 素材文件 URL（远程 URL 或本地路径）
        name: 素材名称

    Returns:
        video: {"video_id": str, "name": str, "asset_type": "video"}
        image: {"image_hash": str, "image_url": str, "name": str, "asset_type": "image"}
    """
    if asset_type == "video":
        is_local = os.path.isfile(file_url)
        if is_local:
            result = upload_video(client, file_path=file_url, name=name)
            thumb_path = _extract_thumbnail(file_url)
        else:
            result = upload_video_from_url(client, file_url=file_url, name=name)
            thumb_path = None

        thumb_hash = ""
        if thumb_path:
            try:
                img_result = upload_image(client, file_path=thumb_path, name=f"{name}_thumb")
                thumb_hash = img_result.get("image_hash", "")
            finally:
                os.unlink(thumb_path)

        return {**result, "asset_type": "video", "image_hash": thumb_hash}

    elif asset_type == "image":
        is_local = os.path.isfile(file_url)
        if is_local:
            result = upload_image(client, file_path=file_url, name=name)
        else:
            suffix = os.path.splitext(file_url.split("?")[0])[-1] or ".jpg"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
                tmp_path = tf.name
            try:
                urllib.request.urlretrieve(file_url, tmp_path)
                result = upload_image(client, file_path=tmp_path, name=name)
            finally:
                os.unlink(tmp_path)
        return {**result, "asset_type": "image"}

    else:
        raise ValueError(f"不支持的 asset_type: {asset_type}，必须是 'video' 或 'image'")


# ─── Ensure Creative OS match ────────────────────────────────────────

def _patch_cta_link(data: dict, link: str) -> None:
    """Replace store URL in call_to_action.value.link, creating the path if absent."""
    cta = data.setdefault("call_to_action", {})
    cta.setdefault("type", "INSTALL_MOBILE_APP")
    cta.setdefault("value", {})["link"] = link


def ensure_creative_for_os(
    client: MetaAdsClient,
    *,
    creative_id: str,
    os_type: str,
    store_url: str,
    page_id: str = "",
    instagram_actor_id: str = "",
) -> str:
    """确保 AdCreative 的 store URL 与目标 OS 匹配。

    检查 creative 当前绑定的 store URL 是否属于目标 OS（iOS/Android）。
    - 匹配：直接返回原 creative_id
    - 不匹配：深拷贝原 object_story_spec，仅替换 store URL，其余字段（
              message、title、image_hash、image_url 等）完整保留，
              然后创建新 AdCreative，返回新 creative_id
    - 无媒体（无 video_id 且无 image_hash）：raise ValueError

    设计原则：copy-and-patch，而非枚举已知字段重建。
    这样不会因 Facebook spec 字段增减而丢失数据。

    Args:
        client:               MetaAdsClient 实例
        creative_id:          原 AdCreative ID
        os_type:              目标操作系统 ("iOS" 或 "Android")
        store_url:            目标 OS 的 App Store / Play Store 链接
        page_id:              Facebook Page ID（创建新 creative 时使用；
                              空时从原 creative 的 actor_id 推断）
        instagram_actor_id:   Instagram 账户 ID（可选，用于 IG 版位）

    Returns:
        str — 新 creative_id（OS 不匹配时）或原 creative_id（已匹配）
    """
    import json
    from facebook_business.adobjects.adcreative import AdCreative

    creative = AdCreative(creative_id)
    creative.api_get(fields=["id", "name", "object_story_spec", "object_store_url", "actor_id"])

    current_url = creative.get("object_store_url", "")
    resolved_page_id = page_id or creative.get("actor_id", "")

    # OS 判断：苹果域名 → iOS，其余 → Android
    current_is_ios = "itunes.apple.com" in current_url or "apps.apple.com" in current_url
    target_is_ios = os_type == "iOS"

    if current_is_ios == target_is_ios:
        return creative_id  # 已匹配，直接使用

    # OS 不匹配：将 spec 完整转为原生 Python 类型再修改。
    # Facebook SDK 返回的 AbstractObject 是 MutableMapping 而非 dict 子类，
    # copy.deepcopy 会因其内部 dict_values 等不可 pickle 属性而失败。
    # json roundtrip 通过 default 回调递归地将所有 MutableMapping 转为 dict，
    # 因为 Facebook API 响应本身就是 JSON，不存在不可序列化的值。
    raw_spec = creative.get("object_story_spec") or {}
    spec = json.loads(json.dumps(
        raw_spec,
        default=lambda o: dict(o) if hasattr(o, "items") else list(o),
    ))
    spec["page_id"] = resolved_page_id
    if instagram_actor_id:
        spec["instagram_user_id"] = instagram_actor_id

    video_data = spec.get("video_data")
    link_data = spec.get("link_data")

    if video_data and video_data.get("video_id"):
        _patch_cta_link(video_data, store_url)
        # Facebook API 拒绝 video_data 同时含 image_hash 和 image_url。
        # api_get 读取时若有 image_hash 会同时返回计算出的 image_url，
        # 创建新 creative 时必须去掉 image_url，保留 image_hash（优先级更高）。
        if video_data.get("image_hash"):
            video_data.pop("image_url", None)
    elif link_data and link_data.get("image_hash"):
        link_data["link"] = store_url
        _patch_cta_link(link_data, store_url)
    else:
        raise ValueError(
            f"Creative {creative_id} 的 object_story_spec 中没有 video_id 或 image_hash，"
            f"无法为 {os_type} 创建新 AdCreative"
        )

    new_name = f"{creative.get('name', creative_id)}_{os_type}"
    result = client.account.create_ad_creative(params={
        "name": new_name,
        "object_story_spec": spec,
    })
    return result["id"]


# ─── Unified upload_creative (upload + AdCreative) ──────────────────

def upload_creative(
    client: MetaAdsClient,
    *,
    asset_type: str,
    file_url: str,
    name: str,
    page_id: str = "",
    link_url: str = "",
) -> dict:
    """统一入口：上传素材文件 + 创建 AdCreative。

    Args:
        client: MetaAdsClient 实例
        asset_type: "video" 或 "image"
        file_url: 素材文件 URL（远程 URL 或本地路径）
        name: 素材名称
        page_id: Facebook Page ID（创建 AdCreative 需要）
        link_url: App Store / Play Store 链接

    Returns:
        {"creative_id": str, "asset_type": str, "name": str,
         "video_id": str (video only), "image_hash": str (image only)}
    """
    media_result = upload_media(client, asset_type=asset_type, file_url=file_url, name=name)

    if asset_type == "video":
        creative_result = create_ad_creative_for_video(
            client,
            video_id=media_result["video_id"],
            name=name,
            page_id=page_id,
            link_url=link_url,
            image_hash=media_result.get("image_hash", ""),
        )
        return {
            "creative_id": creative_result["creative_id"],
            "video_id": media_result["video_id"],
            "image_hash": media_result.get("image_hash", ""),
            "asset_type": "video",
            "name": name,
        }

    else:  # image
        creative_result = create_ad_creative_for_image(
            client,
            image_hash=media_result["image_hash"],
            name=name,
            page_id=page_id,
            link_url=link_url,
        )
        return {
            "creative_id": creative_result["creative_id"],
            "image_hash": media_result["image_hash"],
            "asset_type": "image",
            "name": name,
        }


# ═══════════════════════════════════════════════════════════════════════
# Media Library — 从 DAP 素材 ID 定位 FB 已有素材的 video_id
#
# 流程：DAP detail → 导航 creative_folders 树 → 搜索 creative → video_id
# 调用方：resolve_video_ids(client, [1096114, 1096108])
# ═══════════════════════════════════════════════════════════════════════

# 默认 Business ID — 来自 facebook.config.META_BUSINESS_ID（env 可覆盖）。
# 不再硬编码，避免双源真相。
DEFAULT_BUSINESS_ID = config.META_BUSINESS_ID

# 文件夹 ID 缓存：``f"{biz_id}:{path}"`` → folder_id
# 加 biz_id namespace 防止多 Business 同名顶层文件夹撞 key（P0-2）。
_folder_cache: dict[str, str] = {}

# API 请求间隔（秒）
_REQUEST_INTERVAL = 0.3


class MediaLibraryError(Exception):
    """Media Library 查找失败。"""
    pass


class MaterialNotUploaded(MediaLibraryError):
    """素材未上传到 FB。"""
    pass


class FolderNotFound(MediaLibraryError):
    """文件夹路径导航失败。"""
    pass


class CreativeNotFound(MediaLibraryError):
    """在 Media Library 中找不到素材。"""
    pass


def _navigate_folder_tree(
    client: MetaAdsClient,
    biz_id: str,
    folder_path: str,
) -> str:
    """逐级导航文件夹树，返回末级 folder_id。"""
    segments = [s.strip() for s in folder_path.split("/") if s.strip()]
    if not segments:
        raise FolderNotFound(f"空文件夹路径: {folder_path!r}")

    # 缓存：从最长前缀匹配（namespace 到 biz_id 防撞）
    start_idx = 0
    current_id = ""
    for i in range(len(segments), 0, -1):
        prefix = "/".join(segments[:i])
        cache_key = f"{biz_id}:{prefix}"
        if cache_key in _folder_cache:
            current_id = _folder_cache[cache_key]
            start_idx = i
            break

    # 第一级：Business 根目录
    if start_idx == 0:
        all_folders = client.graph_paginate(
            f"{biz_id}/creative_folders", {"fields": "id,name", "limit": 200}
        )
        current_id = ""
        for f in all_folders:
            if f["name"] == segments[0]:
                current_id = f["id"]
                break
        if not current_id:
            available = [f["name"] for f in all_folders[:20]]
            raise FolderNotFound(f"根目录找不到 '{segments[0]}'，可用: {available}")
        _folder_cache[f"{biz_id}:{segments[0]}"] = current_id
        start_idx = 1

    # 后续各级：subfolders
    for i in range(start_idx, len(segments)):
        seg = segments[i]
        time.sleep(_REQUEST_INTERVAL)
        all_subs = client.graph_paginate(
            f"{current_id}/subfolders", {"fields": "id,name", "limit": 200}
        )
        found = ""
        for f in all_subs:
            if f["name"] == seg:
                found = f["id"]
                break
        if not found:
            available = [f["name"] for f in all_subs[:20]]
            raise FolderNotFound(f"文件夹 {current_id} 下找不到 '{seg}'，可用: {available}")
        current_id = found
        _folder_cache[f"{biz_id}:{'/'.join(segments[: i + 1])}"] = current_id

    return current_id


def _search_creative_in_folder(
    client: MetaAdsClient,
    biz_id: str,
    folder_id: str,
    encrypted_name: str,
) -> dict:
    """在指定文件夹内搜索素材，返回 creative 信息。

    使用 ``name_or_content_filter``（SKILL.md 实测唯一稳定的字段，
    ``name_or_id`` 在多语言版本下漏召）。
    """
    filtering = json.dumps([
        {"field": "name_or_content_filter", "operator": "CONTAIN", "value": encrypted_name},
    ])
    data = client.graph_get(f"{biz_id}/creatives", {
        "creative_folder_id": folder_id,
        "filtering": filtering,
        "fields": "id,name,video_id,type",
        "limit": 5,
    })

    items = data.get("data", [])
    if not items:
        raise CreativeNotFound(
            f"文件夹 {folder_id} 内搜不到素材 '{encrypted_name}'"
        )

    # 精确匹配（去掉 .mp4 后缀比较）
    for item in items:
        item_name = item.get("name", "").replace(".mp4", "")
        if item_name == encrypted_name:
            return item

    # Fuzzy fallback：CONTAIN 命中但无精确匹配时显式告警，避免静默拿到错素材
    fallback = items[0]
    _log.warning(
        "Inexact match in folder %s: searched '%s', returning first hit '%s' (id=%s); "
        "%d total candidates",
        folder_id, encrypted_name, fallback.get("name", ""),
        fallback.get("id", ""), len(items),
    )
    return fallback


def resolve_video_id(
    client: MetaAdsClient,
    material_id: int,
    *,
    biz_id: str = DEFAULT_BUSINESS_ID,
    dap_client: Any = None,
) -> dict:
    """从 DAP 素材 ID 解析出 FB video_id。

    Args:
        client: MetaAdsClient 实例（复用认证和 rate limit 重试）
        material_id: DAP 素材 ID
        biz_id: FB Business ID
        dap_client: DapHttpClient 实例（可选，不传则自动创建）

    Returns:
        {"material_id", "encrypted_name", "folder_path", "folder_id",
         "fb_creative_id", "video_id"}

    Raises:
        MaterialNotUploaded / FolderNotFound / CreativeNotFound — 业务错误
        RateLimitError — rate limit 重试耗尽，需 agent 介入
    """
    if dap_client is None:
        dap_client = _DapHttpClient()

    detail = dap_client.get_material_detail(material_id)
    if not detail:
        raise MaterialNotUploaded(f"DAP 查不到素材 {material_id}")

    encrypted_name = detail.get("encrypted_material_name", "")
    folder_path = detail.get("upload_fb_folder_path", "")
    is_upload_fb = detail.get("is_upload_fb")

    if not encrypted_name:
        raise MaterialNotUploaded(f"素材 {material_id} 无加密命名")
    if not folder_path:
        raise MaterialNotUploaded(f"素材 {material_id} 无 FB 上传路径")
    if not is_upload_fb:
        raise MaterialNotUploaded(f"素材 {material_id} 未标记上传 FB")

    folder_id = _navigate_folder_tree(client, biz_id, folder_path)

    time.sleep(_REQUEST_INTERVAL)
    creative = _search_creative_in_folder(client, biz_id, folder_id, encrypted_name)

    video_id = creative.get("video_id", "")
    if not video_id:
        raise CreativeNotFound(
            f"素材 {material_id} 找到 creative {creative['id']}，但无 video_id"
        )

    return {
        "material_id": material_id,
        "encrypted_name": encrypted_name,
        "folder_path": folder_path,
        "folder_id": folder_id,
        "fb_creative_id": creative["id"],
        "video_id": video_id,
    }


def resolve_video_ids(
    client: MetaAdsClient,
    material_ids: list[int],
    *,
    biz_id: str = DEFAULT_BUSINESS_ID,
    dap_client: Any = None,
) -> dict[int, dict]:
    """批量解析 DAP 素材 ID → FB video_id。

    Returns:
        {material_id: {"video_id": str, ...}, ...}

    Raises:
        MediaLibraryError — 业务错误
        RateLimitError — rate limit 重试耗尽
    """
    if dap_client is None:
        dap_client = _DapHttpClient()

    results: dict[int, dict] = {}
    for mid in material_ids:
        result = resolve_video_id(client, mid, biz_id=biz_id, dap_client=dap_client)
        results[mid] = result
        _log.info("✓ %d → video_id=%s", mid, result["video_id"])

    return results
