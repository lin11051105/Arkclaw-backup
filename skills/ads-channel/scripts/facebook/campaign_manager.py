"""Campaign / AdSet / Ad 创建与管理。

参照 channel-adapters/facebook.md 中的 API 映射实现。
所有 create 函数接收 TypedDict 字典参数（见 params.py）。
金额字段统一用 USD 元，内部自动 ×100 转 cents。
"""
from __future__ import annotations

import copy

from facebook_business.adobjects.adset import AdSet

from .client import MetaAdsClient
from .params import (
    ADSET_DEFAULTS,
    AD_DEFAULTS,
    CAMPAIGN_DEFAULTS,
    USD_FIELDS,
    AdSetCreateParams,
    CampaignCreateParams,
    _cents_to_usd,
    _usd_to_cents,
    validate_usd_fields,
)


def _merge_defaults(defaults: dict, params: dict) -> dict:
    """合并默认值和用户参数。deepcopy defaults 防止可变默认值被共享修改。"""
    return {**copy.deepcopy(defaults), **params}




# ─── Campaign ─────────────────────────────────────────────────────────

def create_campaign(client: MetaAdsClient, params: CampaignCreateParams) -> dict:
    """创建 Campaign（默认 PAUSED，不产生消耗）。"""
    merged = _merge_defaults(CAMPAIGN_DEFAULTS, params)
    validate_usd_fields(merged)

    has_campaign_budget = merged.get("daily_budget") is not None or merged.get("lifetime_budget") is not None
    if "is_adset_budget_sharing_enabled" not in merged:
        # Campaign-level budget (CBO) is incompatible with adset budget sharing
        # Only enable sharing when there's NO campaign budget (ABO mode)
        merged["is_adset_budget_sharing_enabled"] = not has_campaign_budget

    if not has_campaign_budget:
        # ABO mode with adset_budget_sharing requires a bid_strategy
        if merged.get("is_adset_budget_sharing_enabled"):
            if not merged.get("bid_strategy"):
                merged["bid_strategy"] = "LOWEST_COST_WITHOUT_CAP"
        else:
            merged.pop("bid_strategy", None)

    api_params: dict = {}
    for key, val in merged.items():
        if val is None:
            continue
        api_params[key] = _usd_to_cents(val) if key in USD_FIELDS else val

    result = client.account.create_campaign(params=api_params)
    return {"campaign_id": result["id"], "status": merged.get("status", "PAUSED")}


# ─── AdSet ────────────────────────────────────────────────────────────

_TARGETING_OPTIONAL_FIELDS = (
    "publisher_platforms", "age_min", "age_max", "genders",
    "locales", "interests", "custom_audiences",
    "excluded_custom_audiences", "app_install_state",
)


def create_adset(client: MetaAdsClient, params: AdSetCreateParams) -> dict:
    """创建 AdSet。"""
    merged = _merge_defaults(ADSET_DEFAULTS, params)
    validate_usd_fields(merged)

    # 构建 targeting — 从 merged 中提取 targeting 字段
    targeting: dict = {"device_platforms": ["mobile"]}

    countries = merged.pop("countries", None)
    if countries:
        targeting["geo_locations"] = {"countries": countries}

    os_val = merged.pop("os", None)
    if os_val and os_val.lower() in ("ios", "android"):
        targeting["user_os"] = [os_val]

    # audience_type 仅用于业务逻辑判断，不传 API
    merged.pop("audience_type", None)

    # CBO 模式下 AdSet 无预算，bid_strategy 由 Campaign 控制，AdSet 不传
    has_adset_budget = merged.get("daily_budget") is not None or merged.get("lifetime_budget") is not None
    if not has_adset_budget:
        merged.pop("bid_strategy", None)

    for field in _TARGETING_OPTIONAL_FIELDS:
        val = merged.pop(field, None)
        if val is not None:
            targeting[field] = val

    # 构建 API params
    api_params: dict = {"targeting": targeting}
    for key, val in merged.items():
        if val is None:
            continue
        api_params[key] = _usd_to_cents(val) if key in USD_FIELDS else val

    result = client.account.create_ad_set(params=api_params)
    return {"adset_id": result["id"], "status": merged.get("status", "PAUSED")}


# ─── Ad ───────────────────────────────────────────────────────────────

