"""Upload pipeline script.

Implements the upload flow (Step 一 in creative-lifecycle):
- Naming validation per naming-rules.json
- Parameter validation (budget, countries)
- Campaign/AdSet/Ad parameter construction from config
- Sequential creation with injected create functions

Design: dependency-injected create functions for testability.
"""
from __future__ import annotations

import os
from typing import Callable

# Minimum budget in USD
MIN_BUDGET = 10.0
# Maximum budget in USD (single upload cap)
MAX_BUDGET = 5000.0
# Valid OS types for Facebook App Install campaigns
VALID_OS_TYPES = ("iOS", "Android")


# ═══════════════════════════════════════════════════════════════════════════
# validate_naming
# ═══════════════════════════════════════════════════════════════════════════

def validate_naming(name: str, naming_rules: dict) -> dict:
    """Validate a creative asset name against naming rules.

    Returns: {"is_valid": bool, "parsed": dict, "error": str}
    """
    from lib.naming import validate_material_name
    return validate_material_name(name, naming_rules)


# ═══════════════════════════════════════════════════════════════════════════
# validate_params
# ═══════════════════════════════════════════════════════════════════════════

def validate_params(
    *,
    budget: float | None = None,
    adset_budget: float | None = None,
    countries: list[str],
    os_type: str,
) -> dict:
    """Validate upload parameters.

    budget      = Campaign 日预算 (CBO 模式)
    adset_budget = AdSet 日预算   (ABO 模式)
    二者至少传一个，不能同时传。

    Returns: {"is_valid": bool, "error": str}
    """
    if budget is not None and adset_budget is not None:
        return {"is_valid": False, "error": "budget 和 adset_budget 不能同时设置，CBO 传 budget，ABO 传 adset_budget"}
    effective = budget if budget is not None else adset_budget
    if effective is None:
        return {"is_valid": False, "error": "budget 或 adset_budget 必须设置其中之一"}
    if effective < MIN_BUDGET:
        return {"is_valid": False, "error": f"budget ${effective} below minimum ${MIN_BUDGET}"}
    if effective > MAX_BUDGET:
        return {"is_valid": False, "error": f"budget ${effective} above maximum ${MAX_BUDGET}"}
    if not countries:
        return {"is_valid": False, "error": "countries list is empty"}
    if os_type not in VALID_OS_TYPES:
        return {"is_valid": False, "error": f"os_type '{os_type}' invalid, must be one of {VALID_OS_TYPES}"}
    return {"is_valid": True, "error": ""}


# ═══════════════════════════════════════════════════════════════════════════
# build_campaign_params
# ═══════════════════════════════════════════════════════════════════════════

def build_campaign_params(
    *,
    project_id: str,
    countries: list[str],
    budget: float | None = None,
    name: str | None = None,
    objective: str = "OUTCOME_APP_PROMOTION",
    status: str = "PAUSED",
) -> dict:
    """Build Campaign creation params.

    budget    = Campaign 日预算 (CBO 模式，USD)。ABO 模式时传 None，Campaign 不设预算。
    name      = 覆盖自动生成的名称（可选）。
    objective = 广告目标，默认 OUTCOME_APP_PROMOTION。
    status    = 初始状态，默认 PAUSED。
    """
    assert countries, "countries cannot be empty"
    country_str = "_".join(countries[:3])
    campaign_name = name if name is not None else f"{project_id}_{country_str}_test"

    return {
        "name": campaign_name,
        "objective": objective,
        "daily_budget": budget,
        "status": status,
    }


# ═══════════════════════════════════════════════════════════════════════════
# build_adset_params
# ═══════════════════════════════════════════════════════════════════════════

