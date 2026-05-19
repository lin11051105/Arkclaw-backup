"""Ad / AdSet / Campaign 状态查询。

状态更新通过 campaign_manager.update_entity 的通用参数路径处理。
不支持删除操作（遵循 AGENTS.md 红线）。
"""

from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.ad import Ad
from facebook_business.adobjects.adcreative import AdCreative


_ENTITY_CLASS = {
    "campaign": Campaign,
    "adset": AdSet,
    "ad": Ad,
}

_CAMPAIGN_FIELDS = [
    "id", "name", "status", "objective",
    "daily_budget", "lifetime_budget", "bid_strategy",
    "created_time", "updated_time",
]
_ADSET_FIELDS = [
    "id", "name", "status", "daily_budget", "lifetime_budget",
    "bid_strategy", "bid_amount", "billing_event", "optimization_goal",
    "targeting", "promoted_object", "campaign_id",
    "created_time", "updated_time",
]
_AD_FIELDS = [
    "id", "name", "status", "adset_id", "campaign_id",
    "creative", "created_time", "updated_time",
]
_CREATIVE_FIELDS = ["id", "name", "object_story_spec", "thumbnail_url"]


def _cents_to_usd(val) -> float | None:
    """cents 字符串 → USD float，None 透传。"""
    if val is None:
        return None
    try:
        return int(val) / 100
    except (TypeError, ValueError):
        return None


def _to_plain(obj):
    """Facebook SDK AbstractObject → plain Python dict/list，确保 json.dumps 可序列化。"""
    if obj is None:
        return None
    if isinstance(obj, list):
        return [_to_plain(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    # SDK AbstractObject 实现了 .items() 但不是 dict 子类
    try:
        return {k: _to_plain(v) for k, v in obj.items()}
    except (AttributeError, TypeError):
        return obj


def get_entity_status(client, entity_id: str, entity_type: str) -> dict:
    """查询实体完整信息。

    - campaign: 返回 Campaign 全字段 + 下属 AdSet + Ad + Creative 信息链
    - adset:    返回 AdSet 全字段（含 targeting 解析）
    - ad:       返回 Ad 全字段 + Creative 详情

    所有 API 调用走直连 edge（Campaign → AdSet → Ad），
    不走账户级 filtering（避免 PAUSED 实体漏返回的问题）。
    """
    entity_type = entity_type.lower()
    if entity_type == "campaign":
        return _get_campaign_full(entity_id)
    if entity_type == "adset":
        return _get_adset_full(entity_id)
    if entity_type == "ad":
        return _get_ad_full(entity_id)
    raise ValueError(f"不支持的实体类型: {entity_type}。支持: campaign/adset/ad")


# ── Campaign ─────────────────────────────────────────────────────────────────

def _get_campaign_full(campaign_id: str) -> dict:
    """Campaign 全字段 + AdSet + Ad + Creative 完整信息链。"""
    raw_c = Campaign(campaign_id).api_get(fields=_CAMPAIGN_FIELDS)
    campaign_data = {
        "id": raw_c["id"],
        "name": raw_c.get("name"),
        "status": raw_c.get("status"),
        "objective": raw_c.get("objective"),
        "daily_budget": _cents_to_usd(raw_c.get("daily_budget")),
        "lifetime_budget": _cents_to_usd(raw_c.get("lifetime_budget")),
        "bid_strategy": raw_c.get("bid_strategy"),
        "created_time": raw_c.get("created_time"),
        "updated_time": raw_c.get("updated_time"),
    }

    # AdSets via Campaign edge — includes PAUSED, no account-level filtering
    raw_adsets = Campaign(campaign_id).get_ad_sets(
        fields=_ADSET_FIELDS, params={"limit": 200},
    )
    adsets_data = []
    total_ads = 0
    for a in raw_adsets:
        adset_entry = _parse_adset(a)
        adset_entry["ads"] = _fetch_ads_for_adset(a["id"])
        total_ads += len(adset_entry["ads"])
        adsets_data.append(adset_entry)

    return {
        "campaign": campaign_data,
        "adsets": adsets_data,
        "summary": {"adset_count": len(adsets_data), "ad_count": total_ads},
    }


# ── AdSet ─────────────────────────────────────────────────────────────────────

def _fetch_ads_for_adset(adset_id: str) -> list:
    """查询 AdSet 下属 Ads（含 Creative）。Campaign 层级和直查共用此路径。"""
    raw_ads = AdSet(adset_id).get_ads(fields=_AD_FIELDS, params={"limit": 200})
    return [_parse_ad(ad) for ad in raw_ads]


def _get_adset_full(adset_id: str) -> dict:
    """AdSet 全字段（含 targeting 解析）+ 下属 Ads。"""
    raw = AdSet(adset_id).api_get(fields=_ADSET_FIELDS)
    result = _parse_adset(raw)
    result["ads"] = _fetch_ads_for_adset(adset_id)
    return result


# ── Ad ────────────────────────────────────────────────────────────────────────

def _get_ad_full(ad_id: str) -> dict:
    """Ad 全字段 + Creative 详情。"""
    raw = Ad(ad_id).api_get(fields=_AD_FIELDS)
    return _parse_ad(raw)


# ── Parsers ───────────────────────────────────────────────────────────────────

def _parse_adset(a) -> dict:
    targeting = a.get("targeting") or {}
    geo = targeting.get("geo_locations", {})
    return {
        "id": a["id"],
        "name": a.get("name"),
        "status": a.get("status"),
        "campaign_id": a.get("campaign_id"),
        "daily_budget": _cents_to_usd(a.get("daily_budget")),
        "lifetime_budget": _cents_to_usd(a.get("lifetime_budget")),
        "bid_strategy": a.get("bid_strategy"),
        "bid_amount": _cents_to_usd(a.get("bid_amount")),
        "billing_event": a.get("billing_event"),
        "optimization_goal": a.get("optimization_goal"),
        "countries": geo.get("countries", []),
        "os": (targeting.get("user_os") or [""])[0],
        "promoted_object": _to_plain(a.get("promoted_object")),
        "created_time": a.get("created_time"),
        "updated_time": a.get("updated_time"),
        "ads": [],
    }


def _parse_ad(ad) -> dict:
    raw_creative_id = (ad.get("creative") or {}).get("id")
    creative_info: dict = {}
    if raw_creative_id:
        try:
            rc = AdCreative(raw_creative_id).api_get(fields=_CREATIVE_FIELDS)
            creative_info = {
                "id": rc["id"],
                "name": rc.get("name"),
                "object_story_spec": _to_plain(rc.get("object_story_spec")),
                "thumbnail_url": rc.get("thumbnail_url"),
            }
        except Exception:
            creative_info = {"id": raw_creative_id}
    return {
        "id": ad["id"],
        "name": ad.get("name"),
        "status": ad.get("status"),
        "adset_id": ad.get("adset_id"),
        "campaign_id": ad.get("campaign_id"),
        "creative_id": raw_creative_id,
        "creative": creative_info,
        "created_time": ad.get("created_time"),
        "updated_time": ad.get("updated_time"),
    }


def _get_entity_class(entity_type: str):
    entity_type = entity_type.lower()
    if entity_type not in _ENTITY_CLASS:
        raise ValueError(f"不支持的实体类型: {entity_type}。支持: {list(_ENTITY_CLASS.keys())}")
    return _ENTITY_CLASS[entity_type]