def create_ad(client: MetaAdsClient, params: dict) -> dict:
    """创建 Ad。"""
    merged = _merge_defaults(AD_DEFAULTS, params)

    creative_id = merged.pop("creative_id", None)

    api_params: dict = {}
    for key, val in merged.items():
        if val is None:
            continue
        api_params[key] = _usd_to_cents(val) if key in USD_FIELDS else val

    if creative_id:
        api_params["creative"] = {"creative_id": creative_id}

    result = client.account.create_ad(params=api_params)
    return {"ad_id": result["id"], "status": merged.get("status", "PAUSED")}


# ─── Update Budget ───────────────────────────────────────────────────

def update_entity(
    client: MetaAdsClient,
    *,
    entity_type: str,
    entity_id: str,
    params: dict,
) -> dict:
    """更新 Campaign / AdSet / Ad 的任意可修改参数。

    金额字段（daily_budget, lifetime_budget, spend_cap, bid_amount）
    单位 USD，内部自动转 cents。

    常用参数:
      Campaign: name, status, daily_budget, lifetime_budget, bid_strategy, spend_cap
      AdSet: name, status, daily_budget, lifetime_budget, bid_amount, bid_strategy
      Ad: name, status, creative ({"creative_id": "xxx"})

    Returns:
        {"entity_id": str, "entity_type": str, "success": bool, "updated_fields": list}
    """
    from facebook_business.adobjects.campaign import Campaign
    from facebook_business.adobjects.ad import Ad

    if entity_type == "campaign":
        entity = Campaign(entity_id)
    elif entity_type == "adset":
        entity = AdSet(entity_id)
    elif entity_type == "ad":
        entity = Ad(entity_id)
    else:
        raise ValueError(f"entity_type 必须是 campaign/adset/ad，不支持 {entity_type}")

    api_params: dict = {}
    for key, val in params.items():
        if val is None:
            continue
        api_params[key] = _usd_to_cents(val) if key in USD_FIELDS else val

    validate_usd_fields(params)
    entity.api_update(params=api_params)
    return {
        "entity_id": entity_id,
        "entity_type": entity_type,
        "success": True,
        "updated_fields": list(api_params.keys()),
    }


# ─── Duplicate / List / Query ─────────────────────────────────────────

def duplicate_adset(
    client: MetaAdsClient,
    source_adset_id: str,
    target_campaign_id: str,
    budget_override: float | None = None,
    new_name: str | None = None,
) -> dict:
    """复制 AdSet 到目标 Campaign。

    CBO campaign 下的 adset 不设 daily_budget（由 campaign 层控制）。
    """
    source = AdSet(source_adset_id)
    fields = [
        "name", "targeting", "bid_strategy", "billing_event",
        "optimization_goal", "daily_budget", "promoted_object",
        "regional_regulated_categories",
    ]
    info = source.api_get(fields=fields)

    final_name = new_name or f"{info['name']}_dup"
    source_budget = info.get("daily_budget")

    # 直接透传源 targeting，避免拆解/重组丢失 user_os 等字段
    api_params: dict = {
        "campaign_id": target_campaign_id,
        "name": final_name,
        "status": "PAUSED",
        "targeting": info.get("targeting", {}),
        "billing_event": info.get("billing_event", "IMPRESSIONS"),
        "optimization_goal": info.get("optimization_goal", "APP_INSTALLS"),
        "promoted_object": info.get("promoted_object"),
    }

    # 透传合规声明（如 SINGAPORE_UNIVERSAL）
    rrc = info.get("regional_regulated_categories")
    if rrc:
        api_params["regional_regulated_categories"] = rrc

    # CBO campaign: source adset 无 daily_budget 则不传 budget/bid_strategy
    if budget_override is not None:
        api_params["daily_budget"] = int(budget_override * 100)
        api_params["bid_strategy"] = info.get("bid_strategy", "LOWEST_COST_WITHOUT_CAP")
    elif source_budget:
        api_params["daily_budget"] = int(source_budget)  # already in cents from API
        api_params["bid_strategy"] = info.get("bid_strategy", "LOWEST_COST_WITHOUT_CAP")

    result = client.account.create_ad_set(params=api_params)
    return {"adset_id": result["id"], "status": "PAUSED"}