def build_adset_params(
    *,
    campaign_id: str,
    name: str,
    project_id: str,
    config: dict,
    countries: list[str],
    audience: str,
    os_type: str,
    budget: float | None = None,
    optimization_goal: str = "APP_INSTALLS",
    billing_event: str = "IMPRESSIONS",
    bid_strategy: str | None = None,
    bid_amount: float | None = None,
    status: str = "PAUSED",
) -> dict:
    """Build AdSet creation params.

    budget            = AdSet 日预算（ABO 模式，USD）。CBO 模式传 None。
    optimization_goal = 优化目标，默认 APP_INSTALLS。
    billing_event     = 计费事件，默认 IMPRESSIONS。
    bid_strategy      = 出价策略（可选，如 COST_CAP）。
    bid_amount        = 出价上限 USD（bid_strategy=COST_CAP 时使用）。
    status            = 初始状态，默认 PAUSED。
    promoted_object   从 apps.json 按 project + os 解析。
    """
    assert countries, "countries cannot be empty"
    app = config.get("apps", {}).get(project_id, {})
    store_url = app.get("store_urls", {}).get(os_type, "")

    params: dict = {
        "name": f"{name}_adset",
        "campaign_id": campaign_id,
        "daily_budget": budget,
        "billing_event": billing_event,
        "optimization_goal": optimization_goal,
        "countries": countries,
        "os": os_type,
        "audience_type": audience,
        "promoted_object": {
            "application_id": app.get("application_id", ""),
            "object_store_url": store_url,
        },
        "status": status,
    }
    if bid_strategy is not None:
        params["bid_strategy"] = bid_strategy
    if bid_amount is not None:
        params["bid_amount"] = bid_amount
    return params


# ═══════════════════════════════════════════════════════════════════════════
# build_ad_params
# ═══════════════════════════════════════════════════════════════════════════

def build_ad_params(
    *,
    adset_id: str,
    creative_id: str,
    name: str,
) -> dict:
    """Build Ad creation params.

    creative_id is obtained from upload_creative step, not user input.
    """
    return {
        "name": f"{name}_ad",
        "adset_id": adset_id,
        "creative": {"creative_id": creative_id},
        "status": "PAUSED",
    }


# ═══════════════════════════════════════════════════════════════════════════
# do_upload_creative — 纯素材上传（命名校验 + 合规预检 + 上传）
# ═══════════════════════════════════════════════════════════════════════════

def do_upload_creative(
    *,
    name: str,
    file_url: str,
    asset_type: str,
    os_type: str,
    project_id: str,
    config: dict,
    check_creative_fn: Callable | None = None,
    upload_creative_fn: Callable,
) -> dict:
    """上传素材：命名校验 → 合规预检 → 上传文件 → 返回 image_hash/video_id。

    纯媒体上传，不创建 AdCreative。可独立调用（只上传素材不建广告）。

    Returns:
        成功: {"status": "success", "naming_validation": ...,
               "upload": {"asset_type": ..., "image_hash"|"video_id": ..., ...}}
        失败: {"status": "error", "error": ..., ...}
    """
    naming_rules = config["naming_rules"]

    # 1. naming validation
    naming_result = validate_naming(name, naming_rules)
    if not naming_result["is_valid"]:
        return {
            "status": "error",
            "error": f"naming validation failed: {naming_result['error']}",
            "naming_validation": naming_result,
        }

    # 2. creative check (合规预检 — 待实现)
    if check_creative_fn is not None:
        check_result = check_creative_fn(file_url=file_url, asset_type=asset_type, name=name)
        if not check_result.get("is_valid", True):
            return {
                "status": "error",
                "error": f"creative check failed: {check_result.get('error', 'unknown')}",
                "naming_validation": naming_result,
                "check_result": check_result,
            }

    # 3. upload media → get image_hash/video_id
    upload_result = upload_creative_fn(
        asset_type=asset_type,
        file_url=file_url,
        name=name,
    )

    return {
        "status": "success",
        "naming_validation": naming_result,
        "upload": upload_result,
    }


# ═══════════════════════════════════════════════════════════════════════════
# do_build_ad_structure — 纯广告结构搭建（Campaign → AdSet → Ad）
# ═══════════════════════════════════════════════════════════════════════════