def list_campaigns(client: MetaAdsClient, limit: int = 100) -> list[dict]:
    """列出账户下的 Campaign。"""
    fields = ["id", "name", "status", "daily_budget", "lifetime_budget", "objective"]
    params = {
        "filtering": [{"field": "effective_status", "operator": "IN", "value": ["ACTIVE", "PAUSED"]}],
        "limit": limit,
    }
    campaigns = client.account.get_campaigns(fields=fields, params=params)
    return [
        {
            "id": c["id"],
            "name": c["name"],
            "status": c["status"],
            "daily_budget": _cents_to_usd(c.get("daily_budget")),
            "objective": c.get("objective"),
        }
        for c in campaigns
    ]


def get_promoted_object_from_account(client: MetaAdsClient, limit: int = 20) -> list[dict]:
    """从账户现有 AdSet 中反查所有 promoted_object（去重）。"""
    adsets = client.account.get_ad_sets(
        fields=["name", "promoted_object"],
        params={"limit": limit},
    )
    seen: set[tuple[str, str]] = set()
    results: list[dict] = []
    for adset in adsets:
        po = adset.get("promoted_object")
        if po:
            key = (po.get("application_id", ""), po.get("object_store_url", ""))
            if key not in seen:
                seen.add(key)
                results.append({
                    "application_id": po.get("application_id"),
                    "object_store_url": po.get("object_store_url"),
                    "adset_name": adset.get("name"),
                })
    return results


def list_adsets(
    client: MetaAdsClient, limit: int = 100, campaign_id: str | None = None,
) -> list[dict]:
    """列出 AdSet。

    当传入 campaign_id 时，使用 Campaign edge 直查（包含 PAUSED，比账户级 filtering 更可靠）。
    未传 campaign_id 时，从账户级查询 ACTIVE/PAUSED。
    """
    fields = ["id", "name", "status", "daily_budget", "campaign_id", "optimization_goal"]
    params: dict = {"limit": limit}

    if campaign_id:
        from facebook_business.adobjects.campaign import Campaign
        adsets = Campaign(campaign_id).get_ad_sets(fields=fields, params=params)
    else:
        params["filtering"] = [
            {"field": "effective_status", "operator": "IN", "value": ["ACTIVE", "PAUSED"]}
        ]
        adsets = client.account.get_ad_sets(fields=fields, params=params)

    return [
        {
            "id": a["id"],
            "name": a["name"],
            "status": a["status"],
            "daily_budget": _cents_to_usd(a.get("daily_budget")),
            "campaign_id": a.get("campaign_id"),
            "optimization_goal": a.get("optimization_goal"),
        }
        for a in adsets
    ]


def list_ads(
    client: MetaAdsClient,
    limit: int = 100,
    adset_id: str | None = None,
    campaign_id: str | None = None,
) -> list[dict]:
    """列出 Ad。

    优先从 Campaign/AdSet 自身的 /ads edge 查询（比账户级 filtering 更可靠）。
    account 级别的 filtering=[campaign.id=...] 在某些情况下会返回空，
    直接查对象的 edge 不受此影响。
    """
    fields = ["id", "name", "status", "adset_id", "campaign_id", "creative"]
    params: dict = {"limit": limit}

    if campaign_id:
        from facebook_business.adobjects.campaign import Campaign
        ads = Campaign(campaign_id).get_ads(fields=fields, params=params)
    elif adset_id:
        from facebook_business.adobjects.adset import AdSet
        ads = AdSet(adset_id).get_ads(fields=fields, params=params)
    else:
        params["filtering"] = [
            {"field": "effective_status", "operator": "IN", "value": ["ACTIVE", "PAUSED"]}
        ]
        ads = client.account.get_ads(fields=fields, params=params)

    return [
        {
            "id": ad["id"],
            "name": ad["name"],
            "status": ad["status"],
            "adset_id": ad.get("adset_id"),
            "campaign_id": ad.get("campaign_id"),
            "creative_id": ad.get("creative", {}).get("id"),
        }
        for ad in ads
    ]



# ─── helpers ──────────────────────────────────────────────────────────

def _extract_countries(targeting: dict) -> list[str]:
    geo = targeting.get("geo_locations", {})
    return geo.get("countries", ["US"])


def _extract_os(targeting: dict) -> str:
    user_os = targeting.get("user_os", [])
    return user_os[0] if user_os else "iOS"