def do_build_ad_structure(
    *,
    name: str,
    creative_id: str,
    budget: float | None = None,
    adset_budget: float | None = None,
    countries: list[str],
    audience: str,
    os_type: str,
    project_id: str,
    config: dict,
    create_campaign_fn: Callable,
    create_adset_fn: Callable,
    create_ad_fn: Callable,
    ensure_creative_fn: Callable | None = None,
    # Campaign optional overrides
    campaign_name: str | None = None,
    campaign_objective: str = "OUTCOME_APP_PROMOTION",
    campaign_status: str = "PAUSED",
    # AdSet optional overrides
    optimization_goal: str = "APP_INSTALLS",
    billing_event: str = "IMPRESSIONS",
    bid_strategy: str | None = None,
    bid_amount: float | None = None,
    adset_status: str = "PAUSED",
) -> dict:
    """搭建广告结构：参数校验 → Creative 平台校验 → Campaign → AdSet → Ad。

    预算模式（二选一）:
      budget       = Campaign 日预算 (CBO，默认) — AdSet 不设预算
      adset_budget = AdSet 日预算  (ABO)         — Campaign 不设预算

    Campaign 可选覆盖: campaign_name, campaign_objective, campaign_status
    AdSet 可选覆盖:   optimization_goal, billing_event, bid_strategy, bid_amount, adset_status

    如果 creative_id 绑定的 store URL 与目标 os_type 不匹配，
    自动用相同素材创建一个匹配目标平台的新 Creative。

    Returns:
        成功: {"status": "success", "entities": {...}, "params": {...}}
        失败: {"status": "error", "error": ...}
    """
    # 1. param validation
    param_result = validate_params(
        budget=budget, adset_budget=adset_budget,
        countries=countries, os_type=os_type,
    )
    if not param_result["is_valid"]:
        return {"status": "error", "error": param_result["error"]}

    # 1.5 ensure creative matches target OS
    original_creative_id = creative_id
    if ensure_creative_fn is not None:
        try:
            creative_id = ensure_creative_fn(
                creative_id, os_type, project_id, config,
            )
        except Exception as e:
            return {
                "status": "error",
                "error": f"Creative 平台校验失败: {e}",
            }

    # 2. create Campaign (CBO: budget 在 Campaign; ABO: Campaign 不设 budget)
    # campaign_name 未指定时用 creative name（已通过命名规则校验），
    # 确保 Campaign 名称符合 {project}_{region}_{language}_{type}_{version} 规范。
    campaign_params = build_campaign_params(
        project_id=project_id,
        countries=countries,
        budget=budget,
        name=campaign_name if campaign_name is not None else name,
        objective=campaign_objective,
        status=campaign_status,
    )
    campaign_result = create_campaign_fn(campaign_params)
    campaign_id = campaign_result["campaign_id"]

    # 3. create AdSet (ABO: adset_budget 在 AdSet; CBO: AdSet 不设 budget)
    adset_params = build_adset_params(
        campaign_id=campaign_id,
        name=name,
        project_id=project_id,
        config=config,
        countries=countries,
        audience=audience,
        budget=adset_budget,
        os_type=os_type,
        optimization_goal=optimization_goal,
        billing_event=billing_event,
        bid_strategy=bid_strategy,
        bid_amount=bid_amount,
        status=adset_status,
    )
    adset_result = create_adset_fn(adset_params)
    adset_id = adset_result["adset_id"]

    # 4. create Ad
    ad_params = build_ad_params(
        adset_id=adset_id, creative_id=creative_id, name=name,
    )
    ad_result = create_ad_fn(ad_params)

    ad_id = ad_result["ad_id"]

    # Ads Manager 直链（campaign 视图），方便在飞书通知里贴给人看
    _raw_account_id = os.environ.get("META_AD_ACCOUNT_ID", "")
    account_id = f"act_{_raw_account_id}" if _raw_account_id and not _raw_account_id.startswith("act_") else _raw_account_id
    campaign_url = (
        f"https://adsmanager.facebook.com/adsmanager/manage/campaigns"
        f"?act={account_id}&selected_campaign_ids={campaign_id}"
        if account_id else ""
    )

    result = {
        "status": "success",
        "entities": {
            "campaign_id": campaign_id,
            "adset_id": adset_id,
            "ad_id": ad_id,
        },
        "params": {
            "campaign_budget": budget,       # None 表示 ABO 模式
            "adset_budget": adset_budget,    # None 表示 CBO 模式
            "countries": countries,
            "audience": audience,
        },
    }
    if campaign_url:
        result["campaign_url"] = campaign_url
    if creative_id != original_creative_id:
        result["creative_replaced"] = {
            "original": original_creative_id,
            "new": creative_id,
            "reason": f"原 creative 的 store URL 与目标 OS ({os_type}) 不匹配，已自动创建新 creative",
        }
    return result


# ═══════════════════════════════════════════════════════════════════════════
# run_upload_pipeline — 串联: 上传素材 → 搭建广告
# ═══════════════════════════════════════════════════════════════════════════

def run_upload_pipeline(
    *,
    name: str,
    budget: float | None = None,
    adset_budget: float | None = None,
    countries: list[str],
    audience: str,
    os_type: str,
    file_url: str,
    asset_type: str,
    project_id: str,
    config: dict,
    check_creative_fn: Callable | None = None,
    upload_creative_fn: Callable,
    create_ad_creative_fn: Callable,
    create_campaign_fn: Callable,
    create_adset_fn: Callable,
    create_ad_fn: Callable,
    # Campaign optional overrides
    campaign_name: str | None = None,
    campaign_objective: str = "OUTCOME_APP_PROMOTION",
    campaign_status: str = "PAUSED",
    # AdSet optional overrides
    optimization_goal: str = "APP_INSTALLS",
    billing_event: str = "IMPRESSIONS",
    bid_strategy: str | None = None,
    bid_amount: float | None = None,
    adset_status: str = "PAUSED",
) -> dict:
    """完整流程：上传素材 + 创建 AdCreative + 搭建广告结构。

    预算模式（二选一）:
      budget       = Campaign 日预算 (CBO，默认)
      adset_budget  = AdSet 日预算  (ABO)

    Campaign 可选覆盖: campaign_name, campaign_objective, campaign_status
    AdSet 可选覆盖:   optimization_goal, billing_event, bid_strategy, bid_amount, adset_status

    Phase 1: do_upload_creative — 命名校验 + 合规预检 + 上传媒体文件
    Phase 2: create_ad_creative_fn — 用 image_hash/video_id 创建 AdCreative
    Phase 3: do_build_ad_structure — 参数校验 + Campaign/AdSet/Ad 创建
    """
    # Phase 1: upload media
    upload_result = do_upload_creative(
        name=name,
        file_url=file_url,
        asset_type=asset_type,
        os_type=os_type,
        project_id=project_id,
        config=config,
        check_creative_fn=check_creative_fn,
        upload_creative_fn=upload_creative_fn,
    )
    if upload_result["status"] != "success":
        return upload_result

    # Phase 2: create AdCreative from upload result
    creative_result = create_ad_creative_fn(upload_result["upload"])
    creative_id = creative_result["creative_id"]

    # Phase 3: build ad structure
    ads_result = do_build_ad_structure(
        name=name,
        creative_id=creative_id,
        budget=budget,
        adset_budget=adset_budget,
        countries=countries,
        audience=audience,
        os_type=os_type,
        project_id=project_id,
        config=config,
        create_campaign_fn=create_campaign_fn,
        create_adset_fn=create_adset_fn,
        create_ad_fn=create_ad_fn,
        campaign_name=campaign_name,
        campaign_objective=campaign_objective,
        campaign_status=campaign_status,
        optimization_goal=optimization_goal,
        billing_event=billing_event,
        bid_strategy=bid_strategy,
        bid_amount=bid_amount,
        adset_status=adset_status,
    )
    if ads_result["status"] != "success":
        return {**ads_result, "naming_validation": upload_result["naming_validation"]}

    return {
        "status": "success",
        "naming_validation": upload_result["naming_validation"],
        "upload": upload_result["upload"],
        "entities": ads_result["entities"],
        "params": ads_result["params"],
    }
